"""Tests for features/common/retrieval/context_enrichment.py.

Shared MCP-recommendation logic for the Claude/Copilot context-enrichment hook (issue #147):
index loading, near-miss scoring, and hint formatting — the same behavior
features/common/hooks/ai_badger_hooks.py already provides for Hermes, factored out so the new
hook does not have to duplicate it on top of mcp_matcher.py.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json

import pytest


@pytest.fixture
def ce(load_script):
    return load_script("features/common/retrieval/context_enrichment.py")


def _sample_index() -> dict:
    return {
        "sources": [
            {
                "name": "rider",
                "tools": {
                    "build_solution": {
                        "tags": ["build", "dotnet"],
                        "intent": "Compile the solution and return build errors",
                    },
                    "execute_sql_query": {
                        "tags": ["database", "sql"],
                        "intent": "Run a SQL query against a database connection",
                    },
                    "retired_tool": {
                        "tags": ["general"],
                        "intent": "no longer offered",
                        "status": "removed",
                    },
                },
            }
        ]
    }


def _write_index(project, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "mcp-tools.json").write_text(json.dumps(data), encoding="utf-8")


class TestLoadMcpIndex:
    def test_missing_cwd_returns_none(self, ce):
        assert ce.load_mcp_index(None) is None
        assert ce.load_mcp_index("") is None

    def test_no_index_file_returns_none(self, ce, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        assert ce.load_mcp_index(str(project)) is None

    def test_present_index_loads(self, ce, tmp_path):
        project = tmp_path / "proj"
        _write_index(project, _sample_index())
        loaded = ce.load_mcp_index(str(project))
        assert loaded["sources"][0]["name"] == "rider"

    def test_malformed_json_returns_none(self, ce, tmp_path):
        project = tmp_path / "proj"
        aib = project / ".ai-badger"
        aib.mkdir(parents=True)
        (aib / "mcp-tools.json").write_text("{not json", encoding="utf-8")
        assert ce.load_mcp_index(str(project)) is None


class TestLegacyDetection:
    def test_yaml_only_is_legacy(self, ce, tmp_path):
        project = tmp_path / "proj"
        aib = project / ".ai-badger"
        aib.mkdir(parents=True)
        (aib / "mcp-tools.yaml").write_text("sources: []\n", encoding="utf-8")
        assert ce.has_legacy_unmigrated_index(str(project)) is True

    def test_json_present_is_not_legacy_even_with_yaml_alongside(self, ce, tmp_path):
        project = tmp_path / "proj"
        _write_index(project, _sample_index())
        (project / ".ai-badger" / "mcp-tools.yaml").write_text("sources: []\n", encoding="utf-8")
        assert ce.has_legacy_unmigrated_index(str(project)) is False

    def test_nothing_at_all_is_not_legacy(self, ce, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        assert ce.has_legacy_unmigrated_index(str(project)) is False


class TestScoreAllToolsAndCounting:
    def test_score_all_tools_excludes_removed(self, ce):
        index = _sample_index()
        scored = ce.score_all_tools("build the solution", index)
        assert all(r.doc_id != "rider:retired_tool" for r in scored)

    def test_score_all_tools_empty_query_terms_returns_empty(self, ce):
        assert ce.score_all_tools("!!! ---", _sample_index()) == []

    def test_index_tool_count_excludes_removed(self, ce):
        assert ce.index_tool_count(_sample_index()) == 2

    def test_score_all_tools_reports_the_coverage_the_gate_actually_used(self, ce, load_script):
        """Near-miss telemetry that normalises differently from the gate would write a
        `gate` record asserting a comparison that never happened (issue #165, docs §6)."""
        matcher = load_script("features/common/retrieval/mcp_matcher.py")
        index = _sample_index()
        query = ("I pulled main this morning and there are new files everywhere, please "
                 "build the solution before I start on the ticket later today")

        scored = {r.doc_id: r.coverage for r in ce.score_all_tools(query, index)}
        gated = matcher.find_relevant_tools(query, index, threshold=0.0)

        for result in gated:
            assert scored[result.tool] == pytest.approx(result.coverage)


class TestFormatTopCandidates:
    def test_empty_scored_is_empty_string(self, ce):
        assert ce.format_top_candidates([]) == ""

    def test_includes_coverage_when_it_fits(self, ce):
        scored = ce.score_all_tools("build the solution", _sample_index())
        formatted = ce.format_top_candidates(scored)
        assert ":" in formatted
        # name:score:coverage — two colons per triple at minimum.
        assert formatted.count(":") >= 2


class TestTagsForDisplay:
    def test_known_tool_returns_its_tags(self, ce):
        assert ce.tags_for_display("rider:build_solution", _sample_index()) == ["build", "dotnet"]

    def test_unknown_tool_returns_empty(self, ce):
        assert ce.tags_for_display("rider:no_such_tool", _sample_index()) == []

    def test_name_without_colon_returns_empty(self, ce):
        assert ce.tags_for_display("not-a-qualified-name", _sample_index()) == []


class TestBuildHint:
    def test_hint_includes_tool_name_and_tags(self, ce):
        index = _sample_index()
        ranked = ce.find_relevant_tools("build the solution", index)
        hint = ce.build_hint(ranked, index)
        assert hint.startswith("[ai-badger] Relevant MCP tools:")
        assert "rider:build_solution" in hint
        assert "build" in hint

    def test_hint_falls_back_to_bare_names_when_over_budget(self, ce):
        index = {
            "sources": [{
                "name": "s",
                "tools": {
                    f"tool_{i}": {
                        "tags": ["a-very-long-tag-name-that-eats-the-budget"] * 5,
                        "intent": "an intent " * 10,
                    }
                    for i in range(3)
                },
            }]
        }
        ranked = [(f"s:tool_{i}", 1.0) for i in range(3)]
        hint = ce.build_hint(ranked, index, max_chars=60)
        assert len(hint) <= 60 or "(" not in hint
        assert "s:tool_0" in hint
