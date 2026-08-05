"""The AI_BADGER_MEMORY_GRADE gate: exactly "1" on, everything else off.

Every test pins the env var explicitly (F5): the suite must not inherit an
ambient machine-wide enable, and the OFF paths must do zero IO.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import pytest

ENV = "AI_BADGER_MEMORY_GRADE"


@pytest.fixture
def memory_grade(load_script):
    return load_script("features/common/skills/ai-raccoon-memory/scripts/memory_grade.py")


@pytest.fixture
def grade_paths(tmp_path, memory_grade, monkeypatch):
    """Redirect the log and pending store away from the real ~/.ai-badger/."""
    log = tmp_path / "memory-quality.jsonl"
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(memory_grade, "LOG_FILE", log)
    monkeypatch.setattr(memory_grade, "PENDING_FILE", pending)
    return log, pending


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(ENV, "1")


def test_disabled_by_default(tmp_path, monkeypatch, memory_grade, grade_paths, off):
    log, pending = grade_paths

    assert memory_grade.enabled() is False
    assert memory_grade.log_search({"query": "q", "projectId": "p"}, "{}",
                                   str(tmp_path)) is None
    assert memory_grade.pop_ask(str(tmp_path)) is None
    assert not log.exists()
    assert not pending.exists()


def test_enabled_by_ai_badger_memory_grade_1(tmp_path, memory_grade, grade_paths, on):
    log, pending = grade_paths

    assert memory_grade.enabled() is True
    ask = memory_grade.log_search({"query": "q", "projectId": "p"}, "{}", str(tmp_path))
    assert ask is not None
    assert log.exists()
    assert pending.exists()


def test_garbage_value_is_off(tmp_path, memory_grade, grade_paths, monkeypatch):
    log, pending = grade_paths

    for value in ("0", "yes", "true", "garbage", ""):
        monkeypatch.setenv(ENV, value)
        assert memory_grade.enabled() is False, value
        assert memory_grade.log_search({"query": "q", "projectId": "p"}, "{}",
                                       str(tmp_path)) is None, value

    assert not log.exists()
    assert not pending.exists()
