"""Tests for features/common/retrieval/bm25.py.

A generic BM25 corpus over fused per-document term-frequency maps: no knowledge of
skills or MCP tools (docs/adr/0012-bm25-retrieval-with-a-falsifiable-eval.md).
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

from collections import Counter

import pytest


@pytest.fixture
def bm25(load_script):
    return load_script("features/common/retrieval/bm25.py")


def _tf(*words: str) -> Counter:
    return Counter(words)


def test_idf_is_higher_for_a_rarer_term(bm25):
    corpus = bm25.Bm25Corpus({
        "a": _tf("build", "solution"),
        "b": _tf("build", "database"),
        "c": _tf("build", "search"),
    })
    # "build" appears in all 3 docs, "database" in 1 — rarer term scores higher idf.
    assert corpus.idf("database") > corpus.idf("build")


def test_score_ranks_exact_term_match_highest(bm25):
    corpus = bm25.Bm25Corpus({
        "build_solution": _tf("build", "build", "build", "solution", "dotnet"),
        "execute_sql_query": _tf("run", "sql", "query", "database", "connection"),
    })
    ranked = corpus.rank(["build", "solution"])
    assert ranked[0].doc_id == "build_solution"
    assert ranked[0].score > 0


def test_score_is_zero_for_a_doc_matching_no_query_terms(bm25):
    corpus = bm25.Bm25Corpus({
        "a": _tf("build", "solution"),
        "b": _tf("search", "symbol"),
    })
    ranked = corpus.rank(["search"])
    by_id = {r.doc_id: r for r in ranked}
    assert by_id["a"].score == 0.0
    assert by_id["a"].matched_terms == 0


def test_coverage_is_fraction_of_query_idf_matched(bm25):
    corpus = bm25.Bm25Corpus({
        "a": _tf("build"),
        "b": _tf("build", "solution"),
    })
    # Query "build solution": doc "b" matches both terms -> full coverage.
    ranked = corpus.rank(["build", "solution"])
    by_id = {r.doc_id: r for r in ranked}
    assert by_id["b"].coverage == pytest.approx(1.0)
    assert 0.0 < by_id["a"].coverage < 1.0


def test_b_parameter_normalizes_document_length(bm25):
    """A short doc that fully matches should not be buried by a long doc's raw term count."""
    corpus = bm25.Bm25Corpus({
        "short_intent": _tf("build", "solution"),
        "long_description": _tf(
            "build", "solution", "and", "then", "run", "every", "test", "in",
            "the", "project", "before", "reporting", "back", "to", "the", "user",
        ),
    })
    ranked = corpus.rank(["build", "solution"])
    assert ranked[0].doc_id == "short_intent"


def test_empty_query_scores_everything_zero(bm25):
    corpus = bm25.Bm25Corpus({"a": _tf("build")})
    ranked = corpus.rank([])
    assert ranked[0].score == 0.0
    assert ranked[0].coverage == 0.0


def test_rank_is_deterministic_across_runs(bm25):
    corpus = bm25.Bm25Corpus({
        "a": _tf("build", "solution"),
        "b": _tf("build", "solution"),
        "c": _tf("build", "solution"),
    })
    first = [(r.doc_id, r.score) for r in corpus.rank(["build", "solution"])]
    second = [(r.doc_id, r.score) for r in corpus.rank(["build", "solution"])]
    assert first == second


def test_coverage_is_idf_weighted_not_a_plain_term_fraction(bm25):
    """ADR-0012's central claim: coverage weighs matched terms by IDF, not by plain count.

    "build" (df=3) and "solution" (df=1) have unequal document frequency, so
    `matched_idf / total_idf` and `matched_terms / len(query_terms)` diverge numerically
    for doc "a"'s partial match — pinning the exact value is what a loose
    `0.0 < coverage < 1.0` bound (both formulations satisfy it) cannot do.
    """
    corpus = bm25.Bm25Corpus({
        "a": _tf("build"),
        "b": _tf("build", "solution"),
        "c": _tf("build", "solution"),
    })
    ranked = corpus.rank(["build", "solution"])
    by_id = {r.doc_id: r for r in ranked}
    expected = corpus.idf("build") / (corpus.idf("build") + corpus.idf("solution"))
    assert by_id["a"].coverage == pytest.approx(expected)
    # A plain term-count fraction would give 1/2 regardless of idf; confirm it doesn't.
    assert expected != pytest.approx(0.5)


def test_tie_break_is_deterministic_across_insertion_order(bm25):
    """A sort key reduced to `(-score,)` lets ties fall back to insertion order, not `doc_id`.

    Both docs get identical term frequencies so they tie exactly on score and coverage;
    only `doc_id` in the sort key makes the order independent of how the corpus was built.
    Calling the same corpus twice (as a same-process determinism test does) can't see this,
    since ties would then just repeat whatever order the first build already fixed.
    """
    docs = {"zeta": _tf("build", "solution"), "alpha": _tf("build", "solution")}
    corpus_forward = bm25.Bm25Corpus(docs)
    corpus_reversed = bm25.Bm25Corpus(dict(reversed(list(docs.items()))))

    forward_order = [r.doc_id for r in corpus_forward.rank(["build", "solution"])]
    reversed_order = [r.doc_id for r in corpus_reversed.rank(["build", "solution"])]

    assert forward_order == reversed_order == ["alpha", "zeta"]


def test_coverage_breaks_an_exact_score_tie_toward_higher_coverage(bm25):
    """When two documents' BM25 scores land on the exact same float, the higher-coverage one
    must sort first (issue #154): otherwise nothing distinguishes `-r.coverage` from
    `+r.coverage` in the sort key, and a mutant flipping that sign survives untested.

    "doc_a" matches only "term_a", "doc_b" only "term_b", each on a document of equal weighted
    length (so `length_norm` is identical for both and drops out). "doc_c" exists only to make
    "term_a" the rarer term (df 2 vs. 1), so idf(term_a) != idf(term_b) and coverage differs.
    "doc_b"'s term frequency (0.6244807405101783) is solved so that, run through the exact same
    BM25 expression, its score equals "doc_a"'s bit-for-bit — verified below via `==`, not
    `approx`, because an approximate tie would let the primary `-r.score` key decide the order
    and never exercise the coverage tie-break at all.
    """
    fuse = bm25.fuse_document
    corpus = bm25.Bm25Corpus({
        "doc_a": fuse([(["term_a"], 3.0)]),
        "doc_b": fuse([(["term_b"], 0.6244807405101783), (["filler_b"], 2.375519259489822)]),
        "doc_c": fuse([(["term_a"], 1.0), (["filler_c"], 2.0)]),
    })
    ranked = corpus.rank(["term_a", "term_b"])
    by_id = {r.doc_id: r for r in ranked}

    assert by_id["doc_a"].score == by_id["doc_b"].score  # exact tie, not merely close
    assert by_id["doc_a"].coverage != by_id["doc_b"].coverage
    assert by_id["doc_b"].coverage > by_id["doc_a"].coverage

    order = [r.doc_id for r in ranked if r.doc_id in ("doc_a", "doc_b")]
    assert order == ["doc_b", "doc_a"]
