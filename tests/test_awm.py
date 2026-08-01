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


def _entry_here(awm):
    """This project's entry. Since #296 state.json holds one entry per project."""
    found = awm.entry_here(awm.load_state() or {})
    return found[1] if found else {}


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


def test_main_partner_enables_a_bounded_project_scoped_mode(tmp_path, load_script, monkeypatch,
                                                             capsys):
    """Partner mode carries a wall-clock window and the project it was enabled in (F-12)."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = awm.main(["partner"])

    assert rc == 0
    state = _entry_here(awm)
    assert state["enabled"] is True
    assert state["mode"] == "partner"
    assert state["duration"] == awm.DEFAULT_PARTNER_DURATION
    assert state["project"] == str(tmp_path)
    remaining = datetime.fromisoformat(state["expires_at"]) - datetime.now(timezone.utc)
    assert 0 < remaining.total_seconds() <= awm.parse_duration(awm.DEFAULT_PARTNER_DURATION)
    decisions = _read_decisions(awm_dir)
    assert decisions[-1]["type"] == "mode_enabled"
    assert "PARTNER" in capsys.readouterr().out.upper()


def test_main_no_args_defaults_to_partner(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main([])

    assert rc == 0
    assert _entry_here(awm)["mode"] == "partner"


def test_main_away_parses_duration_and_persists_expiry(tmp_path, load_script, monkeypatch,
                                                         capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    rc = awm.main(["away", "4h"])

    assert rc == 0
    state = _entry_here(awm)
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
    state = _entry_here(awm)
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
    state = _entry_here(awm)
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
    assert "remaining" in out
    assert "Scope:" in out


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
    monkeypatch.chdir(tmp_path)
    expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    awm.write_state({
        "enabled": True, "mode": "away", "project": str(tmp_path),
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


def test_main_away_records_the_project_it_was_enabled_in(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    awm.main(["away", "2h"])

    assert _entry_here(awm)["project"] == str(tmp_path)


def test_a_window_longer_than_the_maximum_is_capped(tmp_path, load_script, monkeypatch, capsys):
    """No auto-approval window is open-ended, however long the user asks for (F-12)."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    awm.main(["away", "48h"])

    state = _entry_here(awm)
    assert state["duration_seconds"] == awm.MAX_DURATION_SECONDS
    assert "capping" in capsys.readouterr().out


# ── user-scope state privacy (security I5) ───────────────────────────────────

def test_state_file_is_owner_readable_only(tmp_path, load_script, monkeypatch):
    """~/.claude/awm/ records where you work and what was auto-approved (security I5)."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    monkeypatch.setattr(awm, "AWM_DIR", tmp_path / "awm")
    monkeypatch.setattr(awm, "STATE_FILE", tmp_path / "awm" / "state.json")
    monkeypatch.setattr(awm, "DECISIONS_FILE", tmp_path / "awm" / "decisions.jsonl")

    awm.main(["partner"])

    assert (tmp_path / "awm" / "state.json").stat().st_mode & 0o777 == 0o600


def test_decision_log_is_owner_readable_only(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    monkeypatch.setattr(awm, "AWM_DIR", tmp_path / "awm")
    monkeypatch.setattr(awm, "STATE_FILE", tmp_path / "awm" / "state.json")
    monkeypatch.setattr(awm, "DECISIONS_FILE", tmp_path / "awm" / "decisions.jsonl")

    awm.main(["partner"])

    assert (tmp_path / "awm" / "decisions.jsonl").stat().st_mode & 0o777 == 0o600


def test_the_state_directory_is_not_world_readable(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    monkeypatch.setattr(awm, "AWM_DIR", tmp_path / "awm")
    monkeypatch.setattr(awm, "STATE_FILE", tmp_path / "awm" / "state.json")
    monkeypatch.setattr(awm, "DECISIONS_FILE", tmp_path / "awm" / "decisions.jsonl")

    awm.main(["partner"])

    assert (tmp_path / "awm").stat().st_mode & 0o077 == 0


def test_the_decision_log_is_capped(tmp_path, load_script, monkeypatch):
    """An append-only log of every auto-approved call must not grow without bound."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    monkeypatch.setattr(awm, "AWM_DIR", tmp_path / "awm")
    monkeypatch.setattr(awm, "STATE_FILE", tmp_path / "awm" / "state.json")
    monkeypatch.setattr(awm, "DECISIONS_FILE", tmp_path / "awm" / "decisions.jsonl")
    monkeypatch.setattr(awm, "MAX_DECISION_LINES", 5)

    for i in range(20):
        awm.log_event("decision", f"entry {i}")

    lines = (tmp_path / "awm" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 5
    assert "entry 19" in lines[-1]


# ── per-project state (#296) ─────────────────────────────────────────────────

def _entries(state_file):
    return json.loads(state_file.read_text(encoding="utf-8"))["projects"]


def test_enabling_in_one_project_leaves_another_armed(tmp_path, load_script, monkeypatch, capsys):
    """The defect: one machine-wide scope, so arming repo B silently disarmed repo A."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()

    monkeypatch.chdir(a)
    awm.cmd_away("2h")
    monkeypatch.chdir(b)
    awm.cmd_partner("2h")
    capsys.readouterr()

    entries = _entries(state_file)
    assert entries[str(a)]["enabled"] is True and entries[str(a)]["mode"] == "away"
    assert entries[str(b)]["enabled"] is True and entries[str(b)]["mode"] == "partner"


def test_disable_only_affects_the_current_project(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()

    monkeypatch.chdir(a)
    awm.cmd_away("2h")
    monkeypatch.chdir(b)
    awm.cmd_away("2h")
    awm.cmd_disable()
    capsys.readouterr()

    entries = _entries(state_file)
    assert entries[str(a)]["enabled"] is True, "disabling in beta must not disarm alpha"
    assert entries[str(b)]["enabled"] is False


def test_status_reports_this_project_not_another(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()

    monkeypatch.chdir(a)
    awm.cmd_away("2h")
    capsys.readouterr()
    monkeypatch.chdir(b)
    awm.cmd_status()

    out = capsys.readouterr().out
    assert "inactive" in out.lower()
    assert str(a) in out, "status should say where the window that does exist is scoped"


def test_re_enabling_the_same_project_replaces_its_entry(tmp_path, load_script, monkeypatch,
                                                          capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    a = tmp_path / "alpha"
    a.mkdir()

    monkeypatch.chdir(a)
    awm.cmd_away("2h")
    awm.cmd_partner("3h")
    capsys.readouterr()

    entries = _entries(state_file)
    assert len(entries) == 1
    assert entries[str(a)]["mode"] == "partner"


def test_a_worktree_disables_its_own_entry_not_the_parent_repos(tmp_path, load_script,
                                                                 monkeypatch, capsys):
    """The hooks pick the most specific armed project; the CLI must agree, or `off` in a
    worktree silently disarms the whole checkout."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    repo = tmp_path / "repo"
    worktree = repo / "wt"
    worktree.mkdir(parents=True)

    monkeypatch.chdir(repo)
    awm.cmd_away("2h")
    monkeypatch.chdir(worktree)
    awm.cmd_away("2h")
    awm.cmd_disable()
    capsys.readouterr()

    entries = json.loads(state_file.read_text(encoding="utf-8"))["projects"]
    assert entries[str(repo)]["enabled"] is True, "the parent checkout must stay armed"
    assert entries[str(worktree)]["enabled"] is False
