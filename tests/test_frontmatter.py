"""One frontmatter extractor, one contract — the four that preceded it disagreed.

They disagreed about where a block opens (offset 0 vs the first line vs anywhere `---` appears),
about CRLF, about which key grammar counts, and about whether a blank line ends a folded value.
Each disagreement is pinned here, so the next reader can see which answer was chosen.
"""
from __future__ import annotations

import pytest


@pytest.fixture(name="fm")
def fm_fixture(load_script):
    return load_script("engine/frontmatter.py")


CANONICAL = (
    "---\n"
    "name: my-skill\n"
    "description: >-\n"
    "  Use when the description folds\n"
    "  over two lines.\n"
    "---\n"
    "\n"
    "# Body\n"
)


class TestTheFence:
    def test_head_and_body_reassemble_the_original(self, fm):
        split = fm.split(CANONICAL)
        assert split.present
        assert split.head + split.body == CANONICAL

    def test_a_document_with_no_frontmatter_is_all_body(self, fm):
        split = fm.split("# Just a heading\n")
        assert not split.present
        assert split.body == "# Just a heading\n"
        assert split.fields() == {}

    def test_an_unclosed_block_is_not_frontmatter(self, fm):
        split = fm.split("---\nname: x\n\n# body\n")
        assert not split.present
        assert split.body == "---\nname: x\n\n# body\n"

    def test_a_thematic_break_further_down_is_not_an_opening_fence(self, fm):
        """`text.split("---", 2)` read this as frontmatter; no YAML host does."""
        text = "# Heading\n\n---\n\nnot: frontmatter\n---\n"
        assert not fm.split(text).present

    def test_crlf_frontmatter_is_read_like_lf(self, fm):
        text = "---\r\nname: my-skill\r\n---\r\n\r\n# Body\r\n"
        split = fm.split(text)
        assert split.present
        assert split.fields()["name"] == "my-skill"
        assert split.head + split.body == text

    def test_a_closing_fence_with_no_trailing_newline_still_closes(self, fm):
        split = fm.split("---\nname: x\n---")
        assert split.present
        assert split.body == ""


class TestFields:
    def test_a_folded_block_becomes_one_line(self, fm):
        assert fm.fields(CANONICAL)["description"] == (
            "Use when the description folds over two lines.")

    def test_a_blank_line_inside_a_block_does_not_end_the_value(self, fm):
        """`_folded_lines` stopped at the first blank line and silently truncated."""
        text = "---\ndescription: >-\n  first\n\n  second\nname: x\n---\n"
        assert fm.fields(text)["description"] == "first second"

    def test_a_key_may_start_with_an_underscore_or_carry_a_dot(self, fm):
        """The narrower `[A-Za-z][A-Za-z0-9_-]*` grammar dropped these on the floor."""
        assert fm.fields("---\n_private: a\nx.y: b\n---\n") == {"_private": "a", "x.y": "b"}

    def test_a_repeated_key_resolves_to_the_last_value_as_yaml_does(self, fm):
        split = fm.split("---\nname: first\nname: last\n---\n")
        assert split.fields()["name"] == "last"
        assert split.duplicate_keys() == ["name"]

    def test_no_duplicates_reports_nothing(self, fm):
        assert fm.split(CANONICAL).duplicate_keys() == []

    def test_an_indented_line_is_a_continuation_not_a_key(self, fm):
        text = "---\nmetadata:\n  hermes:\n    tags: [a]\n---\n"
        split = fm.split(text)
        assert [e.key for e in split.entries] == ["metadata"]
        assert split.entry("metadata").lines == (
            "metadata:\n", "  hermes:\n", "    tags: [a]\n")


class TestWellFormed:
    def test_the_canonical_block_is_well_formed(self, fm):
        assert fm.split(CANONICAL).well_formed

    def test_an_unindented_non_key_line_is_not_resolvable(self, fm):
        """Rule 10's oracle: a shape no line-oriented reader can resolve is reported, never passed."""
        assert not fm.split("---\nname: x\nthis is prose\n---\n").well_formed

    def test_a_blank_line_does_not_make_a_block_ill_formed(self, fm):
        assert fm.split("---\nname: x\n\nversion: 1\n---\n").well_formed
