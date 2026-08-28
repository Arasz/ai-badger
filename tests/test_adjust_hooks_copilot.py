"""Tests for features/copilot/adjustments/adjust_hooks.py: Copilot hook wiring.

Covers the properties the generated .github/hooks/ai-badger-hooks.json must hold: each
manifest entry contributes its own script's command, never a sibling's (regression floor), two
entries mapping to the same Copilot event both survive rather than the second overwriting the
first (#149 defect 1), and a manifest-named script is honoured over whatever the filesystem
glob happens to return first — refusing outright when the glob is ambiguous (#149 defect 2).
SessionStart carries more than one command since F-07 split session recording from drift
notice, so a wiring path that copied the whole event would silently mislabel one as the other.
"""
from __future__ import annotations

import json

import pytest
from conftest import _test_write


def _context(root, target) -> dict:
    return {
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["task"],
    }


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, json.dumps(data), encoding="utf-8")


def _fake_framework(tmp_path, manifest_hooks, source_hooks=None):
    """A minimal framework_root with a hand-built hooks-manifest.json / hooks.json."""
    fw_root = tmp_path / "framework"
    _write_json(fw_root / "features" / "common" / "hooks" / "hooks-manifest.json",
                {"hooks": manifest_hooks})
    _write_json(fw_root / "features" / "common" / "hooks" / "hooks.json",
                {"hooks": source_hooks or {}})
    return fw_root


def test_copilot_session_start_wires_drift_notice_not_session_tracking(tmp_path, load_script,
                                                                        root):
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    result = adjust_hooks.adjust(_context(root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    commands = [h["bash"] for h in hooks["hooks"]["sessionStart"]]
    wired = sorted(c.rstrip('"').rsplit("/", 1)[-1] for c in commands)
    # Derived from the manifest, not restated: a hardcoded list here breaks on every new
    # copilot sessionStart hook, which says nothing about the claude-only leak being tested.
    manifest = json.loads(
        (root / "features" / "common" / "hooks" / "hooks-manifest.json").read_text("utf-8"))
    expected = sorted(
        entry["agents"]["copilot"]["script"]
        for entry in manifest["hooks"]
        if entry.get("agents", {}).get("copilot", {}).get("event") == "sessionStart"
    )
    assert wired == expected
    # The point of the test: the claude-only tracking hook never reaches copilot.
    assert "session_start_hook.py" not in wired


def test_two_manifest_entries_on_one_event_both_survive(tmp_path, load_script):
    """Defect 1: a second manifest entry on the same event must not delete the first."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    for skill in ("prompt-markers", "context-enrichment"):
        skill_dir = aib / "skills" / skill / "scripts"
        skill_dir.mkdir(parents=True)
        _test_write(skill_dir / f"{skill.replace('-', '_')}_hook.py", "", encoding="utf-8")

    manifest_hooks = [
        {"name": "prompt-markers",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "userPromptSubmitted"}}},
        {"name": "context-enrichment",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "userPromptSubmitted"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)

    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    commands = [h["bash"] for h in hooks["hooks"]["userPromptSubmitted"]]
    names = sorted(c.rstrip('"').rsplit("/", 1)[-1] for c in commands)
    assert names == ["context_enrichment_hook.py", "prompt_markers_hook.py"]


def test_two_source_hooks_json_entries_on_one_event_both_survive(tmp_path, load_script):
    """Defect 1, primary branch: same collision when both entries resolve via hooks.json.

    This is the shape #147 would actually hit: prompt-markers and context-enrichment both
    wired into hooks.json under userPromptSubmitted, each named by its own manifest entry.
    """
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    manifest_hooks = [
        {"name": "prompt-markers",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "userPromptSubmitted",
                                 "script": "prompt_markers_hook.py"}}},
        {"name": "context-enrichment",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "userPromptSubmitted",
                                 "script": "context_enrichment_hook.py"}}},
    ]
    source_hooks = {
        "UserPromptSubmit": [
            {"hooks": [
                {"type": "command",
                 "command": ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/'
                              'prompt-markers/scripts/prompt_markers_hook.py"')},
                {"type": "command",
                 "command": ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/'
                              'context-enrichment/scripts/context_enrichment_hook.py"')},
            ]},
        ],
    }
    fw_root = _fake_framework(tmp_path, manifest_hooks, source_hooks=source_hooks)

    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    commands = [h["bash"] for h in hooks["hooks"]["userPromptSubmitted"]]
    names = sorted(c.rstrip('"').rsplit("/", 1)[-1] for c in commands)
    assert names == ["context_enrichment_hook.py", "prompt_markers_hook.py"]


def test_manifest_script_name_is_honoured_in_multi_script_skill(tmp_path, load_script):
    """Defect 2: the manifest's named script wins, not whatever the glob returns first."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    skill_dir = aib / "skills" / "task" / "scripts"
    skill_dir.mkdir(parents=True)
    # Four candidates, alphabetically ahead of the one the manifest actually names.
    for script in ("a_hook.py", "b_hook.py", "c_hook.py", "stop_hook.py"):
        _test_write(skill_dir / script, "", encoding="utf-8")

    manifest_hooks = [
        {"name": "task",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "stop", "script": "stop_hook.py"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)

    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    commands = [h["bash"] for h in hooks["hooks"]["stop"]]
    assert [c.rsplit("/", 1)[-1] for c in commands] == ["stop_hook.py"]


def test_a_quoted_source_command_keeps_balanced_quotes_not_a_dangling_one(tmp_path, load_script,
                                                                          root):
    """The real shape every primary-path command actually has: `python3 "<path>"`, quoted for
    shell-safety against spaces. `cmd.strip('"')` strips only the trailing quote here (the
    string's first character is `p`, not `"`, so nothing is removed from the front), producing
    an unterminated-quote bash command that would fail at execution — exactly what this repo's
    own committed `.github/hooks/ai-badger-hooks.json` shipped with, unnoticed, because no
    existing test asserted the command string itself rather than its trailing filename."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    manifest_hooks = [
        {"name": "task",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "sessionStart", "script": "drift_notice_hook.py"}}},
    ]
    source_hooks = {
        "SessionStart": [
            {"matcher": "startup|resume", "hooks": [
                {"type": "command",
                 "command": ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/'
                              'task/scripts/drift_notice_hook.py"')},
            ]},
        ],
    }
    fw_root = _fake_framework(tmp_path, manifest_hooks, source_hooks=source_hooks)

    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    bash = hooks["hooks"]["sessionStart"][0]["bash"]
    assert bash == 'python3 ".ai-badger/skills/task/scripts/drift_notice_hook.py"', bash
    assert bash.count('"') % 2 == 0, f"unbalanced quotes: {bash!r}"


def test_ambiguous_glob_fallback_refuses_naming_candidates(tmp_path, load_script):
    """No script named and more than one candidate on disk: refuse, don't guess."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    skill_dir = aib / "skills" / "task" / "scripts"
    skill_dir.mkdir(parents=True)
    for script in ("drift_notice_hook.py", "session_start_hook.py",
                   "stop_hook.py", "user_prompt_hook.py"):
        _test_write(skill_dir / script, "", encoding="utf-8")

    manifest_hooks = [
        {"name": "task",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "stop"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks)

    with pytest.raises(ValueError) as exc_info:
        adjust_hooks.adjust(_context(fw_root, target))

    message = str(exc_info.value)
    for script in ("drift_notice_hook.py", "session_start_hook.py",
                   "stop_hook.py", "user_prompt_hook.py"):
        assert script in message


# ------------------------------------------------------------ memory-first gate wiring
def test_copilot_pre_tool_use_wires_the_gate(tmp_path, load_script, root):
    """Real framework: the gate lands in .github/hooks/ai-badger-hooks.json with the
    Copilot-cased matcher (runtime tool names are lowercase grep/bash)."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    result = adjust_hooks.adjust(_context(root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    gate = [h for h in hooks["hooks"]["preToolUse"]
            if "memory_first_gate_hook.py" in h.get("bash", "")]
    assert len(gate) == 1, gate
    assert gate[0]["matcher"] == "grep|rg|Glob|bash", gate
    assert gate[0]["bash"].endswith("memory_first_gate_hook.py\""), gate[0]["bash"]
    # The folded recorder is the existing postToolUse memory_search entry.
    recorders = [h for h in hooks["hooks"]["postToolUse"]
                 if "memory_first_gate_post_hook.py" in h.get("bash", "")]
    assert len(recorders) == 1, recorders


def test_copilot_matcher_override_wins_over_the_source_entry(tmp_path, load_script):
    """The manifest arm's `matcher` replaces the Claude-cased source matcher verbatim."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    manifest_hooks = [
        {"name": "memory-first-gate",
         "agents": {"copilot": {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "preToolUse", "script": "memory_first_gate_hook.py",
                                 "matcher": "grep|rg|Glob|bash"}}},
    ]
    source_hooks = {
        "PreToolUse": [
            {"matcher": "Grep|Glob|Bash", "hooks": [
                {"type": "command",
                 "command": ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/'
                              'ai-raccoon-memory/scripts/memory_first_gate_hook.py"')},
            ]},
        ],
    }
    fw_root = _fake_framework(tmp_path, manifest_hooks, source_hooks=source_hooks)

    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    entries = [h for h in hooks["hooks"]["preToolUse"]
               if "memory_first_gate_hook.py" in h.get("bash", "")]
    assert len(entries) == 1, entries
    assert entries[0]["matcher"] == "grep|rg|Glob|bash"
    assert "Grep|Glob|Bash" not in entries[0]["matcher"]
