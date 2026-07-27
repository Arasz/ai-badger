"""Tests for skills/auto-wm/hooks/awm_gate.py (PreToolUse auto-approval gate).

Covers: no decision emitted when AWM is disabled; partner mode auto-approves every tool
except AskUserQuestion (left untouched for normal permission prompting); away mode
auto-approves and denies AskUserQuestion; an away window whose wall-clock expiry has
passed is treated as no-longer-away and falls through to normal permission prompting
even though the state file still nominally says "away" (expiry is re-checked at gate
time, not just when `awm away` was called) and the gate flips the state off itself; that
partner mode is bounded by the same expiry check; that denylisted tool calls (destructive
shell commands, network egress, writes outside the project) are never auto-approved in
either mode; that a state file scoped to one project never auto-approves a call made from
another; and the script's own silent-on-internal-error contract. All state is redirected to
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


PROJECT = "/repo"


def _partner_state(**overrides):
    """An enabled partner-mode state scoped to PROJECT, within its maximum lifetime."""
    state = {
        "enabled": True,
        "mode": "partner",
        "project": PROJECT,
        "enabled_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    }
    state.update(overrides)
    return state


def _away_state(**overrides):
    """An enabled away-mode state scoped to PROJECT, expiring in two hours."""
    state = _partner_state(mode="away")
    state.update(overrides)
    return state


def _payload(tool_name="Bash", tool_input=None, cwd=PROJECT):
    return {"session_id": "sid-1", "cwd": cwd, "tool_name": tool_name,
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
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": False})

    _run_main(gate, monkeypatch, _payload())

    assert capsys.readouterr().out == ""
    assert _read_decisions(decisions_file) == []


def test_partner_mode_auto_approves_normal_tool(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, _partner_state())

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
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, _partner_state())

    _run_main(gate, monkeypatch, _payload(tool_name="AskUserQuestion"))

    assert capsys.readouterr().out == ""
    assert _read_decisions(decisions_file) == []


def test_away_mode_active_auto_approves_normal_tool(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, _away_state())

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    decisions = _read_decisions(decisions_file)
    assert decisions[-1]["type"] == "auto_approve"


def test_away_mode_active_denies_ask_user_question(tmp_path, load_script, monkeypatch, capsys):
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, _away_state())

    _run_main(gate, monkeypatch, _payload(tool_name="AskUserQuestion",
                                           tool_input={"question": "which approach?"}))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    decisions = _read_decisions(decisions_file)
    assert decisions[-1]["type"] == "question_denied"


def test_away_mode_expired_falls_through_and_flips_state_off(tmp_path, load_script, monkeypatch,
                                                               capsys):
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    _write_state(state_file, _away_state(
        enabled_at=(expires_at - timedelta(hours=4)).isoformat(),
        expires_at=expires_at.isoformat(),
    ))

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    # falls through to normal permission prompting: no allow/deny decision emitted
    assert capsys.readouterr().out == ""
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["enabled"] is False
    assert state["disabled_reason"] == "expired"
    decisions = _read_decisions(decisions_file)
    assert decisions[-1]["type"] == "mode_expired"


def test_partner_mode_past_its_maximum_lifetime_falls_through_and_flips_state_off(
        tmp_path, load_script, monkeypatch, capsys):
    """Partner mode is bounded: an indefinite auto-approval window is not offered (F-12)."""
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    _write_state(state_file, _partner_state(expires_at=expires_at.isoformat()))

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    assert capsys.readouterr().out == ""
    assert json.loads(state_file.read_text(encoding="utf-8"))["enabled"] is False
    assert _read_decisions(decisions_file)[-1]["type"] == "mode_expired"


def test_legacy_state_without_an_expiry_is_not_auto_approved(tmp_path, load_script, monkeypatch,
                                                               capsys):
    """A state file written before partner mode was bounded must not auto-approve forever."""
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    state_file, _ = _patch_state_paths(gate, monkeypatch, tmp_path)
    _write_state(state_file, _partner_state(expires_at=None))

    _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

    assert capsys.readouterr().out == ""


class TestToolDenylist:
    """Some tool calls can never be auto-approved, in either mode (F-12)."""

    def _assert_not_approved(self, gate, monkeypatch, capsys, decisions_file, payload):
        _run_main(gate, monkeypatch, payload)
        assert capsys.readouterr().out == ""
        assert _read_decisions(decisions_file)[-1]["type"] == "denylisted"

    def test_denylisted_bash_is_never_auto_approved(self, tmp_path, load_script, monkeypatch,
                                                     capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state())

        self._assert_not_approved(
            gate, monkeypatch, capsys, decisions_file,
            _payload(tool_name="Bash", tool_input={"command": "rm -rf /"}))

    def test_denylisted_bash_is_never_auto_approved_in_partner_mode(self, tmp_path, load_script,
                                                                     monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _partner_state())

        self._assert_not_approved(
            gate, monkeypatch, capsys, decisions_file,
            _payload(tool_name="Bash", tool_input={"command": "sudo rm -rf /etc"}))

    def test_web_fetch_is_never_auto_approved(self, tmp_path, load_script, monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state())

        self._assert_not_approved(
            gate, monkeypatch, capsys, decisions_file,
            _payload(tool_name="WebFetch", tool_input={"url": "https://example.com"}))

    def test_write_outside_the_project_is_never_auto_approved(self, tmp_path, load_script,
                                                               monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state())

        self._assert_not_approved(
            gate, monkeypatch, capsys, decisions_file,
            _payload(tool_name="Write",
                     tool_input={"file_path": "/etc/hosts", "content": "x"}))

    def test_write_inside_the_project_is_auto_approved(self, tmp_path, load_script, monkeypatch,
                                                        capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, _ = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state())

        _run_main(gate, monkeypatch,
                  _payload(tool_name="Write",
                           tool_input={"file_path": f"{PROJECT}/src/app.py", "content": "x"}))

        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_an_ordinary_bash_command_is_still_auto_approved(self, tmp_path, load_script,
                                                              monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, _ = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state())

        _run_main(gate, monkeypatch,
                  _payload(tool_name="Bash", tool_input={"command": "git status"}))

        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_the_denylist_reason_never_echoes_the_scanned_command(self, tmp_path, load_script,
                                                                    monkeypatch, capsys):
        """The decision log records why, from a fixed vocabulary — not the command bytes."""
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state())

        _run_main(gate, monkeypatch,
                  _payload(tool_name="Bash",
                           tool_input={"command": "rm -rf / --token=SUPERSECRET"}))

        capsys.readouterr()
        assert "SUPERSECRET" not in decisions_file.read_text(encoding="utf-8")


class TestProjectScope:
    """Enabling AWM in one project must not auto-approve in another (F-12)."""

    def test_call_from_another_project_is_not_auto_approved(self, tmp_path, load_script,
                                                             monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state(project="/a"))

        _run_main(gate, monkeypatch, _payload(tool_name="Bash", cwd="/b"))

        assert capsys.readouterr().out == ""
        assert _read_decisions(decisions_file)[-1]["type"] == "out_of_scope"

    def test_call_from_a_subdirectory_of_the_project_is_auto_approved(self, tmp_path, load_script,
                                                                       monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, _ = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state(project="/a"))

        _run_main(gate, monkeypatch, _payload(tool_name="Bash", cwd="/a/sub/dir"))

        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_a_sibling_with_a_shared_prefix_is_not_auto_approved(self, tmp_path, load_script,
                                                                  monkeypatch, capsys):
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, _ = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state(project="/a"))

        _run_main(gate, monkeypatch, _payload(tool_name="Bash", cwd="/a-other"))

        assert capsys.readouterr().out == ""

    def test_unscoped_state_is_not_auto_approved(self, tmp_path, load_script, monkeypatch, capsys):
        """A state file with no project (written before scoping) is machine-global — refuse it."""
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, decisions_file = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state(project=None))

        _run_main(gate, monkeypatch, _payload(tool_name="Bash"))

        assert capsys.readouterr().out == ""
        assert _read_decisions(decisions_file)[-1]["type"] == "out_of_scope"

    def test_ask_user_question_is_not_denied_outside_the_project(self, tmp_path, load_script,
                                                                  monkeypatch, capsys):
        """Out of scope means the gate is absent, not that it denies another project's calls."""
        gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
        state_file, _ = _patch_state_paths(gate, monkeypatch, tmp_path)
        _write_state(state_file, _away_state(project="/a"))

        _run_main(gate, monkeypatch, _payload(tool_name="AskUserQuestion", cwd="/b"))

        assert capsys.readouterr().out == ""


def test_missing_state_file_is_silent_via_entrypoint_guard(tmp_path, load_script, monkeypatch,
                                                             capsys):
    gate = load_script("features/claude/skills/auto-wm/hooks/awm_gate.py")
    _patch_state_paths(gate, monkeypatch, tmp_path)  # STATE_FILE points at a nonexistent path

    _run_main_never_raises(gate, monkeypatch, _payload())

    assert capsys.readouterr().out == ""
