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
