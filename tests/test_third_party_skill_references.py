"""A skill that names another plugin's skill says what to do when it is absent.

`differential-feature-refactor` steps 6-7 read `invoke superpowers:brainstorming` and `invoke
superpowers:writing-plans` — bare imperatives, no presence check, no fallback. On a machine
without that plugin the middle of the workflow is a hole and nothing notices, because a
scaffolded SKILL.md is committed and shared while plugin presence is per-machine and mutable.

The same file already carries the shape that works, in its "Relationship to a spec skill"
section: name the *capability*, condition on presence, state the fallback inline. This pins that
as a rule rather than an example, so the next skill reaching for a third-party one cannot quietly
reintroduce the hole.

Deliberately a convention with a test, not a mechanism. Gating such references at scaffold time
was considered and rejected: the output is committed and shared, so it cannot depend on a
per-machine fact.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# `plugin:skill` as it appears in prose — a backticked, qualified id.
QUALIFIED_REFERENCE = re.compile(r"`([a-z][a-z0-9_-]*):([a-z][a-z0-9_-]*)`")


def declared_plugin_names() -> set:
    """Plugin namespaces the catalog itself declares, from features/*/skills.json.

    Derived rather than listed. A denylist of non-plugin prefixes would have to grow forever —
    the first draft flagged `node:fs`, `path:line`, `name:score`, `server:tool` and
    `trust:untrusted`, none of which is a skill reference. Only a name this catalog actually
    installs can be one, and that set maintains itself as sources are added.
    """
    names = set()
    for declaration in ROOT.glob("features/*/skills.json"):
        for skill in json.loads(declaration.read_text(encoding="utf-8")).get("skills", []):
            if skill.get("name"):
                names.add(skill["name"])
    return names

# Any of these in the same paragraph means the reference is conditioned or carries a fallback.
HEDGES = (
    "where the project has", "if the project has", "if it is installed", "if installed",
    "if present", "if available", "when available", "otherwise", "when absent", "if absent",
    "falls back", "fall back", "rather than", "in its absence", "without it",
)

BARE_REFERENCE_SAMPLE = "Brainstorm what the feedback opened up — invoke `superpowers:brainstorming`."


def _skill_files():
    return sorted(ROOT.glob("features/*/skills/*/SKILL.md"))


LIST_ITEM = re.compile(r"^\s*(?:\d+\.|[-*])\s")


def _blocks(text: str) -> list:
    """Split on blank lines *and* list-item boundaries.

    Blank lines alone are not enough: `differential-feature-refactor`'s workflow is one
    unbroken numbered list, so step 1's "fall back" excused the bare reference in step 6 and
    the guard passed on the very defect it was written for. A numbered step is the unit a
    reader follows, so it is the unit a fallback has to reach.
    """
    blocks, current = [], []
    for line in text.splitlines():
        if not line.strip() or LIST_ITEM.match(line):
            if current:
                blocks.append("\n".join(current))
            current = []
        if line.strip():
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def unhedged_references(text: str, plugins: set | None = None) -> list:
    """Every third-party `plugin:skill` reference whose own block offers no fallback."""
    plugins = declared_plugin_names() if plugins is None else plugins
    found = []
    for block in _blocks(text):
        lowered = block.lower()
        if any(hedge in lowered for hedge in HEDGES):
            continue
        found.extend(
            f"{prefix}:{name}"
            for prefix, name in QUALIFIED_REFERENCE.findall(block)
            if prefix in plugins
        )
    return found


@pytest.mark.parametrize("skill_md", _skill_files(), ids=lambda p: p.parent.name)
def test_a_third_party_skill_reference_carries_a_fallback(skill_md):
    """Naming another plugin's skill without saying what to do when it is missing is a hole.

    The reference itself is right — reusing a better-maintained skill beats duplicating it. What
    is wrong is a step that silently does nothing where the plugin was never installed, or was
    renamed, or removed.
    """
    unhedged = unhedged_references(skill_md.read_text(encoding="utf-8"))

    assert not unhedged, (
        f"{skill_md.parent.name} names {sorted(set(unhedged))} with no presence check and no "
        f"fallback in the same paragraph. Name the capability, condition on presence, and say "
        f"what to do without it — see differential-feature-refactor's 'Relationship to a spec "
        f"skill' section for the shape."
    )


class TestTheGuardCanActuallyFail:
    """An empty finding has to mean 'none present', not 'the pattern never matched'."""

    def test_a_bare_reference_is_caught(self):
        assert unhedged_references(BARE_REFERENCE_SAMPLE) == ["superpowers:brainstorming"]

    def test_a_hedged_reference_is_not_caught(self):
        text = (
            "Where the project has one, invoke `superpowers:brainstorming` and treat its design "
            "doc as the specification. Otherwise write it directly in the same shape."
        )

        assert unhedged_references(text) == []

    def test_a_fallback_in_another_paragraph_does_not_count(self):
        """The hedge has to reach the reader following the step, not sit two sections away."""
        text = BARE_REFERENCE_SAMPLE + "\n\nOtherwise write the specification directly."

        assert unhedged_references(text) == ["superpowers:brainstorming"]

    def test_our_own_namespace_is_not_a_third_party_reference(self):
        assert unhedged_references("Invoke `ai-badger:task` to run one backlog item.") == []

    def test_an_ordinary_colon_pair_is_not_a_reference(self):
        """The first draft flagged these. None is a skill; all are just prose."""
        text = "Read `node:fs`, cite `path:line`, and treat `trust:untrusted` accordingly."

        assert unhedged_references(text) == []

    def test_the_plugin_set_comes_from_the_catalog(self):
        assert "superpowers" in declared_plugin_names()

    def test_the_catalog_is_actually_being_scanned(self):
        """A parametrized test over an empty glob passes without asserting anything."""
        assert len(_skill_files()) >= 13

    def test_a_hedge_in_a_sibling_list_item_does_not_excuse_a_step(self):
        """The bug that made this guard vacuous on the file it was written for.

        differential-feature-refactor's workflow is one unbroken numbered list. Splitting on
        blank lines alone made step 1's "fall back" excuse the bare reference in step 6, so the
        guard passed on the exact defect it exists to catch.
        """
        text = (
            "1. **Authority set first.** Where that is silent, fall back to the tree.\n"
            "2. **Brainstorm it** — invoke `superpowers:brainstorming`.\n"
        )

        assert unhedged_references(text) == ["superpowers:brainstorming"]
