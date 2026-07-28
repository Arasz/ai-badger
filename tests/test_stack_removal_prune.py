"""Dropping a stack from config must converge: drift sees it, and the re-scaffold prunes it.

Drift detected additions (#104) and modifications (#110) but never subtractions, so a removed
stack left its files on disk — and a re-scaffold triggered by anything else dropped the entry
from the manifest, putting the file beyond the reach of every later check (#116).
"""
from __future__ import annotations

import json

from scaffold_helpers import _config

DRIFT = "features/common/skills/welcome-ai-badger/scripts/drift.py"
TS_INSTRUCTION = ".ai-badger/instructions/typescript.instructions.md"


def _manifest(entries):
    return {"frameworkVersion": "0.41.0", "agents": ["claude"], "entries": entries}


def _entry(stack, source, target, entry_hash="deadbeef", feature="instructions", name="n"):
    return {"feature": feature, "stack": stack, "name": name, "source": source,
            "target": target, "frameworkVersion": "0.41.0", "hash": entry_hash}


def _scaffolded(make_scaffolder, config, skills=("task",)):
    scaf = make_scaffolder(config=config, skills=list(skills))
    return make_scaffolder.target, scaf.run(generated_at="2026-07-28T00:00:00Z")


class TestDriftSeesASubtraction:
    """An entry whose stack is no longer configured is drift, the same as one whose source moved."""

    def test_an_entry_whose_stack_left_the_config_is_orphaned(self, tmp_path, load_script):
        drift = load_script(DRIFT)
        fw = tmp_path / "fw"
        (fw / "features" / "ts" / "instructions").mkdir(parents=True)
        (fw / "features" / "ts" / "instructions" / "typescript.instructions.md").write_text(
            "ts\n", encoding="utf-8")
        manifest = _manifest([_entry("ts", "features/ts/instructions/typescript.instructions.md",
                                     TS_INSTRUCTION)])

        result = drift.compare(fw, manifest, delivering=["common", "python"], target=tmp_path / "p")

        assert result["orphaned"] == ["features/ts/instructions/typescript.instructions.md"]

    def test_a_configured_stack_is_not_orphaned(self, tmp_path, load_script):
        drift = load_script(DRIFT)
        fw = tmp_path / "fw"
        (fw / "features" / "ts" / "instructions").mkdir(parents=True)
        src = fw / "features" / "ts" / "instructions" / "typescript.instructions.md"
        src.write_text("ts\n", encoding="utf-8")
        bl = load_script("engine/badger_lib.py")
        manifest = _manifest([_entry("ts", "features/ts/instructions/typescript.instructions.md",
                                     TS_INSTRUCTION, bl.sha256_file(src))])

        result = drift.compare(fw, manifest, delivering=["common", "ts"], target=tmp_path / "p")

        assert result["orphaned"] == []

    def test_the_always_on_common_stack_is_never_orphaned(self, tmp_path, load_script):
        """`resolve_stacks` always prepends it; treating it as removed would delete everything."""
        drift = load_script(DRIFT)
        fw = tmp_path / "fw"
        (fw / "features" / "common" / "invariants").mkdir(parents=True)
        src = fw / "features" / "common" / "invariants" / "x.md"
        src.write_text("inv\n", encoding="utf-8")
        bl = load_script("engine/badger_lib.py")
        manifest = _manifest([_entry("common", "features/common/invariants/x.md",
                                     ".ai-badger/invariants/x.md", bl.sha256_file(src),
                                     feature="invariants")])

        result = drift.compare(fw, manifest, delivering=["common"], target=tmp_path / "p")

        assert result["orphaned"] == []

    def test_an_orphaned_entry_is_not_also_reported_changed(self, tmp_path, load_script):
        """It is leaving; reporting it as upstream drift too is noise."""
        drift = load_script(DRIFT)
        fw = tmp_path / "fw"
        (fw / "features" / "ts" / "instructions").mkdir(parents=True)
        (fw / "features" / "ts" / "instructions" / "typescript.instructions.md").write_text(
            "moved on\n", encoding="utf-8")
        manifest = _manifest([_entry("ts", "features/ts/instructions/typescript.instructions.md",
                                     TS_INSTRUCTION, "stale-hash")])

        result = drift.compare(fw, manifest, delivering=["common"], target=tmp_path / "p")

        assert result["changed"] == []
        assert result["orphaned"] == ["features/ts/instructions/typescript.instructions.md"]

    def test_a_configured_agents_stack_is_not_orphaned(self, tmp_path, load_script):
        """`config.agents` reads features/<agent>/ with no entry in config.stacks — and every
        agent-delivered file would otherwise be condemned on every refresh."""
        drift = load_script(DRIFT)
        bl = load_script("engine/badger_lib.py")
        fw = tmp_path / "fw"
        (fw / "features" / "copilot" / "templates").mkdir(parents=True)
        src = fw / "features" / "copilot" / "templates" / "copilot-instructions.md.tmpl"
        src.write_text("copilot\n", encoding="utf-8")
        manifest = _manifest([_entry("copilot",
                                     "features/copilot/templates/copilot-instructions.md.tmpl",
                                     ".github/copilot-instructions.md", bl.sha256_file(src),
                                     feature="templates")])
        config = {"commonStacks": "common", "stacks": ["python"], "agents": ["claude", "copilot"]}

        result = drift.compare(fw, manifest, delivering=bl.delivering_stacks(config),
                               target=tmp_path / "p")

        assert result["orphaned"] == []

    def test_delivering_stacks_carries_agents_as_well_as_stacks(self, load_script):
        bl = load_script("engine/badger_lib.py")
        config = {"commonStacks": "common", "stacks": ["python"], "agents": ["claude", "copilot"]}

        assert bl.delivering_stacks(config) == ["common", "python", "claude", "copilot"]

    def test_without_a_stack_list_nothing_is_orphaned(self, tmp_path, load_script):
        """`compare()` is also called with no config in hand; it must not guess."""
        drift = load_script(DRIFT)
        fw = tmp_path / "fw"
        (fw / "features" / "ts" / "instructions").mkdir(parents=True)
        src = fw / "features" / "ts" / "instructions" / "typescript.instructions.md"
        src.write_text("ts\n", encoding="utf-8")
        bl = load_script("engine/badger_lib.py")
        manifest = _manifest([_entry("ts", "features/ts/instructions/typescript.instructions.md",
                                     TS_INSTRUCTION, bl.sha256_file(src))])

        result = drift.compare(fw, manifest)

        assert result["orphaned"] == []


class TestAnAgentIsNotAStackRemoval:
    """An agent's files are delivered by config.agents; the prune must not condemn them."""

    def test_the_rescaffold_keeps_a_configured_agents_files(self, make_scaffolder):
        config = _config(stacks=["python"], agents=["claude", "copilot"])
        target, _ = _scaffolded(make_scaffolder, config)
        placed = target / ".github" / "copilot-instructions.md"
        assert placed.is_file()

        _, result = _scaffolded(make_scaffolder, config)

        assert placed.is_file()
        assert not [n for n in result["notes"] if "no longer in config.stacks" in n]


class TestTheReScaffoldPrunesTheOrphan:
    """Detection alone leaves the file; the prune is what makes the config edit converge."""

    def test_dropping_a_stack_removes_the_file_it_placed(self, make_scaffolder):
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python", "ts"]))
        assert (target / TS_INSTRUCTION).is_file()

        _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert not (target / TS_INSTRUCTION).exists()

    def test_an_edited_orphan_is_left_in_place_and_reported(self, make_scaffolder):
        """Only what ai-badger placed and the project never touched may be removed."""
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python", "ts"]))
        edited = target / TS_INSTRUCTION
        edited.write_text("# ours now\n", encoding="utf-8")

        _, result = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert edited.read_text(encoding="utf-8") == "# ours now\n"
        assert any("typescript" in n and "edited" in n for n in result["notes"])

    def test_the_manifest_no_longer_claims_the_pruned_file(self, load_script, make_scaffolder):
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python", "ts"]))

        _scaffolded(make_scaffolder, _config(stacks=["python"]))

        manifest = json.loads((target / ".ai-badger" / "manifest.json").read_text(
            encoding="utf-8"))
        assert [e for e in manifest["entries"] if e.get("stack") == "ts"] == []
