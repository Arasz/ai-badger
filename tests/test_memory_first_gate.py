"""Shared memory-first gate module: tool matchers, session markers, deny builders.

The gate blocks repo text-search tools (grep/find/search_files) until the session has
consulted AiRaccoon memory; once a query ran, text search passes. Memory-first,
never memory-only. All logic is pure functions plus marker-file IO, mirroring
memory_grade.py — a hook built on it must never raise.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import badger_store
import pytest

ENV = "AI_BADGER_PROJECT_ID"


@pytest.fixture
def gate(load_script, monkeypatch, tmp_path):
    """The real module: legacy marker dir AND the rows' user store both redirected to tmp."""
    real = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setattr(real, "SEARCHED_DIR", tmp_path / "memory-first-searched", raising=False)
    monkeypatch.setattr(real, "memory_hits", lambda *_a, **_k: None, raising=False)
    monkeypatch.setenv(badger_store.USER_ROOT_ENV, str(tmp_path / "user-root"))
    monkeypatch.setenv(badger_store.DEBUG_DIR_ENV, str(tmp_path / "debug"))
    return real


# ------------------------------------------------------------------ tool matchers
def test_hermes_builtin_search_tools_are_text_search(gate):
    assert gate.is_text_search("search_files", {"pattern": "MemorySearch"})
    assert gate.is_text_search("Search_Files", {"pattern": "x"})


def test_hermes_builtin_non_search_tools_are_not(gate):
    assert not gate.is_text_search("read_file", {"path": "a.cs"})
    assert not gate.is_text_search("write_file", {"path": "a.cs"})
    assert not gate.is_text_search("query", {"query": "q"})


def test_hermes_terminal_first_token_decides(gate):
    assert gate.is_text_search("terminal", {"command": "grep -r foo src/"})
    assert gate.is_text_search("terminal", {"command": "rg foo"})
    assert gate.is_text_search("terminal", {"command": "find . -name x"})
    assert not gate.is_text_search("terminal", {"command": "dotnet build"})
    # every segment of a compound command counts, a piped grep included, except a grep over
    # an EXCLUDED_UPSTREAM program's live output
    assert gate.is_text_search("terminal", {"command": "cat f | grep x"})
    assert not gate.is_text_search("terminal", {"command": "git status | grep x"})
    assert not gate.is_text_search("terminal", {"command": "git status | head -3"})


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


# ------------------------------------------------------------------ session telemetry rows
def _row(gate, session_id):
    store = badger_store.open_user(families={
        "memory_first": badger_store.Family(
            table="memory_first", db="user",
            legacy_path=lambda: gate.MARKER_DIR, legacy_kind="markers",
        ),
    })
    try:
        return store.conn.execute(
            "SELECT payload FROM memory_first WHERE session_id = ?", (session_id,)).fetchone()
    finally:
        store.close()


def test_marker_roundtrip(gate):
    """record_search stays as telemetry: a memory_first row keyed by session id."""
    assert gate.record_search("sess-1")
    assert _row(gate, "sess-2") is None
    # Secondary observable: the row really carries the consulted payload, not a bare key.
    store = badger_store.open_user(families={
        "memory_first": badger_store.Family(
            table="memory_first", db="user",
            legacy_path=lambda: gate.MARKER_DIR, legacy_kind="markers",
        ),
    })
    try:
        row = store.conn.execute(
            "SELECT payload FROM memory_first WHERE session_id = 'sess-1'").fetchone()
    finally:
        store.close()
    assert json.loads(row[0]) == {"consulted": True}


def test_marker_refuses_empty_session(gate):
    assert not gate.record_search("")
    assert not gate.record_search(None)


def test_marker_path_sanitizes_session_id(gate, tmp_path, monkeypatch):
    assert gate.marker_path("a/b").name == "a_b"
    assert gate.marker_path("a\\b").name == "a_b"
    assert gate.marker_path("sess:123 a").name == "sess_123_a"
    assert gate.marker_path(".").name == "_"
    assert gate.marker_path("..").name == "__"


# ------------------------------------------------------------------ project id
def test_project_id_reads_the_walked_id_file(gate, tmp_path, monkeypatch):
    """The denial names the id the memory hook uses: the nearest .ai-badger/project-id,
    found from a directory BELOW the project root.

    Mutation: revert to the basename chain (the id file is on disk and would be ignored).
    """
    guid = "11111111-1111-1111-1111-111111111111"
    project = tmp_path / "walked-project"
    (project / ".ai-badger").mkdir(parents=True)
    (project / ".ai-badger" / "project-id").write_text(guid + "\n", encoding="utf-8")
    nested = project / "deep" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.delenv(ENV, raising=False)

    assert gate.project_id(str(nested)) == guid
    reason = gate.build_decision("claude", "Grep", {}, "s1",
                                 cwd=str(nested))["hookSpecificOutput"]["permissionDecisionReason"]
    assert f"projectId={guid}" in reason


def test_project_id_returns_a_legacy_non_guid_id_verbatim(gate, tmp_path, monkeypatch):
    """den-refresh can reuse a bank project named by a legacy raw-text id.

    Mutation: validate the walked id as a uuid (a legacy hit becomes the fallback name).
    """
    project = tmp_path / "legacy-project"
    (project / ".ai-badger").mkdir(parents=True)
    (project / ".ai-badger" / "project-id").write_text("jsaa\n", encoding="utf-8")
    monkeypatch.delenv(ENV, raising=False)

    assert gate.project_id(str(project)) == "jsaa"


def test_project_id_no_id_file_falls_back_to_basename(gate, tmp_path, monkeypatch):
    """A project predating the id file keeps the old surface: the directory's basename.

    Mutation: return 'unknown' (or '') when the walk finds nothing.
    """
    plain = tmp_path / "no-id-file"
    plain.mkdir()
    monkeypatch.delenv(ENV, raising=False)

    assert gate.project_id(str(plain)) == "no-id-file"


def test_project_id_falls_back_to_unknown(gate):
    assert gate.project_id("") == "unknown"
    assert gate.project_id("/") == "unknown"


def test_project_id_env_override(gate, monkeypatch):
    """AI_BADGER_PROJECT_ID is the one override; the store's resolver reads it first."""
    monkeypatch.setenv(ENV, "custom-bank")
    assert gate.project_id("/some/repo") == "custom-bank"
    monkeypatch.delenv(ENV)


def test_project_id_ignores_the_retired_raccoon_override(gate, tmp_path, monkeypatch):
    """AI_RACCOON_PROJECT_ID is retired: the gate and the memory hook share one override.

    Mutation: keep reading it (the retired variable silently wins over the walk).
    """
    plain = tmp_path / "retired-override"
    plain.mkdir()
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setenv("AI_RACCOON_PROJECT_ID", "custom-bank")

    assert gate.project_id(str(plain)) == "retired-override"


def test_project_id_without_the_store_falls_back_to_basename(gate, tmp_path, monkeypatch):
    """A deployment without the vendored store keeps the legacy basename surface.

    Mutation: call badger_store.resolve_project_id unguarded (AttributeError on None),
    or return the file id when the store is absent.
    """
    monkeypatch.setattr(gate, "badger_store", None)
    monkeypatch.delenv(ENV, raising=False)
    plain = tmp_path / "no-store"
    plain.mkdir()

    assert gate.project_id(str(plain)) == "no-store"


# ------------------------------------------------------------------ deny builders
def test_hermes_decision_shape(gate):
    decision = gate.build_decision("hermes", "search_files", {}, "s1",
                                   cwd="/repos/ai-raccoon")
    assert decision["action"] == "block"
    assert "query" in decision["message"]
    assert "ai-raccoon" in decision["message"]


def test_claude_decision_shape(gate):
    decision = gate.build_decision("claude", "Grep", {}, "s1", cwd="/repos/ai-raccoon")
    out = decision["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "query" in out["permissionDecisionReason"]


def test_copilot_decision_shape(gate):
    decision = gate.build_decision("copilot", "grep", {}, "s1", cwd="/repos/ai-raccoon")
    assert decision["permissionDecision"] == "deny"
    assert "query" in decision["permissionDecisionReason"]


def test_unknown_host_fails_open(gate):
    assert gate.build_decision("codex", "grep", {}, "s1") == {}


# ------------------------------------------------------------------ telemetry fallbacks
def test_first_write_imports_the_legacy_marker_set(gate):
    """Writer-path migration (D6): the first write imports MARKER_DIR's set and renames it."""
    legacy = gate.MARKER_DIR
    legacy.mkdir(parents=True)
    (legacy / "old-sess").touch()

    assert gate.record_search("new-sess") is True
    assert json.loads(_row(gate, "old-sess")[0]).get("consulted") is True
    assert not (legacy / "old-sess").exists()
    assert (legacy / "old-sess.migrated").exists()


def test_the_gate_survives_a_broken_store(gate, monkeypatch):
    """The file surfaces are the fail-open fallback when the stores cannot open."""
    def _broken(*_a, **_k):
        raise OSError("store unavailable")

    monkeypatch.setattr(badger_store, "open_user", _broken)
    monkeypatch.setattr(badger_store, "open_audit", _broken)
    assert gate.record_search("sess-fallback") is True
    assert gate.marker_path("sess-fallback").is_file()
    assert gate.remember("proj-x", ["needle"]) is True
    assert gate.unsearched("proj-x", ["needle"]) == []


def test_the_denial_counter_is_gone(gate):
    """No pass-through after N denials, no session-wide unlock."""
    for name in ("MAX_DENIALS", "deny_count", "increment_denials", "search_consulted",
                 "_denials_path"):
        assert not hasattr(gate, name), name
