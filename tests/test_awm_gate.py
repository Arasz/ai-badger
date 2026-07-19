"""Tests for skills/auto-wm/hooks/awm_gate.py (PreToolUse auto-approval gate).

Covers: no decision emitted when AWM is disabled; partner mode auto-approves every tool
except AskUserQuestion (left untouched for normal permission prompting); away mode
auto-approves and denies AskUserQuestion; an away window whose wall-clock expiry has
passed is treated as no-longer-away and falls through to normal permission prompting
even though the state file still nominally says "away" (expiry is re-checked at gate
time, not just when `awm away` was called) and the gate flips the state off itself; and
the script's own silent-on-internal-error contract. All state is redirected to
tmp_path — the real `~/.claude/awm` directory is never touched, and no subprocess is
spawned (main() is called in-process with sys.stdin patched).
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone


def _patch_state_paths(module, monkeypatch, tmp_path):
    awm_dir = tmp_path / "awm"
    state_file = awm_dir / "state.json"
    decisions_file = awm_dir / "decisions.jsonl"
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "DECISIONS_FILE", decisions_file)
    return state_file, decisions_file


def _write_state(state_file, state):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")


def _read_decisions(decisions_file):
    if not decisions_file.exists():
        return []
    lines = decisions_file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _payload(tool_name="Bash", tool_input=None):
    return {"session_id": "sid-1", "cwd": "/repo", "tool_name": tool_name,
            "tool_input": tool_input if tool_input is not None else {"command": "ls"}}


def _run_main(module, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    module.main()


def _run_main_never_raises(module, monkeypatch, payload):
    """Mirror the script's own top-level guard (`if __name__ == "__main__":`): internal
    errors never surface and never produce output. main() itself has no internal
    try/except, so this reproduces the guard that actually ships around it.
    """
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    try:
        module.main()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def test_disabled_mode_emits_nothing(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": False})

    _run_main(gate, monkeypatch, _payload())

    assert capsys.readouterr().out == ""
    assert _read_decisions(decisions_file) == []


def test_partner_mode_auto_approves_normal_tool(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": True, "mode": "partner",
                               "enabled_at": datetime.now(timezone.utc).isoformat()})

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    decisions = _read_decisions(decisions_file)
    assert len(decisions) == 1
    assert decisions[0]["type"] == "auto_approve"
    assert decisions[0]["tool_name"] == "Bash"


def test_partner_mode_leaves_ask_user_question_untouched(tmp_path, load_script, monkeypatch,
                                                           capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": True, "mode": "partner",
                               "enabled_at": datetime.now(timezone.utc).isoformat()})

    _run_main(gate, monkeypatch, _payload(tool_name="AskUserQuestion"))

    assert capsys.readouterr().out == ""
    assert _read_decisions(decisions_file) == []


def test_away_mode_active_auto_approves_normal_tool(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    _write_state(state_file, {"enabled": True, "mode": "away",
                               "enabled_at": datetime.now(timezone.utc).isoformat(),
                               "expires_at": expires_at.isoformat()})

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    decisions = _read_decisions(decisions_file)
    assert decisions[-1]["type"] == "auto_approve"


def test_away_mode_active_denies_ask_user_question(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    _write_state(state_file, {"enabled": True, "mode": "away",
                               "enabled_at": datetime.now(timezone.utc).isoformat(),
                               "expires_at": expires_at.isoformat()})

    _run_main(gate, monkeypatch, _payload(tool_name="AskUserQuestion",
                                           tool_input={"question": "which approach?"}))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    decisions = _read_decisions(decisions_file)
    assert decisions[-1]["type"] == "question_denied"


def test_away_mode_expired_falls_through_and_flips_state_off(tmp_path, load_script, monkeypatch,
                                                               capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    _write_state(state_file, {"enabled": True, "mode": "away",
                               "enabled_at": (expires_at - timedelta(hours=4)).isoformat(),
                               "expires_at": expires_at.isoformat()})

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    # falls through to normal permission prompting: no allow/deny decision emitted
    assert capsys.readouterr().out == ""
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["enabled"] is False
    assert state["disabled_reason"] == "expired"
    decisions = _read_decisions(decisions_file)
    assert decisions[-1]["type"] == "mode_expired"


def test_missing_state_file_is_silent_via_entrypoint_guard(tmp_path, load_script, monkeypatch,
                                                             capsys):
    gate = load_script("skills/auto-wm/hooks/awm_gate.py")
    _patch_state_paths(gate, monkeypatch, tmp_path)  # STATE_FILE points at a nonexistent path

    _run_main_never_raises(gate, monkeypatch, _payload())

    assert capsys.readouterr().out == ""
