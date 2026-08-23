"""Shared memory-first gate module: tool matchers, session markers, deny builders.

The gate blocks repo text-search tools (grep/find/search_files) until the session has
consulted AiRaccoon memory; once a memory_search ran, text search passes. Memory-first,
never memory-only. All logic is pure functions plus marker-file IO, mirroring
memory_grade.py — a hook built on it must never raise.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import pytest

ENV = "AI_RACCOON_PROJECT_ID"


@pytest.fixture
def gate(load_script, monkeypatch, tmp_path):
    """The real module, with the marker dir redirected to tmp paths."""
    real = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    return real


# ------------------------------------------------------------------ tool matchers
def test_hermes_builtin_search_tools_are_text_search(gate):
    assert gate.is_text_search("search_files", {"pattern": "MemorySearch"})
    assert gate.is_text_search("Search_Files", {"pattern": "x"})


def test_hermes_builtin_non_search_tools_are_not(gate):
    assert not gate.is_text_search("read_file", {"path": "a.cs"})
    assert not gate.is_text_search("write_file", {"path": "a.cs"})
    assert not gate.is_text_search("memory_search", {"query": "q"})


def test_hermes_terminal_first_token_decides(gate):
    assert gate.is_text_search("terminal", {"command": "grep -r foo src/"})
    assert gate.is_text_search("terminal", {"command": "rg foo"})
    assert gate.is_text_search("terminal", {"command": "find . -name x"})
    assert not gate.is_text_search("terminal", {"command": "dotnet build"})
    assert not gate.is_text_search("terminal", {"command": "git status | grep x"})


def test_claude_tool_names(gate):
    assert gate.is_text_search("Grep", {"pattern": "x"})
    assert gate.is_text_search("Glob", {"pattern": "x"})
    assert gate.is_text_search("Bash", {"command": "grep -r x ."})
    assert not gate.is_text_search("Read", {"file_path": "a.cs"})
    assert not gate.is_text_search("Write", {"file_path": "a.cs"})
    assert not gate.is_text_search("Bash", {"command": "npm test"})


def test_copilot_tool_names(gate):
    assert gate.is_text_search("grep", {"pattern": "x"})
    assert gate.is_text_search("rg", {"pattern": "x"})
    assert gate.is_text_search("Glob", {"pattern": "x"})
    assert gate.is_text_search("bash", {"command": "grep foo"})
    assert not gate.is_text_search("view", {"path": "a.cs"})
    assert not gate.is_text_search("read", {"path": "a.cs"})


def test_non_string_inputs_never_match(gate):
    assert not gate.is_text_search(None, {})
    assert not gate.is_text_search("terminal", None)
    assert not gate.is_text_search("terminal", {"command": 42})
    assert not gate.is_text_search("terminal", {"command": "'unterminated"})


# ------------------------------------------------------------------ session markers
def test_marker_roundtrip(gate):
    assert not gate.search_consulted("sess-1")
    assert gate.record_search("sess-1")
    assert gate.search_consulted("sess-1")
    assert not gate.search_consulted("sess-2")


def test_marker_refuses_empty_session(gate):
    assert not gate.record_search("")
    assert not gate.record_search(None)
    assert not gate.search_consulted(None)


def test_marker_path_sanitizes_session_id(gate, tmp_path, monkeypatch):
    assert gate.marker_path("a/b").name == "a_b"
    assert gate.marker_path("a\\b").name == "a_b"
    assert gate.marker_path("sess:123 a").name == "sess_123_a"
    assert gate.marker_path(".").name == "_"
    assert gate.marker_path("..").name == "__"


# ------------------------------------------------------------------ project id
def test_project_id_is_repo_basename(gate):
    assert gate.project_id("/Users/arasz/RiderProjects/ai-raccoon") == "ai-raccoon"


def test_project_id_falls_back_to_unknown(gate):
    assert gate.project_id("") == "unknown"
    assert gate.project_id("/") == "unknown"


def test_project_id_env_override(gate, monkeypatch):
    monkeypatch.setenv(ENV, "custom-bank")
    assert gate.project_id("/some/repo") == "custom-bank"
    monkeypatch.delenv(ENV)


# ------------------------------------------------------------------ deny builders
def test_hermes_decision_shape(gate):
    decision = gate.build_decision("hermes", "search_files", {}, "s1",
                                   cwd="/repos/ai-raccoon")
    assert decision["action"] == "block"
    assert "memory_search" in decision["message"]
    assert "ai-raccoon" in decision["message"]


def test_claude_decision_shape(gate):
    decision = gate.build_decision("claude", "Grep", {}, "s1", cwd="/repos/ai-raccoon")
    out = decision["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "memory_search" in out["permissionDecisionReason"]


def test_copilot_decision_shape(gate):
    decision = gate.build_decision("copilot", "grep", {}, "s1", cwd="/repos/ai-raccoon")
    assert decision["permissionDecision"] == "deny"
    assert "memory_search" in decision["permissionDecisionReason"]


def test_unknown_host_fails_open(gate):
    assert gate.build_decision("codex", "grep", {}, "s1") == {}


# ------------------------------------------------------------------ denial loop guard
def test_denial_counter_roundtrip(gate):
    assert gate.deny_count("sess-d") == 0
    assert gate.increment_denials("sess-d")
    assert gate.increment_denials("sess-d")
    assert gate.deny_count("sess-d") == 2
    assert gate.deny_count("sess-other") == 0


def test_denials_refuse_empty_session(gate):
    assert not gate.increment_denials("")
    assert gate.deny_count(None) == 0


def test_three_strikes_is_the_pass_through_threshold(gate):
    for _ in range(gate.MAX_DENIALS):
        gate.increment_denials("sess-strike")
    assert gate.deny_count("sess-strike") == gate.MAX_DENIALS
