"""Shared pytest helpers for the ai-badger script suite.

The scripts are standalone files (not an installed package) that bootstrap ``badger_lib`` /
``tracker_lib`` onto ``sys.path`` at import time, so tests load them by repo-relative path via the
``load_script`` fixture rather than importing a package. ``ROOT`` is the framework repo root.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The real home, captured before any test can redirect it.
REAL_HOME = Path.home()

# Hooks under test resolve their audit sink from this variable; without it the suite appends to
# the developer's real ~/.ai-badger/debug log (features/common/hooks/debug_log.py). Set at import
# time, not in a fixture: a module imported during collection reads it before fixtures run, and
# a session fixture alone was measured still leaking 76 records into the real log.
DEBUG_DIR_ENV = "AI_BADGER_DEBUG_DIR"
os.environ.setdefault(DEBUG_DIR_ENV, tempfile.mkdtemp(prefix="ai-badger-debug-sink-"))

# The real repo root, captured before any test can redirect it.
REAL_PROJECT_ROOT = ROOT

# tracker_lib resolves <project-root>/.ai-badger/task-tracking/ from this variable, then by
# walking up from the cwd for .ai-badger/config.json — which finds the real checkout even with
# $HOME redirected, so the suite wrote phantom sessions into live state (#222). Assigned, not
# setdefault: a run started from a Claude Code session inherits it already pointing at the real
# project. Set at import time for the same reason DEBUG_DIR_ENV is — tracker_lib freezes its
# path constants at module import, which happens during collection, before any fixture runs.
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"
SCRATCH_PROJECT = Path(tempfile.mkdtemp(prefix="ai-badger-project-"))
(SCRATCH_PROJECT / ".ai-badger").mkdir(parents=True, exist_ok=True)
os.environ[PROJECT_DIR_ENV] = str(SCRATCH_PROJECT)

# session_start_hook and poll_limit detach children with start_new_session=True, so they
# outlive pytest — a run was measured leaving poll_limit.py orphaned at PPID 1, still writing
# and still trying to resume fixture sessions. Production routes both through
# tracker_lib.spawn_detached, but the floor wraps `subprocess.Popen` itself: that is the one
# true singleton, where the module copies `load_script` hands out are fresh objects a
# module-level patch would not reach.
_DETACHED_CHILDREN: list = []


class _TrackedPopen(subprocess.Popen):
    """A Popen that remembers detached children, so the run can reap them."""

    _tracks_detached_children = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if kwargs.get("start_new_session"):
            _DETACHED_CHILDREN.append(self)


# Installed once. A second conftest import would otherwise subclass the installed wrapper,
# and a detached child would be recorded in both generations' lists.
if not getattr(subprocess.Popen, "_tracks_detached_children", False):
    subprocess.Popen = _TrackedPopen


def detached_children() -> list:
    """Every `start_new_session` child spawned so far this run."""
    return list(_DETACHED_CHILDREN)


def reap_detached_children() -> list:
    """Kill every detached child still running; return the ones that had to be killed."""
    killed = []
    for child in _DETACHED_CHILDREN:
        if child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - kill(2) does not negotiate
                pass
            killed.append(child)
    return killed


@pytest.fixture(scope="session", autouse=True)
def _home_off_limits(tmp_path_factory):
    """Point `$HOME` at a scratch directory for the whole session.

    A floor beneath the explicit sink override, and wider than it: the suite also writes
    ~/.ai-badger/hook-errors.log and ~/.hermes/plugins/*.py, which no debug-sink variable
    reaches. Copies loaded before this runs are covered by DEBUG_DIR_ENV above.
    """
    scratch = tmp_path_factory.mktemp("home")
    with pytest.MonkeyPatch.context() as patch:
        for var in ("HOME", "USERPROFILE"):
            patch.setenv(var, str(scratch))
        yield scratch


@pytest.fixture(scope="session", autouse=True)
def isolated_debug_sink():
    """Remove the redirected debug sink once the run is over."""
    sink = Path(os.environ[DEBUG_DIR_ENV])
    yield sink
    shutil.rmtree(sink, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _no_process_outlives_the_run():
    """Reap detached children, then drop the scratch project root the suite wrote into."""
    yield SCRATCH_PROJECT
    reap_detached_children()
    shutil.rmtree(SCRATCH_PROJECT, ignore_errors=True)


@pytest.fixture
def root() -> Path:
    """Absolute path to the ai-badger framework repo root."""
    return ROOT


@pytest.fixture
def make_scaffolder(load_script, root, tmp_path):
    """Build Scaffolders over one loaded module and one shared target.

    Defaults match the shape the call sites spell out by hand; any keyword overrides it, and
    unknown keywords reach the constructor. `.module` and `.target` expose what the factory built.
    """
    import scaffold_helpers

    module = load_script(scaffold_helpers.SCAFFOLD_SCRIPT)
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)

    def _make(**kwargs):
        kwargs.setdefault("root", root)
        kwargs.setdefault("target", target)
        return scaffold_helpers.build_scaffolder(module, **kwargs)

    _make.module = module
    _make.target = target
    return _make


@pytest.fixture
def load_script():
    """Return a loader that imports an ai-badger script by repo-relative path.

    Named by dotted repo-relative path (``features.common.retrieval.bm25``), not an
    ``aib_`` prefix: mutmut's trampoline dispatches a mutant by matching a function's
    ``__module__`` against exactly this dotted form (see
    ``mutmut.utils.format_utils.get_mutant_name``). Renaming this back to ``aib_`` breaks
    mutation testing silently — every mutant reports "no tests" and the run measures
    0.00 mutations/second, a symptom that points at mutmut, not at this fixture.
    """
    def _load(relpath: str):
        path = ROOT / relpath
        name = PurePosixPath(relpath).with_suffix("").as_posix().replace("/", ".")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    return _load
