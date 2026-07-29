"""Tests for features/common/retrieval/mcp_matcher.py.

Replaces the old `_KEYWORD_TAG_MAP` substring matcher: BM25 over name/tags/intent,
gated by coverage rather than an all-or-nothing tag lookup.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import pytest

SAMPLE_INDEX = {
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
                "execute_sql_query": {
                    "tags": ["database", "sql"],
                    "intent": "Run a SQL query against a database connection",
                },
                "search_symbol": {
                    "tags": ["semantic", "search", "csharp", "typescript"],
                    "intent": "Find a class, method, or field by name fragment",
                },
                "removed_tool": {
                    "tags": ["build"],
                    "intent": "A tool that no longer exists",
                    "status": "removed",
                },
            },
        },
    ],
}


@pytest.fixture
def mcp_matcher(load_script):
    return load_script("features/common/retrieval/mcp_matcher.py")


def test_build_query_ranks_build_solution_first(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("build the solution", SAMPLE_INDEX, threshold=0.0)
    assert results[0].tool == "rider:build_solution"


def test_removed_tools_are_excluded(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("build the solution", SAMPLE_INDEX, threshold=0.0)
    assert all(r.tool != "rider:removed_tool" for r in results)


def test_top_n_defaults_to_three(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("csharp", SAMPLE_INDEX, threshold=0.0)
    assert len(results) <= 3


def test_gate_returns_nothing_below_threshold(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("build the solution", SAMPLE_INDEX, threshold=1.1)
    assert results == []


def test_gate_requires_at_least_one_matched_term(mcp_matcher):
    results = mcp_matcher.find_relevant_tools(
        "philosophical question about life", SAMPLE_INDEX, threshold=0.0
    )
    assert results == []


def test_isolated_ts_token_does_not_match_typescript(mcp_matcher):
    """Pins the old bug at the matcher level: 'ts' is not 'typescript'."""
    results = mcp_matcher.find_relevant_tools("ts", SAMPLE_INDEX, threshold=0.0)
    assert results == []


def test_empty_index_returns_nothing(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("build", {"sources": []}, threshold=0.0)
    assert results == []


def test_empty_query_returns_nothing(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("", SAMPLE_INDEX, threshold=0.0)
    assert results == []


def test_default_threshold_still_admits_a_strong_match(mcp_matcher):
    results = mcp_matcher.find_relevant_tools("build the solution", SAMPLE_INDEX)
    assert any(r.tool == "rider:build_solution" for r in results)


def test_result_ordering_is_deterministic(mcp_matcher):
    first = [
        r.tool for r in
        mcp_matcher.find_relevant_tools("csharp diagnostic", SAMPLE_INDEX, threshold=0.0)
    ]
    second = [
        r.tool for r in
        mcp_matcher.find_relevant_tools("csharp diagnostic", SAMPLE_INDEX, threshold=0.0)
    ]
    assert first == second


def test_database_query_ranks_sql_tool_first(mcp_matcher):
    results = mcp_matcher.find_relevant_tools(
        "list all database connections", SAMPLE_INDEX, threshold=0.0
    )
    assert results[0].tool == "rider:execute_sql_query"


def test_diagnostic_query_finds_get_file_problems(mcp_matcher):
    results = mcp_matcher.find_relevant_tools(
        "check this file for errors", SAMPLE_INDEX, threshold=0.0
    )
    tools = {r.tool for r in results}
    assert "rider:get_file_problems" in tools
