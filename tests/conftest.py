"""Shared pytest helpers for the ai-badger script suite.

The scripts are standalone files (not an installed package) that bootstrap ``badger_lib`` /
``tracker_lib`` onto ``sys.path`` at import time, so tests load them by repo-relative path via the
``load_script`` fixture rather than importing a package. ``ROOT`` is the framework repo root.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The real home, captured before any test can redirect it.
REAL_HOME = Path.home()


@pytest.fixture(scope="session", autouse=True)
def _home_off_limits(tmp_path_factory):
    """Point `$HOME` at a scratch directory for the whole session.

    `debug_log` resolves its sink from `Path.home()` at import time, and scripts are loaded
    by path — a fresh module object per call, each with its own unpatched globals. One test
    that loads a copy without redirecting it writes to the user's real audit log. Moving
    home once, before anything is imported, removes the possibility rather than the symptom.
    """
    scratch = tmp_path_factory.mktemp("home")
    with pytest.MonkeyPatch.context() as patch:
        for var in ("HOME", "USERPROFILE"):
            patch.setenv(var, str(scratch))
        yield scratch


@pytest.fixture
def root() -> Path:
    """Absolute path to the ai-badger framework repo root."""
    return ROOT


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
