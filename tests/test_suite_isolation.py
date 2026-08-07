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
# Evaluated at collection, which is before the session fixture redirects `$HOME` — so this is
# the operator's real home, derived here rather than imported from the fixture it checks.
REAL_HOME = Path.home()


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

    def test_the_guard_watches_wherever_a_write_from_here_would_land(self, load_script):
        """The floor watched this tree; tracker_lib sends a worktree's writes to its checkout.

        Measured 2026-08-07 from `.ai-badger/worktrees/`: a mutation run really did write
        `current-session.json` into the main checkout, and every isolation fixture stayed
        green — they all watch `parents[1]`, which is the worktree, not the checkout.
        """
        from conftest import REAL_CHECKOUTS  # pylint: disable=import-outside-toplevel

        tl = load_script("features/common/skills/task/scripts/tracker_lib.py")
        lands_in = tl.collapse_worktree(REAL_PROJECT_ROOT)

        assert lands_in in REAL_CHECKOUTS, (
            f"a tracking write from this tree lands in {lands_in}, which no isolation "
            f"fixture watches (watched: {[str(p) for p in REAL_CHECKOUTS]})")

    def test_the_write_marker_covers_every_watched_checkout(self):
        """`save_json` marks a write against one root, so that root must contain them all."""
        from conftest import (  # pylint: disable=import-outside-toplevel
            REAL_CHECKOUTS, REAL_WRITE_ROOT)

        outside = [str(p) for p in REAL_CHECKOUTS
                   if p != REAL_WRITE_ROOT and REAL_WRITE_ROOT not in p.parents]

        assert not outside, (
            f"these checkouts sit outside {REAL_WRITE_ROOT}, so a write into them would go "
            f"unmarked and the guard could not fail on it: {outside}")

    def test_the_session_guard_looks_beyond_the_obvious_directory(self):
        """`features/.ai-badger/` is where the leak went while a sentinel watched the root."""
        from conftest import real_tracking_files  # pylint: disable=import-outside-toplevel

        probe = REAL_PROJECT_ROOT / "features" / ".ai-badger" / "task-tracking" / "probe.tmp"
        before = real_tracking_files()
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("probe", encoding="utf-8")
        try:
            assert probe not in before
            assert probe in real_tracking_files(), \
                "the guard does not look in features/.ai-badger, which is where #222 escaped"
        finally:
            probe.unlink()
            for parent in (probe.parent, probe.parent.parent):
                if not any(parent.iterdir()):
                    parent.rmdir()

    def test_registering_a_session_lands_outside_the_real_project(self, load_script):
        """The end-to-end write, with nothing patched: it must happen, just somewhere safe."""
        tl = load_script(self.COPIES[1])
        tl.ensure_data_dir()
        tl.save_current_session("isolation-probe", transcript_path="", cwd="")

        assert tl.CURRENT_SESSION.exists(), "the write should have happened"
        assert REAL_PROJECT_ROOT not in tl.CURRENT_SESSION.parents, \
            f"leaked to {tl.CURRENT_SESSION}"


class TestTheCwdIsPartOfTheIsolationFloor:
    """`$HOME` and `CLAUDE_PROJECT_DIR` were redirected; the cwd was not (E4 F12).

    A script that resolves its project root by walking up from `os.getcwd()` found the real
    checkout from every test that had not chdir'd itself — and since the worktree collapse
    landed, that walk reaches the main checkout from a worktree too.
    """

    def test_the_cwd_is_not_inside_the_real_checkout(self):
        cwd = Path.cwd()
        assert cwd != REAL_PROJECT_ROOT
        assert REAL_PROJECT_ROOT not in cwd.parents, f"the run is anchored in {cwd}"

    def test_no_ai_badger_marker_sits_above_the_cwd(self):
        """The property a cwd-walking script actually depends on: the walk must find nothing."""
        cwd = Path.cwd()
        found = [str(a) for a in (cwd, *cwd.parents)
                 if (a / ".ai-badger" / "config.json").is_file()]

        assert not found, f"a cwd walk would adopt {found[0]} as the project root"

    def test_a_script_walking_up_from_the_bare_cwd_finds_no_project(self, load_script):
        """The hazard, exercised through a real resolver rather than asserted about paths."""
        tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

        resolved = tl.resolve_project_root(env={}, script_dir=Path("/nonexistent/a/b/c/d"))

        assert resolved == Path("/nonexistent"), \
            f"the cwd walk found a project root at {resolved} instead of falling through"


class TestTheRealHookErrorLogIsSurfaced:
    """241 swallowed hook exceptions accumulated in `~/.ai-badger/hook-errors.log` unread (B7)."""

    def test_the_log_is_read_from_the_unredirected_home(self):
        """Reading it through the redirected `$HOME` would make the guard permanently green."""
        from conftest import REAL_HOOK_ERRORS_LOG  # pylint: disable=import-outside-toplevel

        assert REAL_HOME in REAL_HOOK_ERRORS_LOG.parents
        assert Path.home() not in REAL_HOOK_ERRORS_LOG.parents, \
            "the guard is watching the scratch home, which no hook writes to"

    def test_an_appended_entry_is_reported(self):
        from conftest import new_hook_errors  # pylint: disable=import-outside-toplevel

        assert new_hook_errors(["old-1", "old-2"], ["old-1", "old-2", "new-1"]) == ["new-1"]

    def test_an_unchanged_log_reports_nothing(self):
        from conftest import new_hook_errors  # pylint: disable=import-outside-toplevel

        assert new_hook_errors(["old-1"], ["old-1"]) == []

    def test_a_rotated_log_still_reports_what_was_never_seen(self):
        """Log rotation must not turn every surviving entry into a fresh accusation."""
        from conftest import new_hook_errors  # pylint: disable=import-outside-toplevel

        assert new_hook_errors(["old-1", "old-2"], ["old-2", "new-1"]) == ["new-1"]

    def test_an_absent_log_reads_as_empty(self, tmp_path):
        from conftest import hook_error_lines  # pylint: disable=import-outside-toplevel

        assert hook_error_lines(tmp_path / "never-written.log") == []


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
