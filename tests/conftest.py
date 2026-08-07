"""Shared pytest helpers for the ai-badger script suite.

The scripts are standalone files (not an installed package) that bootstrap ``badger_lib`` /
``tracker_lib`` onto ``sys.path`` at import time, so tests load them by repo-relative path via the
``load_script`` fixture rather than importing a package. ``ROOT`` is the framework repo root.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
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

# tracker_lib.spawn_detached appends a breadcrumb here when set, so a detached child started by
# a *child interpreter* can be traced back to the test that reached it (#232). The literal is
# repeated rather than imported — conftest does not import production modules — and
# test_spawn_breadcrumb.py asserts both sides still spell it the same.
SPAWN_LOG_ENV = "AI_BADGER_SPAWN_LOG"

# tracker_lib.save_json marks a tracking write that lands outside the scratch project here, so
# the guard below can tell the suite's writes from a leftover daemon's. Same repeated-literal
# arrangement as SPAWN_LOG_ENV, and test_real_write_attribution.py pins both spellings.
REAL_WRITE_LOG_ENV = "AI_BADGER_REAL_WRITE_LOG"
# The reference the marker compares against. NOT CLAUDE_PROJECT_DIR: tests monkeypatch that
# freely, so comparing to it marked every legitimate write into the scratch project and into
# pytest tmpdirs. The invariant is about this checkout and nothing else.
REAL_ROOT_ENV = "AI_BADGER_REAL_ROOT"
REAL_WRITE_LOG = Path(tempfile.mkdtemp(prefix="ai-badger-real-writes-")) / "writes.jsonl"
os.environ[REAL_WRITE_LOG_ENV] = str(REAL_WRITE_LOG)
os.environ[REAL_ROOT_ENV] = str(ROOT)
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
# The marker `resolve_project_root` walks up looking for. Without it a *spawned* child —
# which re-resolves in its own interpreter, where none of this isolation exists — finds no
# marker and falls back to `script_dir.parents[3]`, landing in `<repo>/features` (#222).
(SCRATCH_PROJECT / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
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
    """Kill every detached child still running; return the ones that had to be killed.

    Kills the process *group*, not the leader. `start_new_session` makes each child a group
    leader, and poll_limit shells out to `claude` — signalling only the leader leaves that
    grandchild to reparent to PID 1 and survive, which is the leak this exists to stop (#222).
    """
    killed = []
    for child in _DETACHED_CHILDREN:
        if child.poll() is None:
            try:
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):  # pragma: no cover - race with exit
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
        # $HERMES_HOME outranks $HOME wherever the Hermes user scope is resolved, so a
        # developer who has it set would send the suite's writes to their real Hermes home.
        patch.delenv("HERMES_HOME", raising=False)
        yield scratch


@pytest.fixture(scope="session", autouse=True)
def isolated_debug_sink():
    """Remove the redirected debug sink once the run is over."""
    sink = Path(os.environ[DEBUG_DIR_ENV])
    yield sink
    shutil.rmtree(sink, ignore_errors=True)


def real_tracking_files() -> dict:
    """Every task-tracking file in the real checkout, by path and mtime.

    Checks the repo root and each first-level directory: the leak that got past a sentinel
    landed in `features/.ai-badger/`, one directory over from the one being watched (#222).
    """
    found = {}
    for base in (REAL_PROJECT_ROOT, *(p for p in REAL_PROJECT_ROOT.glob("*") if p.is_dir())):
        tracking = base / ".ai-badger" / "task-tracking"
        if tracking.is_dir():
            found.update({p: p.stat().st_mtime_ns for p in tracking.rglob("*") if p.is_file()})
    return found


def suite_attributed_writes(log: Path) -> list:
    """Tracking writes outside the scratch project that a suite process marked as its own.

    Defensive for the same reason `foreign_spawn_offenders` is: this runs at teardown, several
    processes append to the file, and a crash here would hide the offenders it exists to name.
    """
    if not log.exists():
        return []

    offenders = set()
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue  # torn mid-write by a concurrent appender
        if not isinstance(record, dict):
            continue
        offenders.add(f"{record.get('test') or '<no test recorded>'} -> {record.get('path')}")
    return sorted(offenders)


@pytest.fixture(scope="session", autouse=True)
def _real_tracking_state_is_untouched():
    """No test may add or change a task-tracking file anywhere in the real checkout.

    Wider than a sentinel in one directory, which is what let #222 be called fixed while a
    spawned child was still writing into `features/.ai-badger/` — a path `.gitignore`'s
    unanchored `task-tracking/` rule hides from `git status`.

    The mtime diff alone cannot say *who* wrote. A leftover `poll_limit.py` daemon or a
    `*/30` resume cron writes into that same directory, and this fixture blamed the suite for
    it four times on 2026-08-01, on runs that were clean. So the assertion now fires on writes
    a suite process **marked as its own** (`tracker_lib.save_json`, which an external daemon
    never has the environment for), and unattributed changes are reported without failing —
    a real leak and a passing cron tick no longer produce the same message.
    """
    def rel(paths) -> list:
        return sorted(str(p.relative_to(REAL_PROJECT_ROOT)) for p in paths)

    before = real_tracking_files()
    yield
    after = real_tracking_files()
    added = rel(set(after) - set(before))
    changed = rel(p for p in set(after) & set(before) if after[p] != before[p])
    attributed = suite_attributed_writes(REAL_WRITE_LOG)

    if (added or changed) and not attributed:
        print(
            f"\nNOTE: task-tracking state changed during the run but no suite process claimed "
            f"it — added={added} changed={changed}. An external writer (a poll_limit daemon or "
            f"the resume cron) is the likely author; the suite is not being blamed for it."
        )

    assert not attributed, (
        "a suite process wrote task-tracking state outside the scratch project:\n  "
        + "\n  ".join(attributed)
        + f"\n(mtime diff for corroboration: added={added} changed={changed})")


def foreign_spawn_offenders(log: Path) -> list:
    """Breadcrumbs written by a process other than this one, as reportable strings.

    Defensive on every axis, because this runs at session teardown and a crash here would
    mask the offenders it exists to name. Several processes append to this file
    concurrently, so a torn or partial line is possible, and `argv` elements are stringified
    on the way in but a hand-written or older record may not be.

    A spawn whose `by` is this pid was already tracked and reaped by the Popen wrapper
    (#222). One from any other pid came from a child interpreter — the gap #232 records.
    """
    if not log.exists():
        return []

    offenders = set()
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue  # torn mid-write by a concurrent appender
        if not isinstance(record, dict) or record.get("by") == os.getpid():
            continue
        argv = record.get("argv") or []
        rendered = " ".join(str(part) for part in argv) if isinstance(argv, list) else str(argv)
        offenders.add(f"{record.get('test') or '<no test recorded>'} -> {rendered[:90]}")
    return sorted(offenders)


@pytest.fixture(scope="session", autouse=True)
def _no_test_reaches_a_detached_spawn(tmp_path_factory):
    """Name every test that reached `spawn_detached`, and fail the session if any did (#232).

    `_no_process_outlives_the_run` reaps what *this* process detached. It cannot see what a
    hook run in a child interpreter detaches — the Popen wrapper is a class replaced in one
    process's `subprocess` module, and a subprocess gets a clean one. That is how #222 could
    pass while orphaned `poll_limit.py` daemons accumulated with PPID 1 and a cwd inside the
    checkout.

    So this stops policing the outcome and names the call site instead. `spawn_detached`
    appends a breadcrumb when `AI_BADGER_SPAWN_LOG` is set; the variable is inert outside the
    suite, and it is inherited by child interpreters, which is the whole point — it reaches
    where the wrapper cannot.
    """
    log = tmp_path_factory.mktemp("spawn-breadcrumb") / "spawns.jsonl"
    os.environ[SPAWN_LOG_ENV] = str(log)
    yield log
    os.environ.pop(SPAWN_LOG_ENV, None)

    offenders = foreign_spawn_offenders(log)

    assert not offenders, (
        "these tests reached a detached spawn from a child interpreter, where the Popen "
        "wrapper cannot reap it — point the hook at a scratch project or stub spawn_detached "
        "(see tests/test_debug_log.py):\n  " + "\n  ".join(offenders))


@pytest.fixture(scope="session", autouse=True)
def _no_process_outlives_the_run():
    """Reap detached children, then drop the scratch project root the suite wrote into."""
    yield SCRATCH_PROJECT
    killed = reap_detached_children()
    shutil.rmtree(SCRATCH_PROJECT, ignore_errors=True)

    assert not killed, (
        f"{len(killed)} detached process(es) outlived the suite and had to be killed. "
        "A test that reaches a spawn site must patch tracker_lib.spawn_detached; the reaper "
        "is the floor, not the plan.")


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
