"""Tests for the cwd → projectId resolver (P2, aib-bus-followups-independence).

``engine/badger_store.py`` resolves a working directory to the project's bus identity
(D4; ADR-0025): the explicit override — env ``AI_BADGER_PROJECT_ID`` — wins
unconditionally (the contract's "explicit wins" rule, A3); otherwise the nearest
ancestor ``.ai-badger/project-id`` file decides (minted at scaffold time, backfilled by
den-refresh). One upward walk has one nearest directory — there is no ambiguity to
refuse and no registry to consult: where there is ``.ai-badger``, there is a project.
A cwd with no ``.ai-badger`` in its ancestry — or one whose id file is absent or
blank — resolves to None; the caller owns the fail-open (D7/D8).

Test map (plan aib-bus-followups-independence · spec Rule 8 · ADR-0025):
  1. Same directory resolves ............... test_same_directory_resolves_to_its_project
  2. Ancestor walk, one id ................. test_ancestor_walk_resolves_nested_cwds_to_the_same_project
  3. Sibling dir is not containment ........ test_sibling_directory_resolves_to_its_own_project
                                             (the naive-prefix mutation's killer)
  4. Nearest .ai-badger wins ............... test_nearest_ai_badger_project_id_file_wins
                                             (the worktree-inside-repo live case)
  5. Nothing above → None .................. test_uncontained_cwd_resolves_to_none
  6. Missing probe → None .................. test_missing_probe_resolves_to_none
  7. Id file absent → None (no fallback) ... test_missing_ai_badger_id_resolves_to_none
  8. Explicit wins, walk never consulted ... test_env_override_wins_over_the_walked_id
  9. Blank override falls through .......... test_blank_env_override_falls_through_to_the_walk
 10. Canonicalization applied once ......... test_walk_paths_are_canonicalized_before_containment

Mutation docstrings name the surviving-bug each test exists to kill (plan P2 t5: a
selection derived without the walk misses messages).
"""
from __future__ import annotations

import pytest

import badger_store

PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"


# ---------------------------------------------------------------------------
# helpers — .ai-badger/project-id fixtures
# ---------------------------------------------------------------------------


def _make_project(directory, project_id: str) -> None:
    """Scaffold the minimum identity: <dir>/.ai-badger/project-id carrying *project_id*."""
    aib = directory / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "project-id").write_text(f"{project_id}\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_bus_env(monkeypatch):
    """A developer shell must not poison the resolver's inputs."""
    monkeypatch.delenv(PROJECT_ID_ENV, raising=False)


# ---------------------------------------------------------------------------
# resolver outcomes — Rule 8 at the store level, on project-id fixtures
# ---------------------------------------------------------------------------


def test_same_directory_resolves_to_its_project(tmp_path):
    """Rule 8 sc.1: a cwd carrying .ai-badger/project-id resolves to that id."""
    root = tmp_path / "bus-repo"
    root.mkdir()
    _make_project(root, "bus-proj")

    assert badger_store.resolve_project_id(str(root)) == "bus-proj"


def test_ancestor_walk_resolves_nested_cwds_to_the_same_project(tmp_path):
    """Rule 8 sc.2: cwds under one project root resolve to it — the walk finds the
    nearest ancestor .ai-badger from any depth."""
    root = tmp_path / "bus-repo"
    docs, deep = root / "docs", root / "docs" / "deep"
    docs.mkdir(parents=True)
    _make_project(root, "bus-proj")

    assert badger_store.resolve_project_id(str(root)) == "bus-proj"
    assert badger_store.resolve_project_id(str(docs)) == "bus-proj"
    assert badger_store.resolve_project_id(str(deep)) == "bus-proj"


def test_sibling_directory_resolves_to_its_own_project(tmp_path):
    """A sibling whose name extends the project's path is NOT inside it.

    Mutation killer: naive prefix containment (``probe.startswith(root)`` without the
    separator) would file ``bus-repo-sibling`` under ``bus-proj`` — the selection
    mismatch that silently misses messages (plan P2 t5).
    """
    sibling = tmp_path / "bus-repo-sibling" / "docs"
    sibling.mkdir(parents=True)
    _make_project(tmp_path / "bus-repo", "bus-proj")
    _make_project(tmp_path / "bus-repo-sibling", "sib-proj")

    assert badger_store.resolve_project_id(str(sibling)) == "sib-proj"


def test_nearest_ai_badger_project_id_file_wins(tmp_path):
    """The nearest .ai-badger wins — the worktree-inside-repo live case (ADR-0025):
    a worktree session resolves to the worktree's own project, never the parent's."""
    repo = tmp_path / "repo"
    worktree = repo / "worktree" / "nested"
    worktree.mkdir(parents=True)
    _make_project(repo, "outer-project")
    _make_project(worktree.parent, "inner-project")

    assert badger_store.resolve_project_id(str(worktree / "child")) == "inner-project"


def test_uncontained_cwd_resolves_to_none(tmp_path):
    """No .ai-badger above the cwd → None; the caller owns the fail-open (D7/D8)."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _make_project(tmp_path / "bus-repo", "bus-proj")

    assert badger_store.resolve_project_id(str(elsewhere)) is None


def test_missing_probe_resolves_to_none():
    """A harness that could not produce a cwd resolves to None — no walk, no answer."""
    assert badger_store.resolve_project_id(None) is None
    assert badger_store.resolve_project_id("") is None
    assert badger_store.resolve_project_id("   ") is None


def test_missing_ai_badger_id_resolves_to_none(tmp_path):
    """An .ai-badger directory without a project-id file (legacy repo, pre-backfill)
    resolves to None — id-absent is a permanent fleet state, fail-open (ADR-0025)."""
    root = tmp_path / "bus-repo"
    (root / ".ai-badger").mkdir(parents=True)

    assert badger_store.resolve_project_id(str(root)) is None


# ---------------------------------------------------------------------------
# the explicit override — the contract's "explicit wins" rule (A3)
# ---------------------------------------------------------------------------


def test_env_override_wins_over_the_walked_id(tmp_path):
    """A set override IS the answer — even when the walk would return a different id:
    the file on disk disagrees by construction, proving the override short-circuits."""
    root = tmp_path / "bus-repo"
    root.mkdir()
    _make_project(root, "walked-project")
    monkeypatch_target = PROJECT_ID_ENV

    import os
    os.environ[monkeypatch_target] = "hand-set-project"
    try:
        assert badger_store.resolve_project_id(str(root)) == "hand-set-project"
        assert badger_store.resolve_project_id(None) == "hand-set-project"
    finally:
        os.environ.pop(monkeypatch_target, None)


def test_blank_env_override_falls_through_to_the_walk(tmp_path, monkeypatch):
    """Blank/whitespace override is unset (the contract's IsNullOrWhiteSpace mirror):
    the walk decides, and an id-less cwd still resolves to None."""
    root = tmp_path / "bus-repo"
    root.mkdir()
    _make_project(root, "bus-proj")
    monkeypatch.setenv(PROJECT_ID_ENV, "   ")

    assert badger_store.resolve_project_id(str(root)) == "bus-proj"


def test_blank_id_file_reads_as_unset(tmp_path):
    """A blank project-id file is unset (mirrors the override's whitespace rule):
    the resolver must not return an empty-string id."""
    root = tmp_path / "bus-repo"
    (root / ".ai-badger").mkdir(parents=True)
    (root / ".ai-badger" / "project-id").write_text("   \n", encoding="utf-8")

    assert badger_store.resolve_project_id(str(root)) is None


# ---------------------------------------------------------------------------
# canonicalization — applied once, by the walk, on the probe
# ---------------------------------------------------------------------------


def test_walk_paths_are_canonicalized_before_containment(tmp_path):
    """Trailing separators, ``..`` segments and symlinked ancestors must not decide
    the outcome — the probe resolves to real paths before the walk (the mutation is
    dropping the resolution entirely)."""
    real = tmp_path / "real-root"
    real.mkdir()
    link = tmp_path / "link-root"
    link.symlink_to(real)
    _make_project(real, "bus-proj")
    (real / "sub").mkdir()

    probe_via_real = str(real / "sub")
    probe_via_link = str(link / "sub")
    probe_dotdot = str(real / "sub" / ".." / "sub")

    assert badger_store.resolve_project_id(probe_via_real) == "bus-proj"
    assert badger_store.resolve_project_id(probe_via_link) == "bus-proj"
    assert badger_store.resolve_project_id(probe_dotdot) == "bus-proj"
