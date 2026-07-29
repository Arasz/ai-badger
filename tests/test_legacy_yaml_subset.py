"""Structural tests for the legacy-YAML subset parser's folding boundary (issue #145 review).

`parse_legacy_yaml_subset`'s round-trip guard compares `reemitted` against a *canonical*
rendering of `_logical_lines(text)` — the already-folded, comment/blank-line-stripped form —
not the original bytes. Anything `_logical_lines` gets wrong about *where a fold happens* is
invisible to that comparison, because both sides of it inherit the same folding decision. The
2000-trial fuzz in test_mcp_index.py is evidence about content (scalars, quoting, escapes);
these tests are about the one structural judgment call the guard cannot check for itself:
whether a physical line is a continuation of the previous scalar or a fresh key/item.
"""
from __future__ import annotations

MODULE = "features/common/skills/mcp-index/scripts/legacy_yaml_subset.py"


def test_a_continuation_at_the_wrong_indent_is_not_silently_folded(load_script):
    """pyyaml only ever wraps a scalar onto a line at exactly prev_indent + 2. A line at any
    other indent is not that shape, so it must not be guessed into the previous scalar —
    proven here by a genuine wrap (prev_indent + 2 = 8) mutated to the wrong indent (10),
    which must refuse rather than merge "project" and "root" into one string."""
    mod = load_script(MODULE)
    text = (
        "version: 0.1.0\n"
        "generated_at: '2026-01-01T00:00:00Z'\n"
        "sources:\n"
        "- name: rider\n"
        "  tools:\n"
        "    t1:\n"
        "      tags:\n"
        "      - build\n"
        "      intent: Retrieves the text content of a file using its path relative to project\n"
        "          root\n"
    )
    assert mod.parse_legacy_yaml_subset(text) is None


def test_the_same_continuation_at_the_correct_indent_folds_to_one_scalar(load_script):
    """Positive control for the test above: the identical wrap, at the indent pyyaml actually
    uses (prev_indent + 2 = 8), must fold to a single space-joined scalar."""
    mod = load_script(MODULE)
    text = (
        "version: 0.1.0\n"
        "generated_at: '2026-01-01T00:00:00Z'\n"
        "sources:\n"
        "- name: rider\n"
        "  tools:\n"
        "    t1:\n"
        "      tags:\n"
        "      - build\n"
        "      intent: Retrieves the text content of a file using its path relative to project\n"
        "        root\n"
    )
    parsed = mod.parse_legacy_yaml_subset(text)
    assert parsed is not None
    intent = parsed["sources"][0]["tools"]["t1"]["intent"]
    assert intent == (
        "Retrieves the text content of a file using its path relative to project root"
    )


def test_a_genuine_key_at_prev_indent_plus_2_is_never_folded_into_a_scalar(load_script):
    """A `key:` line landing exactly at prev_indent + 2 — the same offset a wrapped
    continuation would use — must still be read as a fresh key, never merged into the
    previous line's scalar value. This shape is not one pyyaml itself would emit (nesting
    only ever follows a bare `key:`, never a scalar), which is exactly why it is the
    adversarial case worth pinning directly rather than trusting fuzzed content to hit it.
    """
    mod = load_script(MODULE)
    text = (
        "version: 0.1.0\n"
        "generated_at: '2026-01-01T00:00:00Z'\n"
        "sources:\n"
        "- name: rider\n"
        "  tools:\n"
        "    t1:\n"
        "      intent: A short line here\n"
        "        extra: not really nested\n"
    )
    logical = mod._logical_lines(text)  # pylint: disable=protected-access
    # The `key:`-shaped line must survive as its own logical line, not fold into "intent"'s.
    assert (8, "extra: not really nested") in logical
    assert logical[-2] == (6, "intent: A short line here")
    # The document as a whole is not a shape this schema produces (a scalar has no
    # children) — refusing is correct, not merely "didn't crash".
    assert mod.parse_legacy_yaml_subset(text) is None


def test_a_genuine_nested_key_at_the_same_offset_is_not_mistaken_for_a_continuation(load_script):
    """The everyday version of the case above: `tools:`'s nested tool-name keys sit at
    exactly prev_indent + 2 relative to `tools:` itself, and must parse as a mapping, not
    get folded away as if `tools:` were a wrapped scalar."""
    mod = load_script(MODULE)
    text = (
        "version: 0.1.0\n"
        "generated_at: '2026-01-01T00:00:00Z'\n"
        "sources:\n"
        "- name: rider\n"
        "  tools:\n"
        "    build_solution:\n"
        "      tags:\n"
        "      - build\n"
        "      intent: Compile the solution and report errors back\n"
    )
    parsed = mod.parse_legacy_yaml_subset(text)
    assert parsed is not None
    assert parsed["sources"][0]["tools"]["build_solution"]["tags"] == ["build"]
