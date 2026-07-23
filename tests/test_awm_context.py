"""Tests for skills/auto-wm/hooks/awm_context.py (UserPromptSubmit status injector).

Covers: no output when AWM is off; the partner-mode status line; the away-mode status
line with remaining time; an already-expired away window being reported as EXPIRED
(once) and flipping state off; and the script's own silent-on-internal-error contract.
All state is redirected to tmp_path — the real `~/.claude/awm` directory is never
touched, and no subprocess is spawned (main() is called in-process).
"""
from __future__ import annotations

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


def _run_main_never_raises(module):
    """Mirror the script's own top-level guard (`if __name__ == "__main__":`): internal
    errors never surface and never produce output.
    """
    try:
        module.main()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def test_disabled_mode_emits_nothing(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/common/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": False})

    context.main()

    assert capsys.readouterr().out == ""


def test_partner_mode_prints_status(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/common/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": True, "mode": "partner",
                               "enabled_at": datetime.now(timezone.utc).isoformat()})

    context.main()

    out = capsys.readouterr().out
    assert "[auto-wm] PARTNER MODE ACTIVE" in out
    assert "no expiry" in out


def test_away_active_prints_remaining_time(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/common/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1, minutes=30)
    _write_state(state_file, {"enabled": True, "mode": "away",
                               "enabled_at": datetime.now(timezone.utc).isoformat(),
                               "expires_at": expires_at.isoformat()})

    context.main()

    out = capsys.readouterr().out
    assert "[auto-wm] AWAY MODE ACTIVE" in out
    assert "remaining" in out


def test_away_expired_prints_expired_and_flips_state_off(tmp_path, load_script, monkeypatch,
                                                           capsys):
    context = load_script("features/common/skills/auto-wm/hooks/awm_context.py")
    state_file, decisions_file = _patch_state_paths(context, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_state(state_file, {"enabled": True, "mode": "away",
                               "enabled_at": (expires_at - timedelta(hours=4)).isoformat(),
                               "expires_at": expires_at.isoformat()})

    context.main()

    out = capsys.readouterr().out
    assert "AWAY MODE EXPIRED" in out
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["enabled"] is False
    assert state["disabled_reason"] == "expired"
    decisions = decisions_file.read_text(encoding="utf-8").splitlines()
    assert json.loads(decisions[-1])["type"] == "mode_expired"


def test_missing_state_file_is_silent_via_entrypoint_guard(tmp_path, load_script, monkeypatch,
                                                             capsys):
    context = load_script("features/common/skills/auto-wm/hooks/awm_context.py")
    _patch_state_paths(context, monkeypatch, tmp_path)  # STATE_FILE points at a nonexistent path

    _run_main_never_raises(context)

    assert capsys.readouterr().out == ""
