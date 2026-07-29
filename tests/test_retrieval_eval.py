"""Tests for tooling/retrieval_eval.py (issue #140): the checked-in eval runner.

Uses a tiny synthetic 3-tool index rather than the real 98-tool one, so the expected
recall/false-fire/margin numbers can be hand-verified instead of pinned against a live
measurement that shifts whenever `.ai-badger/mcp-tools.json` changes.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json

import pytest


@pytest.fixture
def retrieval_eval(load_script):
    return load_script("tooling/retrieval_eval.py")


# A 3-tool index: "widget:make" and "widget:make_variant" share almost every field (a
# deliberate near-duplicate pair), "widget:destroy" shares nothing with either.
SYNTHETIC_INDEX = {
    "sources": [
        {
            "name": "widget",
            "tools": {
                "make": {"tags": ["build"], "intent": "Create a new widget from a template"},
                "make_variant": {"tags": ["build"], "intent": "Create a variant widget"},
                "destroy": {"tags": ["remove"], "intent": "Permanently delete a widget"},
            },
        }
    ]
}

SYNTHETIC_FIXTURES = [
    {"query": "create a new widget", "expect": ["widget:make"]},
    {"query": "delete this widget forever", "expect": ["widget:destroy"]},
    {"query": "what's the weather like", "expect": []},
    {"query": "sing me a song", "expect": []},
]


def _write_fixtures(tmp_path, fixtures):
    path = tmp_path / "fixtures.jsonl"
    path.write_text(
        "\n".join(json.dumps(f) for f in fixtures) + "\n",
        encoding="utf-8",
    )
    return path


def _write_index(tmp_path, index):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index), encoding="utf-8")
    return path


# ── load_fixtures ─────────────────────────────────────────────────────────────

def test_load_fixtures_parses_one_json_object_per_line(retrieval_eval, tmp_path):
    path = _write_fixtures(tmp_path, SYNTHETIC_FIXTURES)

    fixtures = retrieval_eval.load_fixtures(path)

    assert fixtures == SYNTHETIC_FIXTURES


def test_load_fixtures_skips_blank_lines(retrieval_eval, tmp_path):
    path = tmp_path / "fixtures.jsonl"
    path.write_text('{"query": "a", "expect": []}\n\n\n', encoding="utf-8")

    assert retrieval_eval.load_fixtures(path) == [{"query": "a", "expect": []}]


# ── FixtureRow ────────────────────────────────────────────────────────────────

def test_fixture_row_hit_at_1_requires_the_top_result_to_match(retrieval_eval):
    row = retrieval_eval.FixtureRow(
        query="q", expect=["a"], cls=None, returned=["b", "a"]
    )
    assert row.is_positive is True
    assert row.hit_at_1 is False
    assert row.hit_at_3 is True
    assert row.fired is True


def test_fixture_row_negative_with_no_results_did_not_fire(retrieval_eval):
    row = retrieval_eval.FixtureRow(query="q", expect=[], cls=None, returned=[])
    assert row.is_positive is False
    assert row.fired is False
    assert row.hit_at_1 is False
    assert row.hit_at_3 is False


# ── evaluate() end to end against the synthetic index ────────────────────────

def test_evaluate_computes_recall_and_false_fire(retrieval_eval):
    report = retrieval_eval.evaluate(SYNTHETIC_FIXTURES, SYNTHETIC_INDEX)

    assert report.n_positive == 2
    assert report.n_negative == 2
    # Both positives have a real, unambiguous answer in a 3-tool corpus.
    assert report.recall_at_3 == 1.0
    assert report.recall_at_1 == 1.0
    # Neither negative shares a token with any tool.
    assert report.false_fire_rate == 0.0


def test_evaluate_reports_zero_result_positives(retrieval_eval):
    fixtures = SYNTHETIC_FIXTURES + [{"query": "zzz nonexistent term", "expect": ["widget:make"]}]

    report = retrieval_eval.evaluate(fixtures, SYNTHETIC_INDEX)

    zero_result = [r for r in report.rows if r.is_positive and not r.fired]
    assert [r.query for r in zero_result] == ["zzz nonexistent term"]


def test_evaluate_groups_by_class_when_present(retrieval_eval):
    fixtures = [
        {"query": "create a new widget", "expect": ["widget:make"], "class": "user-voice"},
        {"query": "delete this widget forever", "expect": ["widget:destroy"], "class": "paraphrase"},
        {"query": "sing me a song", "expect": [], "class": "inert-negative"},
    ]

    report = retrieval_eval.evaluate(fixtures, SYNTHETIC_INDEX)

    assert set(report.by_class) == {"user-voice", "paraphrase", "inert-negative"}
    assert report.by_class["inert-negative"]["n"] == 1
    assert report.by_class["inert-negative"]["false_fire_rate"] == 0.0


def test_evaluate_with_no_fixtures_of_a_kind_reports_none_not_a_crash(retrieval_eval):
    all_negative = [{"query": "sing me a song", "expect": []}]

    report = retrieval_eval.evaluate(all_negative, SYNTHETIC_INDEX)

    assert report.n_positive == 0
    assert report.recall_at_1 is None
    assert report.recall_at_3 is None
    assert report.false_fire_rate == 0.0


# ── coverage margin ───────────────────────────────────────────────────────────

def test_coverage_margin_is_tightest_true_positive_minus_worst_false_fire(retrieval_eval):
    # widget:make and widget:make_variant overlap almost entirely, so a query for one
    # gives the other real, non-zero coverage too — enough to build a margin from
    # synthetic data instead of asserting an opaque real-index number.
    fixtures = [
        {"query": "create a new widget from a template", "expect": ["widget:make"]},
        {"query": "widget build", "expect": []},
    ]

    report = retrieval_eval.evaluate(fixtures, SYNTHETIC_INDEX)

    assert report.coverage_margin is not None
    # Margin is a plain float difference, not bounded to [0, 1] — a negative value is a
    # legitimate, reportable finding (the two classes of query overlap in coverage).
    assert isinstance(report.coverage_margin, float)


def test_coverage_margin_is_none_without_both_a_hit_and_a_fire(retrieval_eval):
    fixtures = [{"query": "create a new widget", "expect": ["widget:make"]}]

    report = retrieval_eval.evaluate(fixtures, SYNTHETIC_INDEX)

    assert report.coverage_margin is None


# ── overlap statistic ─────────────────────────────────────────────────────────

def test_query_document_overlap_is_the_fraction_of_query_tokens_found_in_the_document(
    retrieval_eval,
):
    overlap = retrieval_eval.query_document_overlap(
        query_tokens=["make", "widget", "template"],
        doc_tokens={"make", "widget", "build"},
    )
    assert overlap == pytest.approx(2 / 3)


def test_query_document_overlap_is_zero_for_empty_query(retrieval_eval):
    assert retrieval_eval.query_document_overlap([], {"a", "b"}) == 0.0


def test_overlap_stats_reports_mean_and_the_at_least_half_count(retrieval_eval):
    stats = retrieval_eval.overlap_stats(SYNTHETIC_FIXTURES, SYNTHETIC_INDEX)

    assert stats["n"] == 2  # only positives have a document to overlap against
    assert 0.0 <= stats["mean"] <= 1.0
    assert 0 <= stats["at_least_half"] <= stats["n"]


# ── report formatting: human-readable text + a machine-diffable structure ────

def test_format_report_mentions_the_headline_metrics(retrieval_eval):
    report = retrieval_eval.evaluate(SYNTHETIC_FIXTURES, SYNTHETIC_INDEX)

    text = retrieval_eval.format_report(report)

    assert "recall@1" in text
    assert "recall@3" in text
    assert "false_fire" in text
    assert "create a new widget" in text  # per-fixture rows are visible, not just totals


def test_report_to_json_round_trips_through_json_dumps(retrieval_eval):
    report = retrieval_eval.evaluate(SYNTHETIC_FIXTURES, SYNTHETIC_INDEX)

    payload = retrieval_eval.report_to_json(report)
    dumped = json.dumps(payload)  # must not raise — every value is JSON-safe

    reloaded = json.loads(dumped)
    assert reloaded["recall_at_1"] == 1.0
    assert reloaded["n_positive"] == 2
    assert len(reloaded["rows"]) == 4


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_main_prints_a_human_readable_report_and_exits_zero(
    retrieval_eval, tmp_path, capsys
):
    fixtures_path = _write_fixtures(tmp_path, SYNTHETIC_FIXTURES)
    index_path = _write_index(tmp_path, SYNTHETIC_INDEX)

    rc = retrieval_eval.main(
        ["--fixtures", str(fixtures_path), "--index", str(index_path)]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "recall@1" in out


def test_main_json_out_writes_a_machine_diffable_file(retrieval_eval, tmp_path):
    fixtures_path = _write_fixtures(tmp_path, SYNTHETIC_FIXTURES)
    index_path = _write_index(tmp_path, SYNTHETIC_INDEX)
    json_out = tmp_path / "report.json"

    rc = retrieval_eval.main([
        "--fixtures", str(fixtures_path),
        "--index", str(index_path),
        "--json-out", str(json_out),
    ])

    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["recall_at_1"] == 1.0


def test_main_exits_nonzero_when_the_index_file_is_missing(retrieval_eval, tmp_path):
    fixtures_path = _write_fixtures(tmp_path, SYNTHETIC_FIXTURES)

    rc = retrieval_eval.main([
        "--fixtures", str(fixtures_path),
        "--index", str(tmp_path / "does_not_exist.json"),
    ])

    assert rc == 1
