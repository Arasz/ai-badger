"""Raw grep result retrieval contract, including the short retention window."""
from __future__ import annotations

import hashlib
import json
import os

import pytest

SCRIPT = "features/common/skills/get-raw-grep-result/scripts/get_raw_grep_result.py"
TTL_SECONDS = 120
MAX_OUTPUT_BYTES = 1024 * 1024


@pytest.fixture
def result_script(load_script, monkeypatch, tmp_path):
    """Load the retrieval CLI against an isolated ai-badger audit database."""
    monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(tmp_path / "audit"))
    return load_script(SCRIPT)


def _invoke(script, capsys, *args):
    assert script.main(list(args)) == 0
    return json.loads(capsys.readouterr().out)


def _pattern_hash(pattern: str) -> str:
    return hashlib.sha256(pattern.encode("utf-8")).hexdigest()


def _capture(script, digest, command):
    scope = hashlib.sha256(os.path.realpath(os.getcwd()).encode("utf-8")).hexdigest()
    return script.main(["--capture", f"{scope}:{digest}", command])


def test_pattern_and_hash_retrieve_the_same_raw_result(result_script, capsys):
    pattern = "alpha\\.beta"
    digest = _pattern_hash(pattern)

    assert _capture(result_script, digest, "printf 'raw line\\nsecond line\\n'") == 0
    capsys.readouterr()

    by_hash = _invoke(result_script, capsys, "--pattern-hash", digest)
    by_pattern = _invoke(result_script, capsys, "--pattern", pattern)

    assert by_hash["status"] == "ready"
    assert by_hash["hash"] == digest
    assert by_hash["stdout"] == "raw line\nsecond line\n"
    assert by_hash["stderr"] == ""
    assert by_hash["returncode"] == 0
    assert by_pattern == by_hash


def test_missing_hash_is_reported_as_pending(result_script, capsys):
    digest = _pattern_hash("not written yet")

    result = _invoke(result_script, capsys, "--pattern-hash", digest)

    assert result["status"] == "pending"
    assert result["hash"] == digest


def test_result_expires_at_120_seconds(result_script, monkeypatch, capsys):
    pattern = "expire me"
    digest = _pattern_hash(pattern)
    now = [10_000.0]
    monkeypatch.setattr(result_script.time, "time", lambda: now[0])

    assert _capture(result_script, digest, "printf retained") == 0
    capsys.readouterr()
    now[0] += TTL_SECONDS - 1
    assert _invoke(result_script, capsys, "--pattern-hash", digest)["status"] == "ready"
    now[0] += 1

    expired = _invoke(result_script, capsys, "--pattern-hash", digest)
    assert expired["status"] == "expired"
    assert expired["hash"] == digest
    store = result_script._store()
    try:
        key = result_script._storage_key(result_script._scope_hash(), digest)
        assert store.kv_get("hook_state", key) is None
    finally:
        store.close()


def test_nonzero_grep_with_empty_stdout_is_still_a_ready_result(
        result_script, capsys):
    pattern = "no-match-pattern"
    digest = _pattern_hash(pattern)

    assert _capture(result_script, digest, "grep no-match-pattern /dev/null") == 0
    capsys.readouterr()

    result = _invoke(result_script, capsys, "--pattern", pattern)

    assert result["status"] == "ready"
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["returncode"] == 1


def test_capture_error_is_not_reported_as_empty_success(result_script, capsys):
    pattern = "capture-error"
    digest = _pattern_hash(pattern)

    assert _capture(result_script, digest, "command_that_does_not_exist_987") == 0
    capsys.readouterr()

    result = _invoke(result_script, capsys, "--pattern-hash", digest)

    assert result["status"] == "error"
    assert result["hash"] == digest
    assert result["returncode"] not in (None, 0)
    assert result["stderr"]


def test_large_output_is_bounded_and_marked_truncated(result_script, capsys):
    pattern = "large-output"
    digest = _pattern_hash(pattern)

    assert _capture(result_script, digest,
                    "head -c 2097152 /dev/zero | tr '\\0' x") == 0
    capsys.readouterr()

    result = _invoke(result_script, capsys, "--pattern-hash", digest)

    assert result["status"] == "ready"
    assert len(result["stdout"].encode("utf-8")) == MAX_OUTPUT_BYTES
    assert result["stdout_truncated"] is True


def test_same_pattern_result_is_isolated_between_working_directories(
        result_script, monkeypatch, tmp_path, capsys):
    pattern = "private-pattern"
    digest = _pattern_hash(pattern)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    monkeypatch.chdir(repo_a)
    assert _capture(result_script, digest, "printf repo-a-result") == 0
    capsys.readouterr()
    assert _invoke(result_script, capsys, "--pattern-hash", digest)["stdout"] == "repo-a-result"

    monkeypatch.chdir(repo_b)
    result = _invoke(result_script, capsys, "--pattern-hash", digest)

    assert result["status"] == "pending"
