"""Invariant snippets are embedded under a `## Non-negotiable invariants` section.

Their own H1/H2 headings must be demoted so the agent file keeps one document outline
instead of ten competing H1s. The standalone copies under .ai-badger/invariants/ are
unaffected — they are documents in their own right.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import pytest


@pytest.fixture
def scaffold(load_script):
    """Load the scaffold module."""
    return load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")


def test_h1_becomes_h3(scaffold):
    assert scaffold.demote_headings("# TDD is mandatory\n\nWrite the test first.\n") == (
        "### TDD is mandatory\n\nWrite the test first.\n")


def test_h2_becomes_h4(scaffold):
    assert scaffold.demote_headings("## Signal state discipline\n\nBody.\n") == (
        "#### Signal state discipline\n\nBody.\n")


def test_comments_inside_fenced_code_are_untouched(scaffold):
    text = "# Title\n\n```bash\n# not a heading — a shell comment\nls\n```\n"
    out = scaffold.demote_headings(text)
    assert "### Title" in out
    assert "# not a heading — a shell comment" in out
    assert "### not a heading" not in out


def test_tilde_fences_are_honored_too(scaffold):
    text = "# Title\n\n~~~\n# still a comment\n~~~\n"
    assert "# still a comment" in scaffold.demote_headings(text)
    assert "### still a comment" not in scaffold.demote_headings(text)


def test_hash_without_a_space_is_not_a_heading(scaffold):
    """`#5` is an issue reference, not an ATX heading."""
    assert scaffold.demote_headings("#5 is not a heading\n") == "#5 is not a heading\n"


def test_body_text_is_left_alone(scaffold):
    body = "Prefer a guard clause.\n\nSee `docs/adr/0001`.\n"
    assert scaffold.demote_headings("# T\n\n" + body) == "### T\n\n" + body


def test_every_invariant_source_leads_with_a_single_h1(root):
    """Consistent source level means consistent rendered level after demotion."""
    offenders = {}
    for path in sorted(root.glob("features/*/invariants/*.md")):
        first = path.read_text(encoding="utf-8").lstrip().splitlines()[0]
        level = len(first) - len(first.lstrip("#"))
        if level != 1:
            offenders[str(path.relative_to(root))] = first
    assert not offenders, (
        f"invariant sources must start with '# ': {offenders}. "
        "Mixed levels render unevenly once embedded under '## Non-negotiable invariants'."
    )
