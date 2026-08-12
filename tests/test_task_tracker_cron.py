"""Tests for task_tracker.py's crontab handling (F-04).

`crontab -l` exiting non-zero is ambiguous between "no crontab exists yet" and "the read
genuinely failed" (permissions, missing binary, spool corruption, ...). Treating both cases
as "empty" and then writing an authoritative replacement crontab destroys the user's existing
jobs. These tests pin down the fix: only a real "no crontab for <user>" condition may be
treated as empty; every other failure must abort before any `crontab -` write. They also pin
down the default-to-opt-in flip for `task start` and the `%`-escaping of interpolated paths.

Mirrors `tests/test_task_tracker.py`'s loading strategy: `task_tracker.py` relies on being
launched as `python3 task_tracker.py ...` for its bare `import tracker_lib as lib` to resolve,
so the `tt` fixture below prepends the script's own directory to `sys.path` before loading it
via `load_script`. No test in this file ever invokes the real `crontab` binary or the real
`subprocess` module - `subprocess` is always replaced with a scripted stand-in.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import sys

import pytest

SCRIPT_RELPATH = "features/common/skills/task/scripts/task_tracker.py"


class _FakeResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _ScriptedSubprocess:
    """Stand-in for `subprocess`: returns a pre-scripted result (or raises a pre-scripted
    exception) per argv, and records every call so tests can assert on the exact argv list -
    never touches a real process or the real crontab."""

    def __init__(self, responses):
        self.responses = responses  # {tuple(argv): _FakeResult | Exception}
        self.calls = []

    def run(self, cmd, **_kwargs):
        argv = list(cmd)
        self.calls.append(argv)
        outcome = self.responses[tuple(argv)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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
    return module


def _run(monkeypatch, module, *args):
    """Call task_tracker's main() in-process (no subprocess) with the given CLI args."""
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", *args])
    lib = module.lib
    monkeypatch.setitem(lib.SESSION_SOURCES, "claude", {
        "env_var": "CLAUDE_SESSION_ID",
        "resolve": lambda *a: None,
        "checkpoint": lambda *a: {"sessionId": "s1", "transcriptPath": "t", "contextTokens": 0},
        "resume": lambda *a: None,
        "delegation_usage": lambda *a: None,
        "transcript": lambda *a: None,
    })
    return module.main()


# ---------------------------------------------------------------------------
# install_cron must abort, not overwrite, when `crontab -l` fails
# ---------------------------------------------------------------------------

def test_install_cron_aborts_when_crontab_l_fails(tt, monkeypatch):
    fake = _ScriptedSubprocess({
        ("crontab", "-l"): _FakeResult(1, stdout="", stderr="crontab: permission denied\n"),
        # Scripted so a bug that reaches this call fails the assertion below instead of
        # crashing the test on a KeyError.
        ("crontab", "-"): _FakeResult(0, stdout=""),
    })
    monkeypatch.setattr(tt, "subprocess", fake)

    code = tt.install_cron()

    assert code != 0
    assert ["crontab", "-"] not in fake.calls


def test_install_cron_treats_genuine_no_crontab_as_empty(tt, monkeypatch, capsys):
    """The one legitimate case that may proceed: `crontab -l` failing specifically because
    the user has no crontab yet."""
    fake = _ScriptedSubprocess({
        ("crontab", "-l"): _FakeResult(1, stdout="", stderr="no crontab for alice\n"),
        ("crontab", "-"): _FakeResult(0, stdout=""),
    })
    monkeypatch.setattr(tt, "subprocess", fake)

    code = tt.install_cron()

    assert code == 0
    write_calls = [c for c in fake.calls if c == ["crontab", "-"]]
    assert len(write_calls) == 1


def test_uninstall_cron_aborts_when_crontab_l_fails(tt, monkeypatch):
    fake = _ScriptedSubprocess({
        ("crontab", "-l"): _FakeResult(1, stdout="", stderr="crontab: cannot open spool\n"),
        ("crontab", "-"): _FakeResult(0, stdout=""),
    })
    monkeypatch.setattr(tt, "subprocess", fake)

    code = tt.uninstall_cron()

    assert code != 0
    assert ["crontab", "-"] not in fake.calls


# ---------------------------------------------------------------------------
# `task start` no longer installs cron unless explicitly opted in
# ---------------------------------------------------------------------------

def test_cmd_start_does_not_install_cron_by_default(tt, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tt, "install_cron", lambda quiet=False: calls.append(quiet) or 0)
    transcript = tmp_path / "t.jsonl"

    code = _run(
        monkeypatch, tt, "start", "T01",
        "--session-id", "sid-1", "--transcript-path", str(transcript),
    )

    assert code == 0
    assert calls == []


def test_cmd_start_installs_cron_when_opted_in(tt, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tt, "install_cron", lambda quiet=False: calls.append(quiet) or 0)
    transcript = tmp_path / "t.jsonl"

    code = _run(
        monkeypatch, tt, "start", "T02", "--cron",
        "--session-id", "sid-2", "--transcript-path", str(transcript),
    )

    assert code == 0
    assert calls == [True]


def test_cmd_start_no_cron_flag_is_still_accepted_as_a_deprecated_noop(tt, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tt, "install_cron", lambda quiet=False: calls.append(quiet) or 0)
    transcript = tmp_path / "t.jsonl"

    code = _run(
        monkeypatch, tt, "start", "T03", "--no-cron",
        "--session-id", "sid-3", "--transcript-path", str(transcript),
    )

    assert code == 0
    assert calls == []


# ---------------------------------------------------------------------------
# a missing `crontab` binary is a reported condition, never a traceback
# ---------------------------------------------------------------------------

def test_missing_crontab_binary_is_reported_not_raised(tt, monkeypatch, capsys):
    fake = _ScriptedSubprocess({
        ("crontab", "-l"): FileNotFoundError(2, "No such file or directory: 'crontab'"),
    })
    monkeypatch.setattr(tt, "subprocess", fake)

    code = tt.install_cron()

    assert code != 0
    err = capsys.readouterr().err
    assert err.strip() != ""


def test_cmd_start_with_cron_and_missing_binary_does_not_raise(tt, monkeypatch, tmp_path, capsys):
    """The success JSON that `start` always prints must not be followed by an unhandled
    traceback when the opted-in cron install can't find the `crontab` binary."""
    fake = _ScriptedSubprocess({
        ("crontab", "-l"): FileNotFoundError(2, "No such file or directory: 'crontab'"),
    })
    monkeypatch.setattr(tt, "subprocess", fake)
    transcript = tmp_path / "t.jsonl"

    code = _run(
        monkeypatch, tt, "start", "T04", "--cron",
        "--session-id", "sid-4", "--transcript-path", str(transcript),
    )

    assert code == 0
    out = capsys.readouterr()
    assert '"taskId": "T04"' in out.out


# ---------------------------------------------------------------------------
# interpolated paths are quoted and `%` is escaped
# ---------------------------------------------------------------------------

def test_desired_cron_line_escapes_percent_in_interpolated_paths(tt, monkeypatch, tmp_path):
    weird_dir = tmp_path / "100%-done"
    weird_dir.mkdir()
    monkeypatch.setattr(tt.lib, "SCRIPT_DIR", weird_dir)
    monkeypatch.setattr(tt.lib, "DATA_DIR", weird_dir)

    line = tt._desired_cron_line()  # pylint: disable=protected-access

    # cron(5): an unescaped `%` is turned into a newline. A raw, unescaped `%` in the
    # generated line would silently truncate the job.
    assert "%" not in line.replace(r"\%", "")
    assert r"100\%-done" in line


def test_desired_cron_line_quotes_paths_with_spaces(tt, monkeypatch, tmp_path):
    weird_dir = tmp_path / "has a space"
    weird_dir.mkdir()
    monkeypatch.setattr(tt.lib, "SCRIPT_DIR", weird_dir)
    monkeypatch.setattr(tt.lib, "DATA_DIR", weird_dir)

    line = tt._desired_cron_line()  # pylint: disable=protected-access

    assert f"'{weird_dir}/resume_cron.py'" in line
