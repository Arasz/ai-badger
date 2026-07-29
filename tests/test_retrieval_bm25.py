"""Tests for features/common/retrieval/bm25.py.

A generic BM25 corpus over fused per-document term-frequency maps: no knowledge of
skills or MCP tools (docs/adr/0012-bm25-retrieval-with-a-falsifiable-eval.md).
"""
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
