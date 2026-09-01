"""Red tests for the cwd → projectId resolver (P2, aib-user-db-message-bus).

``engine/badger_store.py`` gains the resolver the bus's send and delivery surfaces share
(D4) — the Python side of the raccoon resolver contract (2cda253b): probe = cwd, candidate
surface = each registered project's ingest-scope paths plus its watch paths, containment =
equal-or-ancestor (both sides canonicalized), exactly one match → the id, several → refuse
with the candidates (never guess), none → None (the caller owns the refusal text, D7).
The explicit override — env ``AI_BADGER_PROJECT_ID`` — wins unconditionally and is the
contract's "explicit wins" rule (A3): one entry point serves send and receive identically.

The registry source is injectable (``registry=`` callable): every resolver test runs on a
fixture surface and never touches the real raccoon bank. The default source — the pinned
bank at ``~/.ai-raccoon/memory.db``, read read-only — is tested against a synthetic
bank-shaped SQLite file via ``AI_BADGER_RACCOON_DB``.

Test map (plan aib-user-db-message-bus §3 P2 · spec Rule 8 · contract 2cda253b tests):
  1. Same directory resolves (R8 sc.1) .......... test_same_directory_resolves_to_its_project
  2. Ancestor containment, one id (R8 sc.2) ..... test_ancestor_scope_contains_both_cwds_with_one_id
  3. Sibling dir is not containment ............. test_sibling_directory_resolves_to_its_own_project
                                                  (the naive-prefix mutation's killer)
  4. Ambiguity refuses with candidates .......... test_ambiguous_cwd_refuses_with_sorted_candidates_and_never_guesses
  5. Nothing contains → None .................... test_uncontained_cwd_resolves_to_none
  6. Missing probe → None, no registry read ..... test_missing_probe_resolves_to_none_without_reading_the_registry
  7. Watch-only fallback (contract tests) ....... test_watch_only_registration_resolves_through_the_reader
  8. Explicit wins, resolver never consulted .... test_env_override_wins_without_consulting_the_registry
                                                  (the contract's own throwing-fake proof)
  9. Blank override falls through ............... test_blank_env_override_falls_through_to_the_registry
 10. Canonicalization applied once .............. test_scope_and_probe_paths_are_canonicalized_before_containment
 11. Default reader: scopes + watches ........... test_raccoon_reader_reads_scope_arrays_and_watch_rows
 12. Default reader: global + bad rows skip ..... test_raccoon_reader_skips_the_global_scope_and_bad_rows
 13. Default reader: unreadable bank → empty .... test_unreadable_bank_reads_as_empty_and_resolves_to_none
Fail-open delivery pairing (plan P2 t6, D7) is P1's
``test_deliver_without_project_id_delivers_one_to_one_only`` — the store already delivers
1:1 only when the caller's project id is unresolved.

Mutation docstrings name the surviving-bug each test exists to kill (plan P2 t5: a
selection derived without the resolver's containment misses messages).
"""
from __future__ import annotations

import sqlite3

import pytest

import badger_store

PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"
RACCOON_BANK_ENV = "AI_BADGER_RACCOON_DB"


# ---------------------------------------------------------------------------
# helpers — injectable surfaces, synthetic raccoon bank
# ---------------------------------------------------------------------------


def _surface(mapping):
    """A registry source from a plain ``{project_id: [paths]}`` mapping."""
    return lambda: mapping


class _ExplodingRegistry:
    """A registry source that fails the test the moment it is consulted."""

    def __call__(self):
        raise AssertionError("registry consulted despite an explicit override")


@pytest.fixture(autouse=True)
def _clean_bus_env(monkeypatch):
    """A developer shell must not poison the resolver's inputs."""
    monkeypatch.delenv(PROJECT_ID_ENV, raising=False)
    monkeypatch.delenv(RACCOON_BANK_ENV, raising=False)


def _make_bank(path, settings_rows, watch_rows):
    """A bank-shaped SQLite file carrying just the columns the reader selects."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE watches (project_id TEXT NOT NULL, path TEXT NOT NULL, "
                 "created_at INTEGER NOT NULL, last_change_ts INTEGER NOT NULL)")
    conn.executemany("INSERT INTO settings VALUES (?, ?)", settings_rows)
    conn.executemany("INSERT INTO watches VALUES (?, ?, 0, 0)", watch_rows)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# resolver outcomes — Rule 8 at the store level, on injected surfaces
# ---------------------------------------------------------------------------


def test_same_directory_resolves_to_its_project(tmp_path):
    """Rule 8 sc.1: a cwd equal to a registered project's scope path resolves to it."""
    root = tmp_path / "bus-repo"
    root.mkdir()
    registry = _surface({"bus-proj": [str(root)], "other-proj": [str(tmp_path / "other")]})

    assert badger_store.resolve_project_id(str(root), registry=registry) == "bus-proj"


def test_ancestor_scope_contains_both_cwds_with_one_id(tmp_path):
    """Rule 8 sc.2: two different cwds under one project's registered root resolve alike."""
    root = tmp_path / "bus-repo"
    docs, deep = root / "docs", root / "docs" / "deep"
    docs.mkdir(parents=True)
    registry = _surface({"bus-proj": [str(root)]})

    assert badger_store.resolve_project_id(str(root), registry=registry) == "bus-proj"
    assert badger_store.resolve_project_id(str(docs), registry=registry) == "bus-proj"
    assert badger_store.resolve_project_id(str(deep), registry=registry) == "bus-proj"


def test_sibling_directory_resolves_to_its_own_project(tmp_path):
    """A sibling whose name extends the project's path is NOT inside it.

    Mutation killer: naive prefix containment (``probe.startswith(root)`` without the
    separator) would file ``bus-repo-sibling`` under ``bus-proj`` — the selection
    mismatch that silently misses messages (plan P2 t5).
    """
    sibling = tmp_path / "bus-repo-sibling" / "docs"
    sibling.mkdir(parents=True)
    registry = _surface({"bus-proj": [str(tmp_path / "bus-repo")],
                         "sib-proj": [str(tmp_path / "bus-repo-sibling")]})

    assert badger_store.resolve_project_id(str(sibling), registry=registry) == "sib-proj"


def test_ambiguous_cwd_refuses_with_sorted_candidates_and_never_guesses(tmp_path):
    """Nested scopes both containing the cwd refuse with the sorted candidate list.

    The resolver never guesses (contract outcome Ambiguous); the caller formats the
    refusal (D7) — so the candidates travel on the exception, not in prose here.
    """
    outer, inner = tmp_path / "a-outer", tmp_path / "a-outer" / "b-inner"
    inner.mkdir(parents=True)
    work = inner / "work"
    work.mkdir()
    registry = _surface({"b-inner": [str(inner)], "a-outer": [str(outer)]})

    with pytest.raises(badger_store.ProjectIdAmbiguous) as raised:
        badger_store.resolve_project_id(str(work), registry=registry)
    assert raised.value.candidates == ["a-outer", "b-inner"]


def test_uncontained_cwd_resolves_to_none(tmp_path):
    """No registered project's surface contains the cwd → None; the caller refuses."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    registry = _surface({"bus-proj": [str(tmp_path / "bus-repo")]})

    assert badger_store.resolve_project_id(str(elsewhere), registry=registry) is None


def test_missing_probe_resolves_to_none_without_reading_the_registry():
    """A harness that could not produce a cwd resolves to None — and never reads the bank.

    The raising fake proves the probe check precedes the registry read (order pins:
    no cwd means no containment question, not a registry scan).
    """
    assert badger_store.resolve_project_id(None, registry=_ExplodingRegistry()) is None
    assert badger_store.resolve_project_id("", registry=_ExplodingRegistry()) is None


def test_watch_only_registration_resolves_through_the_reader(tmp_path, monkeypatch):
    """A project registered only by watch rows (no ingest scope) still resolves —
    the contract's watch-only fallback for early adopters without a scope."""
    watch_root = tmp_path / "docs-only"
    watch_root.mkdir()
    _make_bank(tmp_path / "bank" / "memory.db",
               [], [("docs-proj", str(watch_root))])
    monkeypatch.setenv(RACCOON_BANK_ENV, str(tmp_path / "bank" / "memory.db"))

    assert badger_store.resolve_project_id(str(watch_root / "notes")) == "docs-proj"


# ---------------------------------------------------------------------------
# the explicit override — the contract's "explicit wins" rule (A3)
# ---------------------------------------------------------------------------


def test_env_override_wins_without_consulting_the_registry(monkeypatch):
    """A set override IS the answer: the registry would throw if consulted —
    the contract's own throwing-fake proof for 'explicit id → resolver never consulted'."""
    monkeypatch.setenv(PROJECT_ID_ENV, "hand-set-project")

    assert badger_store.resolve_project_id("/any/cwd", registry=_ExplodingRegistry()) \
        == "hand-set-project"
    assert badger_store.resolve_project_id(None, registry=_ExplodingRegistry()) \
        == "hand-set-project"


def test_blank_env_override_falls_through_to_the_registry(tmp_path, monkeypatch):
    """Blank/whitespace override is unset (the contract's IsNullOrWhiteSpace mirror):
    the registry decides, and an uncontained cwd still refuses."""
    root = tmp_path / "bus-repo"
    root.mkdir()
    registry = _surface({"bus-proj": [str(root)]})
    monkeypatch.setenv(PROJECT_ID_ENV, "   ")

    assert badger_store.resolve_project_id(str(root), registry=registry) == "bus-proj"


# ---------------------------------------------------------------------------
# canonicalization — applied once, by the resolver, on both sides
# ---------------------------------------------------------------------------


def test_scope_and_probe_paths_are_canonicalized_before_containment(tmp_path):
    """Trailing separators, ``..`` segments and symlinked ancestors must not decide
    the outcome — both sides resolve to real paths before comparison (the raccoon's
    IsWithinScope semantics; the mutation is dropping the resolution entirely)."""
    real = tmp_path / "real-root"
    real.mkdir()
    link = tmp_path / "link-root"
    link.symlink_to(real)
    (real / "sub").mkdir()
    registry = _surface({"bus-proj": [str(link) + "/"]})  # stored via the link, trailing /

    probe_via_real = str(real / "sub")
    probe_via_link = str(link / "sub")
    probe_dotdot = str(real / "sub" / ".." / "sub")

    assert badger_store.resolve_project_id(probe_via_real, registry=registry) == "bus-proj"
    assert badger_store.resolve_project_id(probe_via_link, registry=registry) == "bus-proj"
    assert badger_store.resolve_project_id(probe_dotdot, registry=registry) == "bus-proj"


# ---------------------------------------------------------------------------
# the default registry source — the raccoon bank, read read-only
# ---------------------------------------------------------------------------


def test_raccoon_reader_reads_scope_arrays_and_watch_rows(tmp_path, monkeypatch):
    """Scope keys parse as JSON path arrays (authoritative), watch rows append (fallback),
    both under their project id — the union is the candidate surface."""
    bank = tmp_path / "bank" / "memory.db"
    _make_bank(
        bank,
        [("ingest.scope.p1", '["/x/p1", "/x/p1/docs"]'),
         ("ingest.scope.p2", '["/x/p2"]')],
        [("p1", "/x/p1-watch"), ("p2", "/x/p2-w2"), ("p2", "/x/p2-w1")],
    )
    monkeypatch.setenv(RACCOON_BANK_ENV, str(bank))

    assert badger_store.raccoon_registry_surface() == {
        "p1": ["/x/p1", "/x/p1/docs", "/x/p1-watch"],
        "p2": ["/x/p2", "/x/p2-w2", "/x/p2-w1"],
    }


def test_raccoon_reader_skips_the_global_scope_and_bad_rows(tmp_path, monkeypatch):
    """``ingest.scope.global`` is the raccoon's fallback entry, not a project — treating
    it as a candidate would make every cwd under it ambiguous. Malformed JSON and
    non-array rows read as absent (the raccoon's own Parse semantics)."""
    bank = tmp_path / "bank" / "memory.db"
    _make_bank(
        bank,
        [("ingest.scope.global", '["/Users/shared"]'),
         ("ingest.scope.broken", "not json"),
         ("ingest.scope.empty", "[]"),
         ("ingest.scope.ok", '["/x/ok"]')],
        [],
    )
    monkeypatch.setenv(RACCOON_BANK_ENV, str(bank))

    surface = badger_store.raccoon_registry_surface()
    assert surface == {"ok": ["/x/ok"]}


def test_unreadable_bank_reads_as_empty_and_resolves_to_none(tmp_path, monkeypatch):
    """A missing (or unreadable) bank is an empty surface — the resolver refuses and the
    caller formats the enriched refusal (D7): a broken registry never crashes a session."""
    monkeypatch.setenv(RACCOON_BANK_ENV, str(tmp_path / "absent" / "memory.db"))

    assert badger_store.raccoon_registry_surface() == {}
    assert badger_store.resolve_project_id(str(tmp_path)) is None
