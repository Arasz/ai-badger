"""Tests for features/common/skills/welcome-ai-badger/scripts/scaffold.py: Scaffolder behavior.

test_scaffold_no_test_leak.py already covers the test-file anti-leak guarantee; this file
exercises preserve-vs-managed file handling, no-stack-leakage, manifest shape, and the
GitHub extension embed gate.
"""
from __future__ import annotations

import json


def _config(stacks=None, source_control=None, commands=None, agents=None) -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": stacks if stacks is not None else ["dotnet"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": source_control if source_control is not None else
            {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": commands if commands is not None else {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


# --------------------------------------------------------- preserve-by-default / overwrite
def test_scaffold_preserves_hand_authored_claude_md_by_default(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    hand_authored = "# My Curated Guidance\n\nDo not touch this.\n"
    (target / "CLAUDE.md").write_text(hand_authored, encoding="utf-8")

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == hand_authored
    assert (target / ".ai-badger" / "CLAUDE.md").exists()  # source of truth still written
    assert any("preserved hand-authored" in n for n in result["notes"])


def test_scaffold_overwrite_replaces_hand_authored_claude_md(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    (target / "CLAUDE.md").write_text("# My Curated Guidance\n", encoding="utf-8")

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False, overwrite=True)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    content = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert content.startswith(scaffold._MANAGED_PREFIX)


def test_scaffold_managed_file_refreshes_on_second_run_without_overwrite(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target,
                                 config=_config(commands={"build": "dotnet build"}),
                                 skills=[], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")
    first = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "dotnet build" in first
    assert first.startswith(scaffold.MANAGED_HEADER.split("{name}", 1)[0])

    scaf2 = scaffold.Scaffolder(root=root, target=target,
                                 config=_config(commands={"build": "dotnet build -c Release"}),
                                 skills=[], install=False)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")
    second = (target / "CLAUDE.md").read_text(encoding="utf-8")

    assert "dotnet build -c Release" in second


# ------------------------------------------------------------------------- new-file creation
def test_scaffold_creates_new_skill_dir_on_first_run(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    assert not (target / ".ai-badger").exists()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / ".ai-badger" / "skills" / "task").is_dir()
    skill_entries = [e for e in result["manifest"]["entries"]
                     if e["feature"] == "skills" and e["name"] == "task"]
    assert len(skill_entries) == 1


# ------------------------------------------------------------------------------- no leakage
def test_scaffold_no_stack_leakage(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    aib = target / ".ai-badger"
    assert (aib / "instructions" / "csharp.instructions.md").exists()
    assert (aib / "agents" / "dotnet-engineer.md").exists()  # personas land under agents/

    all_instruction_names = {p.name for p in (aib / "instructions").glob("*")}
    assert "python.instructions.md" not in all_instruction_names
    assert "react.instructions.md" not in all_instruction_names

    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "frontend-engineer.md" not in all_persona_names


def test_scaffold_no_stack_leakage_react_excludes_dotnet(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target,
                                config=_config(stacks=["react", "ts", "node"]),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    aib = target / ".ai-badger"
    assert (aib / "agents" / "frontend-engineer.md").exists()
    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "dotnet-engineer.md" not in all_persona_names


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
    expected_keys = {"feature", "stack", "name", "source", "target",
                      "frameworkVersion", "hash"}
    for entry in entries:
        assert set(entry.keys()) == expected_keys
        assert entry["source"].startswith("features/")
        assert len(entry["hash"]) == 64
        int(entry["hash"], 16)  # must be valid hex
        assert entry["frameworkVersion"] == result["manifest"]["frameworkVersion"]

    manifest_on_disk = (target / ".ai-badger" / "manifest.json")
    assert manifest_on_disk.exists()


# ------------------------------------------------------------------- github extension gate
def test_scaffold_github_extension_embedded_when_platform_github(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(source_control={
        "platform": "github", "repoUrl": "https://github.com/foo/bar", "projectUrl": None,
    })

    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    ext_dir = target / ".ai-badger" / "skills" / "task" / "extensions" / "github"
    assert ext_dir.is_dir()
    assert any("embedded extension 'github'" in n for n in result["notes"])


def test_scaffold_github_extension_not_embedded_when_platform_none(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(source_control={"platform": "none", "repoUrl": None, "projectUrl": None})

    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    ext_dir = target / ".ai-badger" / "skills" / "task" / "extensions" / "github"
    assert not ext_dir.exists()
    assert any("skipped (config requirements not met)" in n for n in result["notes"])


# ---------------------------------------------------------------------- seed-once vs managed
# GitHub issue Arasz/ai-badger#15: re-scaffolding a live project must never destroy project-owned
# data. state.json (a task index) and features/common/skills/prompt-markers/markers-context.json (a project's
# customized marker config) are SEED-ONCE: the framework writes them on first scaffold, then the
# project owns them. Managed files (SKILL.md, scripts) inside the very same skill directory must
# still refresh normally -- only the specific seed-once sub-file is protected.
def test_scaffold_state_json_mutation_survives_second_scaffold(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=[], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")

    state_path = target / ".ai-badger" / "state.json"
    assert state_path.exists()
    mutated = {"lastUpdated": "2026-07-19T00:00:00Z", "next": None,
               "completedTasks": [{"id": 1}, {"id": 2}, {"id": 3},
                                   {"id": 4}, {"id": 5}, {"id": 6}, {"id": 7}, {"id": 8}]}
    state_path.write_text(json.dumps(mutated), encoding="utf-8")

    scaf2 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=[], install=False)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(state_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_prompt_markers_config_mutation_survives_second_scaffold(
    tmp_path, load_script, root
):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["prompt-markers"], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")

    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    assert marker_path.exists()
    mutated = {"markers": {"h": "custom-hint-marker"}}
    marker_path.write_text(json.dumps(mutated), encoding="utf-8")

    scaf2 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["prompt-markers"], install=False)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(marker_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_prompt_markers_skill_md_still_refreshes_when_config_is_preserved(
    tmp_path, load_script, root
):
    """Guard against over-correction: only markers-context.json is seed-once. SKILL.md (a
    managed file living in the very same skill directory) must still be refreshed to the
    framework's current content on re-scaffold."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["prompt-markers"], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")

    skill_dir = target / ".ai-badger" / "skills" / "prompt-markers"
    marker_path = skill_dir / "markers-context.json"
    marker_path.write_text(json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")
    skill_md_path = skill_dir / "SKILL.md"
    original_skill_md = skill_md_path.read_text(encoding="utf-8")
    skill_md_path.write_text("# locally tampered content, should be refreshed away\n",
                              encoding="utf-8")

    scaf2 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["prompt-markers"], install=False)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")

    assert skill_md_path.read_text(encoding="utf-8") == original_skill_md
    assert json.loads(marker_path.read_text(encoding="utf-8")) == {"markers": {"h": "custom"}}


def test_scaffold_seeds_state_json_on_first_run(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    state_path = target / ".ai-badger" / "state.json"
    assert state_path.exists()
    template = (root / "features" / "common" / "templates" / "state.json")
    assert json.loads(state_path.read_text(encoding="utf-8")) == json.loads(
        template.read_text(encoding="utf-8"))


def test_scaffold_seeds_prompt_markers_config_on_first_run(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=["prompt-markers"], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    assert marker_path.exists()
    template = root / "features" / "common" / "skills" / "prompt-markers" / "markers-context.json"
    assert json.loads(marker_path.read_text(encoding="utf-8")) == json.loads(
        template.read_text(encoding="utf-8"))


def test_scaffold_model_json_seed_once_regression_pin(tmp_path, load_script, root):
    """model.json's seed-once behavior is already correct but had zero test coverage before
    this pin -- nothing stopped a refactor from silently breaking it."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=[], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")

    model_path = target / ".ai-badger" / "agent-instructions" / "model.json"
    assert model_path.exists()
    mutated = {"version": 1, "files": {"custom.md": "custom-instructions"}}
    model_path.write_text(json.dumps(mutated), encoding="utf-8")

    scaf2 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=[], install=False)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(model_path.read_text(encoding="utf-8")) == mutated


# ---------------------------------------------------------------------- hermes skill symlinks
def test_scaffold_creates_hermes_skill_symlinks(tmp_path, load_script, root):
    """Scaffolding with hermes agent should symlink .hermes/skills/ → .ai-badger/skills/."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["hermes"]),
        skills=["task", "prompt-markers"], install=False,
    )
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    hermes_skills = target / ".hermes" / "skills"
    assert hermes_skills.is_dir()

    task_link = hermes_skills / "task"
    assert task_link.is_symlink()
    assert task_link.resolve().is_dir()
    assert (task_link.resolve() / "SKILL.md").exists()

    pm_link = hermes_skills / "prompt-markers"
    assert pm_link.is_symlink()
    assert (pm_link.resolve() / "SKILL.md").exists()


def test_scaffold_no_symlinks_without_hermes_agent(tmp_path, load_script, root):
    """Scaffolding without hermes should not create .hermes/skills/ symlinks."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # .hermes/skills should not exist
    hermes_skills = target / ".hermes" / "skills"
    assert not hermes_skills.exists() or not any(hermes_skills.iterdir())


def test_rescaffold_recreates_hermes_symlinks(tmp_path, load_script, root):
    """Re-scaffold should recreate symlinks even if they already exist."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    config = _config(agents=["hermes"])
    scaf = scaffold.Scaffolder(
        root=root, target=target, config=config,
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    task_link = target / ".hermes" / "skills" / "task"
    first_target = task_link.resolve()

    # Re-scaffold — should recreate the symlink
    scaf2 = scaffold.Scaffolder(
        root=root, target=target, config=config,
        skills=["task"], install=False,
    )
    scaf2.run(generated_at="2026-07-22T01:00:00Z")

    assert task_link.is_symlink()
    assert task_link.resolve() == first_target


def test_scaffold_registers_hermes_external_dirs(tmp_path, load_script, root):
    """Scaffolding with hermes should register .hermes/skills in external_dirs."""
    import yaml
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    # Create a fake hermes home with .hermes/config.yaml
    hermes_dir = tmp_path / "hermes-home"
    (hermes_dir / ".hermes").mkdir(parents=True)
    hermes_config = hermes_dir / ".hermes" / "config.yaml"
    hermes_config.write_text(yaml.dump({"skills": {"external_dirs": []}}),
                             encoding="utf-8")

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["hermes"]),
        skills=["task"], install=False,
    )

    # Patch Path.home() to use our fake hermes dir
    import unittest.mock
    with unittest.mock.patch("pathlib.Path.home", return_value=hermes_dir):
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Verify the project was registered
    cfg = yaml.safe_load(hermes_config.read_text(encoding="utf-8"))
    ext_dirs = cfg.get("skills", {}).get("external_dirs", [])
    skills_path = str((target / ".hermes" / "skills").resolve())
    assert skills_path in ext_dirs


def test_scaffold_no_external_dirs_without_hermes(tmp_path, load_script, root):
    """Scaffolding without hermes should not modify external_dirs."""
    import yaml
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    hermes_dir = tmp_path / "hermes-home"
    (hermes_dir / ".hermes").mkdir(parents=True)
    hermes_config = hermes_dir / ".hermes" / "config.yaml"
    hermes_config.write_text(yaml.dump({"skills": {"external_dirs": []}}),
                             encoding="utf-8")

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=False,
    )

    import unittest.mock
    with unittest.mock.patch("pathlib.Path.home", return_value=hermes_dir):
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    cfg = yaml.safe_load(hermes_config.read_text(encoding="utf-8"))
    ext_dirs = cfg.get("skills", {}).get("external_dirs", [])
    assert ext_dirs == []


def test_scaffold_reset_seed_files_flag_forces_reset(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["prompt-markers"], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")

    state_path = target / ".ai-badger" / "state.json"
    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    state_path.write_text(json.dumps({"lastUpdated": "mutated", "next": None,
                                       "completedTasks": []}), encoding="utf-8")
    marker_path.write_text(json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")

    scaf2 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["prompt-markers"], install=False,
                                 reset_seed_files=True)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")

    template_state = json.loads(
        (root / "features" / "common" / "templates" / "state.json").read_text(encoding="utf-8"))
    template_marker = json.loads(
        (root / "features" / "common" / "skills" / "prompt-markers" / "markers-context.json").read_text(encoding="utf-8"))
    assert json.loads(state_path.read_text(encoding="utf-8")) == template_state
    assert json.loads(marker_path.read_text(encoding="utf-8")) == template_marker
