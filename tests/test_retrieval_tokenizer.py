"""Tests for features/common/retrieval/tokenizer.py.

Pins the bug the old `_KEYWORD_TAG_MAP` had: a short token must never match as a
substring of a longer word (`"ts"` inside `"tests"`, `"tab"` inside `"table"`).
"""
from __future__ import annotations


def test_tokenize_splits_on_non_alnum_and_lowercases(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("Build the Solution!") == ["build", "solution"]


def test_tokenize_splits_hyphens(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("ai-badger") == ["ai", "badger"]


def test_tokenize_drops_tokens_shorter_than_two_chars(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert "a" not in tokenizer.tokenize("a build")


def test_tokenize_keeps_two_char_tokens(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("ts pr db md") == ["ts", "pr", "db", "md"]


def test_tokenize_drops_stopwords(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    tokens = tokenizer.tokenize("the build of this and that")
    assert "the" not in tokens
    assert "this" not in tokens
    assert "and" not in tokens
    assert "that" not in tokens
    assert "build" in tokens


def test_ts_token_never_matches_inside_tests(load_script):
    """The direct bug fix: 'ts' as a token, 'tests' folds to 'test' — never equal."""
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("ts")[0] != tokenizer.tokenize("run the tests")[-1]
    assert "ts" not in tokenizer.tokenize("run the tests")
    assert "ts" not in tokenizer.tokenize("test results and artifacts")


def test_tab_token_never_matches_inside_table(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert "tab" not in tokenizer.tokenize("query the table")


def test_suffix_folding_merges_plurals(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("tests")[0] == tokenizer.tokenize("testing")[0]


def test_suffix_folding_ies_to_y(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("companies") == ["company"]


def test_suffix_folding_requires_three_char_remainder(load_script):
    """A short remainder (e.g. 'gas' -> 'ga') must not be stripped down to noise."""
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("gas") == ["gas"]


def test_tokenize_empty_string(load_script):
    tokenizer = load_script("features/common/retrieval/tokenizer.py")
    assert tokenizer.tokenize("") == []
