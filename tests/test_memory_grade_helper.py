"""The memory_grade.py CLI: `grade <ts> <1-5> [note]` fills the matching line in place,
and `probe` prints config state, the log path, and the last 3 lines."""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

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
    monkeypatch.setenv(ENV, "1")
    return log, pending


def _seed(memory_grade, tmp_path, args, result="{}"):
    """One logged search line, via the same code path the hook uses."""
    memory_grade.log_search(args, result, str(tmp_path))
    return json.loads(memory_grade.LOG_FILE.read_text(encoding="utf-8").splitlines()[-1])


def test_grade_fills_the_matching_line_in_place(tmp_path, memory_grade, grade_paths):
    log, _ = grade_paths
    line = _seed(memory_grade, tmp_path, {"projectId": "p", "query": "q"})

    rc = memory_grade.main(["grade", line["ts"], "4", "nice hit"])

    assert rc == 0
    graded = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert graded["usefulness"] == 4
    assert graded["note"] == "nice hit"
    assert graded["ts"] == line["ts"]
    assert graded["result"] == line["result"]


def test_other_lines_unchanged_byte_for_byte(tmp_path, memory_grade, grade_paths):
    log, _ = grade_paths
    first = _seed(memory_grade, tmp_path, {"projectId": "p", "query": "q1"})
    second = _seed(memory_grade, tmp_path, {"projectId": "p", "query": "q2"})
    raw_second = log.read_text(encoding="utf-8").splitlines()[1]

    memory_grade.main(["grade", first["ts"], "5"])

    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines[1] == raw_second, "the other line must survive byte for byte"
    assert json.loads(lines[0])["usefulness"] == 5


def test_grade_out_of_range_exits_1_and_changes_nothing(tmp_path, memory_grade, grade_paths,
                                                        capsys):
    log, _ = grade_paths
    line = _seed(memory_grade, tmp_path, {"projectId": "p", "query": "q"})
    before = log.read_text(encoding="utf-8")

    for bad in ("0", "6", "x"):
        rc = memory_grade.main(["grade", line["ts"], bad])

        assert rc == 1, bad
        assert log.read_text(encoding="utf-8") == before, bad

    err = capsys.readouterr().err
    assert "1-5" in err


def test_unknown_ts_exits_1_with_message(tmp_path, memory_grade, grade_paths, capsys):
    log, _ = grade_paths
    _seed(memory_grade, tmp_path, {"projectId": "p", "query": "q"})

    rc = memory_grade.main(["grade", "2020-01-01T00:00:00+00:00", "4"])

    assert rc == 1
    assert "not found" in capsys.readouterr().err
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["usefulness"] is None


def test_probe_prints_state_and_log_path(tmp_path, memory_grade, grade_paths, capsys):
    log, _ = grade_paths
    _seed(memory_grade, tmp_path, {"projectId": "p", "query": "q"})

    rc = memory_grade.main(["probe"])

    assert rc == 0
    out = capsys.readouterr().out
    assert ENV in out
    assert "enabled" in out
    assert str(log) in out
    assert "p" in out  # the last-3-lines window shows the seeded line
