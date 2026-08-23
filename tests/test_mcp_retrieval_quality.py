"""Falsifiable accuracy gate for the MCP BM25 matcher (docs/adr/0012).

Runs features/common/retrieval/mcp_matcher.py against the real
.ai-badger/mcp-tools.json corpus in this repo and a hand-authored fixture set,
features/common/retrieval/eval/mcp_queries.jsonl. `expect: []` is a first-class
negative fixture: the assertion is that the gate fires and nothing comes back.

ADR-0004's "100% accuracy on a 16-query spike suite" cites a script in another
repo that cannot be run and cannot fail. This harness is what corrects that: it
runs in this repo, under `pytest`, and every bar below can fail.

Bars sit with margin around measured performance on this fixture set
(recall@3=1.000, top1=0.907, false_fire=0.267, zero_on_positive=0/43) rather
than at the skill-index spec's own numbers, which were derived on a different,
13-document corpus — copying them here would repeat exactly the mistake the
task calls out for the coverage threshold itself.

This suite is coupled to the live `.ai-badger/mcp-tools.json` in this repo, not a frozen
fixture: adding or removing an MCP server shifts all four metrics (the corpus size changes
every IDF), and false-fire (0.267 measured against a 0.30 bar) has the least headroom of
the four — the first one worth checking if this suite starts failing after an index change.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "mcp_queries.jsonl"
INDEX_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "eval_index.json"

RECALL_AT_3_MIN = 0.90
TOP_1_MIN = 0.75
FALSE_FIRE_MAX = 0.30
MIN_NEGATIVE_FRACTION = 0.25


def _load_fixtures() -> list[dict]:
    lines = FIXTURES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _load_index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixtures() -> list[dict]:
    return _load_fixtures()


@pytest.fixture(scope="module")
def index() -> dict:
    return _load_index()


@pytest.fixture
def mcp_matcher(load_script):
    return load_script("features/common/retrieval/mcp_matcher.py")


def _all_tool_names(index: dict) -> set[str]:
    names = set()
    for server in index.get("sources", []):
        for tname in server.get("tools", {}):
            names.add(f"{server['name']}:{tname}")
    return names


# ── structural checks on the fixture file itself ────────────────────────────

def test_fixtures_are_at_least_25_percent_negative(fixtures):
    negatives = [f for f in fixtures if not f["expect"]]
    assert len(negatives) / len(fixtures) >= MIN_NEGATIVE_FRACTION


def test_every_expected_tool_exists_in_the_real_index(fixtures, index):
    known = _all_tool_names(index)
    for fixture in fixtures:
        for tool in fixture["expect"]:
            assert tool in known, f"{tool!r} (query: {fixture['query']!r}) is not in the index"


def test_fixtures_have_at_least_one_positive(fixtures):
    assert any(f["expect"] for f in fixtures)


# ── known-duplicate-tool annotation defects (issue #140) ────────────────────
#
# rider:search_regex and rider:search_in_files_by_regex are the same capability exposed
# twice by the rider MCP server. A fixture whose expect names only one of them is a
# single-answer annotation on a two-answer question — the matcher is not wrong when it
# picks the other one, the fixture is. Each entry below is a pair the corpus makes
# genuinely interchangeable; any fixture matching one member must accept both.
DUPLICATE_TOOL_PAIRS = [
    frozenset({"rider:search_regex", "rider:search_in_files_by_regex"}),
]


def test_known_duplicate_tools_are_annotated_together(fixtures):
    for fixture in fixtures:
        expect = set(fixture["expect"])
        for pair in DUPLICATE_TOOL_PAIRS:
            if expect & pair and not pair <= expect:
                raise AssertionError(
                    f"query {fixture['query']!r} expects {sorted(expect)!r}, a subset of "
                    f"the duplicate pair {sorted(pair)!r} — annotate both or neither"
                )


# ── the four gated metrics ───────────────────────────────────────────────────

def _run(mcp_matcher, index, fixtures):
    """Return (positives, negatives) each as list of (fixture, [tool, ...])."""
    positives, negatives = [], []
    for fixture in fixtures:
        results = mcp_matcher.find_relevant_tools(fixture["query"], index)
        tools = [r.tool for r in results]
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


def test_false_fire_on_negatives(mcp_matcher, index, fixtures):
    _, negatives = _run(mcp_matcher, index, fixtures)
    fires = sum(1 for _, tools in negatives if tools)
    rate = fires / len(negatives)
    assert rate <= FALSE_FIRE_MAX, f"false_fire={rate:.3f}"


def test_zero_result_on_positives_is_a_hard_fail(mcp_matcher, index, fixtures):
    """The current matcher's defining bug: a positive query must never return nothing."""
    positives, _ = _run(mcp_matcher, index, fixtures)
    empty = [f["query"] for f, tools in positives if not tools]
    assert empty == [], f"{len(empty)} positive quer(y/ies) returned nothing: {empty}"


def test_ranking_is_deterministic_across_two_runs(mcp_matcher, index, fixtures):
    first = [
        [r.tool for r in mcp_matcher.find_relevant_tools(f["query"], index)]
        for f in fixtures
    ]
    second = [
        [r.tool for r in mcp_matcher.find_relevant_tools(f["query"], index)]
        for f in fixtures
    ]
    assert first == second
