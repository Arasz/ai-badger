"""Structural checks on the long-query MCP eval fixture set (issue #165).

`features/common/retrieval/eval/mcp_queries_long.jsonl` exists because both older sets are
keyword-shaped — mean 3.8 and 4.8 tokens — and a coverage gate whose denominator runs over
every query term cannot be seen to fail on queries that short. The one property this set
claims is length, so length is what this suite enforces mechanically: every query is at
least LENGTH_FLOOR tokens after the matcher's own tokenizer, and the set's mean sits in the
band a real user message occupies. No recall or false-fire bar is asserted here; see
docs/retrieval.md §4 and tooling/retrieval_eval.py for what is measured.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "mcp_queries_long.jsonl"
INDEX_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "eval_index.json"

VALID_CLASSES = {"embedded-request", "narrative-negative", "adjacent-negative"}
NEGATIVE_CLASSES = {"narrative-negative", "adjacent-negative"}
LENGTH_FLOOR = 10
MEAN_LENGTH_BAND = (10.0, 20.0)
MIN_NEGATIVE_FRACTION = 0.25


def _load_fixtures() -> list:
    lines = FIXTURES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(scope="module")
def fixtures() -> list:
    return _load_fixtures()


@pytest.fixture(scope="module")
def index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def retrieval_eval(load_script):
    return load_script("tooling/retrieval_eval.py")


@pytest.fixture
def tokenize(load_script):
    return load_script("features/common/retrieval/tokenizer.py").tokenize


def _all_tool_names(index: dict) -> set:
    names = set()
    for server in index.get("sources", []):
        for tname in server.get("tools", {}):
            names.add(f"{server['name']}:{tname}")
    return names


def _lengths(fixtures: list, tokenize) -> list:
    return [len(tokenize(f["query"])) for f in fixtures]


# ── structural checks ────────────────────────────────────────────────────────

def test_every_fixture_has_a_valid_class(fixtures):
    for fixture in fixtures:
        assert fixture.get("class") in VALID_CLASSES, fixture


def test_every_class_is_represented(fixtures):
    assert {f["class"] for f in fixtures} == VALID_CLASSES


def test_every_expected_tool_exists_in_the_real_index(fixtures, index):
    known = _all_tool_names(index)
    for fixture in fixtures:
        for tool in fixture["expect"]:
            assert tool in known, f"{tool!r} (query: {fixture['query']!r}) is not in the index"


def test_negative_classes_have_an_empty_expect(fixtures):
    for fixture in fixtures:
        if fixture["class"] in NEGATIVE_CLASSES:
            assert fixture["expect"] == [], fixture


def test_positive_class_has_a_nonempty_expect(fixtures):
    for fixture in fixtures:
        if fixture["class"] == "embedded-request":
            assert fixture["expect"], fixture


def test_no_duplicate_queries(fixtures):
    queries = [f["query"] for f in fixtures]
    assert len(queries) == len(set(queries))


def test_at_least_a_quarter_of_the_set_is_negative(fixtures):
    negatives = [f for f in fixtures if not f["expect"]]
    assert len(negatives) / len(fixtures) >= MIN_NEGATIVE_FRACTION


# ── the mechanically-enforced length invariant ───────────────────────────────

def test_every_query_clears_the_length_floor(fixtures, tokenize):
    """The set's whole reason to exist: a short query here would silently weaken it."""
    lengths = _lengths(fixtures, tokenize)
    short = [(f["query"], n) for f, n in zip(fixtures, lengths) if n < LENGTH_FLOOR]
    assert short == [], short


def test_mean_query_length_sits_in_the_target_band(fixtures, tokenize):
    mean = statistics.mean(_lengths(fixtures, tokenize))
    low, high = MEAN_LENGTH_BAND
    assert low <= mean <= high, f"mean={mean:.2f}"


def test_negatives_are_as_long_as_the_positives(fixtures, tokenize):
    """A negative set that is shorter than the positive one would make the gate look
    better on length than it is — the two means must sit within two tokens."""
    lengths = dict(zip((f["query"] for f in fixtures), _lengths(fixtures, tokenize)))
    positives = [lengths[f["query"]] for f in fixtures if f["expect"]]
    negatives = [lengths[f["query"]] for f in fixtures if not f["expect"]]
    assert abs(statistics.mean(positives) - statistics.mean(negatives)) <= 2.0


# ── the runner can actually be pointed at this file ──────────────────────────

def test_the_runner_produces_a_report_without_crashing(fixtures, index, retrieval_eval):
    report = retrieval_eval.evaluate(fixtures, index)
    assert report.n == len(fixtures)
    assert set(report.by_class) == VALID_CLASSES
