"""P8 integration — the `.ai-badger/project-id` lifecycle, end to end (ADR-0025, ADR-0036).

Cross-package contract in one store-free module: the scaffolder MINTS a uuid4 id at
scaffold time (an installing scaffold may instead reuse or register one), the resolver
WALKS to it from a nested cwd, a re-scaffold PRESERVES it, den-refresh's backfill
REPLACES only a missing/blank id, and the explicit env override wins over anything on
disk. Nothing here reads a registry bank: the session conftest pins
AI_BADGER_RACCOON_REGISTER=0, so every refresh in this file takes the 'off' branch and
mints locally; the ai-raccoon branches live in tests/test_project_id_registration.py.
"""
from __future__ import annotations

import json
import uuid

import pytest

import badger_store

from scaffold_helpers import _config

PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"


@pytest.fixture
def scaffold_module(load_script, monkeypatch, tmp_path):
    """The real scaffolder with HOME redirected so no live cache is consulted."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")


def _scaffold_into(scaffold_module, root, tmp_path, target, monkeypatch) -> None:
    cache = tmp_path / "home" / ".ai-badger" / "framework"
    for name in ("schemas", "features", "engine"):
        (cache / name).mkdir(parents=True, exist_ok=True)
    (cache / "VERSION").write_text("0.13.0\n", encoding="utf-8")
    (cache / "engine" / "badger_lib.py").write_bytes(b"")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config(stacks=["python"])), encoding="utf-8")
    rc = scaffold_module.main(["--config", str(config_path), "--target", str(target),
                               "--root", str(root), "--skills", "", "--no-install"])
    assert rc == 0


def _refresh_module(load_script):
    return load_script("features/common/skills/den-refresh/scripts/refresh.py")


def test_scaffold_mints_a_uuid4_the_walk_finds_from_a_nested_cwd(
        scaffold_module, root, tmp_path, monkeypatch):
    """Scaffold → mint → resolve: the id file exists after scaffold and the store's
    resolver returns it from a directory BELOW the target (the nearest-wins walk)."""
    target = tmp_path / "proj"
    target.mkdir()
    monkeypatch.delenv(PROJECT_ID_ENV, raising=False)
    _scaffold_into(scaffold_module, root, tmp_path, target, monkeypatch)

    id_file = target / ".ai-badger" / "project-id"
    assert id_file.is_file()
    minted = id_file.read_text(encoding="utf-8").strip()
    uuid.UUID(minted)  # raises if not a uuid

    nested = target / "deep" / "nested"
    nested.mkdir(parents=True)
    assert badger_store.resolve_project_id(str(nested)) == minted


def test_rescaffold_preserves_the_minted_id(scaffold_module, root, tmp_path, monkeypatch):
    """A re-scaffold must never regenerate identity: the same uuid survives (the
    id is the project's stable bus address, not scaffold scratch)."""
    target = tmp_path / "proj"
    target.mkdir()
    monkeypatch.delenv(PROJECT_ID_ENV, raising=False)
    _scaffold_into(scaffold_module, root, tmp_path, target, monkeypatch)
    minted = (target / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip()

    _scaffold_into(scaffold_module, root, tmp_path, target, monkeypatch)

    assert (target / ".ai-badger" / "project-id").read_text(
        encoding="utf-8").strip() == minted


def test_den_refresh_backfills_only_a_missing_or_blank_id(scaffold_module, load_script,
                                                          root, tmp_path, monkeypatch):
    """The id-less fleet (pre-ADR scaffolds) heals via den-refresh: step 1c mints when the
    file is absent or blank and PRESERVES a written id — the backfill is idempotent for
    healthy repos."""
    refresh = _refresh_module(load_script)
    monkeypatch.delenv(PROJECT_ID_ENV, raising=False)
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold_into(scaffold_module, root, tmp_path, target, monkeypatch)
    id_file = target / ".ai-badger" / "project-id"

    id_file.unlink()
    assert refresh.main(["--target", str(target), "--root", str(root)]) == 0
    backfilled = id_file.read_text(encoding="utf-8").strip()
    uuid.UUID(backfilled)

    id_file.write_text("  \n", encoding="utf-8")
    assert refresh.main(["--target", str(target), "--root", str(root)]) == 0
    healed = id_file.read_text(encoding="utf-8").strip()
    uuid.UUID(healed)

    id_file.write_text("existing-id\n", encoding="utf-8")
    assert refresh.main(["--target", str(target), "--root", str(root)]) == 0
    assert id_file.read_text(encoding="utf-8").strip() == "existing-id"


def test_explicit_env_override_wins_over_the_planted_id(tmp_path, monkeypatch):
    """A3 (explicit wins): the override beats the walked file at resolve time — the
    resolver never reads the file when the env carries an answer."""
    repo = tmp_path / "repo"
    (repo / ".ai-badger").mkdir(parents=True)
    (repo / ".ai-badger" / "project-id").write_text("planted-id\n", encoding="utf-8")
    monkeypatch.setenv(PROJECT_ID_ENV, "override-id")

    assert badger_store.resolve_project_id(str(repo)) == "override-id"