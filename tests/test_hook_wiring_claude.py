"""Tests for features/common/skills/welcome-ai-badger/scripts/hook_wiring.py: Claude hook wiring.

Same defect class #150 fixed on the Copilot side (adjust_hooks.py), in the branch #150 did not
touch: a manifest entry naming no `script` used to adopt every command registered for its event
via `select_hooks(..., None)`, and the `hook_scripts[0]` fallback picked an arbitrary glob match
instead of the manifest's named script. `prompt-markers` is the one manifest entry that names no
`script`, and it worked only because `hooks.json` had no `UserPromptSubmit` key and its skill
directory happened to hold exactly one `*_hook.py` — both accidents #147 was about to break at
once (issue #152).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from scaffold_helpers import _config

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"


def _load(load_script, root, name):
    """Load one welcome-ai-badger script with its sibling modules importable."""
    for entry in (str(root / SCRIPTS), str(root / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/{name}.py")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _fake_framework(tmp_path, manifest_hooks, source_hooks=None):
    """A minimal framework root with a hand-built hooks-manifest.json / hooks.json."""
    fw_root = tmp_path / "framework"
    _write_json(fw_root / "features" / "common" / "hooks" / "hooks-manifest.json",
                {"hooks": manifest_hooks})
    _write_json(fw_root / "features" / "common" / "hooks" / "hooks.json",
                {"hooks": source_hooks or {}})
    return fw_root


def _wiring(load_script, real_root, fw_root, target, manifest_hooks, source_hooks=None):
    """A HookWiring collaborator over a hand-built context: fake framework, real target."""
    ctx_mod = _load(load_script, real_root, "scaffold_context")
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"])
    ctx = ctx_mod.ScaffoldContext(
        root=fw_root, target=target, aib=target / ".ai-badger", config=config,
        index={}, stacks=[], skills=[], excluded=bl.exclusions(config),
    )
    return _load(load_script, real_root, "hook_wiring").HookWiring(ctx), ctx


def _wired_scripts(target: Path, event: str) -> list:
    """The trailing filename of every command wired for one event, or [] if none was wired."""
    settings_path = target / ".claude" / "settings.json"
    if not settings_path.exists():
        return []
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    return [(re.search(r"([\w.-]+\.py)", h.get("command", "")) or [""])[0].rsplit("/", 1)[-1]
            for entry in settings.get("hooks", {}).get(event, [])
            for h in entry.get("hooks", [])]


def _skill_scripts(target: Path, skill: str, *names: str) -> Path:
    """Create empty `*_hook.py` files under a skill's scaffolded scripts/ dir."""
    scripts_dir = target / ".ai-badger" / "skills" / skill / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (scripts_dir / name).write_text("", encoding="utf-8")
    return scripts_dir


# --------------------------------------------------------------------- test 1: hook_scripts[0]
def test_manifest_named_script_is_wired_not_whichever_glob_sorts_first(tmp_path, load_script,
                                                                        root):
    """Four candidates on disk, manifest names one — that one is wired, not glob order."""
    target = tmp_path / "proj"
    _skill_scripts(target, "task", "a_hook.py", "b_hook.py", "c_hook.py", "stop_hook.py")

    manifest_hooks = [
        {"name": "task",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json",
                                "event": "Stop", "script": "stop_hook.py"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)
    hooks, _ctx = _wiring(load_script, root, fw_root, target, manifest_hooks)

    hooks.wire()

    assert _wired_scripts(target, "Stop") == ["stop_hook.py"]


def test_a_wired_command_survives_the_script_missing_at_runtime(tmp_path, load_script, root):
    """In a git worktree session ${CLAUDE_PROJECT_DIR} resolves to the main checkout, which may
    not carry the script — and a missing file BLOCKS the call a PreToolUse hook gates. The
    wired command tries the project copy, then the session cwd's copy, then says it skipped."""
    target = tmp_path / "proj"
    _skill_scripts(target, "task", "stop_hook.py")
    manifest_hooks = [
        {"name": "task",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json",
                                "event": "Stop", "script": "stop_hook.py"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)
    hooks, _ctx = _wiring(load_script, root, fw_root, target, manifest_hooks)

    hooks.wire()

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for entry in settings["hooks"]["Stop"] for h in entry["hooks"]]
    rel = ".ai-badger/skills/task/scripts/stop_hook.py"
    assert commands == [
        f'if [ -f "${{CLAUDE_PROJECT_DIR}}/{rel}" ]; then python3 "${{CLAUDE_PROJECT_DIR}}/{rel}"; '
        f'elif [ -f "{rel}" ]; then python3 "{rel}"; '
        f'else echo \'{{"systemMessage": "ai-badger: {rel} not found - hook skipped"}}\'; fi']


def test_rewiring_replaces_a_previously_wired_command_shape(tmp_path, load_script, root):
    """A framework upgrade changes the wired command's shape — the old registration must be
    superseded by script identity, not accumulate beside the new one."""
    target = tmp_path / "proj"
    _skill_scripts(target, "task", "stop_hook.py")
    rel = ".ai-badger/skills/task/scripts/stop_hook.py"
    _write_json(target / ".claude" / "settings.json", {"hooks": {"Stop": [
        {"hooks": [{"type": "command",
                    "command": f'[ ! -f "${{CLAUDE_PROJECT_DIR}}/{rel}" ] || '
                               f'python3 "${{CLAUDE_PROJECT_DIR}}/{rel}"'}]},
    ]}})
    manifest_hooks = [
        {"name": "task",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json",
                                "event": "Stop", "script": "stop_hook.py"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)
    hooks, _ctx = _wiring(load_script, root, fw_root, target, manifest_hooks)

    hooks.wire()

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for entry in settings["hooks"]["Stop"] for h in entry["hooks"]]
    assert len(commands) == 1, commands
    assert commands[0].startswith('if [ -f ')


def test_a_script_path_that_could_break_out_of_the_shell_string_is_not_guarded(load_script, root):
    """The guard interpolates the path into a shell command — quotes and $() must not reach it."""
    wiring = _load(load_script, root, "hook_wiring")
    hostile = 'python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/x$(rm -rf ~).py"'

    assert wiring.guarded(hostile) == hostile


# ------------------------------------------------- test 2: the #147 regression, written first
def test_script_less_entry_does_not_adopt_a_neighbours_hooks_json_command(tmp_path, load_script,
                                                                           root):
    """A second UserPromptSubmit command lands in hooks.json for another hook.

    prompt-markers' manifest entry names no script (today's real shape). Before #152, this made
    `select_hooks(..., None)` return the *whole* event's commands, so prompt-markers would adopt
    the newcomer's command — wiring the wrong script under its own name and never wiring its own
    `user_prompt_hook.py` at all. This is the #147 regression, written before #147 exists.
    """
    target = tmp_path / "proj"
    _skill_scripts(target, "prompt-markers", "user_prompt_hook.py")
    _skill_scripts(target, "other-hook", "other_hook.py")

    manifest_hooks = [
        {"name": "prompt-markers",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json",
                                "event": "UserPromptSubmit"}}},
        {"name": "other-hook",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json",
                                "event": "UserPromptSubmit", "script": "other_hook.py"}}},
    ]
    source_hooks = {
        "UserPromptSubmit": [
            {"hooks": [
                {"type": "command",
                 "command": ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/'
                              'other-hook/scripts/other_hook.py"')},
            ]},
        ],
    }
    fw_root = _fake_framework(tmp_path, manifest_hooks, source_hooks=source_hooks)
    hooks, _ctx = _wiring(load_script, root, fw_root, target, manifest_hooks, source_hooks)

    hooks.wire()

    wired = _wired_scripts(target, "UserPromptSubmit")
    assert "user_prompt_hook.py" in wired, wired
    assert "other_hook.py" in wired, wired
    # Exactly one command per script: prompt-markers' own, and other-hook's own — neither
    # duplicated, and prompt-markers never standing in for the newcomer.
    assert sorted(wired) == ["other_hook.py", "user_prompt_hook.py"], wired


# ------------------------------------------------------------- test 3: ambiguous glob refusal
def test_ambiguous_glob_with_no_named_script_refuses_naming_every_candidate(tmp_path, load_script,
                                                                            root):
    """No script named, more than one `*_hook.py` candidate on disk: refuse, don't guess."""
    target = tmp_path / "proj"
    _skill_scripts(target, "task", "drift_notice_hook.py", "session_start_hook.py",
                   "stop_hook.py", "user_prompt_hook.py")

    manifest_hooks = [
        {"name": "task",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json", "event": "Stop"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)
    hooks, ctx = _wiring(load_script, root, fw_root, target, manifest_hooks)

    hooks.wire()

    assert _wired_scripts(target, "Stop") == []
    note = next((n for n in ctx.notes if "task" in n and "more than one" in n), None)
    assert note, ctx.notes
    for script in ("drift_notice_hook.py", "session_start_hook.py",
                   "stop_hook.py", "user_prompt_hook.py"):
        assert script in note, note


# ------------------------------------------------------- the manifest names every script (belt)
def test_every_claude_hooks_json_entry_names_its_script(root):
    """The code-level guard is the braces; a named script is the belt (issue #152).

    `select_hooks(..., None)` refuses to adopt an event's command for a script-less entry, but
    a single wrong candidate on an event that carries exactly one command passes that guard
    without complaint — only a named script tells `select_hooks` it is looking at the wrong
    one. Every claude `hooks-json` manifest entry must therefore name its script.
    """
    manifest = json.loads(
        (root / "features" / "common" / "hooks" / "hooks-manifest.json")
        .read_text(encoding="utf-8"))

    unnamed = [hook["name"] for hook in manifest["hooks"]
               if hook["agents"].get("claude", {}).get("type") == "hooks-json"
               and not hook["agents"]["claude"].get("script")]

    assert unnamed == [], unnamed


# ------------------------------------------------------------ memory-first gate wiring
GATE_SCRIPT = "memory_first_gate_hook.py"


def _hooks_json(root):
    return json.loads(
        (root / "features" / "common" / "hooks" / "hooks.json").read_text(encoding="utf-8"))


def test_hooks_json_pre_tool_use_wires_the_gate(root):
    """The gate must fire for Grep/Glob/Bash — the Bash arm inspects the command itself."""
    entries = [e for e in _hooks_json(root)["hooks"]["PreToolUse"]
               if e.get("matcher") == "Grep|Glob|Bash"]
    assert len(entries) == 1
    commands = [h["command"] for h in entries[0]["hooks"]]
    assert len(commands) == 1
    assert commands[0].endswith(f"ai-raccoon-memory/scripts/{GATE_SCRIPT}\"")
    assert entries[0]["hooks"][0].get("timeout") == 10


def test_hooks_json_post_tool_use_keeps_the_folded_recorder(root):
    """The consulted marker is recorded by the existing memory_search entry — the gate
    must not add a second entry that select_hooks' endswith filter cannot match."""
    entries = [e for e in _hooks_json(root)["hooks"]["PostToolUse"]
               if e.get("matcher") == "memory_search"]
    assert len(entries) == 1
    commands = [h["command"] for e in entries for h in e["hooks"]]
    assert len(commands) == 1
    assert "memory_grade_hook.py" in commands[0]


def test_scaffold_wiring_puts_the_gate_into_settings(tmp_path, load_script, root):
    """End-to-end: a Claude scaffold wires the gate command into .claude/settings.json."""
    target = tmp_path / "proj"
    scripts_dir = target / ".ai-badger" / "skills" / "ai-raccoon-memory" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / GATE_SCRIPT).write_text("", encoding="utf-8")
    (scripts_dir / "memory_grade_hook.py").write_text("", encoding="utf-8")

    manifest_hooks = json.loads(
        (root / "features" / "common" / "hooks" / "hooks-manifest.json")
        .read_text(encoding="utf-8"))["hooks"]
    source_hooks = _hooks_json(root)
    hooks, _ctx = _wiring(load_script, root, root, target, manifest_hooks, source_hooks)

    hooks.wire()

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pre = [h["command"] for e in settings["hooks"]["PreToolUse"]
           for h in e["hooks"] if GATE_SCRIPT in h["command"]]
    assert len(pre) == 1, pre
    assert "${CLAUDE_PROJECT_DIR}" in pre[0]  # guarded command, not a plugin-root path
    # The recorder is folded into the memory_search PostToolUse entry.
    post = [h["command"] for e in settings["hooks"]["PostToolUse"]
            for h in e["hooks"] if "memory_grade_hook.py" in h["command"]]
    assert len(post) == 1, post
