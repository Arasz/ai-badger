"""Provenance keys in .ai-badger/manifest.json (ADR-0001 decision 4)."""
from __future__ import annotations

import json

import pytest

SCHEMA_REL = "schemas/manifest.schema.json"


def _manifest(**overrides):
    base = {
        "frameworkVersion": "0.2.0",
        "frameworkCommit": "a" * 40,
        "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [],
    }
    base.update(overrides)
    return base


def _errors(load_script, root, instance):
    bl = load_script("scripts/badger_lib.py")
    schema = bl.load_json(root / SCHEMA_REL)
    return bl.validate(instance, schema)


def test_manifest_with_all_provenance_keys_is_valid(load_script, root):
    assert _errors(load_script, root, _manifest()) == []


def test_manifest_allows_null_commit_for_plugin_cache_scaffold(load_script, root):
    assert _errors(load_script, root, _manifest(frameworkCommit=None)) == []


@pytest.mark.parametrize("missing", ["frameworkCommit", "frameworkDirty"])
def test_manifest_missing_a_provenance_key_is_invalid(load_script, root, missing):
    instance = _manifest()
    del instance[missing]
    errors = _errors(load_script, root, instance)
    assert errors, f"expected {missing} to be required"
    assert any(missing in e for e in errors)


def test_manifest_dirty_must_be_boolean(load_script, root):
    assert _errors(load_script, root, _manifest(frameworkDirty="yes")) != []


import subprocess


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")


def test_git_provenance_clean_repo_returns_sha_and_not_dirty(tmp_path, load_script):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    repo = tmp_path / "clean"
    _init_repo(repo)

    sha, dirty = scaffold.git_provenance(repo)

    assert sha is not None and len(sha) == 40
    assert dirty is False


def test_git_provenance_dirty_repo_flags_dirty(tmp_path, load_script):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    repo = tmp_path / "dirty"
    _init_repo(repo)
    (repo / "seed.txt").write_text("edited\n", encoding="utf-8")

    sha, dirty = scaffold.git_provenance(repo)

    assert sha is not None
    assert dirty is True


def test_git_provenance_non_repo_returns_null_and_not_dirty(tmp_path, load_script):
    """A plugin cache is a plain copy with no .git; a copy cannot have local edits."""
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    plain = tmp_path / "cache-copy"
    plain.mkdir()

    sha, dirty = scaffold.git_provenance(plain)

    assert sha is None
    assert dirty is False


def test_scaffold_stamps_provenance_into_manifest(tmp_path, load_script, root):
    """The scaffolder records which framework state produced the scaffold."""
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = {
        "frameworkVersion": "0.2.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": [], "agents": ["claude"],
    }

    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                               skills=[], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    manifest = result["manifest"]
    assert "frameworkCommit" in manifest
    assert "frameworkDirty" in manifest
    assert isinstance(manifest["frameworkDirty"], bool)

    written = json.loads((target / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    assert written["frameworkCommit"] == manifest["frameworkCommit"]
    assert written["frameworkDirty"] == manifest["frameworkDirty"]


def test_scaffolded_manifest_validates_against_schema(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    bl = load_script("scripts/badger_lib.py")
    target = tmp_path / "proj2"
    target.mkdir()
    config = {
        "frameworkVersion": "0.2.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": [], "agents": ["claude"],
    }

    scaffold.Scaffolder(root=root, target=target, config=config,
                        skills=[], install=False).run(generated_at=None)

    errors = bl.validate_file(target / ".ai-badger" / "manifest.json",
                              root / "schemas" / "manifest.schema.json")
    assert errors == []


def test_provenance_hint_offered_when_keys_missing(load_script):
    validate = load_script("scripts/validate.py")
    errors = ["'frameworkCommit' is a required property"]

    hint = validate.provenance_hint(errors)

    assert hint is not None
    assert "re-scaffold" in hint.lower()


def test_provenance_hint_absent_for_unrelated_errors(load_script):
    validate = load_script("scripts/validate.py")

    assert validate.provenance_hint(["'agents' is a required property"]) is None
