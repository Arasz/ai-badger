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


def test_fuse_document_applies_the_given_weight(bm25):
    fused = bm25.fuse_document([(["build"], 3.0)])
    assert fused["build"] == 3.0


def test_fuse_document_sums_when_two_fields_share_a_token(bm25):
    """Two fields carrying the same token must accumulate, not overwrite — this is the
    whole point of fusing name/tags/intent into one weighted document."""
    fused = bm25.fuse_document([(["build"], 3.0), (["build"], 2.0)])
    assert fused["build"] == 5.0


def test_fuse_document_empty_field_contributes_nothing(bm25):
    fused = bm25.fuse_document([([], 3.0), (["solution"], 1.0)])
    assert fused["solution"] == 1.0
    assert "build" not in fused


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


# ── the coverage denominator cap (issue #165) ────────────────────────────────
#
# `coverage = sum(idf(matched)) / sum(idf(every query term))` falls roughly as 1/len(query),
# so a sentence-length prompt cannot clear a gate tuned on keyword-length ones. Capping the
# denominator at the `coverage_cap` most informative terms makes the ratio length-invariant.

def _cap_corpus(bm25):
    """Two documents plus filler, so a query can be lengthened with terms nothing contains."""
    return bm25.Bm25Corpus({
        "target": _tf("screenshot", "screenshot", "page", "browser"),
        "other": _tf("database", "query", "sql"),
        "filler": _tf("browser", "page"),
    })


def test_coverage_cap_leaves_a_short_query_untouched(bm25):
    """At or below the cap the top-`n` terms *are* every term, so the denominator is the
    same sum as before — the control fixture set can therefore never move."""
    corpus = _cap_corpus(bm25)
    uncapped = {r.doc_id: r.coverage for r in corpus.rank(["screenshot", "page"])}
    capped = {r.doc_id: r.coverage for r in corpus.rank(["screenshot", "page"], coverage_cap=6)}
    assert capped == uncapped


def test_coverage_cap_makes_coverage_invariant_to_further_padding(bm25):
    """The property the cap actually buys, and the one issue #165 needs: once a query has
    at least `coverage_cap` terms, appending more that nothing matches cannot move coverage.

    Uncapped, each appended term adds to the denominator and to nothing else, so coverage
    decays as roughly 1/len(query) however good the match is.
    """
    corpus = _cap_corpus(bm25)
    base = ["screenshot", "page"]
    # Every junk term is absent from the corpus, and an absent term carries the *highest*
    # idf, so once `coverage_cap` of them are present they alone fix the denominator.
    junk = ["login", "compare", "design", "later", "share", "team",
            "ticket", "morning", "sprint", "budget"]

    counts = (6, 8, 10)
    capped = [corpus.rank(base + junk[:n], coverage_cap=6)[0].coverage for n in counts]
    uncapped = [corpus.rank(base + junk[:n])[0].coverage for n in counts]

    assert len(set(capped)) == 1, capped                 # flat past the cap
    assert uncapped == sorted(uncapped, reverse=True)    # monotonically diluted
    assert uncapped[-1] < uncapped[0]


def test_coverage_cap_uses_the_highest_idf_terms_not_the_first_ones(bm25):
    """"Most informative" is an idf ordering; taking the query's leading terms instead would
    make the gate depend on word order."""
    corpus = _cap_corpus(bm25)
    # "browser" (df 2) is commoner than "screenshot" (df 1), and comes first in the query.
    ranked = corpus.rank(["browser", "screenshot"], coverage_cap=1)
    by_id = {r.doc_id: r for r in ranked}
    assert by_id["target"].coverage == pytest.approx(1.0)
    # "filler" holds only the low-idf term, so it cannot account for the capped denominator.
    assert by_id["filler"].coverage < 1.0


def test_coverage_cap_clips_at_one(bm25):
    """The numerator still sums every matched term, so it can exceed a capped denominator;
    a coverage above 1.0 would be meaningless against a [0, 1] threshold."""
    corpus = _cap_corpus(bm25)
    ranked = corpus.rank(["screenshot", "page", "browser"], coverage_cap=1)
    assert max(r.coverage for r in ranked) == pytest.approx(1.0)


def test_coverage_cap_of_none_is_the_uncapped_denominator(bm25):
    corpus = _cap_corpus(bm25)
    padded = ["screenshot", "page", "login", "compare"]
    assert ({r.doc_id: r.coverage for r in corpus.rank(padded, coverage_cap=None)}
            == {r.doc_id: r.coverage for r in corpus.rank(padded)})


def test_coverage_cap_does_not_change_the_bm25_scores(bm25):
    """Ranking is untouched — issue #165 is a gate defect, not a ranking one."""
    corpus = _cap_corpus(bm25)
    padded = ["screenshot", "page", "login", "compare", "design", "later", "team"]
    assert ([(r.doc_id, r.score) for r in corpus.rank(padded)]
            == [(r.doc_id, r.score) for r in corpus.rank(padded, coverage_cap=6)])
