"""The manifest's record of the config files ai-badger generates but does not own (issue #194).

`.mcp.json` and its family are merged into, never claimed in `entries`, so "did ai-badger
write this file?" was answered by a key-shape heuristic (`only_generated_entries`). The
`generatedConfig` section records the writes instead. It is bookkeeping, never ownership:
drift stays quiet about these paths, and nothing reads a record back to overwrite a file.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scaffold_helpers import _config
from conftest import _test_write

LEGACY_COPILOT = Path(".github") / "copilot" / "mcp-config.json"


def _run(make_scaffolder, **kwargs):
    kwargs.setdefault("config", _config(stacks=["python"], agents=["claude"]))
    kwargs.setdefault("skills", ["task"])
    scaf = make_scaffolder(**kwargs)
    return scaf, scaf.run(generated_at="2026-07-29T00:00:00Z")


def _records(manifest) -> dict:
    return {(rec["path"], rec["destination"]): rec for rec in manifest["generatedConfig"]}


def _write_manifest(target: Path, generated_config) -> None:
    """Leave the manifest an earlier run would have written, carrying *generated_config*."""
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    _test_write(aib / "manifest.json", json.dumps({
        "$schema": "../schemas/manifest.schema.json",
        "frameworkVersion": "0.40.0",
        "frameworkCommit": None,
        "frameworkDirty": False,
        "generatedAt": None,
        "agents": ["claude"],
        "skillScope": "default",
        "entries": [],
        "generatedConfig": generated_config,
    }), encoding="utf-8")


# ── what a run records ───────────────────────────────────────────────────────

def test_the_mcp_json_this_run_wrote_is_recorded(make_scaffolder):
    _, result = _run(make_scaffolder)

    record = _records(result["manifest"])[(".mcp.json", ".mcp.json")]

    assert (make_scaffolder.target / ".mcp.json").is_file()
    assert record["frameworkVersion"] == result["manifest"]["frameworkVersion"]


def test_the_copilot_config_is_recorded_when_copilot_reads_it(make_scaffolder):
    _, result = _run(make_scaffolder,
                     config=_config(stacks=["python"], agents=["claude", "copilot"]))

    assert (".github/mcp.json", ".github/mcp.json") in _records(result["manifest"])


def test_a_destination_no_agent_reads_is_not_recorded(make_scaffolder):
    """No copilot, no `.github/mcp.json` write — and so no record of one."""
    _, result = _run(make_scaffolder)

    assert not (make_scaffolder.target / ".github" / "mcp.json").exists()
    assert (".github/mcp.json", ".github/mcp.json") not in _records(result["manifest"])


def test_the_settings_json_the_hooks_were_wired_into_is_recorded(make_scaffolder):
    """`.claude/settings.json` is merged into by the same rules as `.mcp.json`."""
    _, result = _run(make_scaffolder)

    assert (".claude/settings.json", ".claude/settings.json") in _records(result["manifest"])


def test_the_user_global_proposal_is_never_recorded(make_scaffolder):
    """ADR-0014 decision 6: `~/.claude/settings.json` is proposed, never written."""
    scaf = make_scaffolder(config=_config(stacks=["python"], agents=["claude"]))

    scaf.mcp.propose_claude_mcp_user({"probe": {"name": "probe", "command": "echo probe",
                                               "scope": "user"}})

    assert scaf.generated_config_records() == []


def test_a_refused_merge_records_nothing(make_scaffolder):
    """The record is of writes: a file protected from a write is not recorded as written."""
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({"mcpServers": []}), encoding="utf-8")

    _, result = _run(make_scaffolder)

    assert (".mcp.json", ".mcp.json") not in _records(result["manifest"])
    assert any("refused to overwrite" in note and ".mcp.json" in note
               for note in result["notes"])


def test_an_untracked_generated_config_is_still_recorded(make_scaffolder):
    """`.mcp.json` is gitignored in some repos: the record is about writes, not tracking."""
    target = make_scaffolder.target
    _test_write(target / ".gitignore", ".mcp.json\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(target)], check=True)

    _, result = _run(make_scaffolder)

    tracked = subprocess.run(["git", "-C", str(target), "ls-files", ".mcp.json"],
                             check=True, capture_output=True, text=True).stdout
    assert tracked.strip() == ""
    assert (".mcp.json", ".mcp.json") in _records(result["manifest"])


# ── a record outlives the run that wrote it ──────────────────────────────────

def test_an_earlier_versions_record_survives_a_run_that_does_not_rewrite_the_file(
        make_scaffolder):
    """The point of the record: "0.40.0 wrote here" is what makes the next retirement provable."""
    target = make_scaffolder.target
    (target / LEGACY_COPILOT).parent.mkdir(parents=True, exist_ok=True)
    # A hand shape, so this run leaves the file alone rather than retiring it.
    _test_write(target / LEGACY_COPILOT, json.dumps({"mcpServers": {"mine": {"type": "http", "url": "https://example.invalid"}}}), encoding="utf-8")
    _write_manifest(target, [{"path": LEGACY_COPILOT.as_posix(),
                              "destination": ".github/copilot/mcp-config.json",
                              "frameworkVersion": "0.40.0"}])

    _, result = _run(make_scaffolder)

    carried = _records(result["manifest"])[
        (LEGACY_COPILOT.as_posix(), ".github/copilot/mcp-config.json")]
    assert carried["frameworkVersion"] == "0.40.0"


def test_a_record_dies_with_the_file_it_names(make_scaffolder):
    """The retirement case: the file goes, so the record goes with it."""
    target = make_scaffolder.target
    (target / LEGACY_COPILOT).parent.mkdir(parents=True, exist_ok=True)
    _test_write(target / LEGACY_COPILOT, json.dumps({"mcpServers": {"pyright": {"command": "uvx", "args": ["x"]}}}), encoding="utf-8")
    _write_manifest(target, [{"path": LEGACY_COPILOT.as_posix(),
                              "destination": ".github/copilot/mcp-config.json",
                              "frameworkVersion": "0.40.0"}])

    _, result = _run(make_scaffolder)

    assert not (target / LEGACY_COPILOT).exists()
    assert not [rec for rec in result["manifest"]["generatedConfig"]
                if rec["path"] == LEGACY_COPILOT.as_posix()]


# ── bookkeeping, not ownership ───────────────────────────────────────────────

def test_a_recorded_config_the_project_edited_is_still_the_projects(make_scaffolder):
    """A record licenses nothing: the merge keeps every hand-written key it found."""
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({
        "mcpServers": {"mine": {"command": "echo mine"}},
        "somethingElse": {"kept": True},
    }), encoding="utf-8")
    _write_manifest(target, [{"path": ".mcp.json", "destination": ".mcp.json",
                              "frameworkVersion": "0.40.0"}])

    _, result = _run(make_scaffolder)

    written = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert written["mcpServers"]["mine"] == {"command": "echo mine"}
    assert written["somethingElse"] == {"kept": True}
    assert _records(result["manifest"])[(".mcp.json", ".mcp.json")]["frameworkVersion"] \
        == result["manifest"]["frameworkVersion"]


def test_drift_says_nothing_about_a_recorded_generated_config(load_script, tmp_path):
    """Recording a path must not turn it into something drift compares."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    (fw / "features").mkdir(parents=True)
    _test_write(fw / "VERSION", "0.40.0\n", encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    _test_write(proj / ".mcp.json", "{}\n", encoding="utf-8")
    manifest = {
        "frameworkVersion": "0.40.0", "agents": ["claude"], "entries": [],
        "generatedConfig": [{"path": ".mcp.json", "destination": ".mcp.json",
                             "frameworkVersion": "0.40.0"}],
    }

    result = drift.compare(fw, manifest, target=proj)

    assert ".mcp.json" not in json.dumps(result)


# ── the schema pins the shape ────────────────────────────────────────────────

@pytest.mark.parametrize("agents", [["claude"], ["claude", "copilot"]])
def test_a_manifest_carrying_generated_config_validates_against_the_schema(
        load_script, root, make_scaffolder, agents):
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target

    _, result = _run(make_scaffolder, config=_config(stacks=["python"], agents=agents))

    assert result["manifest"]["generatedConfig"], "expected the section to be exercised"
    assert bl.validate_file(target / ".ai-badger" / "manifest.json",
                            root / "schemas" / "manifest.schema.json") == []


def test_the_schema_pins_the_record_shape(load_script, root):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "manifest.schema.json")

    item = schema["properties"]["generatedConfig"]["items"]

    assert set(item["properties"]) == {"path", "destination", "frameworkVersion"}
    assert set(item["required"]) == {"path", "destination", "frameworkVersion"}
    assert item["additionalProperties"] is False
