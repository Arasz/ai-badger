"""Shared pytest helpers for the ai-badger script suite.

The scripts are standalone files (not an installed package) that bootstrap ``badger_lib`` /
``tracker_lib`` onto ``sys.path`` at import time, so tests load them by repo-relative path via the
``load_script`` fixture rather than importing a package. ``ROOT`` is the framework repo root.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

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
    """Return a loader that imports an ai-badger script by repo-relative path."""
    def _load(relpath: str):
        path = ROOT / relpath
        name = "aib_" + path.stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    return _load
