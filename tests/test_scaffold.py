"""Tests for features/common/skills/welcome-ai-badger/scripts/scaffold.py: Scaffolder behavior.

test_scaffold_no_test_leak.py already covers the test-file anti-leak guarantee; this file
exercises preserve-vs-managed file handling, no-stack-leakage, manifest shape, and the
GitHub extension embed gate.
"""
from __future__ import annotations

import importlib
import json
import os
import re
from unittest.mock import patch


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
def _hermes_scaffold(scaffold, root, target, home, skills, agents=("hermes",)):
    """Scaffold with Path.home patched to *home*; return the hermes namespace dir."""
    scaf = scaffold.Scaffolder(
        root=root, target=target, config=_config(agents=list(agents)),
        skills=list(skills), install=False,
    )
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-22T00:00:00Z")
    return home / ".hermes" / "skills" / "probe"


def _hermes_case(tmp_path):
    """Return (target, home) directories for a hermes symlink test."""
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "hermes-home"
    home.mkdir()
    return target, home


def test_scaffold_creates_hermes_skill_symlinks(tmp_path, load_script, root):
    """Each scaffolded skill is symlinked into ~/.hermes/skills/<project>/ (ADR 0003)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task", "prompt-markers"])

    assert namespace.is_dir() and not namespace.is_symlink()
    for name in ("task", "prompt-markers"):
        link = namespace / name
        assert link.is_symlink()
        assert (link.resolve() / "SKILL.md").exists()


def test_scaffold_hermes_symlinks_are_relative(tmp_path, load_script, root):
    """Links are relative so no absolute home path is baked into the namespace."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task"])

    raw = os.readlink(str(namespace / "task"))
    assert not os.path.isabs(raw)


def test_scaffold_no_symlinks_without_hermes_agent(tmp_path, load_script, root):
    """Scaffolding without hermes should not create ~/.hermes/skills/<project>/."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task"], agents=("claude",))

    assert not namespace.exists()


def test_rescaffold_recreates_hermes_symlinks(tmp_path, load_script, root):
    """Re-scaffold leaves the namespace with a working link for every skill."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task"])
    first_target = (namespace / "task").resolve()
    _hermes_scaffold(scaffold, root, target, home, ["task"])

    assert (namespace / "task").is_symlink()
    assert (namespace / "task").resolve() == first_target


def test_scaffold_preserves_foreign_dirs_in_namespace(tmp_path, load_script, root):
    """A real directory ai-badger did not place survives a re-scaffold byte-identical."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task"])
    foreign = namespace / "agent-skill-discovery"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("# hermes-authored\n", encoding="utf-8")

    _hermes_scaffold(scaffold, root, target, home, ["task"])

    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# hermes-authored\n"


def test_scaffold_removes_stale_managed_symlinks(tmp_path, load_script, root):
    """A link for a skill no longer scaffolded is unlinked on re-scaffold."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task", "prompt-markers"])
    assert (namespace / "prompt-markers").is_symlink()

    _hermes_scaffold(scaffold, root, target, home, ["task"])

    assert not (namespace / "prompt-markers").is_symlink()
    assert (namespace / "task").is_symlink()


def test_scaffold_replaces_broken_symlink(tmp_path, load_script, root):
    """A dangling managed link is relinked rather than left broken."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task"])
    link = namespace / "task"
    link.unlink()
    link.symlink_to(
        os.path.relpath(target / ".ai-badger" / "skills" / "task-gone", namespace)
    )
    assert not link.exists()

    _hermes_scaffold(scaffold, root, target, home, ["task"])

    assert link.is_symlink() and (link.resolve() / "SKILL.md").exists()


def test_scaffold_symlinks_learned_skills_dir(tmp_path, load_script, root):
    """The learned/ tree is reachable through the namespace (one link covers it)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target, home = _hermes_case(tmp_path)
    learned = target / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes"
    learned.mkdir(parents=True)
    (learned / "SKILL.md").write_text("# apple-notes\n", encoding="utf-8")

    namespace = _hermes_scaffold(scaffold, root, target, home, ["task"])

    link = namespace / "learned"
    assert link.is_symlink()
    assert (link.resolve() / "apple" / "apple-notes" / "SKILL.md").exists()



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
    # SessionStart hook (session-start-tracking) should be wired
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


def _wired_scripts(settings: dict, event: str) -> list:
    """The script each wired command for one event ends in.

    Compared by trailing filename, never by substring of the whole command: a
    command embeds an absolute path, and under pytest that path carries the test's
    own name.
    """
    return [h.get("command", "").rstrip('"').rsplit("/", 1)[-1]
            for entry in settings.get("hooks", {}).get(event, [])
            for h in entry.get("hooks", [])]


def test_session_start_hook_is_the_wired_session_start_command(tmp_path, load_script, root):
    """The scaffolded SessionStart hook must be session_start_hook.py itself (F-07).

    Asserting only that *some* SessionStart hook exists is what let a hook that cannot
    resolve its plugin root in a consumer pass as the session-recording feature.
    """
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaffold.Scaffolder(root=root, target=target, config=_config(agents=["claude"]),
                        skills=["task"], install=False).run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    scripts = _wired_scripts(settings, "SessionStart")
    assert "session_start_hook.py" in scripts, scripts


def test_consumer_settings_do_not_wire_the_plugin_only_drift_hook(tmp_path, load_script, root):
    """Drift notice runs from the plugin's own hooks.json; a consumer copy can never
    locate the plugin root, so wiring it there only looks like the feature works (F-07)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaffold.Scaffolder(root=root, target=target, config=_config(agents=["claude"]),
                        skills=["task"], install=False).run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "drift_notice_hook.py" not in _wired_scripts(settings, "SessionStart")


def test_plugin_registers_drift_notice_from_its_own_hooks_json(root):
    """The plugin-provided hooks.json is what actually fires drift notice for consumers."""
    plugin_hooks = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    commands = [h["command"]
                for entry in plugin_hooks["hooks"]["SessionStart"]
                for h in entry["hooks"]]
    assert any("${CLAUDE_PLUGIN_ROOT}" in cmd and "drift_notice_hook.py" in cmd
               for cmd in commands), commands
    plugin_manifest = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_manifest.get("hooks") == "./hooks/hooks.json"


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


def test_scaffold_hook_dedup_does_not_duplicate_multi_hook_entries(tmp_path, load_script, root):
    """Dedup must not re-append an entry when only some of its hooks are new.

    Regression: the old code checked each inner hook individually but appended
    the entire outer entry, so an entry with N hooks could be appended with
    hooks that already existed in another entry — producing duplicates.
    """
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    # existing: one entry with hook-a
    existing = {"SessionStart": [
        {"matcher": "", "hooks": [{"type": "command", "command": "hook-a"}]},
    ]}
    # new: entry with hook-a + hook-b — only hook-b should be appended
    new = {"SessionStart": [
        {"matcher": "m", "hooks": [
            {"type": "command", "command": "hook-a"},
            {"type": "command", "command": "hook-b"},
        ]},
    ]}
    scaffold.merge_hooks(existing, new)
    entries = existing["SessionStart"]
    all_cmds = [h["command"] for e in entries for h in e["hooks"]]
    assert all_cmds.count("hook-a") == 1, f"hook-a duplicated: {all_cmds}"
    assert "hook-b" in all_cmds


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


# ---------------------------------------------------------------------- external tools catalog
def test_scaffold_injects_catalog_external_tool_into_claude_md(tmp_path, load_script, root):
    """External tools from features/common/external-tools.json are auto-injected."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "code-review-graph" in claude_md, "Catalog tool not injected into CLAUDE.md"


def test_scaffold_catalog_tool_generates_mcp_json(tmp_path, load_script, root):
    """Catalog tools with generate_mcp_json produce .mcp.json entries."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    mcp_json = target / ".mcp.json"
    assert mcp_json.exists(), ".mcp.json not created"
    mcp = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "code-review-graph" in mcp.get("mcpServers", {})


def test_scaffold_user_external_tools_override_catalog(tmp_path, load_script, root):
    """config.externalTools overrides catalog tools on name conflict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    config = _config(agents=["claude"])
    config["externalTools"] = [{
        "name": "code-review-graph",
        "package": "code-review-graph",
        "command": "custom-command",
        "instructions": "CUSTOM INSTRUCTIONS",
        "generate_mcp_json": True,
    }]

    scaf = scaffold.Scaffolder(
        root=root, target=target, config=config,
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "CUSTOM INSTRUCTIONS" in claude_md, "User override not applied"
    assert "MCP Tools: code-review-graph" not in claude_md, "Catalog instructions not overridden"


def test_collect_external_tools_reads_common_catalog(tmp_path, load_script, root):
    """_collect_external_tools reads features/common/external-tools.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=False,
    )
    tools = scaf._collect_external_tools()
    names = [t["name"] for t in tools]
    assert "code-review-graph" in names


def test_check_dependencies_surfaces_optional_hints_as_notes(tmp_path, load_script, root):
    """Optional-dependency hints (e.g. code-review-graph[embeddings]) must reach scaffold notes
    so the user is told about silently-degraded semantic search, not left to discover it later."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    dependency_check = importlib.import_module("dependency_check")

    target = tmp_path / "proj"
    target.mkdir()

    hint = "code-review-graph-embeddings: not installed. Install with: /venv/bin/python3 -m pip install ..."

    def fake_run_dependency_check(root_, target_, features=None):
        return {"installed": [], "already_present": [], "errors": [], "hints": [hint]}

    with patch.object(dependency_check, "run_dependency_check", side_effect=fake_run_dependency_check), \
         patch.object(dependency_check, "get_venv_python", return_value=None):
        scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                    skills=["code-review-graph"], install=False)
        scaf._check_dependencies()

    assert any(hint in n for n in scaf.notes)


def test_merge_external_tools_user_overrides_catalog(load_script):
    """_merge_external_tools: user tools override catalog on name conflict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    catalog = [{"name": "tool-a", "package": "p", "command": "c1", "instructions": "orig"}]
    user = [{"name": "tool-a", "package": "p", "command": "c2", "instructions": "override"}]

    merged = scaffold.Scaffolder._merge_external_tools(catalog, user)
    assert len(merged) == 1
    assert merged[0]["command"] == "c2"
    assert merged[0]["instructions"] == "override"


# ------------------------------------------------------------------- managed headers (F-08)
_HEADER_RE = re.compile(r"Source of truth(?: for this file)?: `?([^\s`]+)")


def _referenced_path(text: str):
    """The .ai-badger/ path a managed banner or self-reference names, or None."""
    match = _HEADER_RE.search(text)
    return match.group(1).rstrip(".") if match else None


def _managed_files(target) -> list:
    """Every scaffolded file carrying the managed-by-ai-badger banner."""
    found = []
    for path in sorted(target.rglob("*.md")):
        if path.is_file() and path.read_text(encoding="utf-8").startswith("<!-- Managed by"):
            found.append(path)
    return found


def _scaffold_all_agents(scaffold, root, target):
    scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude", "copilot", "hermes", "junie"]),
        skills=["task"], install=False,
    ).run(generated_at="2026-07-24T00:00:00Z")


def test_every_managed_header_points_at_an_existing_file(tmp_path, load_script, root):
    """The banner is the first line an agent reads about where durable edits go (F-08)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    _scaffold_all_agents(scaffold, root, target)

    managed = _managed_files(target)
    assert managed, "expected at least one managed file"
    for path in managed:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        referenced = _referenced_path(first_line)
        assert referenced, f"{path.relative_to(target)}: unparseable header {first_line!r}"
        assert (target / referenced).exists(), \
            f"{path.relative_to(target)} points at {referenced}, which does not exist"


def test_managed_body_self_reference_matches_the_banner(tmp_path, load_script, root):
    """A rendered file's own 'Source of truth for this file' must name its own source."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    _scaffold_all_agents(scaffold, root, target)

    body = (target / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    self_ref = next(line for line in body.splitlines() if "Source of truth for this file" in line)
    assert _referenced_path(self_ref) == ".ai-badger/copilot-instructions.md"
