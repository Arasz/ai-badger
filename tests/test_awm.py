"""Tests for features/claude/skills/auto-wm/scripts/awm.py (the `/auto-wm` CLI).

Covers mode transitions (partner/away/disable), `status` reporting for each mode
including an already-expired away window, duration parsing, and the decision-logging
command. All state is redirected to a tmp_path directory via monkeypatch — the real
`~/.claude/awm` state directory is never touched.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest


def _patch_state_paths(module, monkeypatch, tmp_path):
    awm_dir = tmp_path / "awm"
    monkeypatch.setattr(module, "AWM_DIR", awm_dir)
    monkeypatch.setattr(module, "STATE_FILE", awm_dir / "state.json")
    monkeypatch.setattr(module, "DECISIONS_FILE", awm_dir / "decisions.jsonl")
    return awm_dir


def _read_decisions(awm_dir):
    path = awm_dir / "decisions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_parse_duration_hours_minutes_and_bare_number(tmp_path, load_script):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")

    assert awm.parse_duration("4h") == 4 * 3600
    assert awm.parse_duration("90m") == 90 * 60
    assert awm.parse_duration("1h30m") == 3600 + 30 * 60
    assert awm.parse_duration("2") == 2 * 3600


def test_parse_duration_rejects_unparseable_or_nonpositive(tmp_path, load_script):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")

    with pytest.raises(ValueError):
        awm.parse_duration("xyz")
    with pytest.raises(ValueError):
        awm.parse_duration("0h")


def test_main_partner_enables_indefinite_mode(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["partner"])

    assert rc == 0
    state = awm.load_state()
    assert state["enabled"] is True
    assert state["mode"] == "partner"
    assert state["expires_at"] is None
    decisions = _read_decisions(awm_dir)
    assert decisions[-1]["type"] == "mode_enabled"
    assert "PARTNER" in capsys.readouterr().out.upper()


def test_main_no_args_defaults_to_partner(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main([])

    assert rc == 0
    assert awm.load_state()["mode"] == "partner"


def test_main_away_parses_duration_and_persists_expiry(tmp_path, load_script, monkeypatch,
                                                         capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["away", "4h"])

    assert rc == 0
    state = awm.load_state()
    assert state["enabled"] is True
    assert state["mode"] == "away"
    assert state["duration"] == "4h"
    assert state["duration_seconds"] == 4 * 3600
    enabled_at = datetime.fromisoformat(state["enabled_at"])
    expires_at = datetime.fromisoformat(state["expires_at"])
    assert expires_at - enabled_at == timedelta(hours=4)
    assert "away" in capsys.readouterr().out.lower()


def test_main_away_without_duration_uses_default(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["away"])

    assert rc == 0
    state = awm.load_state()
    assert state["duration"] == awm.DEFAULT_AWAY_DURATION


def test_main_away_invalid_duration_returns_error(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["away", "not-a-duration"])

    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()
    assert awm.load_state() is None


def test_main_switching_from_partner_to_away_logs_the_switch(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)
    awm.main(["partner"])

    awm.main(["away", "1h"])

    decisions = _read_decisions(awm_dir)
    assert "switched from partner" in decisions[-1]["detail"]


def test_main_disable_when_never_enabled_reports_inactive_and_writes_nothing(
        tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["off"])

    assert rc == 0
    assert "not active" in capsys.readouterr().out.lower()
    assert not (awm_dir / "state.json").exists()


def test_main_disable_after_enabled_flips_state_off(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    awm.main(["partner"])
    capsys.readouterr()

    rc = awm.main(["disable"])

    assert rc == 0
    state = awm.load_state()
    assert state["enabled"] is False
    assert state["disabled_reason"] == "user"
    assert "disabled" in capsys.readouterr().out.lower()


def test_main_status_inactive_when_never_enabled(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["status"])

    assert rc == 0
    assert "inactive" in capsys.readouterr().out.lower()


def test_main_status_reports_active_partner_mode(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    awm.main(["partner"])
    capsys.readouterr()

    rc = awm.main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "PARTNER" in out
    assert "no expiry" in out


def test_main_status_reports_active_away_mode_with_remaining_time(tmp_path, load_script,
                                                                    monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    awm.main(["away", "2h"])
    capsys.readouterr()

    rc = awm.main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "AWAY" in out
    assert "remaining" in out


def test_main_status_reports_expired_away_window_as_no_longer_away(tmp_path, load_script,
                                                                     monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    awm.write_state({
        "enabled": True, "mode": "away",
        "enabled_at": (expired_at - timedelta(hours=4)).isoformat(timespec="seconds"),
        "duration": "4h", "duration_seconds": 4 * 3600,
        "expires_at": expired_at.isoformat(timespec="seconds"),
    })

    rc = awm.main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "EXPIRED" in out
    assert "remaining" not in out


def test_main_decision_registers_event(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["decision", "chose", "X", "because", "Y"])

    assert rc == 0
    assert "registered" in capsys.readouterr().out.lower()
    decisions = _read_decisions(awm_dir)
    assert decisions[-1]["type"] == "decision"
    assert decisions[-1]["detail"] == "chose X because Y"


def test_main_decision_without_text_is_an_error(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["decision"])

    assert rc == 1
    assert "usage" in capsys.readouterr().err.lower()


def test_main_unknown_command_is_an_error(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["bogus"])

    assert rc == 1
    assert "unknown command" in capsys.readouterr().err.lower()
