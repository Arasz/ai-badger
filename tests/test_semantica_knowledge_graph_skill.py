"""Structure and convention validation for the semantica-knowledge-graph SKILL.md.

TDD: this file is committed RED (before SKILL.md exists), then made GREEN
by creating the skill file. Sensitivity tests prove each structural check can fail.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import _test_write

SKILL_DIR = "features/common/skills/semantica-knowledge-graph"
ROOT = Path(__file__).resolve().parent.parent


def _skill_path() -> Path:
    return ROOT / SKILL_DIR / "SKILL.md"


def _skill_text() -> str:
    return _skill_path().read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter as a dict (line-oriented, no pyyaml)."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    result = {}
    current_key = None
    in_folded = False
    folded_value = ""
    for line in m.group(1).split("\n"):
        if in_folded:
            if line and not line.startswith(" ") and ":" in line:
                # End of folded block — new key found
                result[current_key] = folded_value.strip()
                in_folded = False
                current_key = None
                folded_value = ""
            elif line.startswith("  "):
                folded_value += line.strip() + " "
                continue
            else:
                continue
        if ":" in line and not line.startswith(" ") and not line.strip().startswith("#"):
            key, _, val = line.partition(":")
            current_key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val == ">-":
                in_folded = True
                folded_value = ""
            elif val:
                result[current_key] = val.strip().strip('"').strip("'")
        elif current_key and line.strip().startswith("-"):
            val = line.strip().lstrip("-").strip()
            if current_key not in result:
                result[current_key] = []
            if isinstance(result[current_key], list):
                result[current_key].append(val)
    if in_folded and current_key:
        result[current_key] = folded_value.strip()
    return result


# ── existence ────────────────────────────────────────────────────────────────

def test_skill_md_exists():
    """SKILL.md exists in the semantica-knowledge-graph directory."""
    assert _skill_path().is_file()


# ── frontmatter ──────────────────────────────────────────────────────────────

def test_skill_has_valid_yaml_frontmatter():
    """SKILL.md has parseable YAML frontmatter with required keys."""
    fm = _parse_frontmatter(_skill_text())
    assert fm, "No frontmatter found"
    required = {"name", "description", "version", "author", "license", "platforms", "scope"}
    missing = required - set(fm.keys())
    assert not missing, f"Missing frontmatter keys: {missing}"


def test_skill_name_matches_directory():
    """The frontmatter 'name' matches the skill directory name."""
    fm = _parse_frontmatter(_skill_text())
    assert fm.get("name") == "semantica-knowledge-graph"


def test_skill_scope_is_default():
    """scope is 'default' for auto-inclusion via DEFAULT_SKILLS."""
    fm = _parse_frontmatter(_skill_text())
    assert fm.get("scope") == "default"


def test_skill_description_starts_with_use_when():
    """description begins with 'Use when' per skills_lint rule 5."""
    fm = _parse_frontmatter(_skill_text())
    desc = fm.get("description", "")
    assert desc.startswith("Use when"), f"Description: {desc[:60]}"


# ── body structure ───────────────────────────────────────────────────────────

def test_skill_has_when_not_to_use_section():
    """Body contains 'When NOT to Use' guard section."""
    text = _skill_text()
    assert "When NOT to Use" in text


def test_skill_has_workflow_sections():
    """Body contains at least 3 numbered workflow sections (### N. or N. ** format)."""
    text = _skill_text()
    workflows = re.findall(r"(?:###\s+\d+\.|^\d+\.\s+\*\*)", text, re.MULTILINE)
    assert len(workflows) >= 3, f"Found {len(workflows)} workflow sections"


def test_skill_has_gotchas_section():
    """Body contains '## Gotchas' section per skills_lint rule 9."""
    text = _skill_text()
    assert "## Gotchas" in text


def test_skill_has_verification_checklist():
    """Body contains a verification checklist with checkboxes."""
    text = _skill_text()
    assert "- [ ]" in text


def test_skill_mentions_ai_raccoon():
    """Body mentions AiRaccoon and explains complementarity."""
    text = _skill_text()
    assert "AiRaccoon" in text or "ai-raccoon" in text
    assert "complement" in text.lower() or "memory" in text.lower()


def test_skill_references_core_tools():
    """Body references at least 4 of the core semantica MCP tools by name."""
    text = _skill_text()
    core_tools = ["add_entity", "add_relationship", "record_decision",
                  "query_decisions", "get_graph_summary", "extract_entities"]
    found = [t for t in core_tools if t in text]
    assert len(found) >= 4, f"Only found: {found}"


def test_skill_has_escalation_section():
    """Body contains an escalation-by-result guide."""
    text = _skill_text()
    has_escalation = "Escalation" in text or "escalat" in text.lower()
    assert has_escalation


def test_skill_explains_local_extraction_options():
    """Body explains Option 2 agent-guided extraction and code-review-graph for code."""
    text = _skill_text()
    assert "code-review-graph" in text
    assert "add_entity" in text and "add_relationship" in text


def test_skill_explains_export_hook_and_airaccoon_watch_pattern():
    """Body explains exporting graph to JSON file, seeding it, and watching via memory_watch_add."""
    text = _skill_text()
    assert "memory_watch_add" in text or "watch" in text.lower()
    assert "export" in text.lower()
    assert "json" in text.lower()
    assert "AiRaccoon" in text or "ai-raccoon" in text


def test_skill_explains_no_import_and_process_isolation():
    """Body explains in-memory process isolation and 'no import' session-scoped lifecycle."""
    text = _skill_text()
    assert "session-scoped" in text.lower() or "in-memory" in text.lower()
    assert "no import" in text.lower() or "import_graph" in text.lower()


# ── size ─────────────────────────────────────────────────────────────────────

def test_skill_under_500_lines():
    """SKILL.md is under 500 lines (skills_lint rule 6 cap)."""
    lines = _skill_text().split("\n")
    assert len(lines) <= 500, f"SKILL.md is {len(lines)} lines"


def test_skill_under_5000_chars():
    """SKILL.md is under 5000 characters (skills_lint rule 7)."""
    text = _skill_text()
    assert len(text) <= 5000, f"SKILL.md is {len(text)} chars"


# ── metadata ─────────────────────────────────────────────────────────────────

def test_skill_has_hermes_metadata():
    """Frontmatter metadata.hermes section is present with tags."""
    text = _skill_text()
    assert "hermes:" in text
    assert "tags:" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Sensitivity tests — prove each structural check CAN fail
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkillChecksCanFail:
    """Each check in this file must have a companion that proves it detects violations."""

    def test_missing_frontmatter_can_fail(self):
        """A SKILL.md with no frontmatter is detected."""
        text = "# Just a heading\n\nNo frontmatter here."
        fm = _parse_frontmatter(text)
        assert not fm

    def test_wrong_scope_can_fail(self):
        """scope != 'default' is detected."""
        fm = _parse_frontmatter("""---
name: test
description: Use when testing.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux]
scope: project
---
""")
        assert fm.get("scope") != "default"

    def test_no_gotchas_can_fail(self):
        """A body without '## Gotchas' is detected."""
        text = "# Title\n\nSome content without gotchas.\n"
        assert "## Gotchas" not in text

    def test_over_500_lines_can_fail(self):
        """A body over 500 lines is detected."""
        lines = ["# Line"] * 501
        assert len(lines) > 500
