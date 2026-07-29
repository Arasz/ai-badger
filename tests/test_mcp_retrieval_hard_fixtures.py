"""Structural checks on the harder MCP eval fixture set (issue #140).

`features/common/retrieval/eval/mcp_queries_hard.jsonl` is a *separate* file from
`mcp_queries.jsonl` on purpose — it is a measurement instrument, not a regression gate, and
mixing the two would silently reinterpret the existing gate's bars. This suite checks the
fixture data is well-formed and, for the `paraphrase` class specifically, mechanically
enforces the one property that class claims: zero lexical overlap with the tool it targets.
It does not assert recall/false-fire bars — see docs/retrieval.md and the PR body for what the
runner (`tooling/retrieval_eval.py`) actually measures against this file.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "features" / "common" / "retrieval" / "eval" / "mcp_queries_hard.jsonl"
INDEX_PATH = ROOT / ".ai-badger" / "mcp-tools.json"

VALID_CLASSES = {"paraphrase", "user-voice", "near-dup", "adjacent-negative", "inert-negative"}


def _load_fixtures() -> list:
    lines = FIXTURES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _load_index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixtures() -> list:
    return _load_fixtures()


@pytest.fixture(scope="module")
def index() -> dict:
    return _load_index()


@pytest.fixture
def retrieval_eval(load_script):
    return load_script("tooling/retrieval_eval.py")


def _all_tool_names(index: dict) -> set:
    names = set()
    for server in index.get("sources", []):
        for tname in server.get("tools", {}):
            names.add(f"{server['name']}:{tname}")
    return names


# ── structural checks ────────────────────────────────────────────────────────

def test_every_fixture_has_a_valid_class(fixtures):
    for fixture in fixtures:
        assert fixture.get("class") in VALID_CLASSES, fixture


def test_every_expected_tool_exists_in_the_real_index(fixtures, index):
    known = _all_tool_names(index)
    for fixture in fixtures:
        for tool in fixture["expect"]:
            assert tool in known, f"{tool!r} (query: {fixture['query']!r}) is not in the index"


def test_negative_classes_have_an_empty_expect(fixtures):
    for fixture in fixtures:
        if fixture["class"] in {"adjacent-negative", "inert-negative"}:
            assert fixture["expect"] == [], fixture


def test_positive_classes_have_a_nonempty_expect(fixtures):
    for fixture in fixtures:
        if fixture["class"] in {"paraphrase", "user-voice", "near-dup"}:
            assert fixture["expect"], fixture


def test_every_class_is_represented(fixtures):
    seen = {f["class"] for f in fixtures}
    assert seen == VALID_CLASSES


def test_no_duplicate_queries(fixtures):
    queries = [f["query"] for f in fixtures]
    assert len(queries) == len(set(queries))


# ── the mechanically-enforced paraphrase invariant ───────────────────────────

def test_paraphrase_fixtures_have_zero_lexical_overlap_with_their_target(
    fixtures, index, retrieval_eval
):
    """issue #140: "paraphrase ... mechanically enforced (write the check; do not eyeball it)".

    Tokenizes the query the same way the matcher does, and tokenizes each expected tool's
    fused document (name + tags + intent) the same way `mcp_matcher.build_corpus` does, then
    asserts the two token sets are disjoint. Sharing even one token would mean the fixture is
    testing lexical recall, not the paraphrase gap it claims to.
    """
    from tokenizer import tokenize  # pylint: disable=import-outside-toplevel

    violations = []
    for fixture in fixtures:
        if fixture["class"] != "paraphrase":
            continue
        query_tokens = set(tokenize(fixture["query"]))
        for tool in fixture["expect"]:
            doc_tokens = retrieval_eval._doc_tokens(index, tool)  # pylint: disable=protected-access
            overlap = query_tokens & doc_tokens
            if overlap:
                violations.append((fixture["query"], tool, sorted(overlap)))
    assert not violations, violations


# ── the runner can actually be pointed at this file ──────────────────────────

def test_the_runner_produces_a_report_without_crashing(fixtures, index, retrieval_eval):
    report = retrieval_eval.evaluate(fixtures, index)
    assert report.n == len(fixtures)
    assert set(report.by_class) == VALID_CLASSES
