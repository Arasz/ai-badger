"""Sibling-module loading in ai_badger_hooks.py (`_load_memory_first_gate` and friends).

A missing sibling (an older scaffold) must fail open in silence. A broken one (syntax error,
or a module that raises at import time) must be loud instead: the memory-first gate's failure
must say "gate disabled" (the acceptance criterion), and every loader must report a broken
module exactly once per process rather than re-logging on every call.
"""
from __future__ import annotations

import importlib.util
import logging
import shutil
import sys
from pathlib import Path

import pytest

HOOKS = "features/common/hooks/ai_badger_hooks.py"

SYNTAX_ERROR_SOURCE = "def broken(:\n"
RUNTIME_ERROR_SOURCE = "raise RuntimeError('boom at import time')\n"
HEALTHY_MEMORY_FIRST_GATE_SOURCE = "LOADED = True\n"
HEALTHY_COMMIT_REMINDER_SOURCE = "LOADED = True\n"


@pytest.fixture
def hooks_module(tmp_path, root):
    """A scratch copy of ai_badger_hooks.py, importable with siblings staged beside it.

    Copied into tmp_path (not loaded in place) so a fixture-written sibling file lands next
    to *this* copy, per `Path(__file__).resolve().parent` inside the loader. Isolated per test:
    the label is unique, and every sibling module name this file can cache in `sys.modules`
    is scrubbed on teardown so one test's broken/healthy sibling never leaks into the next.
    """
    target = tmp_path / "ai_badger_hooks.py"
    shutil.copy2(root / HOOKS, target)
    label = f"aib_probe_sibling_loading_{tmp_path.name}"
    spec = importlib.util.spec_from_file_location(label, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[label] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(label, None)
        for name in (
                module.MEMORY_FIRST_GATE_MODULE_NAME,
                module.MCP_MATCHER_MODULE_NAME,
                module.SYNC_MODULE_NAME,
                module.COMMIT_REMINDER_MODULE_NAME,
                module.IMPACT_ESTIMATOR_MODULE_NAME,
                module.MEMORY_GRADE_MODULE_NAME,
        ):
            sys.modules.pop(name, None)


def _stage_sibling(hooks_module, tmp_path, filename, source):
    """Write a sibling module beside the scratch copy of ai_badger_hooks.py."""
    hooks_dir = Path(hooks_module.__file__).resolve().parent
    (hooks_dir / filename).write_text(source, encoding="utf-8")


# --------------------------------------------------------------------------- broken: loud
def test_a_broken_memory_first_gate_logs_gate_disabled(hooks_module, tmp_path, caplog):
    _stage_sibling(hooks_module, tmp_path, "memory_first_gate.py", SYNTAX_ERROR_SOURCE)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    result = hooks_module._load_memory_first_gate()

    assert result is None
    assert any("gate disabled" in record.message for record in caplog.records)


def test_a_broken_sibling_logs_exactly_once_across_repeated_calls(hooks_module, tmp_path, caplog):
    _stage_sibling(hooks_module, tmp_path, "memory_first_gate.py", SYNTAX_ERROR_SOURCE)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    results = [hooks_module._load_memory_first_gate() for _ in range(3)]

    matching = [r for r in caplog.records if "gate disabled" in r.message]
    assert len(matching) == 1
    assert results == [None, None, None]
    assert hooks_module.MEMORY_FIRST_GATE_MODULE_NAME not in sys.modules


def test_a_sibling_that_raises_at_import_time_is_also_caught(hooks_module, tmp_path, caplog):
    """Not every broken module is a SyntaxError — one that imports fine but raises counts too."""
    _stage_sibling(hooks_module, tmp_path, "memory_first_gate.py", RUNTIME_ERROR_SOURCE)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    result = hooks_module._load_memory_first_gate()

    assert result is None
    assert any("gate disabled" in record.message for record in caplog.records)


# ------------------------------------------------------------------------- absent: silent
def test_an_absent_sibling_logs_nothing(hooks_module, caplog):
    caplog.set_level(logging.DEBUG, logger="ai_badger_hooks")

    result = hooks_module._load_memory_first_gate()

    assert result is None
    assert caplog.records == []


# ------------------------------------------------------------------------- healthy: loads
def test_a_healthy_sibling_loads_and_is_cached(hooks_module, tmp_path):
    _stage_sibling(hooks_module, tmp_path, "memory_first_gate.py", HEALTHY_MEMORY_FIRST_GATE_SOURCE)

    first = hooks_module._load_memory_first_gate()
    second = hooks_module._load_memory_first_gate()

    assert first is not None
    assert first.LOADED is True
    assert second is first


# ------------------------------------------------------------------- a second call site too
def test_a_broken_commit_reminder_is_also_reported_once(hooks_module, tmp_path, caplog):
    _stage_sibling(hooks_module, tmp_path, "commit_reminder.py", SYNTAX_ERROR_SOURCE)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    results = [hooks_module._load_commit_reminder() for _ in range(3)]

    disabled = [r for r in caplog.records if "disabled" in r.message]
    assert len(disabled) == 1
    assert "commit reminder" in disabled[0].message
    assert results == [None, None, None]


def test_a_healthy_commit_reminder_loads(hooks_module, tmp_path):
    _stage_sibling(hooks_module, tmp_path, "commit_reminder.py", HEALTHY_COMMIT_REMINDER_SOURCE)

    result = hooks_module._load_commit_reminder()

    assert result is not None
    assert result.LOADED is True