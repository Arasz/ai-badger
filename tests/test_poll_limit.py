"""Tests for skills/task/scripts/poll_limit.py.

Ported from the originating job-search-ai-assistant repo's test_poll_limit.py (unittest style)
to this repo's pytest + load_script pattern. Covers session discovery (task-tracking store and
the ~/.claude/projects fallback), the dynamic wait schedule, resume-after-limit-lifts transition,
and the statusline-vs-probe branches (fresh/stale/expired/not-exhausted).
"""
from __future__ import annotations

import json

import pytest


def test_discovers_unfinished_task_sessions_from_tracking_store(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    # .ai-badger/task-tracking/, not .claude/ -- this must match wherever tracker_lib actually
    # writes executed-tasks.json (see the regression test below for what happens if it doesn't).
    data = tmp_path / ".ai-badger" / "task-tracking"
    data.mkdir(parents=True)
    transcript = data / "active.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    (data / "executed-tasks.json").write_text(json.dumps({
        "tasks": [
            {"taskId": "T01", "state": "IN_PROGRESS", "sessionId": "sid-1",
             "transcriptPath": str(transcript)},
            {"taskId": "T02", "state": "FINISHED", "sessionId": "sid-2"},
            {"taskId": "T03", "state": "STARTED"},
        ]
    }), encoding="utf-8")

    sessions = poll_limit.discover_target_sessions(tmp_path)

    assert [s.session_id for s in sessions] == ["sid-1"]
    assert sessions[0].task_id == "T01"


def test_discovers_sessions_from_user_claude_projects_jsonl_when_tracking_missing(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    user_claude = tmp_path / "home" / ".claude"
    project_dir = user_claude / "projects" / "repo"
    project_dir.mkdir(parents=True)
    transcript = project_dir / "session.jsonl"
    transcript.write_text(json.dumps({"sessionId": "sid-json", "cwd": str(project_root)}) + "\n",
                           encoding="utf-8")

    sessions = poll_limit.discover_target_sessions(project_root, user_claude)

    assert [s.session_id for s in sessions] == ["sid-json"]
    assert sessions[0].source == "claude-projects"


def test_discover_target_sessions_prefers_task_tracking_over_user_claude_fallback(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    project_root = tmp_path / "repo"
    data = project_root / ".ai-badger" / "task-tracking"
    data.mkdir(parents=True)
    (data / "executed-tasks.json").write_text(json.dumps({
        "tasks": [{"taskId": "T01", "state": "IN_PROGRESS", "sessionId": "sid-tracking"}]
    }), encoding="utf-8")
    user_claude = tmp_path / "home" / ".claude"
    project_dir = user_claude / "projects" / "repo"
    project_dir.mkdir(parents=True)
    (project_dir / "session.jsonl").write_text(
        json.dumps({"sessionId": "sid-fallback", "cwd": str(project_root)}) + "\n",
        encoding="utf-8",
    )

    sessions = poll_limit.discover_target_sessions(project_root, user_claude)

    assert [s.session_id for s in sessions] == ["sid-tracking"]


def test_discover_target_sessions_reads_tracker_libs_actual_data_dir(tmp_path, load_script):
    """Regression: on main, poll_limit reads executed-tasks.json from
    `<project_root>/.claude/task-tracking/`, but tracker_lib always writes it under
    `<project_root>/.ai-badger/task-tracking/`. That mismatch means _discover_task_sessions
    ALWAYS misses and silently falls through to the transcript-scanning fallback -- so the
    poller can never resume a tracked task after a usage limit lifts. Write the file through
    tracker_lib's own compute_paths() (the single source of truth for where it lives) and
    assert discovery actually finds it -- no hardcoded directory literal in this test either.
    """
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    project_root = tmp_path / "repo"
    tasks_path = poll_limit.lib.compute_paths(project_root)["executed_tasks"]
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text(json.dumps({
        "tasks": [{"taskId": "T09", "state": "IN_PROGRESS", "sessionId": "sid-real"}]
    }), encoding="utf-8")
    empty_user_claude = tmp_path / "home" / ".claude"  # isolate from the fallback path

    sessions = poll_limit.discover_target_sessions(project_root, empty_user_claude)

    assert [s.session_id for s in sessions] == ["sid-real"]


def test_log_pid_statusline_paths_share_tracker_libs_data_dir(load_script):
    """LOG_FILE / PID_FILE / STATUSLINE_STATE must live under the same directory tracker_lib
    computes for task tracking, not a separately hand-built `.claude/task-tracking/` literal --
    otherwise a scaffolded project ends up with two tracking directories, one of which isn't in
    the project's .gitignore."""
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")

    assert poll_limit.LOG_FILE.parent == poll_limit.lib.DATA_DIR
    assert poll_limit.PID_FILE.parent == poll_limit.lib.DATA_DIR
    assert poll_limit.STATUSLINE_STATE.parent == poll_limit.lib.DATA_DIR


def test_poll_once_resumes_after_limit_transition(load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")

    calls = []
    state = poll_limit.PollState(was_limited=True, auto_wm_on_reset=True)
    session = poll_limit.TargetSession(session_id="sid-1", task_id="T01", source="task-tracking")

    def check_limit():
        return False, "ok"

    def discover():
        return [session]

    def run_auto_wm():
        calls.append("auto")
        return True

    def resume(target):
        calls.append(("resume", target.session_id, target.task_id))
        return True

    poll_limit.poll_once(state, check_limit, discover, run_auto_wm, resume,
                          sleep_between_resumes=lambda _: None)

    assert calls == ["auto", ("resume", "sid-1", "T01")]
    assert state.was_limited is False


def test_poll_once_does_not_self_enable_auto_wm(load_script):
    """A limit reset must never turn auto-approval on by itself: opt-in is explicit (F-12)."""
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")

    calls = []
    state = poll_limit.PollState(was_limited=True)
    session = poll_limit.TargetSession(session_id="sid-1", source="task-tracking")

    poll_limit.poll_once(
        state,
        lambda: (False, "ok"),
        lambda: [session],
        lambda: calls.append("auto") or True,
        lambda target: calls.append(("resume", target.session_id)) or True,
        sleep_between_resumes=lambda _: None,
    )

    assert "auto" not in calls
    assert calls == [("resume", "sid-1")]


def test_main_does_not_opt_into_auto_wm_by_default(load_script, monkeypatch):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    seen = {}
    monkeypatch.setattr(poll_limit, "poll_once", lambda state: seen.update(state=state))
    monkeypatch.setattr(poll_limit.sys, "argv", ["poll_limit.py", "--once"])

    poll_limit.main()

    assert seen["state"].auto_wm_on_reset is False


def test_main_opts_into_auto_wm_only_with_the_explicit_flag(load_script, monkeypatch):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    seen = {}
    monkeypatch.setattr(poll_limit, "poll_once", lambda state: seen.update(state=state))
    monkeypatch.setattr(poll_limit.sys, "argv",
                        ["poll_limit.py", "--once", "--auto-wm-on-reset"])

    poll_limit.main()

    assert seen["state"].auto_wm_on_reset is True


def test_dynamic_wait_schedule_after_limit_detection(load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state = poll_limit.PollState()

    waits = [
        poll_limit.poll_once(state, lambda: (True, "limit"), lambda: [])
        for _ in range(5)
    ]

    assert waits == [7200, 1800, 900, 300, 300]


def test_dynamic_wait_resets_after_limit_lifts(load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state = poll_limit.PollState(was_limited=True, limited_checks=4)

    wait = poll_limit.poll_once(
        state,
        lambda: (False, "ok"),
        lambda: [],
        lambda: True,
        lambda target: True,
        sleep_between_resumes=lambda _: None,
    )

    assert wait == poll_limit.DEFAULT_AVAILABLE_INTERVAL_SECONDS
    assert state.limited_checks == 0


def test_poll_once_no_sessions_to_resume_still_clears_was_limited(load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state = poll_limit.PollState(was_limited=True)

    wait = poll_limit.poll_once(state, lambda: (False, "ok"), lambda: [], lambda: True)

    assert state.was_limited is False
    assert wait == poll_limit.DEFAULT_AVAILABLE_INTERVAL_SECONDS


def test_statusline_reset_time_is_used_before_probe(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state_file = tmp_path / "statusline-state.json"
    future_reset = int(poll_limit.time.time()) + 3600
    state_file.write_text(json.dumps({
        "capturedAt": poll_limit.datetime.now(poll_limit.timezone.utc).isoformat(),
        "rateLimits": {
            "five_hour": {"used_percentage": 100, "resets_at": future_reset},
        },
    }), encoding="utf-8")

    limited, output = poll_limit.check_limit_from_statusline(state_file)

    assert limited is True
    assert "statusline" in output


def test_statusline_expired_reset_reports_available(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state_file = tmp_path / "statusline-state.json"
    past_reset = int(poll_limit.time.time()) - 1
    state_file.write_text(json.dumps({
        "capturedAt": poll_limit.datetime.now(poll_limit.timezone.utc).isoformat(),
        "rateLimits": {
            "five_hour": {"used_percentage": 100, "resets_at": past_reset},
        },
    }), encoding="utf-8")

    limited, output = poll_limit.check_limit_from_statusline(state_file)

    assert limited is False
    assert "reset time passed" in output


def test_statusline_future_reset_but_window_not_exhausted_is_available(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state_file = tmp_path / "statusline-state.json"
    future_reset = int(poll_limit.time.time()) + 3600
    state_file.write_text(json.dumps({
        "capturedAt": poll_limit.datetime.now(poll_limit.timezone.utc).isoformat(),
        "rateLimits": {
            "five_hour": {"used_percentage": 42, "resets_at": future_reset},
        },
    }), encoding="utf-8")

    limited, output = poll_limit.check_limit_from_statusline(state_file)

    assert limited is False
    assert "not exhausted" in output
    assert "reset time passed" not in output


def test_stale_statusline_state_is_ignored_so_probe_can_run(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state_file = tmp_path / "statusline-state.json"
    stale_capture = poll_limit.datetime.fromtimestamp(0, tz=poll_limit.timezone.utc).isoformat()
    future_reset = int(poll_limit.time.time()) + 3600
    state_file.write_text(json.dumps({
        "capturedAt": stale_capture,
        "rateLimits": {
            "five_hour": {"used_percentage": 100, "resets_at": future_reset},
        },
    }), encoding="utf-8")

    result = poll_limit.check_limit_from_statusline(state_file)

    assert result is None


def test_statusline_missing_state_file_is_ignored_so_probe_can_run(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state_file = tmp_path / "does-not-exist.json"

    result = poll_limit.check_limit_from_statusline(state_file)

    assert result is None


def test_check_limit_from_statusline_missing_resets_at_returns_none(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    state_file = tmp_path / "statusline-state.json"
    state_file.write_text(json.dumps({
        "capturedAt": poll_limit.datetime.now(poll_limit.timezone.utc).isoformat(),
        "rateLimits": {"five_hour": {"used_percentage": 100}},
    }), encoding="utf-8")

    result = poll_limit.check_limit_from_statusline(state_file)

    assert result is None


def test_next_limit_wait_seconds_clamps_at_last_schedule_entry(load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")

    assert poll_limit.next_limit_wait_seconds(1) == 7200
    assert poll_limit.next_limit_wait_seconds(100) == 300


def test_already_running_false_when_pid_file_missing(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")

    assert poll_limit.already_running(tmp_path / "missing.pid") is False


def test_already_running_false_for_a_dead_pid(tmp_path, load_script):
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    pid_file = tmp_path / "poll_limit.pid"
    # PID unlikely to be alive: a huge, almost-certainly-unused process id.
    pid_file.write_text("999999", encoding="utf-8")

    assert poll_limit.already_running(pid_file) is False


def test_already_running_false_for_current_process_pid(tmp_path, load_script):
    import os
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    pid_file = tmp_path / "poll_limit.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    # The poller treats its own PID as "not already running" (it's this run's own marker).
    assert poll_limit.already_running(pid_file) is False


def test_write_pid_writes_current_pid(tmp_path, load_script):
    import os
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    pid_file = tmp_path / "nested" / "poll_limit.pid"

    poll_limit.write_pid(pid_file)

    assert pid_file.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_resume_session_reattach_prompt_references_task_tracker_under_own_script_dir(
    load_script, monkeypatch
):
    """The reattach prompt must point at task_tracker.py next to poll_limit.py itself, not a
    hardcoded `.claude/skills/task/scripts/` path -- that hardcoded path breaks whenever the
    skill is installed somewhere else (e.g. the plugin cache)."""
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    target = poll_limit.TargetSession(session_id="sid-1", task_id="T01", source="task-tracking")
    captured = {}

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd

    monkeypatch.setattr(poll_limit.subprocess, "Popen", fake_popen)

    poll_limit.resume_session(target)

    prompt = captured["cmd"][4]
    assert str(poll_limit.SCRIPT_DIR / "task_tracker.py") in prompt


# ── run_forever's stopping conditions ────────────────────────────────────────────
#
# run_forever was `while True:` with no cap, no liveness check and no parent check, so every
# poller ever started outlived its session and ran until the machine rebooted. Ten of them were
# found alive at once, six belonging to /private/tmp worktrees that no longer existed, and their
# writes into .ai-badger/task-tracking/ broke an unrelated pre-push test run.
#
# owner-gate-review's SKILL.md already states the rule this violated: "a watch with no stopping
# condition is a loop nobody can answer 'what ends this?' for, and it outlives the session that
# started it."


def _poller_at(tmp_path, load_script, monkeypatch):
    """poll_limit bound to a throwaway project root, with the real limit probe stubbed out."""
    poll_limit = load_script("features/common/skills/task/scripts/poll_limit.py")
    data = tmp_path / ".ai-badger" / "task-tracking"
    data.mkdir(parents=True)
    monkeypatch.setattr(poll_limit, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(poll_limit, "PID_FILE", data / "poll_limit.pid")
    monkeypatch.setattr(poll_limit, "LOG_FILE", data / "poll_limit.log")
    monkeypatch.setattr(poll_limit, "poll_once", lambda *a, **k: 300)
    return poll_limit, data


def _write_tasks(data, tasks):
    (data / "executed-tasks.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")


def test_run_forever_stops_at_the_wall_clock_cap(tmp_path, load_script, monkeypatch):
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    _write_tasks(data, [{"taskId": "T", "state": "IN_PROGRESS", "sessionId": "s"}])
    ticks = iter([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

    result = poll_limit.run_forever(
        interval_seconds=0, max_hours=5 / 3600, clock=lambda: next(ticks), sleeper=lambda _s: None,
    )

    assert result == 0


def test_the_cap_is_what_stopped_it_and_it_says_so(tmp_path, load_script, monkeypatch):
    """Asserts the *exit* line, not the word "cap".

    The first version of this test matched "cap" anywhere in the log — and the startup line
    says "Stops at the 12h cap", so it passed whatever ended the loop. Reported by review on
    PR #251. The sensitivity check below is what proves this one can now fail.
    """
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    _write_tasks(data, [{"taskId": "T", "state": "IN_PROGRESS", "sessionId": "s"}])
    ticks = iter(range(50))

    poll_limit.run_forever(
        interval_seconds=0, max_hours=3 / 3600, clock=lambda: next(ticks), sleeper=lambda _s: None,
    )

    assert "Reached the" in (data / "poll_limit.log").read_text()


def test_the_idle_exit_does_not_claim_the_cap_stopped_it(tmp_path, load_script, monkeypatch):
    """The sensitivity check: two exits, two different reasons, two different lines."""
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    _write_tasks(data, [{"taskId": "T", "state": "FINISHED", "sessionId": "s"}])

    poll_limit.run_forever(
        interval_seconds=0, max_hours=12, clock=lambda: 0.0, sleeper=lambda _s: None,
    )

    text = (data / "poll_limit.log").read_text()
    assert "nothing left to resume" in text
    assert "Reached the" not in text


def test_a_zero_or_negative_cap_is_refused(tmp_path, load_script, monkeypatch):
    """argparse accepts --max-hours 0 and -5 as floats; both would exit before the first poll."""
    poll_limit, _ = _poller_at(tmp_path, load_script, monkeypatch)

    for bad in (0, -5):
        with pytest.raises(ValueError):
            poll_limit.bounded_max_hours(bad)


def test_a_non_finite_cap_is_refused(tmp_path, load_script, monkeypatch):
    """nan makes every `clock() < deadline` false, so the loop exits logging "the nanh cap"."""
    poll_limit, _ = _poller_at(tmp_path, load_script, monkeypatch)

    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            poll_limit.bounded_max_hours(bad)


def test_remove_pid_resolves_its_path_at_call_time(tmp_path, load_script, monkeypatch):
    """Called bare after PID_FILE moved, it must not unlink the file at the old path.

    The PR fixed the call sites and left the default argument, which is the same import-time
    freeze it claimed to have fixed. Reported by review on PR #251.
    """
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    stale = tmp_path / "elsewhere.pid"
    stale.write_text("1", encoding="utf-8")
    monkeypatch.setattr(poll_limit, "PID_FILE", data / "poll_limit.pid")
    (data / "poll_limit.pid").write_text("2", encoding="utf-8")

    poll_limit.remove_pid()

    assert stale.exists(), "removed a pid file at the import-time path"
    assert not (data / "poll_limit.pid").exists()


def test_run_forever_exits_when_no_unfinished_task_remains(tmp_path, load_script, monkeypatch):
    """The poller resumes unfinished tasks. With none left it can never do anything again."""
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    _write_tasks(data, [{"taskId": "T", "state": "FINISHED", "sessionId": "s"}])

    result = poll_limit.run_forever(
        interval_seconds=0, max_hours=12, clock=lambda: 0.0, sleeper=lambda _s: None,
    )

    assert result == 0


def test_an_unfinished_task_keeps_it_polling_until_the_cap(tmp_path, load_script, monkeypatch):
    """The idle exit must not fire while there is still work to resume."""
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    _write_tasks(data, [{"taskId": "T", "state": "IN_PROGRESS", "sessionId": "s"}])
    polls = []
    monkeypatch.setattr(poll_limit, "poll_once", lambda *a, **k: polls.append(1) or 300)
    ticks = iter(range(60))

    poll_limit.run_forever(
        interval_seconds=0, max_hours=20 / 3600, clock=lambda: next(ticks), sleeper=lambda _s: None,
    )

    assert len(polls) > poll_limit.IDLE_POLLS_BEFORE_EXIT


def test_run_forever_removes_its_pid_file_on_exit(tmp_path, load_script, monkeypatch):
    """A poller that exits leaving its pid file behind is one already_running has to second-guess."""
    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    _write_tasks(data, [{"taskId": "T", "state": "FINISHED", "sessionId": "s"}])

    poll_limit.run_forever(
        interval_seconds=0, max_hours=12, clock=lambda: 0.0, sleeper=lambda _s: None,
    )

    assert not (data / "poll_limit.pid").exists()


def test_a_second_poller_still_refuses_to_start(tmp_path, load_script, monkeypatch):
    """The cap must not weaken the existing single-instance guard."""
    import os

    poll_limit, data = _poller_at(tmp_path, load_script, monkeypatch)
    (data / "poll_limit.pid").write_text(str(os.getppid()), encoding="utf-8")
    _write_tasks(data, [{"taskId": "T", "state": "IN_PROGRESS", "sessionId": "s"}])

    result = poll_limit.run_forever(
        interval_seconds=0, max_hours=12, clock=lambda: 0.0, sleeper=lambda _s: None,
    )

    assert result == 0
    assert "already running" in (data / "poll_limit.log").read_text()


def test_the_cap_is_bounded_even_when_asked_for_more(tmp_path, load_script, monkeypatch):
    """A caller cannot re-create the unbounded loop by passing a huge cap."""
    poll_limit, _ = _poller_at(tmp_path, load_script, monkeypatch)

    assert poll_limit.bounded_max_hours(9999) == poll_limit.MAX_MAX_HOURS
    assert poll_limit.bounded_max_hours(4) == 4


def test_a_bad_cap_on_the_command_line_is_a_message_not_a_traceback(
    tmp_path, load_script, monkeypatch, capsys
):
    """bounded_max_hours raising is right; showing the user a stack trace for a typo is not."""
    poll_limit, _ = _poller_at(tmp_path, load_script, monkeypatch)
    monkeypatch.setattr("sys.argv", ["poll_limit.py", "--max-hours", "0"])

    result = poll_limit.main()

    assert result == 2
    assert "greater than zero" in capsys.readouterr().err
