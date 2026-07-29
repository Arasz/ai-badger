"""Tests for MCP index integration in ai_badger_hooks.py.

Covers:
- _load_mcp_index: discovering and parsing .ai-badger/mcp-tools.yaml, and degrading
  to None (not crashing) when pyyaml is absent
- _find_relevant_tools: delegates to features/common/retrieval/mcp_matcher.py
  (docs/adr/0012) rather than containing the ranking itself
- pre_llm_inject_context: injecting tool recommendations based on user message

The BM25 algorithm itself (tokenizer, scoring, gate) is covered by
tests/test_retrieval_tokenizer.py, tests/test_retrieval_bm25.py and
tests/test_mcp_matcher.py — this file only covers the hook's wiring to it.
"""
# pylint: disable=protected-access,redefined-outer-name  # hook internals + local module handle; see pyproject.toml

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


# ── Helpers ────────────────────────────────────────────────────────────────

def _write_mcp_index(project: Path, data: dict) -> Path:
    """Write .ai-badger/mcp-tools.yaml to a project directory."""
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    path = aib / "mcp-tools.yaml"
    path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    return path


def _sample_index() -> dict:
    """Return a sample index with representative tools for testing."""
    return {
        "version": "0.1.0",
        "generated_at": "2026-07-22T00:00:00Z",
        "sources": [
            {
                "name": "rider",
                "tools": {
                    "build_solution": {
                        "tags": ["dotnet", "build", "csharp"],
                        "intent": "Compile the solution and return build errors",
                    },
                    "get_file_problems": {
                        "tags": ["diagnostic", "csharp", "typescript"],
                        "intent": "Check a file for Rider code analysis errors",
                    },
                    "execute_run_configuration": {
                        "tags": ["run", "dotnet", "csharp"],
                        "intent": "Run a configuration or code location with overrides",
                    },
                    "execute_sql_query": {
                        "tags": ["database", "sql"],
                        "intent": "Run a SQL query against a database connection",
                    },
                    "get_log_records": {
                        "tags": ["tracing", "opentelemetry", "diagnostic"],
                        "intent": "Query log records by service, severity, and time",
                    },
                    "search_symbol": {
                        "tags": ["semantic", "search", "csharp", "typescript"],
                        "intent": "Find a class, method, or field by name fragment",
                    },
                },
            },
        ],
    }


@pytest.fixture
def hooks(load_script):
    """Load a fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def real_mcp_matcher(hooks, load_script, monkeypatch):
    """Inject the real mcp_matcher module, matching the fake_commit_reminder pattern.

    In the dev tree mcp_matcher.py isn't copied beside ai_badger_hooks.py yet (that
    only happens at scaffold time), so _load_mcp_matcher's sibling-file lookup
    would return None here without this — mirrors how test_commit_reminder_hermes.py
    injects its sibling module via sys.modules.
    """
    module = load_script("features/common/retrieval/mcp_matcher.py")
    monkeypatch.setitem(sys.modules, hooks.MCP_MATCHER_MODULE_NAME, module)
    return module


# ── _load_mcp_index ────────────────────────────────────────────────────────

def test_load_index_when_present(hooks, tmp_path):
    """Should return parsed index when .ai-badger/mcp-tools.yaml exists."""
    index_data = _sample_index()
    _write_mcp_index(tmp_path, index_data)

    result = hooks._load_mcp_index(str(tmp_path))
    assert result is not None
    assert result["version"] == "0.1.0"
    assert len(result["sources"]) == 1


def test_load_index_when_missing(hooks, tmp_path):
    """Should return None when .ai-badger/mcp-tools.yaml doesn't exist."""
    assert hooks._load_mcp_index(str(tmp_path)) is None


def test_load_index_when_cwd_is_empty(hooks):
    """Should return None when cwd is empty/None."""
    assert hooks._load_mcp_index("") is None


def test_load_index_degrades_to_none_without_pyyaml(hooks, tmp_path, monkeypatch):
    """An absent pyyaml must degrade the index to None, not crash the hook (issue #136)."""
    _write_mcp_index(tmp_path, _sample_index())
    monkeypatch.setattr(hooks, "yaml", None)

    assert hooks._load_mcp_index(str(tmp_path)) is None


# ── _find_relevant_tools delegates to the BM25 matcher ─────────────────────

def test_find_relevant_tools_is_inert_without_the_matcher_module(hooks, tmp_path):
    """No mcp_matcher.py beside the hook (older scaffold) -> [], not an exception."""
    index = _sample_index()
    assert hooks._find_relevant_tools("build the solution", index) == []


def test_find_relevant_tools_delegates_to_the_real_matcher(hooks, real_mcp_matcher):
    """With the matcher available, a build query ranks build_solution first."""
    index = _sample_index()
    ranked = hooks._find_relevant_tools("build the solution", index, top_n=3)

    assert ranked
    assert ranked[0][0] == "rider:build_solution"


def test_find_relevant_tools_uses_the_matchers_coverage_gate(hooks, real_mcp_matcher):
    """An unrelated query must return [] — the gate, not a keyword miss, decides this now."""
    index = _sample_index()
    ranked = hooks._find_relevant_tools("philosophical question about life", index)
    assert ranked == []


def test_find_relevant_tools_fixes_the_ts_inside_tests_bug(hooks, real_mcp_matcher):
    """'ts' must not match 'typescript' via substring anymore (the old defect)."""
    index = _sample_index()
    ranked = hooks._find_relevant_tools("ts", index)
    assert ranked == []


# ── pre_llm_inject_context with index ──────────────────────────────────────

def test_pre_llm_inject_no_index(hooks):
    """Without an index, should still return context (usage hints)."""
    hooks.reset_session_hints()
    result = hooks.pre_llm_inject_context(cwd="/nonexistent/path")
    assert result is not None
    assert "context" in result
    assert "/usage" in result["context"] or "session_search" in result["context"]


def test_pre_llm_inject_with_index_build_query_recommends_a_tool(
        hooks, real_mcp_matcher, tmp_path):
    """With the matcher available and a build query, the hint names build_solution."""
    _write_mcp_index(tmp_path, _sample_index())
    hooks.reset_session_hints()

    result = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="build the solution")

    assert result is not None
    assert "rider:build_solution" in result["context"]


def test_pre_llm_inject_without_a_message_recommends_no_tools(hooks, real_mcp_matcher, tmp_path):
    """Tool hints come from keywords in the user message; with no message there are none.

    Previously named ..._no_double_injection and asserted only `result is not None`,
    with two comments describing a check that was never written (F-48).
    """
    _write_mcp_index(tmp_path, _sample_index())
    hooks.reset_session_hints()

    result = hooks.pre_llm_inject_context(cwd=str(tmp_path))

    assert result is not None
    context = result["context"]
    assert "/usage" in context
    for tool in ("build_solution", "execute_sql_query", "get_file_problems"):
        assert tool not in context


# ── post_tool_observer with index ──────────────────────────────────────────

def test_post_tool_observer_noop(hooks):
    """post_tool_observer should not crash with or without index data."""
    hooks.post_tool_observer(
        tool_name="rider:get_file_problems",
        result='{"errors": []}',
        duration_ms=42,
    )


def test_usage_hint_is_injected_once_per_session(hooks, tmp_path):
    """A line repeated every turn is a line the agent stops reading (F-37)."""
    hooks.reset_session_hints()

    first = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="hello")
    second = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="hello again")

    assert "/usage" in (first or {}).get("context", "")
    assert "/usage" not in (second or {}).get("context", "")


def test_usage_hint_returns_after_a_session_reset(hooks, tmp_path):
    hooks.reset_session_hints()
    hooks.pre_llm_inject_context(cwd=str(tmp_path), message="hello")

    hooks.on_session_start_drift_notice(cwd=str(tmp_path))
    again = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="new session")

    assert "/usage" in (again or {}).get("context", "")
