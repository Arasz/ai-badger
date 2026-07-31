"""The suite must not touch the developer's real state, nor outlive itself.

Both properties are floors under the explicit isolation individual tests already do, in the
shape `test_debug_log.py::TestTheSuiteCannotWriteToTheRealLog` established for `$HOME`. A test
that forgets to redirect must still be harmless (#222).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Self-derived, never imported from conftest: these two tests assert a property of the
# environment, and importing the fix's own symbols would make them fail with ImportError
# rather than with the leak, proving only that the symbol exists.
REAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class TestTheSuiteCannotWriteToTheRealTrackingDir:
    """`.ai-badger/task-tracking/` is live state a real run reads; a test must never write it."""

    COPIES = (".ai-badger/skills/task/scripts/tracker_lib.py",
              "features/common/skills/task/scripts/tracker_lib.py",
              "skills/task/scripts/tracker_lib.py")

    def test_a_freshly_loaded_copy_points_away_from_the_real_project(self, load_script):
        """tracker_lib freezes its paths at import, so the redirect must already be in force."""
        for relpath in self.COPIES:
            data_dir = load_script(relpath).DATA_DIR
            assert REAL_PROJECT_ROOT not in data_dir.parents, \
                f"{relpath} would write to {data_dir}"

    def test_registering_a_session_lands_outside_the_real_project(self, load_script):
        """The end-to-end write, with nothing patched: it must happen, just somewhere safe."""
        tl = load_script(self.COPIES[1])
        tl.ensure_data_dir()
        tl.save_current_session("isolation-probe", transcript_path="", cwd="")

        assert tl.CURRENT_SESSION.exists(), "the write should have happened"
        assert REAL_PROJECT_ROOT not in tl.CURRENT_SESSION.parents, \
            f"leaked to {tl.CURRENT_SESSION}"


class TestNoProcessOutlivesTheRun:
    """session_start_hook spawns poll_limit.py detached; it must not survive the suite."""

    def test_a_detached_child_is_registered_for_reaping(self):
        """Popen is wrapped at conftest import, before any hook module can be loaded."""
        from conftest import detached_children  # pylint: disable=import-outside-toplevel

        before = len(detached_children())
        child = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            assert len(detached_children()) == before + 1, \
                "a start_new_session child was not tracked, so nothing will reap it"
            assert child in detached_children()
        finally:
            child.kill()
            child.wait(timeout=5)

    def test_an_undetached_child_is_left_alone(self):
        """Ordinary subprocesses die with pytest already; tracking them would just leak memory."""
        from conftest import detached_children  # pylint: disable=import-outside-toplevel

        before = len(detached_children())
        subprocess.run([sys.executable, "-c", "pass"], check=True)

        assert len(detached_children()) == before

    def test_reaping_kills_a_grandchild_too(self, tmp_path):
        """poll_limit shells out to `claude`; killing only the leader reparents it to PID 1."""
        from conftest import reap_detached_children  # pylint: disable=import-outside-toplevel

        pidfile = tmp_path / "grandchild.pid"
        code = ("import pathlib, subprocess, sys, time\n"
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"pathlib.Path({str(pidfile)!r}).write_text(str(g.pid))\n"
                "time.sleep(60)\n")
        child = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-c", code], start_new_session=True)
        deadline = time.time() + 10
        while not pidfile.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert pidfile.exists(), "the child never reported its grandchild"
        grandchild = int(pidfile.read_text())

        reap_detached_children()

        deadline = time.time() + 5
        while _alive(grandchild) and time.time() < deadline:
            time.sleep(0.05)
        assert not _alive(grandchild), "the grandchild outlived the reaper"

    def test_reaping_kills_a_survivor(self):
        """What the session teardown does, asserted directly rather than trusted."""
        from conftest import reap_detached_children  # pylint: disable=import-outside-toplevel

        child = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        assert child.poll() is None, "the child should still be running"

        reap_detached_children()

        deadline = time.time() + 5
        while child.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        assert child.poll() is not None, "the reaper left a process running past the suite"
