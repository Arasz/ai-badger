"""Falsifiable accuracy gate for sentence-length queries (issue #165).

The sibling of tests/test_mcp_retrieval_quality.py, against the same real
.ai-badger/mcp-tools.json corpus but the long-query fixture set. It exists because that
suite's fixtures average 3.8 tokens and every bar in it stayed green while the gate
suppressed half of all sentence-length matches.

Bars sit with margin around measured performance at COVERAGE_TERM_CAP=6 / threshold 0.20
(recall@3=0.969, recall@1=0.938, false_fire=0.000, zero-result-on-positives=0/32). Before
the cap the same fixtures measured recall@3=0.469 with 16 of 32 positives returning nothing,
so every bar here can fail and did.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "mcp_queries_long.jsonl"
INDEX_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "eval_index.json"

RECALL_AT_3_MIN = 0.90
TOP_1_MIN = 0.85
FALSE_FIRE_MAX = 0.10


@pytest.fixture(scope="module")
def fixtures() -> list:
    lines = FIXTURES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(scope="module")
def index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def mcp_matcher(load_script):
    return load_script("features/common/retrieval/mcp_matcher.py")


def _run(mcp_matcher, index, fixtures):
    positives, negatives = [], []
    for fixture in fixtures:
        tools = [r.tool for r in mcp_matcher.find_relevant_tools(fixture["query"], index)]
        (positives if fixture["expect"] else negatives).append((fixture, tools))
    return positives, negatives


def test_recall_at_3(mcp_matcher, index, fixtures):
    positives, _ = _run(mcp_matcher, index, fixtures)
    hits = sum(1 for f, tools in positives if any(t in f["expect"] for t in tools))
    recall = hits / len(positives)
    assert recall >= RECALL_AT_3_MIN, f"recall@3={recall:.3f}"


def test_top_1(mcp_matcher, index, fixtures):
    positives, _ = _run(mcp_matcher, index, fixtures)
    hits = sum(1 for f, tools in positives if tools and tools[0] in f["expect"])
    top1 = hits / len(positives)
    assert top1 >= TOP_1_MIN, f"top1={top1:.3f}"


def test_false_fire_on_long_negatives(mcp_matcher, index, fixtures):
    """The half of #165 a naive fix breaks: recovering long positives must not start
    recommending tools to someone talking about their daughter's career plans."""
    _, negatives = _run(mcp_matcher, index, fixtures)
    fired = [(f["query"], tools) for f, tools in negatives if tools]
    rate = len(fired) / len(negatives)
    assert rate <= FALSE_FIRE_MAX, f"false_fire={rate:.3f}: {fired}"


def test_zero_result_on_positives_is_a_hard_fail(mcp_matcher, index, fixtures):
    """Issue #165's defining symptom: 16 of these 32 returned nothing before the cap."""
    positives, _ = _run(mcp_matcher, index, fixtures)
    empty = [f["query"] for f, tools in positives if not tools]
    assert empty == [], f"{len(empty)} positive quer(y/ies) returned nothing: {empty}"


def test_the_reported_screenshot_query_fires(mcp_matcher, index):
    """The exact query from the issue, which measured coverage 0.1435 against a 0.20 gate."""
    reported = (
        "I am working on the login flow and things look off in the browser, so before I "
        "change anything I want to take a screenshot of the page so I can compare it "
        "against the design later and share it with the team in the review"
    )
    results = mcp_matcher.find_relevant_tools(reported, index)
    assert results, "the issue's own reproduction still returns nothing"
    assert results[0].tool == "playwright:browser_take_screenshot"
    assert results[0].coverage >= mcp_matcher.DEFAULT_COVERAGE_THRESHOLD
