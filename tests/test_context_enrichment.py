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
from conftest import _test_write


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
    _test_write(aib / "mcp-tools.json", json.dumps(data), encoding="utf-8")


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
        _test_write(aib / "mcp-tools.json", "{not json", encoding="utf-8")
        assert ce.load_mcp_index(str(project)) is None


class TestLegacyDetection:
    def test_yaml_only_is_legacy(self, ce, tmp_path):
        project = tmp_path / "proj"
        aib = project / ".ai-badger"
        aib.mkdir(parents=True)
        _test_write(aib / "mcp-tools.yaml", "sources: []\n", encoding="utf-8")
        assert ce.has_legacy_unmigrated_index(str(project)) is True

    def test_json_present_is_not_legacy_even_with_yaml_alongside(self, ce, tmp_path):
        project = tmp_path / "proj"
        _write_index(project, _sample_index())
        _test_write(project / ".ai-badger" / "mcp-tools.yaml", "sources: []\n", encoding="utf-8")
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


class TestSemanticaNudgeHelpers:
    def test_semantica_indexed_matches_bare_and_decorated(self, ce):
        assert ce.semantica_indexed({"sources": [{"name": "semantica"}]}) is True
        assert ce.semantica_indexed({"sources": [{"name": "plugin:semantica:semantica"}]}) is True
        assert ce.semantica_indexed({"sources": [{"name": "semantica-fork"}]}) is False
        assert ce.semantica_indexed({"sources": []}) is False
        assert ce.semantica_indexed(None) is False
        assert ce.semantica_indexed({}) is False

    def test_semantica_nudge_marker_path_sanitizes_and_handles_empty(self, ce, tmp_path):
        assert ce.semantica_nudge_marker_path(None) == ce.Path("")
        assert ce.semantica_nudge_marker_path("") == ce.Path("")
        # All non-alphanumeric, non-dot/dash/underscore chars become '_'
        path = ce.semantica_nudge_marker_path("sess/1\\2:3", base_dir=tmp_path)
        assert path == tmp_path / "sess_1_2_3"
        # Traversal dot-segments are guarded
        assert ce.semantica_nudge_marker_path(".", base_dir=tmp_path) == tmp_path / "_"
        assert ce.semantica_nudge_marker_path("..", base_dir=tmp_path) == tmp_path / "__"

    def test_semantica_nudge_record_and_check(self, ce, tmp_path):
        assert ce.semantica_nudge_already_shown("sess-1", base_dir=tmp_path) is False
        assert ce.record_semantica_nudge_shown("sess-1", base_dir=tmp_path) is True
        assert (tmp_path / "sess-1").is_file()
        assert ce.semantica_nudge_already_shown("sess-1", base_dir=tmp_path) is True

        # Missing or empty session_id safely returns False without raising
        assert ce.record_semantica_nudge_shown(None, base_dir=tmp_path) is False
        assert ce.record_semantica_nudge_shown("", base_dir=tmp_path) is False
        assert ce.semantica_nudge_already_shown(None, base_dir=tmp_path) is False
        assert ce.semantica_nudge_already_shown("", base_dir=tmp_path) is False

    def test_nudge_line_matches_contract(self, ce):
        assert "[ai-badger] Semantica is configured:" in ce.NUDGE_LINE
        assert "record_decision" in ce.NUDGE_LINE

    def test_the_nudge_does_not_instruct_a_call_that_always_fails(self, ce):
        """export_graph errors in every format on semantica 0.6.6.

        This line is injected on every prompt of every session, so instructing the
        call means instructing a guaranteed failure. Measured in
        docs/work/2026-08-28-semantica-support-research.md (F3, F6).
        """
        assert "export_graph" not in ce.NUDGE_LINE

    def test_every_nudge_definition_agrees(self):
        """All NUDGE_LINE definitions under features/ carry identical text.

        Derived, not hardcoded to a known pair: the copies exist because the files
        are delivered to different destinations and cannot import one another, so
        the list is discovered by scanning rather than maintained by hand.
        """
        import ast
        from pathlib import Path as _Path
        root = _Path(__file__).resolve().parent.parent
        found = {}
        for path in (root / "features").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "NUDGE_LINE" not in names:
                    continue
                value = ast.literal_eval(node.value)
                found[str(path.relative_to(root))] = value
        assert len(found) >= 2, f"expected several definitions, found {list(found)}"
        assert len(set(found.values())) == 1, (
            "NUDGE_LINE definitions have drifted:\n"
            + "\n".join(f"  {k}: {v!r}" for k, v in found.items())
        )