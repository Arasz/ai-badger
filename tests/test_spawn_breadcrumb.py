"""spawn_detached leaves a breadcrumb naming the test that reached it (#232).

#222 wrapped `subprocess.Popen` in `conftest` so every detached child the *pytest process*
starts is tracked and reaped. It cannot reach a hook run in a child interpreter: the wrapper
is a class replaced in one process's `subprocess` module, and a subprocess gets a clean one,
so the grandchild it detaches is invisible to the parent and never reaped.

The residual is real — orphaned `poll_limit.py` daemons with PPID 1 and a cwd inside the
checkout, started during suite runs, while #222's teardown assertion passed. Ten such daemons
were found alive at once on 2026-08-01, aged 17-21 hours, six of them owned by worktrees that
had already been deleted.

Policing the outcome does not work: there is no reach into another interpreter, an `ps` scan
is racy and would match a developer's own daemon, and a kill-switch is production code that
exists only for tests. So this names the *call site* instead. When `$AI_BADGER_SPAWN_LOG` is
set, every detached spawn appends a record; `conftest` points it at a scratch file and fails
the session if anything is in it. Outside the suite the variable is unset and the code is
inert.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def pathlib_parent(file_path: str) -> str:
    """The directory holding a loaded module, for a child interpreter's sys.path."""
    return str(Path(file_path).resolve().parent)


def _tracker(load_script):
    return load_script("features/common/skills/task/scripts/tracker_lib.py")


def _noop_argv():
    """A command that exits immediately, so a spawn under test leaves nothing behind."""
    return [sys.executable, "-c", "pass"]


class TestBreadcrumbIsInertByDefault:
    """Production must not pay for a diagnostic the suite asked for."""

    def test_no_log_is_written_when_the_variable_is_unset(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        monkeypatch.delenv("AI_BADGER_SPAWN_LOG", raising=False)
        expected = tmp_path / "spawns.jsonl"

        proc = tracker.spawn_detached(_noop_argv(), cwd=tmp_path)
        proc.wait(timeout=30)

        assert not expected.exists()

    def test_the_spawn_still_happens_when_the_variable_is_set(
        self, tmp_path, load_script, monkeypatch
    ):
        """The breadcrumb observes; it must never prevent."""
        tracker = _tracker(load_script)
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(tmp_path / "spawns.jsonl"))

        proc = tracker.spawn_detached(_noop_argv(), cwd=tmp_path)

        assert proc.wait(timeout=30) == 0


class TestBreadcrumbNamesTheCallSite:
    """A record nobody can trace back to a test is the guessing this replaces."""

    def test_a_record_is_appended_for_each_spawn(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        log = tmp_path / "spawns.jsonl"
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(log))

        tracker.spawn_detached(_noop_argv(), cwd=tmp_path).wait(timeout=30)
        tracker.spawn_detached(_noop_argv(), cwd=tmp_path).wait(timeout=30)

        assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_the_record_carries_argv_cwd_and_pid(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        log = tmp_path / "spawns.jsonl"
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(log))

        proc = tracker.spawn_detached(_noop_argv(), cwd=tmp_path)
        proc.wait(timeout=30)

        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
        assert record["argv"] == _noop_argv()
        assert record["cwd"] == str(tmp_path)
        assert record["pid"] == proc.pid

    def test_the_record_names_the_test_that_reached_it(self, tmp_path, load_script, monkeypatch):
        """$PYTEST_CURRENT_TEST is what turns 'something spawned' into 'this test spawned'."""
        tracker = _tracker(load_script)
        log = tmp_path / "spawns.jsonl"
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(log))

        tracker.spawn_detached(_noop_argv(), cwd=tmp_path).wait(timeout=30)

        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
        assert "test_the_record_names_the_test_that_reached_it" in record["test"]


class TestABrokenBreadcrumbNeverBreaksTheSpawn:
    """A diagnostic that can fail the thing it observes is worse than no diagnostic."""

    def test_an_unwritable_log_path_does_not_raise(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        unwritable = tmp_path / "nope" / "deeper" / "spawns.jsonl"
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(unwritable))

        proc = tracker.spawn_detached(_noop_argv(), cwd=tmp_path)

        assert proc.wait(timeout=30) == 0

    def test_a_stubbed_popen_returning_no_pid_does_not_raise(
        self, tmp_path, load_script, monkeypatch
    ):
        """test_tracker_lib stubs Popen and returns None; the breadcrumb must survive that.

        Caught by those existing tests on the first run of this change — the first draft read
        `proc.pid` directly and turned a diagnostic into an AttributeError at the call site.
        """
        tracker = _tracker(load_script)
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(tmp_path / "spawns.jsonl"))
        monkeypatch.setattr(tracker.subprocess, "Popen", lambda *a, **k: None)

        assert tracker.spawn_detached(_noop_argv(), cwd=tmp_path) is None

    def test_a_directory_where_the_log_should_be_does_not_raise(
        self, tmp_path, load_script, monkeypatch
    ):
        tracker = _tracker(load_script)
        collision = tmp_path / "spawns.jsonl"
        collision.mkdir()
        monkeypatch.setenv("AI_BADGER_SPAWN_LOG", str(collision))

        proc = tracker.spawn_detached(_noop_argv(), cwd=tmp_path)

        assert proc.wait(timeout=30) == 0


class TestTheSuiteArmsIt:
    """conftest must set the variable, or the whole mechanism is dormant in the one place
    it exists for."""

    def test_the_suite_run_has_the_variable_set(self):
        assert os.environ.get("AI_BADGER_SPAWN_LOG"), (
            "conftest must point AI_BADGER_SPAWN_LOG at a scratch file for the session"
        )

    def test_both_sides_spell_the_variable_the_same(self, load_script):
        """conftest repeats the literal rather than importing production code.

        A mismatch would disable the whole mechanism silently — conftest would arm a variable
        nothing reads, and the session assertion would pass on an empty log forever.
        """
        import conftest  # noqa: PLC0415 - the module under test here is the suite's own

        assert _tracker(load_script).SPAWN_LOG_ENV == conftest.SPAWN_LOG_ENV


class TestItCatchesTheCaseItExistsFor:
    """#232 is specifically about a spawn from a *child interpreter*. If this class cannot
    be made to fail, the session assertion is decoration."""

    def test_a_spawn_from_a_child_interpreter_records_a_different_pid(
        self, tmp_path, load_script, monkeypatch
    ):
        """The whole point: the Popen wrapper lives in one process and cannot see this.

        Runs tracker_lib in a real subprocess, exactly as a hook reached from a child
        interpreter does, and asserts the breadcrumb crosses the process boundary carrying a
        `by` that is not this pid — which is what makes conftest able to tell the two apart.
        """
        import subprocess as sp

        tracker_path = _tracker(load_script).__file__
        log = tmp_path / "spawns.jsonl"
        child = sp.run(
            [sys.executable, "-c",
             "import sys, pathlib;"
             f"sys.path.insert(0, {str(pathlib_parent(tracker_path))!r});"
             "import tracker_lib;"
             f"p = tracker_lib.spawn_detached([{sys.executable!r}, '-c', 'pass'],"
             f" cwd=pathlib.Path({str(tmp_path)!r}));"
             "p.wait(timeout=30)"],
            env={**os.environ, "AI_BADGER_SPAWN_LOG": str(log)},
            capture_output=True, text=True, timeout=60, check=False,
        )

        assert child.returncode == 0, child.stderr
        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
        assert record["by"] != os.getpid(), (
            "a child-interpreter spawn recorded this process's pid, so conftest would filter "
            "it out as already-reaped — the exact blind spot #232 is about"
        )
