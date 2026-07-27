"""Tests for the commit-reminder skill's impact estimation: a pure default heuristic and
a guarded, optional code-review-graph subprocess call the cheap path must never invoke.
"""
# pylint: disable=redefined-outer-name  # pytest fixtures reuse param names by design
from __future__ import annotations

import subprocess

import pytest

SCRIPT = "features/common/skills/commit-reminder/scripts/impact_estimator.py"


@pytest.fixture
def impact_estimator(load_script):
    return load_script(SCRIPT)


# ---------------------------------------------------------------------------
# default_impact
# ---------------------------------------------------------------------------

def test_default_impact_four_files_is_low_severity(impact_estimator):
    files = [f"dir/file{i}.py" for i in range(4)]
    assert "low" in impact_estimator.default_impact(files)


def test_default_impact_five_files_is_medium_severity(impact_estimator):
    files = [f"dir/file{i}.py" for i in range(5)]
    assert "medium" in impact_estimator.default_impact(files)


def test_default_impact_fourteen_files_is_medium_severity(impact_estimator):
    files = [f"dir/file{i}.py" for i in range(14)]
    assert "medium" in impact_estimator.default_impact(files)


def test_default_impact_fifteen_files_is_high_severity(impact_estimator):
    files = [f"dir/file{i}.py" for i in range(15)]
    assert "high" in impact_estimator.default_impact(files)


def test_default_impact_single_file_never_reads_as_high(impact_estimator):
    assert "high" not in impact_estimator.default_impact(["a.py"])


def test_default_impact_mentions_file_count(impact_estimator):
    result = impact_estimator.default_impact(["a.py", "b.py", "c.py"])
    assert "3" in result


def test_default_impact_mentions_distinct_parent_directory_count(impact_estimator):
    files = ["dir_a/a.py", "dir_a/b.py", "dir_b/c.py"]
    result = impact_estimator.default_impact(files)
    assert "2" in result


def test_default_impact_empty_list_returns_sensible_string(impact_estimator):
    result = impact_estimator.default_impact([])
    assert isinstance(result, str)
    assert "0" in result
    assert "low" in result


# ---------------------------------------------------------------------------
# graph_impact
# ---------------------------------------------------------------------------

def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                        stdout=stdout, stderr=stderr)


def test_graph_impact_returns_string_on_success(impact_estimator, monkeypatch):
    stdout = '{"status": "ok", "summary": "touches auth module", "total_impacted": 12}'
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(0, stdout))

    result = impact_estimator.graph_impact(["a.py"], "/repo")

    assert result is not None
    assert "touches auth module" in result
    assert "12" in result


def test_graph_impact_returns_none_on_missing_binary(impact_estimator, monkeypatch):
    def _raise(*_a, **_k):
        raise FileNotFoundError("no code_review_graph")
    monkeypatch.setattr(impact_estimator.subprocess, "run", _raise)

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_module_imports_and_runs_without_code_review_graph_installed(
        impact_estimator, monkeypatch):
    """Proves there is no top-level `import code_review_graph` in this module."""
    def _raise(*_a, **_k):
        raise FileNotFoundError("no such module")
    monkeypatch.setattr(impact_estimator.subprocess, "run", _raise)

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_returns_none_on_timeout(impact_estimator, monkeypatch):
    def _raise(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=8.0)
    monkeypatch.setattr(impact_estimator.subprocess, "run", _raise)

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_returns_none_on_nonzero_returncode(impact_estimator, monkeypatch):
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(1, "", "boom"))

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_returns_none_on_invalid_json(impact_estimator, monkeypatch):
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(0, "not json"))

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_returns_none_when_keys_missing(impact_estimator, monkeypatch):
    stdout = '{"status": "ok", "summary": "touches auth module"}'
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(0, stdout))

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_returns_none_when_status_is_not_ok(impact_estimator, monkeypatch):
    stdout = '{"status": "error", "summary": "x", "total_impacted": 1}'
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(0, stdout))

    assert impact_estimator.graph_impact(["a.py"], "/repo") is None


def test_graph_impact_never_echoes_stderr_in_return_value(impact_estimator, monkeypatch):
    secret_stderr = "SECRET-STDERR-MARKER: internal scan output"
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(1, "", secret_stderr))

    result = impact_estimator.graph_impact(["a.py"], "/repo")

    assert result is None


# ---------------------------------------------------------------------------
# estimate_impact
# ---------------------------------------------------------------------------

def test_estimate_impact_default_path_never_calls_subprocess(impact_estimator, monkeypatch):
    def _fail(*_a, **_k):
        raise AssertionError("subprocess.run must never be called on the default path")
    monkeypatch.setattr(impact_estimator.subprocess, "run", _fail)

    result = impact_estimator.estimate_impact(["a.py"], "/repo", use_graph=False)

    assert result == impact_estimator.default_impact(["a.py"])


def test_estimate_impact_use_graph_true_returns_graph_result_when_available(
        impact_estimator, monkeypatch):
    stdout = '{"status": "ok", "summary": "touches auth module", "total_impacted": 3}'
    monkeypatch.setattr(impact_estimator.subprocess, "run",
                         lambda *a, **k: _completed(0, stdout))

    result = impact_estimator.estimate_impact(["a.py"], "/repo", use_graph=True)

    assert "touches auth module" in result


def test_estimate_impact_use_graph_true_falls_back_to_default_on_graph_failure(
        impact_estimator, monkeypatch):
    def _raise(*_a, **_k):
        raise FileNotFoundError("no code_review_graph")
    monkeypatch.setattr(impact_estimator.subprocess, "run", _raise)

    result = impact_estimator.estimate_impact(["a.py"], "/repo", use_graph=True)

    assert result == impact_estimator.default_impact(["a.py"])
