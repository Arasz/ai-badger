"""Dropping a stack from config must converge: drift sees it, and the re-scaffold prunes it.

Drift detected additions (#104) and modifications (#110) but never subtractions, so a removed
stack left its files on disk — and a re-scaffold triggered by anything else dropped the entry
from the manifest, putting the file beyond the reach of every later check (#116).
"""
from __future__ import annotations

import json
import shutil

from scaffold_helpers import _config
from conftest import _test_write

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
        _test_write(fw / "features" / "ts" / "instructions" / "typescript.instructions.md", "ts\n", encoding="utf-8")
        manifest = _manifest([_entry("ts", "features/ts/instructions/typescript.instructions.md",
                                     TS_INSTRUCTION)])

        result = drift.compare(fw, manifest, delivering=["common", "python"], target=tmp_path / "p")

        assert result["orphaned"] == ["features/ts/instructions/typescript.instructions.md"]

    def test_a_configured_stack_is_not_orphaned(self, tmp_path, load_script):
        drift = load_script(DRIFT)
        fw = tmp_path / "fw"
        (fw / "features" / "ts" / "instructions").mkdir(parents=True)
        src = fw / "features" / "ts" / "instructions" / "typescript.instructions.md"
        _test_write(src, "ts\n", encoding="utf-8")
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
        _test_write(src, "inv\n", encoding="utf-8")
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
        _test_write(fw / "features" / "ts" / "instructions" / "typescript.instructions.md", "moved on\n", encoding="utf-8")
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
        _test_write(src, "copilot\n", encoding="utf-8")
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
        _test_write(src, "ts\n", encoding="utf-8")
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
        _test_write(edited, "# ours now\n", encoding="utf-8")

        _, result = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert edited.read_text(encoding="utf-8") == "# ours now\n"
        assert any("typescript" in n and "edited" in n for n in result["notes"])

    def test_the_manifest_no_longer_claims_the_pruned_file(self, load_script, make_scaffolder):
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python", "ts"]))

        _scaffolded(make_scaffolder, _config(stacks=["python"]))

        manifest = json.loads((target / ".ai-badger" / "manifest.json").read_text(
            encoding="utf-8"))
        assert [e for e in manifest["entries"] if e.get("stack") == "ts"] == []


def _inject_entry(target, entry):
    """Append `entry` to the on-disk manifest a prior run left, as if that run had placed it."""
    manifest_path = target / ".ai-badger" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"].append(entry)
    _test_write(manifest_path, json.dumps(manifest), encoding="utf-8")


class TestTheFrameworkDroppedTheItem:
    """A manifest entry whose catalog `source` no longer exists: the framework moved the
    item, not the project — distinct from a stack leaving `config.stacks` (#130)."""

    def test_a_copy_whose_catalog_source_is_gone_is_removed(self, load_script, make_scaffolder):
        bl = load_script("engine/badger_lib.py")
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python"]))
        gone = target / ".ai-badger" / "invariants" / "gone.md"
        _test_write(gone, "# Gone\n\nNo longer in the catalog.\n", encoding="utf-8")
        _inject_entry(target, _entry(
            "common", "features/common/invariants/gone.md", ".ai-badger/invariants/gone.md",
            entry_hash=bl.sha256_file(gone), feature="invariants", name="gone"))

        _, result = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert not gone.exists()
        assert any("no longer in the framework catalog" in n for n in result["notes"])

    def test_an_edited_copy_of_a_dropped_item_is_left_in_place(self, load_script, make_scaffolder):
        bl = load_script("engine/badger_lib.py")
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python"]))
        gone = target / ".ai-badger" / "invariants" / "gone.md"
        _test_write(gone, "# Gone\n\nNo longer in the catalog.\n", encoding="utf-8")
        _inject_entry(target, _entry(
            "common", "features/common/invariants/gone.md", ".ai-badger/invariants/gone.md",
            entry_hash=bl.sha256_file(gone), feature="invariants", name="gone"))
        _test_write(gone, "# Gone\n\nEdited by the project.\n", encoding="utf-8")

        _, result = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert gone.read_text(encoding="utf-8") == "# Gone\n\nEdited by the project.\n"
        assert any("edited" in n for n in result["notes"])

    def test_an_item_still_in_the_catalog_is_never_pruned(self, make_scaffolder):
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        _, result = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert (target / ".ai-badger" / "invariants" / "tdd-mandatory.md").is_file()
        assert not [n for n in result["notes"] if "no longer in the framework catalog" in n]

    def test_a_template_whose_source_is_gone_is_not_reported_as_edited(self, make_scaffolder):
        """`templates`/`adjustments` record the SOURCE hash, not the target's (scaffold.py's
        `record`) — unscoped, a vanished source would always mismatch and misreport an
        untouched CLAUDE.md as edited here."""
        target, _ = _scaffolded(make_scaffolder, _config(stacks=["python"]))
        _inject_entry(target, _entry(
            "common", "features/common/templates/gone.md.tmpl", "CLAUDE.md",
            entry_hash="deadbeef", feature="templates", name="templates/gone.md.tmpl"))

        _, result = _scaffolded(make_scaffolder, _config(stacks=["python"]))

        assert not [n for n in result["notes"]
                   if "CLAUDE.md" in n and ("no longer in the framework catalog" in n
                                            or "was edited here" in n)]
        assert (target / "CLAUDE.md").is_file()


BEHAVIORIST = ".ai-badger/skills/call-behaviorist"


def _catalog_dropped_skill(target, skill_name):
    """Rewrite the manifest as if the framework had deleted `skill_name` from its catalog.

    Every entry the skill placed — the directory and each extension file — points at a source
    path that no longer exists, which is what an upstream deletion or rename leaves behind.
    """
    manifest_path = target / ".ai-badger" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marker = f"/skills/{skill_name}"
    for entry in manifest["entries"]:
        source = entry.get("source", "")
        if marker in source:
            entry["source"] = source.replace(marker, f"{marker}-deleted-upstream")
    _test_write(manifest_path, json.dumps(manifest), encoding="utf-8")


class TestARemovedSkillTakesItsDirectory:
    """A skill the framework deleted must not leave a tree nothing claims or updates (#243)."""

    def test_the_directory_of_a_dropped_skill_is_pruned(self, make_scaffolder):
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        assert (target / BEHAVIORIST / "SKILL.md").is_file()
        _catalog_dropped_skill(target, "call-behaviorist")

        _, result = _scaffolded(make_scaffolder, config, skills=["task"])

        assert not (target / BEHAVIORIST).exists()
        assert any(BEHAVIORIST in n and "no longer in the framework catalog" in n
                   for n in result["notes"])

    def test_the_whole_subtree_goes_not_just_skill_md(self, make_scaffolder):
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        assert (target / BEHAVIORIST / "scripts").is_dir()
        _catalog_dropped_skill(target, "call-behaviorist")

        _scaffolded(make_scaffolder, config, skills=["task"])

        assert not (target / BEHAVIORIST / "scripts").exists()

    def test_an_edited_skill_directory_is_left_in_place(self, make_scaffolder):
        """Only what ai-badger placed and the project never touched may be removed."""
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        edited = target / BEHAVIORIST / "SKILL.md"
        _test_write(edited, "# ours now\n", encoding="utf-8")
        _catalog_dropped_skill(target, "call-behaviorist")

        _, result = _scaffolded(make_scaffolder, config, skills=["task"])

        assert edited.read_text(encoding="utf-8") == "# ours now\n"
        assert any(BEHAVIORIST in n and "edited" in n for n in result["notes"])

    def test_a_rename_leaves_only_the_new_directory(self, make_scaffolder):
        """The common shape of the bug: old name removed, new name delivered in one refresh."""
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config, skills=["call-behaviorist"])
        _catalog_dropped_skill(target, "call-behaviorist")

        _scaffolded(make_scaffolder, config, skills=["mcp-index"])

        assert not (target / BEHAVIORIST).exists()
        assert (target / ".ai-badger" / "skills" / "mcp-index" / "SKILL.md").is_file()

    def test_a_refresh_after_the_prune_is_a_no_op(self, make_scaffolder):
        """`removed` fires once, against the manifest entry; the second run has nothing left."""
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        _catalog_dropped_skill(target, "call-behaviorist")
        _scaffolded(make_scaffolder, config, skills=["task"])

        _, result = _scaffolded(make_scaffolder, config, skills=["task"])

        assert not (target / BEHAVIORIST).exists()
        assert not [n for n in result["notes"] if BEHAVIORIST in n]

    def test_a_directory_deleted_by_hand_is_not_reported(self, make_scaffolder):
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        _catalog_dropped_skill(target, "call-behaviorist")
        shutil.rmtree(target / BEHAVIORIST)

        _, result = _scaffolded(make_scaffolder, config, skills=["task"])

        assert not [n for n in result["notes"] if BEHAVIORIST in n]

    def test_a_project_owned_file_keeps_the_directory(self, make_scaffolder):
        """project-local.md is content the framework never wrote and cannot put back (#15)."""
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        local = target / BEHAVIORIST / "project-local.md"
        _test_write(local, "## Ours\n\nProject rule.\n", encoding="utf-8")
        # Re-scaffolded so the recorded hash covers it: an unrecorded file already reads as an
        # edit, and this must hold for one the manifest knows about.
        _scaffolded(make_scaffolder, config, skills=["task", "call-behaviorist"])
        _catalog_dropped_skill(target, "call-behaviorist")

        _, result = _scaffolded(make_scaffolder, config, skills=["task"])

        assert local.is_file()
        assert any(BEHAVIORIST in n and "project-local.md" in n for n in result["notes"])

    def test_an_edited_extension_file_keeps_the_skill_directory(self, make_scaffolder):
        """The directory entry owns its subtree, so an edit anywhere inside it stops the prune."""
        config = _config(stacks=["python"], agents=["claude"])
        target, _ = _scaffolded(make_scaffolder, config, skills=["task"])
        extension = target / ".ai-badger" / "skills" / "task" / "extensions" / "claude" \
            / "extension.md"
        _test_write(extension, "# ours now\n", encoding="utf-8")
        _catalog_dropped_skill(target, "task")

        _scaffolded(make_scaffolder, config, skills=[])

        assert extension.read_text(encoding="utf-8") == "# ours now\n"
        assert (target / ".ai-badger" / "skills" / "task" / "SKILL.md").is_file()

    def test_a_declined_skill_directory_still_stays(self, make_scaffolder):
        """`config.exclude` declines a skill the framework still ships — unchanged by #243."""
        config = _config(stacks=["python"])
        target, _ = _scaffolded(make_scaffolder, config,
                                skills=["task", "call-behaviorist"])
        declining = dict(config, exclude={"skills": ["call-behaviorist"]})

        _, result = _scaffolded(make_scaffolder, declining,
                                skills=["task", "call-behaviorist"])

        assert (target / BEHAVIORIST).is_dir()
        assert any("call-behaviorist" in n and "left on disk" in n for n in result["notes"])
