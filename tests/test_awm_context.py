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


def _scope_here(module, monkeypatch, tmp_path):
    """Point the session at a project dir and return it, so state can be scoped to it.

    Since #296 the banner only speaks for the project the window was enabled in, so a
    state file with no project reaches no session at all.
    """
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    monkeypatch.setattr(module, "session_cwd", lambda: str(project))
    return project


def _entry(state_file, project):
    """The per-project entry the hook writes back."""
    return json.loads(state_file.read_text(encoding="utf-8"))["projects"][str(project)]


def _run_main_never_raises(module):
    """Mirror the script's own top-level guard (`if __name__ == "__main__":`): internal
    errors never surface and never produce output.
    """
    try:
        module.main()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def test_disabled_mode_emits_nothing(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    _write_state(state_file, {"enabled": False})

    context.main()

    assert capsys.readouterr().out == ""


def test_partner_mode_prints_status(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    project = _scope_here(context, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=3)
    _write_state(state_file, {"enabled": True, "mode": "partner", "project": str(project),
                               "enabled_at": datetime.now(timezone.utc).isoformat(),
                               "expires_at": expires_at.isoformat()})

    context.main()

    out = capsys.readouterr().out
    assert "[auto-wm] PARTNER MODE ACTIVE" in out
    assert "remaining" in out


def test_partner_expired_prints_expired_and_flips_state_off(tmp_path, load_script, monkeypatch,
                                                              capsys):
    """Partner mode is bounded now, so the context hook must retire it like away mode (F-12)."""
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, decisions_file = _patch_state_paths(context, monkeypatch, tmp_path)
    project = _scope_here(context, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_state(state_file, {"enabled": True, "mode": "partner", "project": str(project),
                               "enabled_at": (expires_at - timedelta(hours=8)).isoformat(),
                               "expires_at": expires_at.isoformat()})

    context.main()

    assert "PARTNER MODE EXPIRED" in capsys.readouterr().out
    entry = _entry(state_file, project)
    assert entry["enabled"] is False
    assert entry["disabled_reason"] == "expired"
    assert json.loads(decisions_file.read_text(encoding="utf-8").splitlines()[-1])["type"] == \
        "mode_expired"


def test_away_active_prints_remaining_time(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    project = _scope_here(context, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1, minutes=30)
    _write_state(state_file, {"enabled": True, "mode": "away", "project": str(project),
                               "enabled_at": datetime.now(timezone.utc).isoformat(),
                               "expires_at": expires_at.isoformat()})

    context.main()

    out = capsys.readouterr().out
    assert "[auto-wm] AWAY MODE ACTIVE" in out
    assert "remaining" in out


def test_away_expired_prints_expired_and_flips_state_off(tmp_path, load_script, monkeypatch,
                                                           capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, decisions_file = _patch_state_paths(context, monkeypatch, tmp_path)
    project = _scope_here(context, monkeypatch, tmp_path)
    expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_state(state_file, {"enabled": True, "mode": "away", "project": str(project),
                               "enabled_at": (expires_at - timedelta(hours=4)).isoformat(),
                               "expires_at": expires_at.isoformat()})

    context.main()

    out = capsys.readouterr().out
    assert "AWAY MODE EXPIRED" in out
    entry = _entry(state_file, project)
    assert entry["enabled"] is False
    assert entry["disabled_reason"] == "expired"
    decisions = decisions_file.read_text(encoding="utf-8").splitlines()
    assert json.loads(decisions[-1])["type"] == "mode_expired"


def test_missing_state_file_is_silent_via_entrypoint_guard(tmp_path, load_script, monkeypatch,
                                                             capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    _patch_state_paths(context, monkeypatch, tmp_path)  # STATE_FILE points at a nonexistent path

    _run_main_never_raises(context)

    assert capsys.readouterr().out == ""


def test_internal_error_is_recorded_somewhere(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    errors = tmp_path / "hook-errors.log"
    monkeypatch.setattr(context, "HOOK_ERRORS_FILE", errors)

    def explode():
        raise RuntimeError("unreadable state")

    monkeypatch.setattr(context, "main", explode)

    rc = context.guarded_main()

    assert rc == 0
    assert "awm_context" in errors.read_text(encoding="utf-8")
    assert "awm_context" in capsys.readouterr().err


# ── project scope (#296) ─────────────────────────────────────────────────────
# The gate has always refused a call from outside the scoped project; the banner never
# checked, so it announced away mode in projects where every call was denied.

def _armed(project, mode="away", hours=3):
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {"enabled": True, "mode": mode, "project": str(project),
            "enabled_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires.isoformat()}


def test_no_banner_when_the_window_belongs_to_another_project(
        tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    elsewhere = tmp_path / "other-project"
    here = tmp_path / "this-project"
    here.mkdir()
    _write_state(state_file, _armed(elsewhere))
    monkeypatch.setattr(context, "session_cwd", lambda: str(here))

    context.main()

    assert capsys.readouterr().out == ""


def test_banner_when_the_window_belongs_to_this_project(
        tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    here = tmp_path / "this-project"
    here.mkdir()
    _write_state(state_file, _armed(here))
    monkeypatch.setattr(context, "session_cwd", lambda: str(here))

    context.main()

    assert "[auto-wm] AWAY MODE ACTIVE" in capsys.readouterr().out


def test_a_subdirectory_of_the_scoped_project_still_gets_the_banner(
        tmp_path, load_script, monkeypatch, capsys):
    """Worktrees and nested dirs are the normal case, not an edge one."""
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    here = tmp_path / "this-project"
    (here / "sub" / "deeper").mkdir(parents=True)
    _write_state(state_file, _armed(here))
    monkeypatch.setattr(context, "session_cwd", lambda: str(here / "sub" / "deeper"))

    context.main()

    assert "[auto-wm] AWAY MODE ACTIVE" in capsys.readouterr().out


def test_two_projects_are_armed_at_once(tmp_path, load_script, monkeypatch, capsys):
    """The whole point of per-project state: enabling one no longer disarms the other."""
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    expires = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    _write_state(state_file, {"version": 2, "projects": {
        str(a): {"enabled": True, "mode": "away", "expires_at": expires},
        str(b): {"enabled": True, "mode": "partner", "expires_at": expires},
    }})

    monkeypatch.setattr(context, "session_cwd", lambda: str(a))
    context.main()
    assert "AWAY MODE ACTIVE" in capsys.readouterr().out

    monkeypatch.setattr(context, "session_cwd", lambda: str(b))
    context.main()
    assert "PARTNER MODE ACTIVE" in capsys.readouterr().out


def test_one_projects_expiry_does_not_retire_another(tmp_path, load_script, monkeypatch, capsys):
    context = load_script("features/claude/skills/auto-wm/hooks/awm_context.py")
    state_file, _ = _patch_state_paths(context, monkeypatch, tmp_path)
    stale, live = tmp_path / "stale", tmp_path / "live"
    stale.mkdir()
    live.mkdir()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    _write_state(state_file, {"version": 2, "projects": {
        str(stale): {"enabled": True, "mode": "away", "expires_at": past},
        str(live): {"enabled": True, "mode": "away", "expires_at": future},
    }})

    monkeypatch.setattr(context, "session_cwd", lambda: str(stale))
    context.main()
    assert "EXPIRED" in capsys.readouterr().out

    monkeypatch.setattr(context, "session_cwd", lambda: str(live))
    context.main()
    assert "AWAY MODE ACTIVE" in capsys.readouterr().out
