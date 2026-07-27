"""Manifest provenance: entry shape, and the partial marker a failed run leaves behind."""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import json

import pytest

from scaffold_helpers import _config


# -------------------------------------------------------------------------- manifest shape
def test_scaffold_manifest_entries_have_expected_shape(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    entries = result["manifest"]["entries"]
    assert entries, "expected at least one manifest entry"
    base_keys = {"feature", "stack", "name", "source", "target",
                 "frameworkVersion", "hash"}
    for entry in entries:
        # Directory entries (skills) also have dirMeta
        allowed_keys = base_keys | ({"dirMeta"} if "dirMeta" in entry else set())
        assert set(entry.keys()) == allowed_keys
        assert entry["source"].startswith("features/")
        assert len(entry["hash"]) == 64
        int(entry["hash"], 16)  # must be valid hex
        assert entry["frameworkVersion"] == result["manifest"]["frameworkVersion"]

    manifest_on_disk = (target / ".ai-badger" / "manifest.json")
    assert manifest_on_disk.exists()


@pytest.mark.parametrize("stacks,agents", [
    (["dotnet"], ["claude"]),
    (["python", "js"], ["claude", "copilot"]),
])
def test_scaffolded_manifest_validates_against_the_manifest_schema(
        tmp_path, load_script, root, stacks, agents):
    """The manifest scaffold writes must satisfy schemas/manifest.schema.json."""
    bl = load_script("scripts/badger_lib.py")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target,
                                config=_config(stacks=stacks, agents=agents),
                                skills=["task"], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    manifest_on_disk = target / ".ai-badger" / "manifest.json"
    assert any("dirMeta" in entry
               for entry in json.loads(manifest_on_disk.read_text(encoding="utf-8"))["entries"]), \
        "expected at least one directory entry so dirMeta is actually exercised"
    assert bl.validate_file(manifest_on_disk, root / "schemas" / "manifest.schema.json") == []


# -------------------------------------------------------------------- template provenance
def test_scaffolded_templates_are_recorded_in_the_manifest(tmp_path, load_script, root):
    """Templates are placed into the project, so the manifest must say where they came from."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=[], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    templates = [e for e in result["manifest"]["entries"] if e["feature"] == "templates"]

    assert {(e["stack"], e["name"]) for e in templates} == {
        ("common", "state.json"),
        ("common", "agent-instructions/schema.json"),
        ("common", "agent-instructions/model.template.json"),
        ("claude", "CLAUDE.md.tmpl"),
    }


def test_recorded_templates_hash_their_framework_source(tmp_path, load_script, root):
    """drift.compare hashes the source for file entries; recording the target would misreport."""
    bl = load_script("scripts/badger_lib.py")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=[], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    for entry in (e for e in result["manifest"]["entries"] if e["feature"] == "templates"):
        assert entry["hash"] == bl.sha256_file(root / entry["source"])


def test_a_scaffolded_template_is_not_reported_as_new_on_a_second_run(
        tmp_path, load_script, root):
    """The anti-false-positive gate: a recorded template must never re-appear as drift."""
    bl = load_script("scripts/badger_lib.py")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(stacks=["dotnet"])

    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=[], install=False)
    manifest = scaf.run(generated_at="2026-07-19T00:00:00Z")["manifest"]

    result = drift.compare(root, manifest, stacks=bl.resolve_stacks(config), target=target)

    assert [i for i in result["newItems"] if i["feature"] == "templates"] == []
    assert [p for p in result["changed"] if "/templates/" in p] == []


@pytest.mark.parametrize("stacks", [["python"], ["python", "hermes"]])
def test_no_catalog_item_drift_reports_as_new_survives_a_full_scaffold(
        tmp_path, load_script, root, stacks):
    """Every reportable feature type must be recorded by scaffold, or the gate cries wolf.

    `hermes` is an agent whose catalog is also a selectable stack — the shape that turns an
    unrecorded feature type into a permanent false positive (#104).
    """
    bl = load_script("scripts/badger_lib.py")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(stacks=stacks)

    scaf = scaffold.Scaffolder(
        root=root, target=target, config=config,
        skills=bl.default_skills_in(root / "features" / "common" / "skills"), install=False)
    manifest = scaf.run(generated_at="2026-07-19T00:00:00Z")["manifest"]

    result = drift.compare(root, manifest, stacks=bl.resolve_stacks(config), target=target)

    assert result["newItems"] == []


# --------------------------------------------------------- partial-run recovery (F-25)
def test_failed_run_leaves_a_detectable_partial_marker(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False)

    def _explode():
        raise RuntimeError("hook wiring blew up mid-scaffold")

    scaf.wire_hooks = _explode

    with pytest.raises(RuntimeError):
        scaf.run(generated_at="2026-07-19T00:00:00Z")

    partial = json.loads(
        (target / ".ai-badger" / "manifest.json.partial").read_text(encoding="utf-8"))
    assert not (target / ".ai-badger" / "manifest.json").exists()
    assert "agent-files" in partial["completedSteps"]
    assert "hooks" not in partial["completedSteps"]


def test_a_successful_run_leaves_no_partial_marker(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / ".ai-badger" / "manifest.json").exists()
    assert not (target / ".ai-badger" / "manifest.json.partial").exists()


def test_a_failing_user_scope_write_degrades_to_a_note(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False)

    def _explode(*_args, **_kwargs):
        raise OSError("read-only home directory")

    scaf._scaffold_claude_mcp_user = _explode

    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / ".ai-badger" / "manifest.json").exists()
    assert any("OSError" in note for note in result["notes"])
