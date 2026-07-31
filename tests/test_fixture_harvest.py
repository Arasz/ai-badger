"""Tests for tooling/fixture_harvest.py (issue #140): telemetry records to candidate fixtures.

Synthetic audit records only — the real log is machine-local and may be redacted; the whole
point of the harvester is to behave honestly in both cases.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import hashlib
import json

import pytest


@pytest.fixture
def harvester(load_script):
    return load_script("tooling/fixture_harvest.py")


COMPONENT = "ai_badger_hooks/mcp_retrieval"


def _record(event="hit", query="take a screenshot of the page", returned="", project=None,
            component=COMPONENT, **extra):
    rec = {"t": "2026-07-30T10:00:00+00:00", "c": component, "e": event, "v": "0.53.0"}
    if query is not None:
        rec["q"] = query
    if returned:
        rec["r"] = returned
    if project:
        rec["p"] = project
    rec.update(extra)
    return rec


def _write_log(tmp_path, records):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


# ── load_records ─────────────────────────────────────────────────────────────

def test_load_records_parses_one_json_object_per_line(harvester, tmp_path):
    path = _write_log(tmp_path, [_record(), _record(event="gate")])
    assert len(harvester.load_records(path)) == 2


def test_load_records_skips_unparseable_lines(harvester, tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('not json\n' + json.dumps(_record()) + '\n', encoding="utf-8")
    assert len(harvester.load_records(path)) == 1


# ── classification ───────────────────────────────────────────────────────────

def test_non_retrieval_components_are_counted_but_never_harvested(harvester):
    result = harvester.harvest([_record(component="commit_reminder_hook")], "2026-07-30")
    assert result.total == 1
    assert result.retrieval == 0
    assert result.candidates == []


def test_tool_check_events_are_counted_but_never_candidates(harvester):
    records = [_record(event=e, query=None, l="rider:build_solution")
               for e in ("known", "unknown", "server_unindexed")]
    result = harvester.harvest(records, "2026-07-30")
    assert result.tool_checks == 3
    assert result.candidates == []


def test_redacted_record_counts_as_redacted_and_yields_no_candidate(harvester):
    result = harvester.harvest([_record(query=None)], "2026-07-30")
    assert result.redacted == 1
    assert result.candidates == []


def test_query_clipped_at_the_field_cap_is_not_harvestable(harvester):
    result = harvester.harvest([_record(query="x" * 200)], "2026-07-30")
    assert result.clipped == 1
    assert result.candidates == []


def test_machine_shaped_query_is_not_harvestable(harvester):
    result = harvester.harvest(
        [_record(query="<task-notification> <task-id>abc</task-id>")], "2026-07-30")
    assert result.machine == 1
    assert result.candidates == []


def test_duplicate_queries_collapse_into_one_candidate_with_a_count(harvester):
    result = harvester.harvest([_record(), _record()], "2026-07-30")
    assert len(result.candidates) == 1
    assert result.candidates[0]["seen"] == 2


# ── candidates are candidates, not truth ─────────────────────────────────────

def test_candidate_carries_the_observed_outcome_but_never_an_expectation(harvester):
    result = harvester.harvest(
        [_record(returned="playwright:browser_take_screenshot")], "2026-07-30")
    candidate = result.candidates[0]
    assert "expect" not in candidate
    assert candidate["observed"]["event"] == "hit"
    assert candidate["observed"]["returned"] == ["playwright:browser_take_screenshot"]


def test_gate_record_observed_returned_is_an_empty_list(harvester):
    result = harvester.harvest([_record(event="gate", query="hi there friend")], "2026-07-30")
    assert result.candidates[0]["observed"] == {"event": "gate", "returned": []}


def test_returned_field_with_several_tools_parses_into_a_list(harvester):
    result = harvester.harvest(
        [_record(returned="rider:search_regex, rider:search_file")], "2026-07-30")
    assert result.candidates[0]["observed"]["returned"] == [
        "rider:search_regex", "rider:search_file"]


# ── provenance ───────────────────────────────────────────────────────────────

def test_candidate_provenance_names_telemetry_and_the_harvest_date(harvester):
    result = harvester.harvest([_record()], "2026-07-30")
    candidate = result.candidates[0]
    assert candidate["source"] == "telemetry"
    assert candidate["harvested"] == "2026-07-30"


def test_candidate_project_is_a_short_hash_never_the_path(harvester):
    path = "/Users/someone/RiderProjects/secret-client-repo"
    result = harvester.harvest([_record(project=path)], "2026-07-30")
    expected = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
    assert result.candidates[0]["project"] == expected
    assert path not in json.dumps(result.candidates)


def test_candidate_without_a_project_field_carries_none(harvester):
    result = harvester.harvest([_record()], "2026-07-30")
    assert result.candidates[0]["project"] is None


# ── query text stays out of output unless explicitly asked for ───────────────

def test_render_without_include_queries_replaces_text_with_its_sha256(harvester):
    result = harvester.harvest([_record()], "2026-07-30")
    rendered = harvester.render_candidates(result.candidates, include_queries=False)
    assert "query" not in rendered[0]
    digest = hashlib.sha256("take a screenshot of the page".encode("utf-8")).hexdigest()
    assert rendered[0]["query_sha256"] == digest


def test_render_with_include_queries_keeps_the_text(harvester):
    result = harvester.harvest([_record()], "2026-07-30")
    rendered = harvester.render_candidates(result.candidates, include_queries=True)
    assert rendered[0]["query"] == "take a screenshot of the page"


# ── honest reporting ─────────────────────────────────────────────────────────

def test_report_on_a_fully_redacted_log_says_how_to_enable_unredacted_logging(harvester):
    result = harvester.harvest([_record(query=None), _record(query=None)], "2026-07-30")
    report = harvester.format_report(result, "some/audit.jsonl")
    assert "AI_BADGER_DEBUG_REDACT" in report
    assert "behaviorist" in report


def test_report_counts_every_bucket(harvester):
    records = [_record(), _record(query=None), _record(query="x" * 200),
               _record(query="<tag>"), _record(component="other")]
    report = harvester.format_report(harvester.harvest(records, "2026-07-30"), "log")
    for needle in ("5", "redacted", "clipped", "machine", "harvestable"):
        assert needle in report


# ── main ─────────────────────────────────────────────────────────────────────

def test_main_exits_nonzero_when_the_log_is_missing(harvester, tmp_path, capsys):
    assert harvester.main(["--log", str(tmp_path / "missing.jsonl")]) == 1
    assert "not found" in capsys.readouterr().out


def test_main_writes_candidates_jsonl_with_include_queries(harvester, tmp_path, capsys):
    log = _write_log(tmp_path, [_record(returned="playwright:browser_take_screenshot")])
    out = tmp_path / "candidates.jsonl"
    assert harvester.main(
        ["--log", str(log), "--out", str(out), "--include-queries"]) == 0
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[0]["query"] == "take a screenshot of the page"
    assert lines[0]["source"] == "telemetry"
    assert "candidates" in capsys.readouterr().out


def test_main_without_include_queries_writes_no_query_text(harvester, tmp_path):
    log = _write_log(tmp_path, [_record()])
    out = tmp_path / "candidates.jsonl"
    assert harvester.main(["--log", str(log), "--out", str(out)]) == 0
    assert "take a screenshot" not in out.read_text(encoding="utf-8")
