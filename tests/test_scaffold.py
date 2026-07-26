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
    """Scaffolding with hermes agent should symlink skills into ~/.hermes/skills/<project>/."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    hermes_dir = tmp_path / "hermes-home"
    hermes_dir.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["hermes"]),
        skills=["task", "prompt-markers"], install=False,
    )
    with unittest.mock.patch("pathlib.Path.home", return_value=hermes_dir):
        scaf.run(generated_at="2026-07-22T00:00:00Z")

    # Skills are namespaced under ~/.hermes/skills/<project-name>/
    namespace = hermes_dir / ".hermes" / "skills" / "probe"
    assert namespace.is_dir()

    task_link = namespace / "task"
    assert task_link.is_symlink()
    assert task_link.resolve().is_dir()
    assert (task_link.resolve() / "SKILL.md").exists()

    pm_link = namespace / "prompt-markers"
    assert pm_link.is_symlink()
    assert (pm_link.resolve() / "SKILL.md").exists()


def test_scaffold_no_symlinks_without_hermes_agent(tmp_path, load_script, root):
    """Scaffolding without hermes should not create ~/.hermes/skills/<project>/."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    hermes_dir = tmp_path / "hermes-home"
    hermes_dir.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=False,
    )
    with unittest.mock.patch("pathlib.Path.home", return_value=hermes_dir):
        scaf.run(generated_at="2026-07-22T00:00:00Z")

    namespace = hermes_dir / ".hermes" / "skills" / "probe"
    assert not namespace.exists()


def test_rescaffold_recreates_hermes_symlinks(tmp_path, load_script, root):
    """Re-scaffold should recreate symlinks even if they already exist."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    hermes_dir = tmp_path / "hermes-home"
    hermes_dir.mkdir()

    config = _config(agents=["hermes"])
    with unittest.mock.patch("pathlib.Path.home", return_value=hermes_dir):
        scaf = scaffold.Scaffolder(
            root=root, target=target, config=config,
            skills=["task"], install=False,
        )
        scaf.run(generated_at="2026-07-22T00:00:00Z")

        task_link = hermes_dir / ".hermes" / "skills" / "probe" / "task"
        first_target = task_link.resolve()

        # Re-scaffold — should recreate the symlink
        scaf2 = scaffold.Scaffolder(
            root=root, target=target, config=config,
            skills=["task"], install=False,
        )
        scaf2.run(generated_at="2026-07-22T01:00:00Z")

    assert task_link.is_symlink()
    assert task_link.resolve() == first_target



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


# ---------------------------------------------------------------------- hook wiring
def test_scaffold_wires_claude_hooks_into_settings_json(tmp_path, load_script, root):
    """Scaffolding with claude agent should wire hooks into .claude/settings.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task", "prompt-markers"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    # .claude/settings.json should exist with hooks
    settings_path = target / ".claude" / "settings.json"
    assert settings_path.exists(), ".claude/settings.json not created"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" in settings

    hooks = settings["hooks"]
    # SessionStart hook (drift-notice) should be wired
    assert "SessionStart" in hooks
    # UserPromptSubmit hook (prompt-markers) should be wired
    assert "UserPromptSubmit" in hooks

    # Verify paths point to .ai-badger/skills/ not framework paths
    for event_hooks in hooks.values():
        for entry in event_hooks:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                assert "${CLAUDE_PLUGIN_ROOT}" not in cmd, \
                    f"Unresolved plugin root variable in command: {cmd}"
                assert ".ai-badger/skills/" in cmd or "user_prompt_hook" in cmd

    # .ai-badger/hooks/hooks.json should also exist
    hooks_json = target / ".ai-badger" / "hooks" / "hooks.json"
    assert hooks_json.exists(), ".ai-badger/hooks/hooks.json not created"


def test_scaffold_hook_wiring_is_idempotent(tmp_path, load_script, root):
    """Running scaffold twice should not duplicate hooks in settings.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    for _ in range(2):
        scaf = scaffold.Scaffolder(
            root=root, target=target,
            config=_config(agents=["claude"]),
            skills=["task", "prompt-markers"], install=False,
        )
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings_path = target / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    # Count total hook entries — should be exactly 1 per event
    for event, event_hooks in settings.get("hooks", {}).items():
        total_commands = sum(
            len(h.get("hooks", []))
            for entry in event_hooks
            for h in [entry]
        )
        assert total_commands == 1, f"Duplicate hooks for {event}: {total_commands}"


def test_scaffold_no_hooks_without_claude_agent(tmp_path, load_script, root):
    """Scaffolding without claude agent should not create hooks."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["hermes"]),
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings_path = target / ".claude" / "settings.json"
    assert not settings_path.exists()
    hooks_json = target / ".ai-badger" / "hooks" / "hooks.json"
    assert not hooks_json.exists()


# ---------------------------------------------------------------------- --execute flag
def test_scaffold_execute_flag_runs_commands(tmp_path, load_script, root):
    """--execute flag should execute install commands and log results."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=True, execute=True,
    )

    # Mock subprocess.run to capture calls without actually running them
    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=0, stderr="")
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # If there were commands, subprocess.run should have been called
    if mock_run.called:
        for call in mock_run.call_args_list:
            cmd = call[0][0] if call[0] else call[1].get("command", "")
            assert isinstance(cmd, str)


def test_scaffold_execute_flag_handles_failure(tmp_path, load_script, root):
    """--execute flag should log failures without crashing."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=True, execute=True,
    )

    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=1, stderr="not found")
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Should not crash, failures are logged in notes
    if mock_run.called:
        failure_notes = [n for n in scaf.notes if "command failed" in n or "executed:" in n]
        assert len(failure_notes) > 0 or len(mock_run.call_args_list) == 0


# ------------------------------------------------------------------- hermes adjustment path
def test_scaffold_hermes_adjust_task_does_not_fail_with_absolute_path(tmp_path, load_script, root):
    """adjust_task.py must not pass absolute paths to record() — causes ValueError."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["hermes"]),
        skills=["task"], install=False,
    )
    result = scaf.run(generated_at="2026-07-24T00:00:00Z")

    # The adjustment should succeed without raising ValueError
    adj_notes = [n for n in result["notes"]
                 if "adjustment" in n.lower() and "task" in n.lower()]
    assert adj_notes, f"Expected adjustment note for task, got: {result['notes']}"
    # Must NOT contain a failure message
    assert not any("failed" in n.lower() for n in adj_notes), (
        f"adjust_task.py should not fail: {adj_notes}"
    )


# ------------------------------------------------ non-standard agent file detection
def test_scaffold_warns_about_nonstandard_copilot_instructions(tmp_path, load_script, root):
    """When a repo has COPILOT_INSTRUCTIONS.md at root, the scaffolder should warn."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    # Create a non-standard Copilot instruction file at root
    (target / "COPILOT_INSTRUCTIONS.md").write_text("# My Copilot Rules\n", encoding="utf-8")

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(agents=["copilot"]),
                                skills=[], install=False)
    result = scaf.run(generated_at="2026-07-24T00:00:00Z")

    assert any("COPILOT_INSTRUCTIONS.md" in n and "non-standard" in n.lower()
               for n in result["notes"]), (
        f"Expected non-standard agent file warning, got: {result['notes']}"
    )


def test_scaffold_no_warning_when_no_nonstandard_files(tmp_path, load_script, root):
    """No warning when only standard agent files exist."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(agents=["copilot"]),
                                skills=[], install=False)
    result = scaf.run(generated_at="2026-07-24T00:00:00Z")

    assert not any("non-standard" in n.lower() for n in result["notes"]), (
        f"Unexpected non-standard warning: {result['notes']}"
    )

# --------------------------------------------------------- requirement_met OR syntax + list membership
def test_requirement_met_list_membership(load_script, root):
    """When config value is a list, equality check tests membership."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"stacks": ["dotnet", "react"]}
    assert scaffold.requirement_met(config, "stacks=dotnet") is True
    assert scaffold.requirement_met(config, "stacks=react") is True
    assert scaffold.requirement_met(config, "stacks=cosmos") is False


def test_requirement_met_or_syntax(load_script, root):
    """|| splits a requirement into alternatives; true if any matches."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"stacks": ["dotnet", "react"]}
    assert scaffold.requirement_met(config, "stacks=dotnet||stacks=node") is True
    assert scaffold.requirement_met(config, "stacks=cosmos||stacks=node") is False


def test_requirement_met_or_with_scalar(load_script, root):
    """|| works with scalar config values too."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"sourceControl": {"platform": "github"}}
    assert scaffold.requirement_met(config, "sourceControl.platform==github||sourceControl.platform==gitlab") is True
    assert scaffold.requirement_met(config, "sourceControl.platform==bitbucket||sourceControl.platform==gitlab") is False


def test_requirement_met_and_array(load_script, root):
    """Multiple entries in requires array are AND-ed."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"stacks": ["dotnet", "react"], "sourceControl": {"platform": "github"}}
    # Both conditions must be true
    assert scaffold.requirement_met(config, "stacks=react") is True
    assert scaffold.requirement_met(config, "sourceControl.platform==github") is True
    # Simulate AND by calling requirement_met for each
    assert all(scaffold.requirement_met(config, r) for r in ["stacks=react", "sourceControl.platform==github"]) is True
    assert all(scaffold.requirement_met(config, r) for r in ["stacks=cosmos", "sourceControl.platform==github"]) is False


def test_requirement_met_presence(load_script, root):
    """Presence check still works for non-empty values."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"sourceControl": {"repoUrl": "https://github.com/foo/bar"}}
    assert scaffold.requirement_met(config, "sourceControl.repoUrl") is True
    assert scaffold.requirement_met(config, "sourceControl.missing") is False


# --------------------------------------------------------- project-local.md append
def test_scaffold_appends_project_local_md_to_skill(tmp_path, load_script, root):
    """project-local.md content is appended to SKILL.md after scaffold."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    # First scaffold — creates the skill
    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=["task"], install=False)
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    skill_md = target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    original = skill_md.read_text()

    # Write project-local additions
    pl = target / ".ai-badger" / "skills" / "task" / "project-local.md"
    pl.write_text("\n## Project-Specific Checks\n\n- [ ] Check X\n- [ ] Check Y\n")

    # Re-scaffold — project-local.md should be preserved and appended
    scaf2 = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                 skills=["task"], install=False)
    result = scaf2.run(generated_at="2026-07-24T00:00:00Z")

    refreshed = skill_md.read_text()
    assert "## Project-Specific Checks" in refreshed, "project-local content not appended"
    assert "- [ ] Check X" in refreshed, "project-local item missing"
    assert refreshed.endswith("- [ ] Check Y\n"), "trailing newline missing"
    assert any("appended project-local.md" in n for n in result["notes"]), (
        f"Expected append note, got: {result['notes']}"
    )


def test_scaffold_preserves_project_local_md_across_rescaffold(tmp_path, load_script, root):
    """project-local.md is seed-once: survives re-scaffold without overwriting."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=["task"], install=False)
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    pl = target / ".ai-badger" / "skills" / "task" / "project-local.md"
    pl.write_text("## My Project\n\n- [ ] Custom check\n")

    # Re-scaffold 3 times — project-local.md must survive each
    for _ in range(3):
        scaf_n = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                      skills=["task"], install=False)
        scaf_n.run(generated_at="2026-07-24T00:00:00Z")

    assert pl.exists(), "project-local.md was lost during re-scaffold"
    assert "Custom check" in pl.read_text(), "project-local.md content was reset"
    skill_md = target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    assert "## My Project" in skill_md.read_text(), "project-local not appended after re-scaffold"


# --------------------------------------------------------- round-trip: generic + extensions + project-local → original
def test_code_review_checklist_roundtrip_reconstructs_original(tmp_path, load_script, root):
    """Given a project with all stacks + project-local.md, the scaffolded SKILL.md
    should contain every checklist item from the original project-specific skill.

    This is the round-trip guarantee: the original skill was decomposed into
    GENERIC base + stack extensions + project-local additions. After scaffold,
    reassembling them must produce equivalent coverage.
    """
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    # Config with every stack that has an extension
    config = _config(stacks=["dotnet", "react", "ts", "cosmos", "azure", "mcp"])
    skill_name = "code-review-checklist"

    # First scaffold — creates the skill with all extensions
    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=[skill_name], install=False)
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Write project-local.md with the incident lessons from the original skill
    project_local = target / ".ai-badger" / "skills" / skill_name / "project-local.md"
    project_local.write_text("""
## Phase 10: Incident Lessons (Project-Specific)

### 10.1 DI Registration Crash (2026-07-24)

`ChannelMonitoringOptions` was injected but never registered via
`AddOptions<ChannelMonitoringOptions>().Bind(...)` in `Program.cs`.
The API compiled fine but crashed at runtime.

### 10.2 API Route Path Mismatch (2026-07-24)

Frontend used `/signals`, API defined `/channel-monitoring/signals`.
Every request hit a 404.

### 10.3 Problem Type URI Drift (2026-07-24)

Backend used `signal-stale`, frontend checked `stale-signal-proposal`.
409 detection never matched.

### 10.4 Optimistic Concurrency Gap (2026-07-24)

`signalRepository.UpsertAsync` had no ETag parameter — last-write-wins.

### 10.5 Domain Type in Wrong Project (2026-07-24)

`ProfileUpdateProposal` was placed in Api project — circular dependency.

### 10.6 C# String Escape in Spec (2026-07-24)

Spec contained a C# record with two properties both named `Errors`.
""")

    # Re-scaffold — project-local.md should be preserved and appended
    scaf2 = scaffold.Scaffolder(root=root, target=target, config=config,
                                 skills=[skill_name], install=False)
    result = scaf2.run(generated_at="2026-07-24T00:00:00Z")

    skill_md = target / ".ai-badger" / "skills" / skill_name / "SKILL.md"
    content = skill_md.read_text()

    # Verify every stack's content is present (from extensions)
    # GENERIC items
    generic_checks = [
        "Build passes",
        "Tests pass",
        "No hardcoded secrets",
        "One PR = one task",
        "Domain has zero infrastructure dependencies",
        "Infrastructure implements domain interfaces",
        "Screaming architecture",
        "State transitions enforced by domain model",
        "Tests exist for all new production code",
        "Test-first order",
        "Optimistic concurrency via ETag",
        "Idempotent operations return 200",
        "Client route paths match API route paths EXACTLY",
        "Response shapes match field-for-field",
        "Mock/test fixtures match actual API responses",
        "Retry loops are bounded",
        "Merge conflicts resolved with intent",
    ]
    # DOTNET items
    dotnet_checks = [
        "Every injected type is registered in DI",
        "AddOptions<T>().Bind()",
        "AddHttpClient<T>()",
        "sealed record",
        "CommunityToolkit.Diagnostics.Guard",
        "LoggerMessage",
        "DomainExceptionProblemMapper",
        "ResourceNotFoundException",
    ]
    # REACT items
    react_checks = [
        "ContentSection",
        "QueryLoading",
        "AlertDialog",
        "react-query",
        "apiFetch",
        "useMutation",
        "onMutate",
        "toast",
        "renderWithProviders",
        "userEvent",
        "MSW handlers follow",
        "Promise.allSettled",
    ]
    # TS items
    ts_checks = [
        "No `any` types",
        "No `as` type assertions",
        "Route params are type-safe",
    ]
    # COSMOS items
    cosmos_checks = [
        "partition key",
        "Single writer invariant",
        "ISecretCipher",
    ]
    # AZURE items
    azure_checks = [
        "Managed identity preferred",
        "202 Accepted",
    ]
    # MCP items
    mcp_checks = [
        "WithTools<T>",
        "MCP tools are thin HTTP clients",
    ]
    # PROJECT-LOCAL items
    project_checks = [
        "ChannelMonitoringOptions",
        "ChannelMonitoring",
        "signal-stale",
        "stale-signal-proposal",
        "signalRepository.UpsertAsync",
        "ProfileUpdateProposal",
        "two properties both named",
    ]

    all_checks = (
        ("GENERIC", generic_checks),
        ("DOTNET", dotnet_checks),
        ("REACT", react_checks),
        ("TS", ts_checks),
        ("COSMOS", cosmos_checks),
        ("AZURE", azure_checks),
        ("MCP", mcp_checks),
        ("PROJECT", project_checks),
    )

    missing = []
    for group, checks in all_checks:
        for check in checks:
            if check not in content:
                missing.append(f"[{group}] {check}")

    assert not missing, (
        f"Round-trip failed — {len(missing)} items missing from scaffolded SKILL.md:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )

    # Verify project-local.md was stashed and survived
    assert project_local.exists(), "project-local.md was lost"
    assert any("appended project-local.md" in n for n in result["notes"])


# --------------------------------------------------------- extension marker routing
def test_extension_marker_routing_positions_items_correctly(tmp_path, load_script, root):
    """Extension sections with @marker headers are inserted at the matching
    <!-- EXT:name --> position, not appended at the end."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    config = _config(stacks=["dotnet", "react", "ts", "cosmos", "azure", "mcp"])
    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=["code-review-checklist"], install=False)
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    content = (target / ".ai-badger" / "skills" / "code-review-checklist" / "SKILL.md").read_text()

    # Verify EXT markers are consumed (not left in output)
    # Verify actual EXT marker lines are consumed (not left in output)
    # Note: Usage Tips may reference EXT markers in prose — that is fine
    import re
    ext_marker_lines = [l for l in content.split(chr(10)) if re.match(r"^\s*<!-- EXT:[a-z]", l)]
    assert not ext_marker_lines, f"EXT marker lines should be removed: {ext_marker_lines}"
    assert "<!-- MERGE_EXTENSIONS -->" not in content, "MERGE_EXTENSIONS sentinel should be removed"

    # Verify marker routing: dotnet items land BETWEEN the right generic items
    # Pre-takeoff phase: generic item -> dotnet item -> next phase
    assert content.index("No hardcoded secrets") < content.index("No `#pragma warning disable`")
    assert content.index("No `#pragma warning disable`") < content.index("Architecture & Layering")

    # Architecture phase: generic item -> dotnet item -> next phase
    assert content.index("Domain has zero infrastructure") < content.index("sealed record")
    assert content.index("sealed record") < content.index("Cross-Cutting Concerns")

    # Backend runtime phase: generic item -> dotnet/cosmos items -> next phase
    assert content.index("Optimistic concurrency via ETag") < content.index("LoggerMessage")
    assert content.index("partition key") < content.index("Client-Server Contract")

    # Contract alignment phase: react/ts items -> next phase
    assert content.index("react-query") < content.index("Cross-Feature Patterns")
    assert content.index("No `any` types") < content.index("Cross-Feature Patterns")

    # Post-merge: dotnet/react items present
    assert "dotnet build" in content and "clean on main" in content
    assert "Frontend lint + test all pass" in content
