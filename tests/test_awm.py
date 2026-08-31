"""Tests for features/claude/skills/auto-wm/scripts/awm.py (the `/auto-wm` CLI).

Covers mode transitions (partner/away/disable), `status` reporting for each mode
including an already-expired away window, duration parsing, and the decision-logging
command. All state is redirected to a tmp_path directory via monkeypatch — the real
`~/.claude/awm` state directory is never touched.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _patch_state_paths(module, monkeypatch, tmp_path):
    awm_dir = tmp_path / "awm"
    monkeypatch.setattr(module, "AWM_DIR", awm_dir)
    monkeypatch.setattr(module, "STATE_FILE", awm_dir / "state.json")
    monkeypatch.setattr(module, "DECISIONS_FILE", awm_dir / "decisions.jsonl")
    # The awm_state rows land in the user store (AI_BADGER_USER_ROOT, call-time resolved);
    # without this redirect a suite write would reach the real ~/.ai-badger/ai-badger.db.
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    return awm_dir


def _entry_here(awm):
    """This project's entry. Since #296 state.json holds one entry per project."""
    found = awm.entry_here(awm.load_state() or {})
    return found[1] if found else {}


def _read_decisions(awm):
    """The awm_decisions rows, oldest first (P1.2b: decisions live in the user store)."""
    store = awm.open_store()
    try:
        rows = store.conn.execute("SELECT payload FROM awm_decisions ORDER BY id").fetchall()
    finally:
        store.close()
    return [json.loads(row[0]) for row in rows]


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
    decisions = _read_decisions(awm)
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
    assert not awm.projects(awm.load_state() or {}), "the rejected mode persists nothing"


def test_main_switching_from_partner_to_away_logs_the_switch(tmp_path, load_script, monkeypatch):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)
    awm.main(["partner"])

    awm.main(["away", "1h"])

    decisions = _read_decisions(awm)
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
    awm.save_entry(str(tmp_path), {
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
    decisions = _read_decisions(awm)
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
    """The state store records where you work and what was auto-approved (security I5).

    State lives in the user DB now, so the 0600 discipline moved with it: the store
    re-asserts owner-only on the DB and its WAL sidecars on every write (D17).
    """
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    awm.main(["partner"])

    db = Path(os.environ["AI_BADGER_USER_ROOT"]) / "ai-badger.db"
    assert db.stat().st_mode & 0o777 == 0o600
    store = awm.open_store()  # sidecars exist only while a WAL connection is open
    try:
        for sidecar in ("-wal", "-shm"):
            assert Path(str(db) + sidecar).stat().st_mode & 0o777 == 0o600
    finally:
        store.close()


def test_decision_log_is_owner_readable_only(tmp_path, load_script, monkeypatch):
    """Decisions live in the user DB now; the store re-asserts 0600 on every write (D17, I5)."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    awm.main(["partner"])

    db = Path(os.environ["AI_BADGER_USER_ROOT"]) / "ai-badger.db"
    assert db.stat().st_mode & 0o777 == 0o600


def test_the_state_directory_is_not_world_readable(tmp_path, load_script, monkeypatch):
    """The store root replaces ~/.claude/awm as the sensitive directory (0700, D17)."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)

    awm.main(["partner"])

    root = Path(os.environ["AI_BADGER_USER_ROOT"])
    assert root.stat().st_mode & 0o077 == 0


def test_decisions_older_than_60_days_are_pruned_on_write(tmp_path, load_script, monkeypatch):
    """60-day retention replaces the 5000-line cap: old rows prunable, fresh rows kept (D9).

    The prune is throttled to once an hour per store, so this fresh store (no pruned_at stamp
    yet) prunes on the triggering write itself. Legacy rows are seeded at two ages — 90 and 10
    days — so the assertion pins the age boundary, not merely a row count.
    """
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    stale = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
    fresh = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    store = awm.open_store()
    try:
        store.log_append("awm_decisions", stale,
                         {"ts": stale, "type": "decision", "detail": "stale"})
        store.log_append("awm_decisions", fresh,
                         {"ts": fresh, "type": "decision", "detail": "fresh"})
    finally:
        store.close()

    awm.log_event("decision", "trigger")

    assert [d["detail"] for d in _read_decisions(awm)] == ["fresh", "trigger"]


# ── per-project state (#296) ─────────────────────────────────────────────────

def _entries(awm, state_file):
    """Persisted per-project entries: the awm_state rows (legacy file only pre-first-write)."""
    return awm.projects(awm.load_state() or {})


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

    entries = _entries(awm, state_file)
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

    entries = _entries(awm, state_file)
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

    entries = _entries(awm, state_file)
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

    entries = _entries(awm, state_file)
    assert entries[str(repo)]["enabled"] is True, "the parent checkout must stay armed"
    assert entries[str(worktree)]["enabled"] is False


# ── forget (#298) ────────────────────────────────────────────────────────────
# disable leaves the entry behind, so state.json accumulated one per directory AWM was
# ever enabled in — including deleted worktrees.

def _forget_fixture(awm, monkeypatch, tmp_path):
    """Two projects, both previously used; returns (state_file, here, other)."""
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    here, other = tmp_path / "here", tmp_path / "other"
    here.mkdir()
    other.mkdir()
    monkeypatch.chdir(other)
    awm.cmd_away("2h")
    monkeypatch.chdir(here)
    awm.cmd_away("2h")
    return state_file, here, other


def test_forget_refuses_an_armed_entry(tmp_path, load_script, monkeypatch, capsys):
    """Forgetting a live window is far likelier to be a slip than an intent."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file, here, _ = _forget_fixture(awm, monkeypatch, tmp_path)
    capsys.readouterr()

    rc = awm.cmd_forget()

    assert rc == 1
    assert "--force" in capsys.readouterr().out
    assert str(here) in _entries(awm, state_file)


def test_force_forgets_an_armed_entry(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file, here, other = _forget_fixture(awm, monkeypatch, tmp_path)
    capsys.readouterr()

    rc = awm.cmd_forget(force=True)

    assert rc == 0
    entries = _entries(awm, state_file)
    assert str(here) not in entries
    assert str(other) in entries, "forgetting one project must not touch another"


def test_forget_drops_a_disabled_entry_without_force(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file, here, other = _forget_fixture(awm, monkeypatch, tmp_path)
    awm.cmd_disable()
    capsys.readouterr()

    rc = awm.cmd_forget()

    assert rc == 0
    entries = _entries(awm, state_file)
    assert str(here) not in entries
    assert str(other) in entries


def test_forget_accepts_a_named_path(tmp_path, load_script, monkeypatch, capsys):
    """The usual case is a deleted worktree — you cannot cd into it to forget it."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file, here, other = _forget_fixture(awm, monkeypatch, tmp_path)
    capsys.readouterr()

    rc = awm.cmd_forget(str(other), force=True)

    entries = _entries(awm, state_file)
    assert rc == 0
    assert str(other) not in entries
    assert str(here) in entries


def test_forget_a_path_with_no_entry_says_so(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _forget_fixture(awm, monkeypatch, tmp_path)
    capsys.readouterr()

    rc = awm.cmd_forget(str(tmp_path / "never-used"))

    assert rc == 1
    assert "no entry" in capsys.readouterr().out.lower()


def test_forget_is_recorded_in_the_audit_log(tmp_path, load_script, monkeypatch, capsys):
    """Removal must be as auditable as enabling was."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    awm.cmd_away("2h")
    capsys.readouterr()

    awm.cmd_forget(force=True)

    last = _read_decisions(awm)[-1]
    assert last["type"] == "mode_forgotten"
    assert str(here) in last["detail"]


def test_forget_a_deleted_directory_still_works(tmp_path, load_script, monkeypatch, capsys):
    """The entry that motivated this was a worktree that no longer exists."""
    import shutil
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    gone, here = tmp_path / "gone", tmp_path / "here"
    gone.mkdir()
    here.mkdir()
    monkeypatch.chdir(gone)
    awm.cmd_away("2h")
    monkeypatch.chdir(here)
    shutil.rmtree(gone)
    capsys.readouterr()

    rc = awm.cmd_forget(str(gone), force=True)

    assert rc == 0
    assert str(gone) not in _entries(awm, state_file)


def test_main_routes_forget_and_its_force_flag(tmp_path, load_script, monkeypatch, capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    awm.main(["away", "2h"])
    capsys.readouterr()

    assert awm.main(["forget"]) == 1, "an armed entry needs --force"
    assert awm.main(["forget", "--force"]) == 0
    assert _entries(awm, state_file) == {}
# entry_here picks the most specific entry even when disabled, but the gate skips disabled
# entries and falls back to an enclosing one — so the CLI could claim "inactive" while every
# call auto-approved. That is the same disagreement this release exists to remove.

def _parent_armed_worktree_disabled(awm, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    worktree = repo / "wt"
    worktree.mkdir(parents=True)
    monkeypatch.chdir(repo)
    awm.cmd_away("2h")
    monkeypatch.chdir(worktree)
    awm.cmd_away("2h")
    awm.cmd_disable()
    return repo, worktree


def test_status_reports_the_window_the_gate_would_use(tmp_path, load_script, monkeypatch,
                                                       capsys):
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    repo, _ = _parent_armed_worktree_disabled(awm, monkeypatch, tmp_path)
    capsys.readouterr()

    awm.cmd_status()

    out = capsys.readouterr().out
    assert "inactive" not in out.lower(), "the gate auto-approves here; status must not deny it"
    assert "AWAY" in out
    assert str(repo) in out, "status should name the entry actually covering this directory"


def test_disable_says_when_an_enclosing_project_still_covers_this_directory(
        tmp_path, load_script, monkeypatch, capsys):
    """"Normal approvals resume" is false if a parent entry still matches this cwd."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    worktree = repo / "wt"
    worktree.mkdir(parents=True)
    monkeypatch.chdir(repo)
    awm.cmd_away("2h")
    monkeypatch.chdir(worktree)
    awm.cmd_away("2h")
    capsys.readouterr()

    awm.cmd_disable()

    out = capsys.readouterr().out
    assert "resume" not in out.lower(), "approvals do not resume while the parent is armed"
    assert str(repo) in out


def test_forget_from_a_subdirectory_removes_the_nearest_project(tmp_path, load_script,
                                                                 monkeypatch, capsys):
    """Third instance of first-match-vs-most-specific (#299 review): from inside a worktree,
    containment matches the enclosing repo too, and forgetting it would delete the wrong one."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    repo = tmp_path / "repo"
    worktree = repo / "wt"
    deep = worktree / "src" / "nested"
    deep.mkdir(parents=True)

    monkeypatch.chdir(repo)
    awm.cmd_away("2h")
    monkeypatch.chdir(worktree)
    awm.cmd_away("2h")
    monkeypatch.chdir(deep)
    capsys.readouterr()

    awm.cmd_forget(force=True)

    entries = _entries(awm, state_file)
    assert str(repo) in entries, "forgetting from a worktree must not delete the checkout"
    assert str(worktree) not in entries


# -- P1.2a: away-mode state as awm_state rows (per-project keys, legacy import, D5a window) --


def _row(awm, key):
    """One awm_state row of the test's user store, or None."""
    store = awm.open_store()
    try:
        return store.kv_get("awm_state", key)
    finally:
        store.close()


def _rows(awm):
    """Every awm_state row of the test's user store, keyed by project path."""
    store = awm.open_store()
    try:
        return store.kv_all("awm_state")
    finally:
        store.close()


def _write_legacy(state_file, projects):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"version": 2, "projects": projects}), encoding="utf-8")


def test_enable_persists_the_entry_as_an_awm_state_row_keyed_by_project(tmp_path, load_script,
                                                                        monkeypatch):
    """Partner mode lands as one row keyed by the resolved project root, not as a JSON file."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    awm.cmd_partner("2h")

    row = _row(awm, str(tmp_path.resolve()))
    assert row["enabled"] is True and row["mode"] == "partner"
    assert row["expires_at"] > row["enabled_at"], "the window stays wall-clock bounded"
    assert row["project"] == str(tmp_path.resolve())
    assert not (awm_dir / "state.json").exists(), "the legacy file is retired, not rewritten"


def test_first_write_imports_the_legacy_document_and_renames_it(tmp_path, load_script,
                                                                monkeypatch):
    """The first store write imports every legacy project, then renames state.json (D6).

    The other project's armed entry must survive verbatim: a migration keyed by anything but
    the project path would clobber or orphan it.
    """
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    other = tmp_path / "other-project"
    other_entry = {"enabled": True, "mode": "away", "project": str(other),
                   "expires_at": "2099-01-01T00:00:00+00:00"}
    _write_legacy(state_file, {str(other): other_entry})
    monkeypatch.chdir(tmp_path)

    awm.cmd_partner("2h")

    assert not state_file.exists()
    assert state_file.with_name("state.migrated.json").exists()
    rows = _rows(awm)
    assert rows[str(tmp_path.resolve())]["mode"] == "partner"
    assert rows[str(other)] == other_entry, "the imported sibling window is untouched"


def test_legacy_decisions_jsonl_imports_on_first_write_and_renames(tmp_path, load_script,
                                                                   monkeypatch):
    """The legacy JSONL audit log migrates to awm_decisions rows on the first write (D6).

    The JSONL has no natural key, so import identity is the row's own (ts, payload) content;
    every field the legacy appenders wrote (ts/type/detail, plus tool_name/session_id/cwd on
    gate lines) must survive verbatim. Legacy ts values are recent so the 60-day prune —
    which runs on this same triggering write — does not eat the imported rows mid-test.
    """
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    awm_dir = _patch_state_paths(awm, monkeypatch, tmp_path)
    decisions_file = awm_dir / "decisions.jsonl"
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    older = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
    legacy = [
        {"ts": older, "type": "mode_enabled", "detail": "mode=away"},
        {"ts": recent, "type": "auto_approve", "tool_name": "Bash",
         "session_id": "s1", "cwd": "/repo", "detail": "{}"},
    ]
    awm_dir.mkdir()
    decisions_file.write_text(
        "".join(json.dumps(entry) + "\n" for entry in legacy), encoding="utf-8")

    awm.log_event("decision", "first write after migration")

    assert not decisions_file.exists(), "the legacy file is retired, not rewritten"
    assert decisions_file.with_name("decisions.migrated.jsonl").exists()
    decisions = _read_decisions(awm)
    assert [d["type"] for d in decisions] == ["mode_enabled", "auto_approve", "decision"]
    assert decisions[1]["tool_name"] == "Bash"
    assert decisions[1]["session_id"] == "s1"
    assert decisions[1]["detail"] == "{}"


def test_reads_merge_the_legacy_file_until_the_first_write(tmp_path, load_script, monkeypatch):
    """D5a: reads see legacy-only projects during the window, and a read never migrates."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    other = tmp_path / "other-project"
    _write_legacy(state_file, {str(other): {"enabled": True, "mode": "away",
                                            "project": str(other),
                                            "expires_at": "2099-01-01T00:00:00+00:00"}})

    entries = awm.projects(awm.load_state() or {})

    assert str(other) in entries and entries[str(other)]["enabled"] is True
    assert state_file.exists(), "a read never renames the legacy file"


def test_load_state_falls_back_to_the_legacy_file_when_the_store_is_unavailable(
        tmp_path, load_script, monkeypatch):
    """A broken store reads exactly like today's missing file: fail open, never crash."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    (tmp_path / "user-root").write_text("a file, not a directory", encoding="utf-8")
    other = tmp_path / "other-project"
    _write_legacy(state_file, {str(other): {"enabled": True, "mode": "away",
                                            "project": str(other),
                                            "expires_at": "2099-01-01T00:00:00+00:00"}})

    entries = awm.projects(awm.load_state() or {})

    assert entries[str(other)]["enabled"] is True


def test_pre_296_single_project_legacy_imports_as_one_row(tmp_path, load_script, monkeypatch):
    """The pre-#296 shape (the top level IS the entry) imports under its own project key."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    state_file = _patch_state_paths(awm, monkeypatch, tmp_path) / "state.json"
    legacy_entry = {"enabled": False, "mode": "away", "project": str(tmp_path),
                    "expires_at": "2020-01-01T00:00:00+00:00", "disabled_reason": "expired"}
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(legacy_entry), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    awm.cmd_partner("2h")

    rows = _rows(awm)
    assert rows[str(tmp_path.resolve())]["mode"] == "partner"
    assert state_file.with_name("state.migrated.json").exists()


def test_disable_flips_only_this_projects_row(tmp_path, load_script, monkeypatch):
    """Disable writes this project's row off and leaves the other checkout's window armed."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    other = tmp_path / "other-project"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    awm.cmd_partner("2h")
    monkeypatch.chdir(other)
    awm.cmd_partner("2h")

    awm.cmd_disable("done")

    rows = _rows(awm)
    assert rows[str(other.resolve())]["enabled"] is False
    assert rows[str(other.resolve())]["disabled_reason"] == "done"
    assert rows[str(tmp_path.resolve())]["enabled"] is True, "the other window stays armed"


def test_forget_deletes_the_row_and_keeps_the_sibling(tmp_path, load_script, monkeypatch):
    """Forget drops exactly one project's row; the sibling checkout's row survives."""
    awm = load_script("features/claude/skills/auto-wm/scripts/awm.py")
    _patch_state_paths(awm, monkeypatch, tmp_path)
    other = tmp_path / "other-project"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    awm.cmd_away("2h")
    monkeypatch.chdir(other)
    awm.cmd_away("2h")

    assert awm.cmd_forget(force=True) == 0

    rows = _rows(awm)
    assert str(other.resolve()) not in rows
    assert str(tmp_path.resolve()) in rows
