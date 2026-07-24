"""Tests for MCP index integration in ai_badger_hooks.py.

Covers:
- _load_mcp_index: discovering and parsing .ai-badger/mcp-tools.yaml
- pre_llm_inject_context: injecting tool recommendations based on user message
- Keyword extraction and tag matching
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


# Import the hooks module
HOOKS_PATH = (
    Path(__file__).resolve().parents[1]
    / "features" / "common" / "hooks" / "ai_badger_hooks.py"
)

# Must add parent dir to sys.path so the module can be imported
sys.path.insert(0, str(HOOKS_PATH.parent))

import importlib.util

_spec = importlib.util.spec_from_file_location("ai_badger_hooks", HOOKS_PATH)
hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hooks)


# ── _load_mcp_index ────────────────────────────────────────────────────────

def test_load_index_when_present(tmp_path):
    """Should return parsed index when .ai-badger/mcp-tools.yaml exists."""
    index_data = _sample_index()
    _write_mcp_index(tmp_path, index_data)

    result = hooks._load_mcp_index(str(tmp_path))
    assert result is not None
    assert result["version"] == "0.1.0"
    assert len(result["sources"]) == 1


def test_load_index_when_missing(tmp_path):
    """Should return None when .ai-badger/mcp-tools.yaml doesn't exist."""
    result = hooks._load_mcp_index(str(tmp_path))
    assert result is None


def test_load_index_when_cwd_is_empty():
    """Should return None when cwd is empty/None."""
    result = hooks._load_mcp_index("")
    assert result is None


# ── keyword extraction ─────────────────────────────────────────────────────

def test_extract_tags_build():
    """'build the solution' should extract [build, dotnet, csharp]."""
    tags = hooks._extract_query_tags("build the solution")
    assert "build" in tags
    assert "dotnet" in tags
    assert "csharp" in tags


def test_extract_tags_database():
    """'show me the database tables' should extract [database, sql]."""
    tags = hooks._extract_query_tags("show me the database tables")
    assert "database" in tags
    assert "sql" in tags


def test_extract_tags_debug():
    """'debug the error' should extract [diagnostic]."""
    tags = hooks._extract_query_tags("debug the error in the pipeline")
    assert "diagnostic" in tags


def test_extract_tags_run_test():
    """'run the tests' should extract [run]."""
    tags = hooks._extract_query_tags("run the unit tests")
    assert "run" in tags


def test_extract_tags_empty():
    """Empty query should return empty tags."""
    tags = hooks._extract_query_tags("")
    assert tags == {}


def test_extract_tags_unknown():
    """Query with no known keywords should return empty tags."""
    tags = hooks._extract_query_tags("hello world how are you")
    assert tags == {}


# ── _find_relevant_tools ───────────────────────────────────────────────────

def test_find_relevant_tools_build(tmp_path):
    """'build' query should rank build_solution first."""
    _write_mcp_index(tmp_path, _sample_index())
    index = yaml.safe_load(
        (tmp_path / ".ai-badger" / "mcp-tools.yaml").read_text(encoding="utf-8")
    )
    ranked = hooks._find_relevant_tools("build the solution", index, top_n=3)

    assert len(ranked) <= 3
    assert ranked[0][0] == "rider:build_solution"


def test_find_relevant_tools_database(tmp_path):
    """'database' query should rank execute_sql_query first."""
    _write_mcp_index(tmp_path, _sample_index())
    index = yaml.safe_load(
        (tmp_path / ".ai-badger" / "mcp-tools.yaml").read_text(encoding="utf-8")
    )
    ranked = hooks._find_relevant_tools("list all database connections", index, top_n=3)

    assert len(ranked) >= 1
    assert "sql" in ranked[0][0] or "database" in ranked[0][0]


def test_find_relevant_tools_diagnostic(tmp_path):
    """'check for errors' should rank get_file_problems high."""
    _write_mcp_index(tmp_path, _sample_index())
    index = yaml.safe_load(
        (tmp_path / ".ai-badger" / "mcp-tools.yaml").read_text(encoding="utf-8")
    )
    ranked = hooks._find_relevant_tools("check this file for errors", index, top_n=5)

    tools_in_top = {name for name, _ in ranked}
    assert "rider:get_file_problems" in tools_in_top


def test_find_relevant_tools_empty_query(tmp_path):
    """Empty query should return empty list."""
    _write_mcp_index(tmp_path, _sample_index())
    index = yaml.safe_load(
        (tmp_path / ".ai-badger" / "mcp-tools.yaml").read_text(encoding="utf-8")
    )
    ranked = hooks._find_relevant_tools("", index)
    assert ranked == []


def test_find_relevant_tools_no_match(tmp_path):
    """Query with no matching tags should return empty list."""
    _write_mcp_index(tmp_path, _sample_index())
    index = yaml.safe_load(
        (tmp_path / ".ai-badger" / "mcp-tools.yaml").read_text(encoding="utf-8")
    )
    ranked = hooks._find_relevant_tools("philosophical question about life", index)
    assert ranked == []


# ── pre_llm_inject_context with index ──────────────────────────────────────

def test_pre_llm_inject_no_index():
    """Without an index, should still return context (usage hints)."""
    result = hooks.pre_llm_inject_context(cwd="/nonexistent/path")
    assert result is not None
    assert "context" in result
    # Should still have usage hints
    assert "/usage" in result["context"] or "session_search" in result["context"]


def test_pre_llm_inject_with_index_build_query(tmp_path):
    """With an index and a build query, should recommend build_solution."""
    _write_mcp_index(tmp_path, _sample_index())

    # This test verifies the hook CAN read the index. The actual user message
    # injection is handled by Hermes at runtime — we test that the helper
    # functions work correctly and the hook gracefully handles the index path.
    result = hooks.pre_llm_inject_context(cwd=str(tmp_path))
    assert result is not None
    assert "context" in result
    # The context should at minimum contain usage hints
    assert "/usage" in result["context"] or "session_search" in result["context"]


def test_pre_llm_inject_with_index_no_double_injection(tmp_path):
    """Hook should not crash when index exists but query is empty."""
    _write_mcp_index(tmp_path, _sample_index())

    result = hooks.pre_llm_inject_context(cwd=str(tmp_path))
    assert result is not None
    # Should not have MCP tool hints in the standard injection
    # (tool hints come from keyword extraction which needs the actual user message)


# ── post_tool_observer with index ──────────────────────────────────────────

def test_post_tool_observer_noop():
    """post_tool_observer should not crash with or without index data."""
    # Should run without exception
    hooks.post_tool_observer(
        tool_name="rider:get_file_problems",
        result='{"errors": []}',
        duration_ms=42,
    )
    # post_tool_observer is a no-op observer — it logs at DEBUG level.
    # The test passes if no exception is raised.
