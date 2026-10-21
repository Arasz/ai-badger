"""PostToolUse hook for the memory-first gate: record the consulted marker.

The marker must be recorded for every query spelling (plain, mcp__-prefixed,
colon-qualified); other tools and malformed payloads must be silent no-ops. Exit 0 on
every path is a hard requirement: Copilot command hooks are fail-closed.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json
import sys

import badger_store
import pytest


@pytest.fixture
def gate(load_script, monkeypatch, tmp_path):
    """The real gate module with markers redirected to tmp paths."""
    real = load_script(
        "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setattr(real, "SEARCHED_DIR", tmp_path / "memory-first-searched", raising=False)
    monkeypatch.setenv(badger_store.DEBUG_DIR_ENV, str(tmp_path / "debug"))
    monkeypatch.setenv("AI_BADGER_PROJECT_ID", "post-proj")
    # P2.1a: gate presence is a store row — hook runs land in a scratch user root.
    monkeypatch.setenv(badger_store.USER_ROOT_ENV, str(tmp_path / "user-root"))
    monkeypatch.setitem(sys.modules, "memory_first_gate", real)
    return real


@pytest.fixture
def hook(gate, load_script):
    return load_script(
        "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate_post_hook.py")


def _run(hook, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(
        payload if isinstance(payload, str) else json.dumps(payload)))
    return hook.main([])


def _searched(gate, query):
    return gate.unsearched("post-proj", [query]) == []


def test_plain_memory_search_records_marker(hook, gate, monkeypatch, tmp_path):
    rc = _run(hook, monkeypatch, {"tool_name": "query", "session_id": "t1",
                                  "tool_input": {"projectId": "post-proj", "query": "alpha"}})

    assert rc == 0
    assert _searched(gate, "alpha")


def test_mcp_prefixed_spelling_records_marker(hook, gate, monkeypatch):
    rc = _run(hook, monkeypatch, {
        "toolName": "mcp__ai_raccoon__memory_search", "sessionId": "t2",
        "toolArgs": '{"projectId": "post-proj", "query": "beta"}'})

    assert rc == 0
    assert _searched(gate, "beta")


def test_colon_spelling_records_marker(hook, gate, monkeypatch):
    rc = _run(hook, monkeypatch, {"tool_name": "ai-raccoon:query",
                                  "session_id": "t3", "tool_input": {"projectId": "post-proj", "query": "gamma"}})

    assert rc == 0
    assert _searched(gate, "gamma")


def test_non_search_tool_is_silent_noop(hook, gate, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, {"tool_name": "search_files",
                                  "session_id": "t4", "tool_input": {"pattern": "x"}})

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert not _searched(gate, "x")


def test_malformed_payload_exits_zero(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, "{not json")

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_missing_session_id_is_silent_noop(hook, gate, monkeypatch):
    rc = _run(hook, monkeypatch, {"tool_name": "query"})

    assert rc == 0


class TestMatcher:
    def test_matches_only_memory_search(self, gate):
        for name in ("query", "mcp__x__memory_search", "a:b:query",
                     "mcp_ai-raccoon_memory_search", "mcp_ai_raccoon_memory_search"):
            assert gate.is_memory_search(name), name
        for name in ("add_memory", "memory_search_extra", "search", "", 42, None,
                     "mcp_ai-raccoon_memory_search_extra", "mcp_write"):
            assert not gate.is_memory_search(name), name
