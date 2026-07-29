"""Tests for features/common/retrieval/bm25.py.

A generic BM25 corpus over fused per-document term-frequency maps: no knowledge of
skills or MCP tools (docs/adr/0012-bm25-retrieval-with-a-falsifiable-eval.md).
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import math
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


def test_avgdl_is_mean_document_length_not_product(bm25):
    """avgdl = sum(doc lengths) / n. A construction bug swapping division for
    multiplication distorts every length_norm, but the existing length-normalization test's
    huge length gap (2 tokens vs 16) survives that distortion by coincidence."""
    corpus = bm25.Bm25Corpus({
        "a": _tf("build", "solution"),           # length 2
        "b": _tf("build", "solution", "run"),    # length 3
    })
    assert corpus._avgdl == pytest.approx(2.5)  # pylint: disable=protected-access


def test_idf_for_a_term_absent_from_every_document(bm25):
    """A query term with zero document frequency must use df=0 in the formula, not None
    (crashes) or 1 (wrong value) — a real query condition (typos, novel words) the
    existing relative-ordering test never exercises."""
    corpus = bm25.Bm25Corpus({"a": _tf("build"), "b": _tf("solution")})
    expected = math.log(1 + (2 - 0 + 0.5) / (0 + 0.5))
    assert corpus.idf("nonexistent") == pytest.approx(expected)


def test_idf_formula_uses_minus_document_frequency(bm25):
    """Pins df=2 (n=3) against the hand-computed formula so a sign flip on `df`, or either
    `+0.5` becoming `-0.5`/`+1.5`, or the division becoming a multiply, all fail — the
    existing rarer-term comparison stays true under several of these because it only checks
    relative order, not the value."""
    corpus = bm25.Bm25Corpus({"a": _tf("build"), "b": _tf("build"), "c": _tf("solution")})
    expected = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))
    assert corpus.idf("build") == pytest.approx(expected)


def test_rank_score_matches_the_bm25_formula_exactly(bm25):
    """Pins score, matched_terms and coverage to hand-computed values (k1=1.2, b=0.75, per
    this module's own docstring) so every arithmetic operator in the scoring loop —
    length_norm's sign and factor, the two multiplies, the final divide, and the
    matched_terms/score accumulators — has something that fails if it changes. The
    existing length-normalization test only compares which document ranks first, which
    several of these mutations still get right by accident.
    """
    k1, b = 1.2, 0.75
    corpus = bm25.Bm25Corpus({
        "a": _tf("build", "solution"),
        "b": _tf("build"),
    })
    # n=2, avgdl=(2+1)/2=1.5; df(build)=2 (both docs), df(solution)=1 (doc "a" only)
    idf_build = math.log(1 + (2 - 2 + 0.5) / (2 + 0.5))
    idf_solution = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    length_norm_a = 1 - b + b * (2 / 1.5)
    expected_score_a = (
        idf_build * (1 * (k1 + 1)) / (1 + k1 * length_norm_a)
        + idf_solution * (1 * (k1 + 1)) / (1 + k1 * length_norm_a)
    )
    ranked = corpus.rank(["build", "solution"])
    by_id = {r.doc_id: r for r in ranked}
    assert by_id["a"].score == pytest.approx(expected_score_a)
    assert by_id["a"].matched_terms == 2
    assert by_id["a"].coverage == pytest.approx(1.0)


def test_length_norm_falls_back_to_one_when_avgdl_is_zero(bm25):
    """`dl / self._avgdl if self._avgdl else 1.0` guards the zero-avgdl case explicitly, so
    it is reachable and worth pinning: a term-frequency map is only required to be a
    `Counter` (no non-negative constraint), so a doc whose weighted counts sum to zero
    while still matching a query term is valid input, not a contrived one.
    """
    corpus = bm25.Bm25Corpus({
        "a": Counter({"build": 5, "junk": -5}),   # doc_len sums to 0
        "b": Counter({"other": 3, "junk2": -3}),  # doc_len sums to 0 -> avgdl == 0
    })
    ranked = corpus.rank(["build"])
    by_id = {r.doc_id: r for r in ranked}
    k1, b = 1.2, 0.75
    length_norm = 1 - b + b * 1.0  # the documented fallback, not some other constant
    idf_build = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    expected_score = idf_build * (5 * (k1 + 1)) / (5 + k1 * length_norm)
    assert by_id["a"].score == pytest.approx(expected_score)


def test_rank_skips_only_the_zero_freq_term_not_the_rest(bm25):
    """A zero-frequency query term must `continue` to the next term, not `break` out of
    the loop — confirmed by putting the zero-freq term first, so a `break` would also
    skip a later term this document genuinely matches."""
    corpus = bm25.Bm25Corpus({
        "a": _tf("build", "solution"),
        "b": _tf("build"),
    })
    ranked = corpus.rank(["solution", "build"])  # "solution" first; absent from doc "b"
    by_id = {r.doc_id: r for r in ranked}
    assert by_id["b"].matched_terms == 1
    assert by_id["b"].score > 0


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
