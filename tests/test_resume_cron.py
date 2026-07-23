"""Tests for skills/task/scripts/resume_cron.py.

Covers the cron-invoked resume-after-usage-limit logic: staleness/cooldown predicates, the
usage-limit probe, resuming a single task (success, dry-run, timeout), and the full run() loop
(no stalled tasks, probe succeeds, probe fails, --dry-run, and the cross-process lock guard).

Every subprocess.run call (probe + resume) is mocked via monkeypatch on the module's own
`subprocess` reference — a real `claude` process must never be spawned. The lock-file test
acquires a real fcntl flock, but only on a file under tmp_path, never the real repo's lock.
"""
from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def resume_cron(tmp_path, load_script, monkeypatch):
    module = load_script("features/common/skills/task/scripts/resume_cron.py")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(module.lib, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module.lib, "DATA_DIR", data_dir)
    monkeypatch.setattr(module.lib, "EXECUTED_TASKS", data_dir / "executed-tasks.json")
    monkeypatch.setattr(module.lib, "LOCK_FILE", data_dir / ".write.lock")
    monkeypatch.setattr(module, "CRON_LOCK", data_dir / ".cron.lock")
    return module


def _write_tasks(module, tasks):
    module.lib.save_json(module.lib.EXECUTED_TASKS, {"tasks": tasks})


def _old_iso(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _stale_transcript(tmp_path, name="t.jsonl"):
    """A transcript file with an mtime old enough to count as stale (see transcript_stale())."""
    transcript = tmp_path / name
    transcript.write_text("{}\n", encoding="utf-8")
    old_time = time.time() - 60 * 60
    os.utime(transcript, (old_time, old_time))
    return str(transcript)


# --- transcript_stale ------------------------------------------------------------------

def test_transcript_stale_true_for_old_transcript_mtime(resume_cron, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    old_time = time.time() - 60 * 60  # 60 minutes ago, > STALE_MINUTES (25)
    os.utime(transcript, (old_time, old_time))

    assert resume_cron.transcript_stale({"transcriptPath": str(transcript)}) is True


def test_transcript_stale_false_for_fresh_transcript(resume_cron, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")

    assert resume_cron.transcript_stale({"transcriptPath": str(transcript)}) is False


def test_transcript_stale_falls_back_to_started_at_for_a_missing_transcript_file(resume_cron, tmp_path):
    # transcriptPath is set but the file was never written (or was removed) -- the "no
    # transcript to watch" branch in transcript_stale() -- so staleness must come from startedAt.
    missing = str(tmp_path / "never-written.jsonl")
    assert resume_cron.transcript_stale({"transcriptPath": missing, "startedAt": _old_iso(60)}) is True
    assert resume_cron.transcript_stale({"transcriptPath": missing, "startedAt": _old_iso(5)}) is False


def test_transcript_stale_missing_transcript_key_checks_cwd_mtime_not_started_at(
    resume_cron, tmp_path, monkeypatch
):
    """Documents a quirk in transcript_stale(), not fixed here (ported-verbatim script; see task
    report): `Path(entry.get("transcriptPath") or "")` collapses to `Path("")` == `Path(".")`
    when transcriptPath is absent/empty, and `Path(".").exists()` is always True (the cwd always
    exists) -- so the "no transcript to watch; fall back to startedAt" branch described in the
    function's own comment is unreachable for a missing transcriptPath. What actually runs is
    the mtime branch, checking the *process cwd's* mtime and ignoring startedAt entirely.
    """
    monkeypatch.chdir(tmp_path)
    old = time.time() - 60 * 60
    os.utime(tmp_path, (old, old))

    # A *recent* startedAt would mean "not stale" if the docstring's fallback ran -- but this
    # entry has no transcriptPath, so staleness tracks the (artificially aged) cwd instead.
    assert resume_cron.transcript_stale({"startedAt": _old_iso(1)}) is True


# --- recently_attempted -----------------------------------------------------------------

def test_recently_attempted_true_within_cooldown(resume_cron):
    entry = {"resumeAttempts": [{"at": resume_cron.lib.now_iso()}]}
    assert resume_cron.recently_attempted(entry) is True


def test_recently_attempted_false_after_cooldown(resume_cron):
    entry = {"resumeAttempts": [{"at": _old_iso(90)}]}
    assert resume_cron.recently_attempted(entry) is False


def test_recently_attempted_false_when_no_attempts(resume_cron):
    assert resume_cron.recently_attempted({}) is False


# --- usage_limit_lifted (the probe) ------------------------------------------------------

def test_usage_limit_lifted_true_on_successful_probe(resume_cron, monkeypatch):
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
    monkeypatch.setattr(resume_cron.subprocess, "run", lambda *a, **k: completed)

    assert resume_cron.usage_limit_lifted() is True


def test_usage_limit_lifted_false_on_nonzero_exit(resume_cron, monkeypatch, capsys):
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="rate limited")
    monkeypatch.setattr(resume_cron.subprocess, "run", lambda *a, **k: completed)

    assert resume_cron.usage_limit_lifted() is False
    assert "rate limited" in capsys.readouterr().out


def test_usage_limit_lifted_false_when_probe_times_out(resume_cron, monkeypatch, capsys):
    def _raise(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=120)

    monkeypatch.setattr(resume_cron.subprocess, "run", _raise)

    assert resume_cron.usage_limit_lifted() is False
    assert "probe failed to run" in capsys.readouterr().out


# --- resume_task -------------------------------------------------------------------------

def test_resume_task_dry_run_does_not_invoke_subprocess(resume_cron, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(resume_cron.subprocess, "run", lambda *a, **k: calls.append(1))

    resume_cron.resume_task({"taskId": "T01", "sessionId": "sid-1"}, dry_run=True)

    assert calls == []
    assert "[dry-run]" in capsys.readouterr().out


def test_resume_task_logs_exit_code_on_success(resume_cron, monkeypatch, capsys):
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="done", stderr="")
    monkeypatch.setattr(resume_cron.subprocess, "run", lambda *a, **k: completed)

    resume_cron.resume_task({"taskId": "T01", "sessionId": "sid-1"}, dry_run=False)

    assert "resume T01 exited 0" in capsys.readouterr().out


def test_resume_task_logs_still_running_when_timeout_expires(resume_cron, monkeypatch, capsys):
    def _raise(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=resume_cron.RESUME_TIMEOUT_S)

    monkeypatch.setattr(resume_cron.subprocess, "run", _raise)

    resume_cron.resume_task({"taskId": "T01", "sessionId": "sid-1"}, dry_run=False)

    out = capsys.readouterr().out
    assert "still running after" in out
    assert "leaving it to the next cron cycle" in out


# --- run() (the main resume loop) ---------------------------------------------------------

def test_run_does_nothing_when_no_tasks_are_stalled(resume_cron, monkeypatch):
    _write_tasks(resume_cron, [])
    monkeypatch.setattr(
        resume_cron.subprocess, "run", lambda *a, **k: pytest.fail("should not shell out")
    )

    assert resume_cron.run(dry_run=False) == 0


def test_run_resumes_stalled_task_when_probe_succeeds(resume_cron, monkeypatch, tmp_path):
    _write_tasks(resume_cron, [
        {"taskId": "T01", "state": "IN_PROGRESS", "sessionId": "sid-1",
         "startedAt": _old_iso(60), "transcriptPath": _stale_transcript(tmp_path)},
    ])
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return completed

    monkeypatch.setattr(resume_cron.subprocess, "run", fake_run)

    rc = resume_cron.run(dry_run=False)

    assert rc == 0
    assert len(calls) == 2  # probe + resume
    entry = resume_cron.lib.load_tasks()["tasks"][0]
    assert entry["state"] == "IN_PROGRESS"
    assert len(entry["resumeAttempts"]) == 1
    assert entry["resumeAttempts"][0]["dryRun"] is False


def test_run_skips_resume_when_probe_fails(resume_cron, monkeypatch, tmp_path):
    _write_tasks(resume_cron, [
        {"taskId": "T01", "state": "IN_PROGRESS", "sessionId": "sid-1",
         "startedAt": _old_iso(60), "transcriptPath": _stale_transcript(tmp_path)},
    ])
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="still limited")
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return completed

    monkeypatch.setattr(resume_cron.subprocess, "run", fake_run)

    rc = resume_cron.run(dry_run=False)

    assert rc == 0
    assert len(calls) == 1  # probe only, resume never attempted
    entry = resume_cron.lib.load_tasks()["tasks"][0]
    assert "resumeAttempts" not in entry


def test_run_dry_run_skips_probe_and_never_shells_out(resume_cron, monkeypatch, tmp_path):
    _write_tasks(resume_cron, [
        {"taskId": "T01", "state": "IN_PROGRESS", "sessionId": "sid-1",
         "startedAt": _old_iso(60), "transcriptPath": _stale_transcript(tmp_path)},
    ])
    monkeypatch.setattr(
        resume_cron.subprocess, "run", lambda *a, **k: pytest.fail("dry-run must not shell out")
    )

    rc = resume_cron.run(dry_run=True)

    assert rc == 0
    entry = resume_cron.lib.load_tasks()["tasks"][0]
    assert entry["resumeAttempts"][0]["dryRun"] is True


def test_run_skips_when_lock_already_held(resume_cron, monkeypatch):
    _write_tasks(resume_cron, [
        {"taskId": "T01", "state": "IN_PROGRESS", "sessionId": "sid-1", "startedAt": _old_iso(60)},
    ])
    monkeypatch.setattr(
        resume_cron.subprocess, "run", lambda *a, **k: pytest.fail("should not run while locked")
    )

    resume_cron.lib.ensure_data_dir()
    holder = open(resume_cron.CRON_LOCK, "w", encoding="utf-8")
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        rc = resume_cron.run(dry_run=False)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()

    assert rc == 0
    entry = resume_cron.lib.load_tasks()["tasks"][0]
    assert "resumeAttempts" not in entry


def test_main_wires_dry_run_flag_through_argv(resume_cron, monkeypatch):
    _write_tasks(resume_cron, [])
    monkeypatch.setattr(sys, "argv", ["resume_cron.py", "run", "--dry-run"])

    assert resume_cron.main() == 0
