"""Tests for skills/task/scripts/task_tracker.py.

task_tracker.py does `import tracker_lib as lib` with no sys.path bootstrap of its own (unlike
the hook scripts): it relies on being launched as `python3 task_tracker.py ...`, where Python
auto-adds the script's own directory to sys.path[0]. Loading it via `load_script` (importlib) does
not get that for free, so the `tt` fixture below explicitly prepends
`skills/task/scripts` to sys.path before loading it.

`main()` reads argv via `argparse`'s default (`sys.argv[1:]`) rather than accepting a parameter,
so the `_run` helper drives it in-process by patching `sys.argv` and calling `tt.main()` directly
- no subprocess is ever spawned for the CLI.

Every test redirects all of tracker_lib's path constants into `tmp_path` (see `_redirect_lib`),
and replaces the `subprocess` name inside the task_tracker module with a guard that raises if
anything tries to shell out - so `install-cron`/`uninstall-cron` tests must explicitly install
their own fake before exercising that code path, and every other test would fail loudly instead
of silently touching a real crontab.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta

import pytest
from conftest import _test_write

SCRIPT_RELPATH = "features/common/skills/task/scripts/task_tracker.py"


class _GuardedSubprocess:
    """Stand-in for the `subprocess` module: raises if anything tries to shell out.

    It mirrors the module's *exception* surface as well as its callables. `except
    subprocess.CalledProcessError` is evaluated even on the paths that never shell out, so a stub
    missing the attribute fails those with an AttributeError that looks like a product bug.
    """

    CalledProcessError = subprocess.CalledProcessError

    @staticmethod
    def run(*args, **kwargs):
        raise AssertionError(
            f"unexpected subprocess.run call (real cron/process access is forbidden in tests): "
            f"args={args!r} kwargs={kwargs!r}"
        )


def _redirect_lib(lib, tmp_path):
    data_dir = tmp_path / ".ai-badger" / "task-tracking"
    lib.PROJECT_ROOT = tmp_path
    lib.DATA_DIR = data_dir
    lib.EXECUTED_TASKS = data_dir / "executed-tasks.json"
    lib.TOKEN_USAGE = data_dir / "token-usage.json"
    lib.CURRENT_SESSION = data_dir / "current-session.json"
    lib.LOCK_FILE = data_dir / ".write.lock"
    lib.STATE_JSON = tmp_path / ".ai-badger" / "state.json"
    lib.CONFIG_JSON = tmp_path / ".ai-badger" / "config.json"
    lib.CLAUDE_MD = tmp_path / "CLAUDE.md"


@pytest.fixture
def tt(load_script, root, monkeypatch, tmp_path):
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    module = load_script(SCRIPT_RELPATH)
    _redirect_lib(module.lib, tmp_path)
    # These tests exercise the transcript (claude) data path; register its session source
    # exactly as the claude adjustment would in a scaffolded project.
    claude = load_script("features/claude/adjustments/claude_session_source.py")
    claude.register(module.lib)
    monkeypatch.setattr(module, "subprocess", _GuardedSubprocess())
    return module


def _run(monkeypatch, module, *args):
    """Call task_tracker's main() in-process (no subprocess) with the given CLI args."""
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", *args])
    return module.main()


def _write_transcript(path, records):
    """records: list of (is_sidechain, input, output, cache_read, cache_creation) tuples."""
    lines = []
    for is_side, inp, out, cr, cc in records:
        lines.append(json.dumps({
            "type": "assistant",
            "isSidechain": is_side,
            "message": {
                "usage": {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": cr,
                    "cache_creation_input_tokens": cc,
                }
            },
        }))
    _test_write(path, "\n".join(lines) + "\n", encoding="utf-8")


def _no_cron_recorder(monkeypatch, tt_module):
    """Replace install_cron with a call recorder so 'start' never touches real cron."""
    calls = []
    monkeypatch.setattr(tt_module, "install_cron", lambda quiet=False: calls.append(quiet) or 0)
    return calls


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

def test_start_registers_task_and_starts_checkpoint(tt, monkeypatch, tmp_path, capsys):
    _no_cron_recorder(monkeypatch, tt)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [(False, 10, 2, 0, 0)])

    code = _run(monkeypatch, tt, "start", "T01",
                "--session-id", "sid-1", "--transcript-path", str(transcript))

    assert code == 0
    tasks = tt.lib.load_tasks()
    entry = tt.lib.find_entry(tasks, "T01")
    assert entry["state"] == tt.lib.STATE_STARTED
    assert entry["sessionId"] == "sid-1"
    assert entry["title"] == ""
    assert entry["branch"] == ""
    usage = tt.lib.load_usage()
    usage_entry = tt.lib.find_entry(usage, "T01")
    assert usage_entry["checkpoints"]["start"]["contextTokens"] == 10
    out = json.loads(capsys.readouterr().out)
    assert out["taskId"] == "T01"
    assert out["startContextTokens"] == 10


def test_start_persists_title_and_branch(tt, monkeypatch, tmp_path):
    """`--no-worktree` keeps this focused on persistence — and keeps the no-subprocess guard.

    Since D2, a bare `start` creates a git worktree for the branch it records. That is covered
    by `test_task_owns_a_worktree.py`, which uses a real repo; here it would only mean shelling
    out, which `_GuardedSubprocess` exists to forbid.
    """
    _no_cron_recorder(monkeypatch, tt)
    transcript = tmp_path / "t.jsonl"

    code = _run(monkeypatch, tt, "start", "T02", "--title", "Fix widgets",
                "--branch", "feat/widgets", "--no-worktree", "--session-id", "sid-2",
                "--transcript-path", str(transcript))

    assert code == 0
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T02")
    assert entry["title"] == "Fix widgets"
    assert entry["branch"] == "feat/widgets"


def test_start_reaches_for_a_worktree_unless_told_not_to(tt, monkeypatch, tmp_path):
    """The flag must actually gate the call, or `--no-worktree` is decoration.

    The session ids must differ. A first draft reused one, and `cmd_start` refuses to attach a
    session to a second unfinished task — so the second run exited before reaching the gate and
    the test passed with the gate deleted outright. Verified by deleting it.
    """
    _no_cron_recorder(monkeypatch, tt)
    asked = []
    monkeypatch.setattr(tt, "ensure_worktree",
                        lambda root, task_id, branch: asked.append((task_id, branch)))

    assert _run(monkeypatch, tt, "start", "T02a", "--branch", "feat/w", "--session-id", "s-a",
                "--transcript-path", str(tmp_path / "a.jsonl")) == 0
    assert _run(monkeypatch, tt, "start", "T02b", "--branch", "feat/w", "--no-worktree",
                "--session-id", "s-b", "--transcript-path", str(tmp_path / "b.jsonl")) == 0

    assert asked == [("T02a", "feat/w")]


def test_start_keeps_stdout_valid_json_when_it_makes_a_worktree(tt, monkeypatch, tmp_path,
                                                                capsys):
    """stdout is a machine-readable contract; the worktree path is a JSON field, not a line."""
    _no_cron_recorder(monkeypatch, tt)
    monkeypatch.setattr(tt, "ensure_worktree",
                        lambda root, task_id, branch: tmp_path / "wt" / task_id)

    _run(monkeypatch, tt, "start", "T02c", "--branch", "feat/w", "--session-id", "s-c",
         "--transcript-path", str(tmp_path / "c.jsonl"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["worktree"] == str(tmp_path / "wt" / "T02c")


def test_start_survives_git_being_missing(tt, monkeypatch, tmp_path, capsys):
    """A missing git must not traceback after state was already persisted."""
    _no_cron_recorder(monkeypatch, tt)

    def _no_git(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(tt, "ensure_worktree", _no_git)

    code = _run(monkeypatch, tt, "start", "T02d", "--branch", "feat/w", "--session-id", "s-d",
                "--transcript-path", str(tmp_path / "d.jsonl"))

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["worktree"] is None
    assert "git" in captured.err
    assert tt.lib.find_entry(tt.lib.load_tasks(), "T02d") is not None


def test_start_with_no_cron_flag_never_calls_install_cron(tt, monkeypatch, tmp_path):
    calls = _no_cron_recorder(monkeypatch, tt)
    transcript = tmp_path / "t.jsonl"

    code = _run(monkeypatch, tt, "start", "T03", "--no-cron",
                "--session-id", "sid-3", "--transcript-path", str(transcript))

    assert code == 0
    assert calls == []


def test_start_without_cron_flag_does_not_install_cron(tt, monkeypatch, tmp_path):
    """Cron install is opt-in: no --cron, no crontab write (F-04)."""
    calls = _no_cron_recorder(monkeypatch, tt)
    transcript = tmp_path / "t.jsonl"

    code = _run(monkeypatch, tt, "start", "T04",
                "--session-id", "sid-4", "--transcript-path", str(transcript))

    assert code == 0
    assert calls == []


def test_start_refuses_when_session_already_attached_to_another_unfinished_task(
    tt, monkeypatch, tmp_path, capsys
):
    _no_cron_recorder(monkeypatch, tt)
    transcript = tmp_path / "t.jsonl"
    _run(monkeypatch, tt, "start", "T01",
         "--session-id", "sid-shared", "--transcript-path", str(transcript))

    code = _run(monkeypatch, tt, "start", "T02",
                "--session-id", "sid-shared", "--transcript-path", str(transcript))

    assert code == 2
    err = capsys.readouterr().err
    assert "already attached to task" in err
    assert "'T01'" in err
    assert tt.lib.find_entry(tt.lib.load_tasks(), "T02") is None


def test_start_refuses_to_restart_a_finished_task(tt, monkeypatch, tmp_path, capsys):
    _no_cron_recorder(monkeypatch, tt)
    transcript = tmp_path / "t.jsonl"
    _run(monkeypatch, tt, "start", "T01",
         "--session-id", "sid-1", "--transcript-path", str(transcript))
    tasks = tt.lib.load_tasks()
    tt.lib.find_entry(tasks, "T01")["state"] = tt.lib.STATE_FINISHED
    tt.lib.save_json(tt.lib.EXECUTED_TASKS, tasks)

    code = _run(monkeypatch, tt, "start", "T01",
                "--session-id", "sid-new", "--transcript-path", str(transcript))

    assert code == 2
    assert "already FINISHED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------

def _start(monkeypatch, tt, task_id, transcript, session_id="sid-1"):
    _no_cron_recorder(monkeypatch, tt)
    _run(monkeypatch, tt, "start", task_id,
         "--session-id", session_id, "--transcript-path", str(transcript))


def test_finish_is_blocked_when_state_json_not_updated_since_start(tt, monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)

    code = _run(monkeypatch, tt, "finish", "T01")

    assert code == 3
    err = capsys.readouterr().err
    assert "state.json has not been modified since task start" in err
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T01")
    assert entry["state"] == tt.lib.STATE_STARTED


def test_finish_succeeds_when_state_json_was_updated_since_start(tt, monkeypatch, tmp_path, capsys):
    start_transcript = tmp_path / "t.jsonl"
    _write_transcript(start_transcript, [(False, 100, 20, 10, 5)])
    _start(monkeypatch, tt, "T01", start_transcript)
    capsys.readouterr()  # discard start's output

    started_at = tt.lib.find_entry(tt.lib.load_tasks(), "T01")["startedAt"]
    started_dt = tt.lib.parse_iso(started_at)
    tt.lib.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    _test_write(tt.lib.STATE_JSON, "{}", encoding="utf-8")
    later = (started_dt + timedelta(seconds=5)).timestamp()
    import os
    os.utime(tt.lib.STATE_JSON, (later, later))

    # Grow the transcript before finishing, so the usage delta is non-zero.
    _write_transcript(start_transcript, [
        (False, 100, 20, 10, 5),
        (False, 250, 60, 10, 5),
    ])

    code = _run(monkeypatch, tt, "finish", "T01")

    assert code == 0
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T01")
    assert entry["state"] == tt.lib.STATE_FINISHED
    assert entry["finishedAt"] is not None
    assert entry["stateJsonUpdated"] is True
    out = json.loads(capsys.readouterr().out)
    assert out["usage"]["inputTokens"] == 250
    assert out["usage"]["outputTokens"] == 60


def test_finish_force_bypasses_the_state_json_check(tt, monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)

    code = _run(monkeypatch, tt, "finish", "T01", "--force")

    assert code == 0
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T01")
    assert entry["state"] == tt.lib.STATE_FINISHED


def test_finish_unknown_task_returns_exit_code_2(tt, monkeypatch, capsys):
    code = _run(monkeypatch, tt, "finish", "T-nope")

    assert code == 2
    assert "Unknown task" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------

def test_grade_saves_a_valid_grade(tt, monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)

    code = _run(monkeypatch, tt, "grade", "T01", "4")

    assert code == 0
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "T01")
    assert usage_entry["grade"] == 4
    assert usage_entry["gradedAt"] is not None
    assert "4/5" in capsys.readouterr().out


def test_grade_rejects_out_of_range_value(tt, monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)

    code = _run(monkeypatch, tt, "grade", "T01", "6")

    assert code == 2
    assert "Grade must be 0-5" in capsys.readouterr().err
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "T01")
    assert usage_entry.get("grade") is None


def test_grade_unknown_task_returns_exit_code_2(tt, monkeypatch, capsys):
    code = _run(monkeypatch, tt, "grade", "T-nope", "3")

    assert code == 2
    assert "Unknown task" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# subagent
# ---------------------------------------------------------------------------

def test_subagent_records_cost_with_description(tt, monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)

    code = _run(monkeypatch, tt, "subagent", "T01", "500", "--description", "review pass")

    assert code == 0
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "T01")
    assert usage_entry["subagents"] == [
        {"description": "review pass", "totalTokens": 500, "at": usage_entry["subagents"][0]["at"]}
    ]
    assert "500 subagent tokens" in capsys.readouterr().out


def test_subagent_records_cost_without_description(tt, monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)

    code = _run(monkeypatch, tt, "subagent", "T01", "300")

    assert code == 0
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "T01")
    assert usage_entry["subagents"][0]["description"] == ""


def test_subagent_recomputes_usage_after_finish(tt, monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript)
    _run(monkeypatch, tt, "finish", "T01", "--force")

    code = _run(monkeypatch, tt, "subagent", "T01", "200")

    assert code == 0
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "T01")
    assert usage_entry["usage"]["subagentTokens"] == 200


def test_subagent_unknown_task_returns_exit_code_2(tt, monkeypatch, capsys):
    code = _run(monkeypatch, tt, "subagent", "T-nope", "100")

    assert code == 2
    assert "Unknown task" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# reattach
# ---------------------------------------------------------------------------

def test_reattach_points_task_at_the_new_session(tt, monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript, session_id="sid-old")

    code = _run(monkeypatch, tt, "reattach", "T01",
                "--session-id", "sid-new", "--transcript-path", str(transcript))

    assert code == 0
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T01")
    assert entry["sessionId"] == "sid-new"
    assert entry["state"] == tt.lib.STATE_IN_PROGRESS
    assert "sid-new" in entry["resumeCommand"]
    assert "reattached to session sid-new" in capsys.readouterr().out


def test_reattach_preserves_finished_state(tt, monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript, session_id="sid-old")
    _run(monkeypatch, tt, "finish", "T01", "--force")

    code = _run(monkeypatch, tt, "reattach", "T01",
                "--session-id", "sid-new", "--transcript-path", str(transcript))

    assert code == 0
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T01")
    assert entry["state"] == tt.lib.STATE_FINISHED


def test_reattach_refuses_when_session_belongs_to_another_unfinished_task(
    tt, monkeypatch, tmp_path, capsys
):
    transcript = tmp_path / "t.jsonl"
    _start(monkeypatch, tt, "T01", transcript, session_id="sid-1")
    _start(monkeypatch, tt, "T02", transcript, session_id="sid-2")

    code = _run(monkeypatch, tt, "reattach", "T01",
                "--session-id", "sid-2", "--transcript-path", str(transcript))

    assert code == 2
    err = capsys.readouterr().err
    assert "already attached to task" in err
    assert "'T02'" in err
    assert "Refusing to also reattach" in err
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "T01")
    assert entry["sessionId"] == "sid-1"


def test_reattach_unknown_task_returns_exit_code_2(tt, monkeypatch, capsys):
    code = _run(monkeypatch, tt, "reattach", "T-nope",
                "--session-id", "sid-1", "--transcript-path", "/tmp/x.jsonl")

    assert code == 2
    assert "Unknown task" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_status_on_empty_store_does_not_crash(tt, monkeypatch, capsys):
    code = _run(monkeypatch, tt, "status")

    assert code == 0
    assert "No tracked tasks." in capsys.readouterr().out


def test_status_reflects_state_tokens_and_grade(tt, monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [(False, 100, 20, 0, 0)])
    _start(monkeypatch, tt, "T01", transcript)
    capsys.readouterr()  # discard start's output
    _write_transcript(transcript, [(False, 100, 20, 0, 0), (False, 400, 80, 0, 0)])
    _run(monkeypatch, tt, "finish", "T01", "--force")
    _run(monkeypatch, tt, "grade", "T01", "5")

    code = _run(monkeypatch, tt, "status")

    out = capsys.readouterr().out
    assert code == 0
    assert "T01" in out
    assert tt.lib.STATE_FINISHED in out
    assert "grade=5" in out
    assert "tokens=-" not in out


# ---------------------------------------------------------------------------
# install-cron / uninstall-cron
# ---------------------------------------------------------------------------

class _FakeSubprocess:
    """Records crontab-editing calls; never touches the real crontab."""

    def __init__(self, existing_crontab=""):
        self.existing_crontab = existing_crontab
        self.calls = []

    def run(self, cmd, capture_output=True, text=True, check=False, input=None):  # noqa: A002
        self.calls.append((list(cmd), input))
        if cmd == ["crontab", "-l"]:
            return _FakeResult(0, stdout=self.existing_crontab)
        if cmd == ["crontab", "-"]:
            return _FakeResult(0, stdout="")
        raise AssertionError(f"unexpected crontab invocation: {cmd}")


class _FakeResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_install_cron_writes_new_crontab_with_marker(tt, monkeypatch, capsys):
    fake = _FakeSubprocess(existing_crontab="")
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "install-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    assert len(write_calls) == 1
    written = write_calls[0][1]
    assert tt.CRON_MARKER in written
    assert "resume_cron.py" in written
    assert "Installed 30-min resume cron job." in capsys.readouterr().out


def test_install_cron_replaces_marker_line_with_unrecognized_stale_command(
    tt, monkeypatch, capsys
):
    """A marker line is only a no-op when its command matches exactly; any other command under
    the marker (however it went stale) gets corrected rather than left in place. This used to be
    a marker-presence-only no-op — see the self-heal bug this guards against."""
    fake = _FakeSubprocess(existing_crontab=f"* * * * * echo hi {tt.CRON_MARKER}\n")
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "install-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    assert len(write_calls) == 1
    written = write_calls[0][1]
    assert "echo hi" not in written
    assert written.count(tt.CRON_MARKER) == 1
    assert "Updated 30-min resume cron job." in capsys.readouterr().out


def test_uninstall_cron_removes_only_marked_lines(tt, monkeypatch):
    existing = f"* * * * * echo keep-me\n*/30 * * * * echo resume {tt.CRON_MARKER}\n"
    fake = _FakeSubprocess(existing_crontab=existing)
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "uninstall-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    assert len(write_calls) == 1
    written = write_calls[0][1]
    assert "keep-me" in written
    assert tt.CRON_MARKER not in written


def _current_marker_line(tt_module):
    """Build the exact marker line install_cron would generate right now."""
    script = tt_module.lib.SCRIPT_DIR / "resume_cron.py"
    log = tt_module.lib.DATA_DIR / "resume.log"
    return f"*/30 * * * * /usr/bin/env python3 {script} run >> {log} 2>&1 {tt_module.CRON_MARKER}"


def test_install_cron_is_a_noop_when_marker_line_already_matches(tt, monkeypatch, capsys):
    current_line = _current_marker_line(tt)
    fake = _FakeSubprocess(existing_crontab=f"* * * * * echo keep-me\n{current_line}\n")
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "install-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    assert write_calls == []
    assert "already installed" in capsys.readouterr().out


def test_install_cron_replaces_marker_line_with_stale_script_path(tt, monkeypatch):
    log = tt.lib.DATA_DIR / "resume.log"
    stale_line = (
        f"*/30 * * * * /usr/bin/env python3 /old/relocated/skills/task/scripts/resume_cron.py "
        f"run >> {log} 2>&1 {tt.CRON_MARKER}"
    )
    fake = _FakeSubprocess(existing_crontab=f"* * * * * echo keep-me\n{stale_line}\n")
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "install-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    assert len(write_calls) == 1
    written = write_calls[0][1]
    assert "/old/relocated/skills/task/scripts/resume_cron.py" not in written
    assert str(tt.lib.SCRIPT_DIR / "resume_cron.py") in written
    assert written.count(tt.CRON_MARKER) == 1
    assert "keep-me" in written


def test_install_cron_replaces_marker_line_with_stale_log_path(tt, monkeypatch):
    script = tt.lib.SCRIPT_DIR / "resume_cron.py"
    stale_line = (
        f"*/30 * * * * /usr/bin/env python3 {script} "
        f"run >> /old/relocated/.claude/task-tracking/resume.log 2>&1 {tt.CRON_MARKER}"
    )
    fake = _FakeSubprocess(existing_crontab=f"* * * * * echo keep-me\n{stale_line}\n")
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "install-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    assert len(write_calls) == 1
    written = write_calls[0][1]
    assert "/old/relocated/.claude/task-tracking/resume.log" not in written
    assert str(tt.lib.DATA_DIR / "resume.log") in written
    assert written.count(tt.CRON_MARKER) == 1
    assert "keep-me" in written


def test_install_cron_preserves_unrelated_lines_across_a_replacement(tt, monkeypatch):
    stale_line = f"*/30 * * * * echo stale {tt.CRON_MARKER}"
    existing = f"* * * * * echo before\n{stale_line}\n@daily echo after\n"
    fake = _FakeSubprocess(existing_crontab=existing)
    monkeypatch.setattr(tt, "subprocess", fake)

    code = _run(monkeypatch, tt, "install-cron")

    assert code == 0
    write_calls = [c for c in fake.calls if c[0] == ["crontab", "-"]]
    written = write_calls[0][1]
    assert "echo before" in written
    assert "echo after" in written


# ---------------------------------------------------------------------------
# malformed / missing CLI args -> exit code 2
# ---------------------------------------------------------------------------

def test_missing_task_id_for_start_is_a_usage_error(tt, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", "start"])

    with pytest.raises(SystemExit) as exc:
        tt.main()

    assert exc.value.code == 2


def test_non_integer_grade_is_a_usage_error(tt, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", "grade", "T01", "not-a-number"])

    with pytest.raises(SystemExit) as exc:
        tt.main()

    assert exc.value.code == 2


def test_unknown_subcommand_is_a_usage_error(tt, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", "bogus-command"])

    with pytest.raises(SystemExit) as exc:
        tt.main()

    assert exc.value.code == 2


# --------------------------------------------------------------------------- full lifecycle
def test_full_lifecycle_start_subagent_finish_grade(tt, monkeypatch, tmp_path, capsys):
    """Integration: start → subagent → finish → grade exercises the complete task cycle."""
    import os

    transcript = tmp_path / "lifecycle.jsonl"
    _write_transcript(transcript, [(False, 100, 20, 10, 5)])

    # 1. Start
    _start(monkeypatch, tt, "LIFECYCLE-1", transcript, session_id="sid-lc")
    capsys.readouterr()

    entry = tt.lib.find_entry(tt.lib.load_tasks(), "LIFECYCLE-1")
    assert entry["state"] == tt.lib.STATE_STARTED

    # 2. Record a subagent
    code = _run(monkeypatch, tt, "subagent", "LIFECYCLE-1", "5000",
                "--description", "implemented feature X")
    assert code == 0
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "LIFECYCLE-1")
    assert usage_entry["subagents"][0]["totalTokens"] == 5000

    # 3. Update state.json (mimics orchestrator updating project state)
    started_dt = tt.lib.parse_iso(entry["startedAt"])
    tt.lib.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    _test_write(tt.lib.STATE_JSON, "{}", encoding="utf-8")
    later = (started_dt + timedelta(seconds=5)).timestamp()
    os.utime(tt.lib.STATE_JSON, (later, later))

    # Grow transcript before finishing
    _write_transcript(transcript, [
        (False, 100, 20, 10, 5),
        (False, 300, 80, 20, 10),
    ])

    # 4. Finish
    code = _run(monkeypatch, tt, "finish", "LIFECYCLE-1")
    assert code == 0
    entry = tt.lib.find_entry(tt.lib.load_tasks(), "LIFECYCLE-1")
    assert entry["state"] == tt.lib.STATE_FINISHED
    assert entry["finishedAt"] is not None

    # 5. Grade
    code = _run(monkeypatch, tt, "grade", "LIFECYCLE-1", "4")
    assert code == 0
    usage_entry = tt.lib.find_entry(tt.lib.load_usage(), "LIFECYCLE-1")
    assert usage_entry["grade"] == 4

    # 6. Status reflects everything
    code = _run(monkeypatch, tt, "status")
    assert code == 0
    status_out = capsys.readouterr().out
    assert "LIFECYCLE-1" in status_out
    assert "FINISHED" in status_out


class TestTheRiskSwitchRunsGatesInLimitedMode:
    """`--risk` trades gate coverage for speed, so it has to be recorded and readable.

    A task running on formatting + fast tests only, with nothing on screen saying so, is the
    dangerous shape: the next person reads a green run as a full one.
    """

    def test_start_records_the_switch_on_the_task_entry(self, tt, monkeypatch, tmp_path):
        _no_cron_recorder(monkeypatch, tt)

        code = _run(monkeypatch, tt, "start", "RISK-1", "--risk", "--no-worktree",
                    "--branch", "feat/risky", "--session-id", "sid-r1",
                    "--transcript-path", str(tmp_path / "r1.jsonl"))

        assert code == 0
        entry = tt.lib.find_entry(tt.lib.load_tasks(), "RISK-1")
        assert entry["risk"] is True
        assert entry["branch"] == "feat/risky"  # the switch does not eat the other fields

    def test_a_task_that_did_not_ask_for_it_is_not_marked(self, tt, monkeypatch, tmp_path):
        """Absent means false, not missing-and-therefore-anything."""
        _no_cron_recorder(monkeypatch, tt)

        _run(monkeypatch, tt, "start", "RISK-2", "--no-worktree", "--session-id", "sid-r2",
             "--transcript-path", str(tmp_path / "r2.jsonl"))

        entry = tt.lib.find_entry(tt.lib.load_tasks(), "RISK-2")
        assert entry["risk"] is False

    def test_the_switch_survives_a_resume_and_a_later_start(self, tt, monkeypatch, tmp_path):
        """Resuming a task must not quietly restore full gates the run was never sized for."""
        _no_cron_recorder(monkeypatch, tt)
        transcript = tmp_path / "r3.jsonl"
        _run(monkeypatch, tt, "start", "RISK-3", "--risk", "--no-worktree",
             "--session-id", "sid-r3", "--transcript-path", str(transcript))
        _run(monkeypatch, tt, "reattach", "RISK-3", "--session-id", "sid-r3b",
             "--transcript-path", str(transcript))

        code = _run(monkeypatch, tt, "start", "RISK-3", "--no-worktree",
                    "--session-id", "sid-r3b", "--transcript-path", str(transcript))

        assert code == 0
        entry = tt.lib.find_entry(tt.lib.load_tasks(), "RISK-3")
        assert entry["risk"] is True
        assert entry["sessionId"] == "sid-r3b"

    def test_a_later_start_can_raise_the_switch_on_a_task_that_began_without_it(
        self, tt, monkeypatch, tmp_path
    ):
        _no_cron_recorder(monkeypatch, tt)
        transcript = tmp_path / "r4.jsonl"
        _run(monkeypatch, tt, "start", "RISK-4", "--no-worktree", "--session-id", "sid-r4",
             "--transcript-path", str(transcript))

        _run(monkeypatch, tt, "start", "RISK-4", "--risk", "--no-worktree",
             "--session-id", "sid-r4", "--transcript-path", str(transcript))

        assert tt.lib.find_entry(tt.lib.load_tasks(), "RISK-4")["risk"] is True

    def test_status_names_the_risky_task_and_leaves_the_others_alone(
        self, tt, monkeypatch, tmp_path, capsys
    ):
        """Two tasks, one switched: absence has to be absence, not an empty store."""
        _no_cron_recorder(monkeypatch, tt)
        _run(monkeypatch, tt, "start", "RISK-5", "--risk", "--no-worktree",
             "--session-id", "sid-r5", "--transcript-path", str(tmp_path / "r5.jsonl"))
        _run(monkeypatch, tt, "start", "SAFE-5", "--no-worktree", "--session-id", "sid-s5",
             "--transcript-path", str(tmp_path / "s5.jsonl"))
        capsys.readouterr()

        assert _run(monkeypatch, tt, "status") == 0

        out = capsys.readouterr().out
        risky = next(line for line in out.splitlines() if line.startswith("RISK-5"))
        safe = next(line for line in out.splitlines() if line.startswith("SAFE-5"))
        assert "risk=on" in risky
        assert "risk" not in safe


class TestTheStatusLineShowsTheModelMix:
    """`cacheEff` measures ~0.98 on every real task; the mix is what a reader can act on."""

    def test_the_dominant_model_and_its_share_are_shown(self, tt):
        assert tt._format_mix({"claude-opus-5": 0.8, "claude-haiku-4-5": 0.2}) == "opus-5:80%"

    def test_no_mix_renders_as_a_dash_rather_than_an_empty_column(self, tt):
        assert tt._format_mix({}) == "-"
        assert tt._format_mix(None) == "-"
