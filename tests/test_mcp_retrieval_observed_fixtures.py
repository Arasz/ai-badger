"""Structural checks on the observed MCP eval fixture set (issues #221, #140).

`features/common/retrieval/eval/mcp_queries_observed.jsonl` is the first fixture set drawn from
telemetry rather than written by hand, so it is the only one free of the bias #140 names: the
other three were invented by the person who also wrote the descriptions being matched.

Like the hard and long sets it is an instrument, not a gate — nothing here asserts a recall bar.
The one number it *does* pin is the count of conversational turns the matcher answers, because
that count is the defect #221 is about and a fixture set that let it drift silently would be
worth nothing. See docs/retrieval.md §5 for what the runner measures against this file.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "mcp_queries_observed.jsonl"
INDEX_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "eval_index.json"

VALID_CLASSES = {"observed-request", "observed-conversational"}

# Both were produced by the shipped matcher against prompts actually typed (#221). They are the
# evidence this file exists to carry, so they are named here: a cleanup that drops them should
# have to delete a test that says why they matter.
KNOWN_FALSE_POSITIVES = ("lets wait with #170 for now", "/auto-wm away 8h")


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


def _all_tool_names(index: dict) -> set:
    return {f"{server['name']}:{tool}"
            for server in index.get("sources", [])
            for tool in server.get("tools", {})}


# ── structural checks ────────────────────────────────────────────────────────

def test_every_fixture_has_a_valid_class(fixtures):
    for fixture in fixtures:
        assert fixture.get("class") in VALID_CLASSES, fixture


def test_every_expected_tool_exists_in_the_index(fixtures, index):
    """A fixture naming a tool the index does not carry measures nothing."""
    known = _all_tool_names(index)
    for fixture in fixtures:
        for tool in fixture["expect"]:
            assert tool in known, f"{tool} is not in the index ({fixture['query']!r})"


def test_a_conversational_turn_always_expects_silence(fixtures):
    """The class is the claim: a turn addressed to the agent is not a request for a tool."""
    for fixture in fixtures:
        if fixture["class"] == "observed-conversational":
            assert fixture["expect"] == [], fixture


def test_both_observed_false_positives_are_carried_as_negatives(fixtures):
    """#221's evidence: these need no labelling judgement, because silence is the right answer."""
    conversational = {f["query"] for f in fixtures if f["class"] == "observed-conversational"}

    for query in KNOWN_FALSE_POSITIVES:
        assert query in conversational, f"{query!r} is the defect this set exists to record"


# ── the measurement ──────────────────────────────────────────────────────────

def test_the_runner_produces_a_report_without_crashing(fixtures, index, retrieval_eval):
    report = retrieval_eval.evaluate(fixtures, index)

    assert report.n == len(fixtures)
    assert report.n_negative > 0, "the whole point of this set is its negatives"


def test_the_matcher_still_answers_exactly_two_conversational_turns(
        fixtures, index, retrieval_eval):
    """Pinned so it can fail in both directions — the standing rule for this matcher (#140).

    Not a bar the matcher passes: 2 is a defect, recorded at its measured size. A change that
    fixes it must lower this number deliberately, and one that makes it worse cannot land quietly.
    """
    report = retrieval_eval.evaluate(fixtures, index)
    fired = sorted(row.query for row in report.negatives if row.fired)

    assert fired == sorted(KNOWN_FALSE_POSITIVES), (
        f"observed false positives changed: {fired}. If the matcher improved, update "
        f"KNOWN_FALSE_POSITIVES and docs/retrieval.md §5 in the same commit."
    )


def test_no_conversational_turn_over_four_tokens_is_answered(fixtures, index, retrieval_eval):
    """Both false positives are short. Nothing longer fires — the one lead worth measuring."""
    report = retrieval_eval.evaluate(fixtures, index)
    long_fires = [row.query for row in report.negatives if row.fired and row.tokens > 4]

    assert long_fires == [], f"a longer conversational turn now fires too: {long_fires}"
