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


def test_top_n_defaults_to_exactly_three_given_more_qualifying_candidates(mcp_matcher):
    """`<= 3` is also satisfied by `TOP_N = 1`; pin the exact count with >=3 real qualifiers.

    Three tools in SAMPLE_INDEX carry the "csharp" tag (build_solution, get_file_problems,
    search_symbol) and none others do, so a single-term query for it clears the gate with
    exactly three candidates.
    """
    results = mcp_matcher.find_relevant_tools("csharp", SAMPLE_INDEX, threshold=0.0)
    assert len(results) == 3


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


def test_tags_only_match_outranks_intent_only_match(mcp_matcher):
    """ADR-0012: existing tool tags are not discarded, they become a weighted field.

    Both tools have symmetric name tokens and equal total document length (13 vs 13
    tokens once weighted) so length normalization cancels out; the only difference is
    which field carries "widget" — tags (TAGS_WEIGHT=2.0) vs intent (INTENT_WEIGHT=1.0).
    """
    index = {
        "sources": [{
            "name": "rider",
            "tools": {
                "alpha_tool": {
                    "tags": ["widget"],
                    "intent": "filler words here another",
                },
                "beta_tool": {
                    "tags": [],
                    "intent": "widget filler words here",
                },
            },
        }],
    }
    results = mcp_matcher.find_relevant_tools("widget", index, threshold=0.0)
    assert results[0].tool == "rider:alpha_tool"


def test_gate_admits_at_exact_threshold_boundary(mcp_matcher):
    """The gate is `coverage >= threshold`, not `>` — a result exactly at the boundary
    must still clear it. Computed from a real match rather than a hand-picked number, so
    it exercises the true boundary regardless of how the corpus changes."""
    baseline = mcp_matcher.find_relevant_tools("build the solution", SAMPLE_INDEX, threshold=0.0)
    exact = next(r for r in baseline if r.tool == "rider:build_solution")
    results = mcp_matcher.find_relevant_tools(
        "build the solution", SAMPLE_INDEX, threshold=exact.coverage
    )
    assert any(r.tool == "rider:build_solution" for r in results)


def test_result_score_and_coverage_are_populated(mcp_matcher):
    """Neither field is ever asserted elsewhere in this file — issue #148's own finding."""
    results = mcp_matcher.find_relevant_tools("build the solution", SAMPLE_INDEX, threshold=0.0)
    top = results[0]
    assert isinstance(top.score, float) and top.score > 0
    assert isinstance(top.coverage, float) and top.coverage > 0


def test_iter_tools_defaults_missing_sources_to_empty(mcp_matcher):
    assert not list(mcp_matcher._iter_tools({}))  # pylint: disable=protected-access


def test_iter_tools_defaults_missing_name_to_empty_string(mcp_matcher):
    index = {"sources": [{"tools": {"solo_tool": {"tags": [], "intent": "does a thing"}}}]}
    names = [full for full, _tags, _intent in mcp_matcher._iter_tools(index)]  # pylint: disable=protected-access
    assert names == [":solo_tool"]


def test_iter_tools_defaults_missing_tools_to_empty(mcp_matcher):
    index = {"sources": [{"name": "rider"}]}
    assert not list(mcp_matcher._iter_tools(index))  # pylint: disable=protected-access


def test_iter_tools_skips_only_the_removed_tool(mcp_matcher):
    """A `break` instead of `continue` on a removed tool would silently drop every tool
    that follows it in iteration order — put one after the removed entry to prove it."""
    index = {
        "sources": [{
            "name": "rider",
            "tools": {
                "before_removed": {"tags": [], "intent": "runs first"},
                "removed_tool": {"tags": [], "intent": "gone", "status": "removed"},
                "after_removed": {"tags": [], "intent": "runs last"},
            },
        }],
    }
    names = {full for full, _tags, _intent in mcp_matcher._iter_tools(index)}  # pylint: disable=protected-access
    assert names == {"rider:before_removed", "rider:after_removed"}


def test_iter_tools_defaults_missing_tags_to_empty_list(mcp_matcher):
    index = {"sources": [{"name": "rider", "tools": {"solo_tool": {"intent": "does a thing"}}}]}
    _full, tags, _intent = next(mcp_matcher._iter_tools(index))  # pylint: disable=protected-access
    assert tags == []


def test_iter_tools_defaults_missing_intent_to_empty_string(mcp_matcher):
    index = {"sources": [{"name": "rider", "tools": {"solo_tool": {"tags": []}}}]}
    _full, _tags, intent = next(mcp_matcher._iter_tools(index))  # pylint: disable=protected-access
    assert intent == ""


def test_name_match_outweighs_equivalent_intent_match(mcp_matcher):
    """A name-field hit (NAME_WEIGHT=3.0) must outrank an equal-length intent-field hit
    (INTENT_WEIGHT=1.0) — both tools have identical total document length (13 tokens
    weighted), so length normalization cancels and only NAME_WEIGHT can explain the order.
    """
    index = {
        "sources": [{
            "name": "rider",
            "tools": {
                "widget_tool": {
                    "tags": [],
                    "intent": "filler words here another",
                },
                "other_tool": {
                    "tags": [],
                    "intent": "widget filler words here",
                },
            },
        }],
    }
    results = mcp_matcher.find_relevant_tools("widget", index, threshold=0.0)
    assert results[0].tool == "rider:widget_tool"
