"""`config.exclude`: the project declines a framework artifact, and both entry points obey.

The enforcement point is `Scaffolder.__init__`, so `welcome-ai-badger` and `den-refresh`
cannot disagree. These tests assert the outcome at the target, not the mechanism.
"""
from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from scaffold_helpers import _config

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _excluding(**kinds) -> dict:
    config = _config(agents=["claude"])
    config["exclude"] = {k: list(v) for k, v in kinds.items()}
    return config


def _scaffold(make_scaffolder, config, skills=("task",)):
    target = make_scaffolder.target
    scaf = make_scaffolder(config=config, skills=list(skills))
    result = scaf.run(generated_at="2026-07-28T00:00:00Z")
    return target, result


# ------------------------------------------------------------------------------- schema
def test_config_schema_accepts_an_exclude_block(load_script, root):
    bl = load_script("engine/badger_lib.py")
    config = _excluding(skills=["task"], personas=["architect"],
                        invariants=["tdd-mandatory"], instructions=["python.instructions"])

    assert bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json")) == []


def test_config_schema_rejects_a_misspelled_feature_key(load_script, root):
    """A typo must fail validation rather than silently exclude nothing."""
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"])
    config["exclude"] = {"skils": ["task"]}

    assert bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))


def test_config_schema_rejects_excluding_a_feature_type_with_no_stable_name(load_script, root):
    """templates/hooks/adjustments materialise outputs named otherwise — not excludable."""
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"])
    config["exclude"] = {"templates": ["CLAUDE.md.tmpl"]}

    assert bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))


def test_excludable_features_are_the_name_addressable_ones(load_script):
    bl = load_script("engine/badger_lib.py")

    assert list(bl.EXCLUDABLE_FEATURES) == [ft.name for ft in bl.FEATURE_TYPES
                                            if ft.drift_reports_new]


# --------------------------------------------------------------------------- delivery
def test_an_excluded_skill_is_not_delivered(make_scaffolder):
    target, result = _scaffold(make_scaffolder, _excluding(skills=["call-behaviorist"]),
                               skills=["task", "call-behaviorist"])

    assert not (target / ".ai-badger" / "skills" / "call-behaviorist").exists()
    assert (target / ".ai-badger" / "skills" / "task").is_dir()
    names = [e["name"] for e in result["manifest"]["entries"] if e["feature"] == "skills"]
    assert "call-behaviorist" not in names


def test_an_excluded_invariant_is_neither_copied_nor_rendered(make_scaffolder):
    target, _ = _scaffold(make_scaffolder, _excluding(invariants=["tdd-mandatory"]))

    assert not (target / ".ai-badger" / "invariants" / "tdd-mandatory.md").exists()
    assert "TDD is mandatory" not in (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert (target / ".ai-badger" / "invariants" / "minimal-comments.md").exists()


def test_an_excluded_persona_is_not_copied(make_scaffolder):
    target, _ = _scaffold(make_scaffolder, _excluding(personas=["architect"]))

    assert not (target / ".ai-badger" / "agents" / "architect.md").exists()
    assert (target / ".ai-badger" / "agents" / "code-reviewer.md").exists()


def test_an_excluded_instruction_is_not_copied(make_scaffolder):
    config = _excluding(instructions=["csharp.instructions"])
    config["stacks"] = ["dotnet"]

    target, _ = _scaffold(make_scaffolder, config)

    assert not (target / ".ai-badger" / "instructions" / "csharp.instructions.md").exists()
    assert (target / ".ai-badger" / "instructions" / "documentation.instructions.md").exists()


def test_an_exclusion_matching_no_catalog_item_is_reported_and_not_fatal(make_scaffolder):
    """An upstream deletion must not break the next refresh — §4.2 of the research."""

    target, result = _scaffold(make_scaffolder, _excluding(skills=["no-such-skill"]))

    assert (target / ".ai-badger" / "manifest.json").exists()
    assert any("no-such-skill" in n and "matches no catalog" in n for n in result["notes"])


def test_an_excluded_skill_left_on_disk_is_reported(make_scaffolder):
    """An exclusion stops delivery; it never deletes project-visible content silently."""
    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]),
                          skills=["task", "call-behaviorist"])

    _, result = _scaffold(make_scaffolder, _excluding(skills=["call-behaviorist"]),
                          skills=["task", "call-behaviorist"])

    assert (target / ".ai-badger" / "skills" / "call-behaviorist").is_dir()
    assert any("call-behaviorist" in n and "left on disk" in n for n in result["notes"])


def test_excluding_an_invariant_removes_the_copy_a_previous_run_placed(make_scaffolder):
    """Otherwise feed-badger reads the orphan as a project addition to contribute back."""
    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]))
    assert (target / ".ai-badger" / "invariants" / "tdd-mandatory.md").is_file()

    _scaffold(make_scaffolder, _excluding(invariants=["tdd-mandatory"]))

    assert not (target / ".ai-badger" / "invariants" / "tdd-mandatory.md").exists()


def test_an_edited_copy_of_a_declined_invariant_is_left_in_place(make_scaffolder):
    """Only what ai-badger placed and the project never touched may be removed."""
    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]))
    edited = target / ".ai-badger" / "invariants" / "tdd-mandatory.md"
    edited.write_text("# ours now\n", encoding="utf-8")

    _, result = _scaffold(make_scaffolder, _excluding(invariants=["tdd-mandatory"]))

    assert edited.read_text(encoding="utf-8") == "# ours now\n"
    assert any("tdd-mandatory" in n and "edited" in n for n in result["notes"])


# ------------------------------------------------------------------------ discovery links
def test_excluding_a_skill_prunes_the_claude_link_a_previous_run_placed(make_scaffolder):
    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]),
                          skills=["task", "call-behaviorist"])
    assert (target / ".claude" / "skills" / "call-behaviorist").is_symlink()

    _scaffold(make_scaffolder, _excluding(skills=["call-behaviorist"]),
              skills=["task", "call-behaviorist"])

    assert not (target / ".claude" / "skills" / "call-behaviorist").exists()
    assert not (target / ".claude" / "skills" / "call-behaviorist").is_symlink()
    assert (target / ".claude" / "skills" / "task").is_symlink()


def test_an_excluded_skill_is_not_linked_into_the_hermes_namespace(tmp_path, make_scaffolder):
    home = tmp_path / "home"
    home.mkdir()
    config = _excluding(skills=["call-behaviorist"])
    config["agents"] = ["hermes"]
    scaf = make_scaffolder(config=config, skills=["task", "call-behaviorist"], install=True)
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-28T00:00:00Z")

    namespace = home / ".hermes" / "skills" / "probe"
    assert (namespace / "task").is_symlink()
    assert not (namespace / "call-behaviorist").exists()


def test_a_skill_directory_still_on_disk_is_not_relinked_for_hermes(
        tmp_path, load_script, root):
    """den-refresh re-links from disk, where an excluded skill's copy still sits."""
    scaffold = load_script(SCAFFOLD)
    target = tmp_path / "proj"
    skills_root = target / ".ai-badger" / "skills"
    for name in ("task", "call-behaviorist"):
        (skills_root / name).mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    config = _excluding(skills=["call-behaviorist"])

    with patch("pathlib.Path.home", return_value=home):
        result = scaffold.relink_hermes_skills(target, config, ["task", "call-behaviorist"])

    assert result["created"] == ["task"]


# ------------------------------------------------------------------------- hook wiring
def test_excluding_the_task_skill_wires_no_hook_at_a_missing_script(make_scaffolder):
    """Rewritten commands name a scaffolded script; an absent one is skipped, not wired."""

    target, result = _scaffold(make_scaffolder, _excluding(skills=["task"]),
                               skills=["task", "prompt-markers", "commit-reminder"])

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    wired = [h.get("command", "")
             for entries in settings.get("hooks", {}).values()
             for entry in entries for h in entry.get("hooks", [])]
    assert wired, "the surviving skills' hooks must still be wired"
    for command in wired:
        rel = re.search(r'\$\{CLAUDE_PROJECT_DIR\}/([\w./-]+\.py)', command).group(1)
        assert (target / rel).is_file(), f"wired command names a missing script: {command}"
    assert any("task" in n and "not wired" in n for n in result["notes"])


def test_a_hook_whose_script_was_never_scaffolded_is_skipped(make_scaffolder):
    """A partial scaffold must not leave settings.json pointing at a missing script."""
    target = make_scaffolder.target
    scaf = make_scaffolder(config=_config(agents=["claude"]))

    scaf.wire_hooks()

    assert not (target / ".claude" / "settings.json").exists()
    assert any("session_start_hook.py" in n and "not scaffolded" in n for n in scaf.notes)


def test_excluding_a_skill_unwires_the_hook_a_previous_run_registered(make_scaffolder):
    """The skill's copy stays on disk, so only the declaration can stop its hook."""
    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]),
                          skills=["task", "prompt-markers"])
    settings_path = target / ".claude" / "settings.json"
    assert "session_start_hook.py" in settings_path.read_text(encoding="utf-8")

    _scaffold(make_scaffolder, _excluding(skills=["task"]),
              skills=["task", "prompt-markers"])

    settings = settings_path.read_text(encoding="utf-8")
    assert "session_start_hook.py" not in settings
    assert "user_prompt_hook.py" in settings


# ---------------------------------------------------------------------------- defaults
def test_default_skills_are_the_common_catalog_not_every_declared_scope(load_script, root):
    """DEFAULT_SKILLS must resolve where scaffold_skills looks — features/common/skills."""
    scaffold = load_script(SCAFFOLD)
    bl = load_script("engine/badger_lib.py")

    assert scaffold.DEFAULT_SKILLS == bl.default_skills_in(
        root / "features" / "common" / "skills")
    assert "auto-wm" not in scaffold.DEFAULT_SKILLS


def test_a_default_scaffold_reports_no_unresolvable_skill(load_script, make_scaffolder):
    scaffold = load_script(SCAFFOLD)

    _, result = _scaffold(make_scaffolder, _config(agents=["claude"]),
                          skills=scaffold.DEFAULT_SKILLS)

    assert not [n for n in result["notes"] if "not in index common.skills" in n]


# ------------------------------------------------------------------------------- drift
@pytest.fixture(name="excluded_project")
def _excluded_project(make_scaffolder):
    """A project scaffolded with `call-behaviorist` excluded, plus its manifest."""
    config = _excluding(skills=["call-behaviorist"])
    target, result = _scaffold(make_scaffolder, config,
                               skills=["task", "call-behaviorist"])
    (target / ".ai-badger" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return target, result["manifest"]


def test_drift_does_not_report_an_excluded_item_as_new(excluded_project, load_script, root):
    """Otherwise every refresh nags to install what the project declined."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    target, manifest = excluded_project

    result = drift.compare(root, manifest, stacks=["common"], target=target)

    assert "call-behaviorist" not in [i["name"] for i in result["newItems"]]
