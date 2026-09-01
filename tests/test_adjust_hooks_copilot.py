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

import importlib.util
import json
import sys

import pytest
from conftest import ROOT, _test_write


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


# ----------------------------------------------------------- message-bus delivery wiring
# P8 (aib-user-db-message-bus): the manifest rows themselves are P5's (F2 fold — one flat
# hooks array cannot take two parallel editors), so every test here runs the generator over a
# fixture manifest shaped exactly as the plan declares P5's folded rows: three message-delivery
# entries (start / per-turn / close), claude + hermes + copilot arms, copilot event spellings
# sessionStart / userPromptSubmitted / sessionEnd. The close-event verdict these tests encode:
# Copilot CLI DOES support a sessionEnd hook (tooling/validate.py's task-checkpoint-session-end
# exemption: "Copilot's sessionEnd would fire correctly"; docs/changelog/0.50.0: "Copilot has
# agentStop and sessionEnd") — the research record's no-close-event hypothesis is rejected, and
# agentStop (turn-end, not close) is deliberately not wired: cursor cleanup on it would re-gate
# every turn and lose arrivals older than 30 minutes to an idle session.


def _bus_manifest_hooks():
    """The message-delivery rows as P5's fold declares them: one entry per event."""
    script = "message_delivery_hook.py"

    def _arms(claude_event, hermes_method, copilot_event):
        return {
            "claude": {"type": "hooks-json", "entry": "hooks.json",
                        "event": claude_event, "script": script},
            "hermes": {"type": "plugin", "entry": "ai_badger_hooks.py",
                        "method": hermes_method},
            "copilot": {"type": "hooks-json", "entry": "hooks.json",
                         "event": copilot_event, "script": script},
        }

    return [
        {"name": "message-delivery-start",
         "description": "Deliver the session's unread bus mail at session start",
         "agents": _arms("SessionStart", "on_session_start", "sessionStart")},
        {"name": "message-delivery-per-turn",
         "description": "Deliver bus mail that arrived since the last turn",
         "agents": _arms("UserPromptSubmit", "pre_llm_call", "userPromptSubmitted")},
        {"name": "message-delivery-close",
         "description": "Drop the session's bus cursor when the session closes",
         "agents": _arms("SessionEnd", "on_session_end", "sessionEnd")},
    ]


def _bus_source_hooks():
    """Framework hooks.json rows naming the shared delivery script under features/common/hooks/."""
    command = ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/hooks/'
               'message_delivery_hook.py"')
    return {
        event: [{"hooks": [{"type": "command", "command": command}]}]
        for event in ("SessionStart", "UserPromptSubmit", "SessionEnd")
    }


def _bus_fake_framework(tmp_path):
    """The bus fixture framework, carrying the REAL delivery script pair as copy sources."""
    import shutil

    fw_root = _fake_framework(tmp_path, _bus_manifest_hooks(),
                              source_hooks=_bus_source_hooks())
    hooks_dir = fw_root / "features" / "common" / "hooks"
    for name in ("message_delivery_hook.py", "badger_store.py"):
        shutil.copy2(ROOT / "features" / "common" / "hooks" / name, hooks_dir / name)
    return fw_root


def test_copilot_session_end_wires_cursor_cleanup(tmp_path, load_script):
    """The close-event verdict's executable record (the @deferred rule's Copilot leg):
    a copilot sessionEnd arm on the delivery manifest row must generate the close command.

    Failure mode: the generator's event map knows only sessionStart/userPromptSubmitted/
    preToolUse/postToolUse, so a landed sessionEnd arm falls through to a source lookup of the
    literal camelCase key, finds nothing, falls to the skill-dir fallback, finds nothing there
    either, and silently wires no close hook — the cursor then dies only of old age. Mutation:
    drop "sessionEnd" from the event map and this goes red."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    fw_root = _fake_framework(tmp_path, _bus_manifest_hooks(),
                              source_hooks=_bus_source_hooks())
    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    close = hooks["hooks"]["sessionEnd"]
    assert len(close) == 1, close
    assert close[0]["bash"].rstrip('"').rsplit("/", 1)[-1] == "message_delivery_hook.py"
    assert close[0]["bash"].count('"') % 2 == 0, f"unbalanced quotes: {close[0]['bash']!r}"
    assert close[0]["type"] == "command" and "bash" in close[0]


def test_copilot_delivery_commands_point_at_the_shipped_script(tmp_path, load_script):
    """Every delivery command must name a script the scaffolded project actually has.

    Failure mode: the generator rewrites only ${CLAUDE_PLUGIN_ROOT}/features/common/skills/
    paths, so a delivery row whose command lives under features/common/hooks/ (where P4's
    shared script deliberately lives, beside its vendored badger_store.py) passes through
    UNREWRITTEN — the generated hook carries a ${CLAUDE_PLUGIN_ROOT} path that Copilot never
    substitutes and a features/ tree no scaffolded consumer has. Wiring a dead command looks
    like delivery works and drops every event (R7 scenario 3). Mutations: remove the hooks/
    rewrite (pass-through returns) or the script shipping (no file behind the path) — both red."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    fw_root = _bus_fake_framework(tmp_path)
    result = adjust_hooks.adjust(_context(fw_root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    for event in ("sessionStart", "userPromptSubmitted", "sessionEnd"):
        commands = hooks["hooks"][event]
        assert len(commands) == 1, (event, commands)
        assert commands[0]["bash"] == 'python3 ".ai-badger/hooks/message_delivery_hook.py"', \
            (event, commands[0]["bash"])
    shipped = target / ".ai-badger" / "hooks" / "message_delivery_hook.py"
    assert shipped.is_file(), "delivery script not shipped into the scaffolded project"
    shipped_names = [f for f in result["files"] if f.endswith("message_delivery_hook.py")]
    assert shipped_names, "shipped script not recorded in the adjust result files"


def test_shipped_script_pair_is_byte_identical_to_the_framework_source(tmp_path, load_script,
                                                                        root):
    """The shipped delivery script travels with its store sibling, byte-identical (D16).

    Failure mode: shipping the named script without the badger_store.py it imports beside
    itself — the generated hook then runs, fails its import, and fails open to a no-op: a
    silent, undelivered bus that every wiring test still calls green. Mutation: ship only the
    named script and drop the sibling — red."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    fw_root = _bus_fake_framework(tmp_path)
    adjust_hooks.adjust(_context(fw_root, target))

    hooks_dir = target / ".ai-badger" / "hooks"
    for name in ("message_delivery_hook.py", "badger_store.py"):
        shipped = (hooks_dir / name).read_bytes()
        source = (fw_root / "features" / "common" / "hooks" / name).read_bytes()
        assert shipped == source, f"{name} drifted from the framework source"


def test_wired_copilot_events_are_spellings_the_delivery_script_accepts(tmp_path, load_script):
    """The copilot surface pin of the delivery script's case-insensitive event contract (P4):
    every event the generated file wires must be a spelling the script routes.

    Failure mode: a manifest arm renamed to a spelling the script rejects (say
    "promptSubmitted") still generates a hook — the file parses, the command runs, and the
    script answers {} to an event it does not know. Wiring and routing drift apart silently.
    This test reads DELIVERY_EVENTS/CLOSE_EVENTS from the actual script rather than restating
    them, so the two sides cannot drift without going red. Mutation: rename an arm's event and
    the exact-set assert fails."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    hook = load_script("features/common/hooks/message_delivery_hook.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    fw_root = _bus_fake_framework(tmp_path)
    adjust_hooks.adjust(_context(fw_root, target))

    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    wired = set(hooks["hooks"])
    assert wired == {"sessionStart", "userPromptSubmitted", "sessionEnd"}, wired

    # The three bus events are exactly the script's accepted spellings, case-folded: Copilot's
    # camelCase reaches the script as hook_event_name and must route (P4 accepts both
    # harnesses' spellings case-insensitively; this pins that the wiring never leaves that
    # superset).
    for event in ("sessionStart", "userPromptSubmitted"):
        assert event.lower() in hook.DELIVERY_EVENTS, event
    assert "sessionEnd".lower() in hook.CLOSE_EVENTS


def test_no_copilot_arm_generates_nothing_and_agentStop_is_never_a_close_leg(
        tmp_path, load_script, root):
    """Rule 7 scenario 2 (the unwired stays safe) and the close-verdict's negative row.

    Two contrasts against the wired state: (a) a manifest hook with no copilot arm at all —
    Claude-only by design — contributes no copilot command, so adding bus rows cannot leak
    delivery onto harnesses it was never declared for; (b) the ONLY close wiring the bus
    registers for Copilot is the sessionEnd close event — agentStop exists in Copilot's event
    inventory (it is the turn-end analogue of Claude's Stop) but wiring cursor cleanup on it
    would re-gate every turn and lose arrivals older than 30 minutes to an idle session, so
    the verdict explicitly leaves it unwired. Mutation: add an agentStop arm to the fixture
    and the exact-key-set assert goes red."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    manifest_hooks = _bus_manifest_hooks() + [
        {"name": "claude-only-hook",
         "description": "Wired for Claude alone",
         "agents": {"claude": {"type": "hooks-json", "entry": "hooks.json",
                                "event": "Stop", "script": "stop_hook.py"}}},
    ]
    fw_root = _fake_framework(tmp_path, manifest_hooks, source_hooks={
        **_bus_source_hooks(),
        "Stop": [{"hooks": [{"type": "command",
                              "command": ('python3 "${CLAUDE_PLUGIN_ROOT}/features/common/'
                                          'skills/task/scripts/stop_hook.py"')}]}],
    })
    adjust_hooks.adjust(_context(fw_root, target))

    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    # (a) the claude-only hook never reaches copilot
    for event_commands in hooks["hooks"].values():
        for entry in event_commands:
            assert "stop_hook.py" not in entry.get("bash", "")
    # (b) the bus's close wiring is exactly the sessionEnd leg — nothing else cleans up
    assert set(hooks["hooks"]) == {"sessionStart", "userPromptSubmitted", "sessionEnd"}

    # The TTL backstop the unwired agentStop rests on is proven at store level in
    # tests/test_message_bus_store.py (Rule 6 scenario 2, cursor pruned at 4 days); the
    # shipped-copy leg of that proof is test_ttl_backstop_prunes_through_the_shipped_store_copy.


def test_generated_copilot_delivery_hook_delivers_end_to_end(tmp_path, load_script,
                                                              monkeypatch):
    """Rule 7 through the artifact Copilot actually loads: the generated sessionStart command
    delivers the session's mail and the generated sessionEnd command removes its cursor.

    Failure mode: every static pin above can stay green while the generated hook is dead —
    a wrong path, an unimportable shipped copy, a fail-open net swallowing a real defect —
    because a delivery hook's failure mode is indistinguishable from an empty inbox. This test
    runs the generated bash commands as Copilot would (payload stdin, project cwd) against an
    env-redirected user DB and demands the message arrives; then runs the close command twice
    and demands the cursor row is gone and the second close is harmless. Mutations: break the
    rewrite/shipping (no delivery — the response is {}) or the close path (cursor survives)."""
    import os
    import sqlite3
    import subprocess

    store = load_script("engine/badger_store.py")
    user_root = tmp_path / "user"
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(user_root))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    # Seed two 1:1 messages from another session, newest last — ordering needs two elements.
    seed_store = store.open_user()
    try:
        seed_store.send_message(sender_session="sess-other", sender_project="proj-x",
                                 content="first: the left tree is safe to delete",
                                 target_session="sess-c")
        seed_store.send_message(sender_session="sess-other", sender_project="proj-x",
                                 content="second: found it, see src/bus.py",
                                 target_session="sess-c")
    finally:
        seed_store.close()

    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)
    fw_root = _bus_fake_framework(tmp_path)
    adjust_hooks.adjust(_context(fw_root, target))
    generated = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))

    def _fire(event, session_id="sess-c"):
        proc = subprocess.run(
            ["bash", "-c", generated["hooks"][event][0]["bash"]],
            input=json.dumps({"hook_event_name": event, "session_id": session_id,
                               "cwd": str(target)}),
            cwd=target,
            env={**os.environ, "AI_BADGER_USER_ROOT": str(user_root), "HOME": str(home)},
            capture_output=True, text=True, timeout=60, check=False)
        return proc

    # session start: the mail arrives, chronological, content verbatim
    proc = _fire("sessionStart")
    assert proc.returncode == 0, proc.stderr
    response = json.loads(proc.stdout)
    context = response["hookSpecificOutput"]["additionalContext"]
    docs = [json.loads(line) for line in context.splitlines()]
    assert [d["content"] for d in docs] == [
        "first: the left tree is safe to delete", "second: found it, see src/bus.py"]
    assert all(d["sender"]["sessionId"] == "sess-other" for d in docs)

    db_path = user_root / "ai-badger.db"
    conn = sqlite3.connect(db_path)
    try:
        cursor_rows = conn.execute(
            "SELECT session_id FROM cursors WHERE session_id = 'sess-c'").fetchall()
        assert cursor_rows, "start delivery did not land the session's cursor"
    finally:
        conn.close()

    # close: cursor gone; a second close is harmless
    proc = _fire("sessionEnd")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {}
    proc = _fire("sessionEnd")
    assert proc.returncode == 0, proc.stderr
    conn = sqlite3.connect(db_path)
    try:
        cursor_rows = conn.execute(
            "SELECT session_id FROM cursors WHERE session_id = 'sess-c'").fetchall()
        assert cursor_rows == [], "close event did not remove the cursor row"
    finally:
        conn.close()


def test_ttl_backstop_prunes_through_the_shipped_store_copy(tmp_path, load_script, monkeypatch):
    """The Copilot leg of Rule 6 scenario 2: the 4-day cursor TTL prunes through the copy of
    badger_store.py the generated commands actually load — not just through the canonical one.

    Byte-identity (the pair test) pins the copy's content, not its runtime behaviour in the
    target layout; a copy that cannot open, migrate or prune leaves crashed Copilot sessions'
    cursors forever, growing storage without bound behind a green suite. A crashed session's
    cursor (5 days stale) must die; a live one (3 days) must survive — one cursor per state,
    never a degenerate single-row fixture. Mutations: breaking the shipped copy's prune path
    (retention dropped on cursors) turns the survival assert red."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    store = load_script("engine/badger_store.py")
    user_root = tmp_path / "user"
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(user_root))

    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)
    fw_root = _bus_fake_framework(tmp_path)
    adjust_hooks.adjust(_context(fw_root, target))

    shipped_spec = importlib.util.spec_from_file_location(
        "shipped_copilot_store",
        target / ".ai-badger" / "hooks" / "badger_store.py")
    shipped_module = importlib.util.module_from_spec(shipped_spec)
    sys.modules[shipped_spec.name] = shipped_module
    shipped_spec.loader.exec_module(shipped_module)

    now = datetime.now(timezone.utc)
    seed = store.open_user()
    try:
        seed.conn.execute(
            "INSERT INTO cursors (session_id, cursor_id, ts) VALUES ('crashed', 7, ?)",
            ((now - timedelta(days=5)).isoformat(),))
        seed.conn.execute(
            "INSERT INTO cursors (session_id, cursor_id, ts) VALUES ('live', 3, ?)",
            ((now - timedelta(days=3)).isoformat(),))
        seed.conn.commit()
    finally:
        seed.close()

    # The open-time prune is throttled by pruned_at.cursors, stamped when the seed store
    # opened — clear it (F7) so the shipped copy's open actually runs the prune, as it does
    # in production whenever a Copilot delivery command opens the user store.
    throttle_db = sqlite3.connect(user_root / "ai-badger.db")
    try:
        throttle_db.execute("DELETE FROM meta WHERE key = 'pruned_at.cursors'")
        throttle_db.commit()
    finally:
        throttle_db.close()

    pruned_store = shipped_module.open_user()
    try:
        pruned_store.prune_expired("cursors", max_age_days=4)
    finally:
        pruned_store.close()

    conn = sqlite3.connect(user_root / "ai-badger.db")
    try:
        remaining = dict(conn.execute("SELECT session_id, cursor_id FROM cursors").fetchall())
        assert "crashed" not in remaining, remaining
        assert remaining.get("live") == 3, remaining
    finally:
        conn.close()
