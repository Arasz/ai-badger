"""Contract pin for the `change` skill: the smallest lane, run by the main agent alone.

Each row is one rule the skill exists to carry. Phrases are matched against
whitespace-normalized text, so a row survives re-wrapping but not silent removal.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "features" / "common" / "skills" / "change" / "SKILL.md"
PLUGIN_COPY = ROOT / "skills" / "change" / "SKILL.md"

REQUIRED_PHRASES = [
    "## 1. Plan",
    "## 2. Review the plan",
    "## 3. Implement test-first",
    "## 4. Review the diff",
    "watch it fail",
    "No delegation",
    "VERSION",
    "README",
    "escalate to `task`",
]


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def test_the_skill_ships_by_default():
    assert re.search(r"^scope: default$", SOURCE.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_the_skill_carries_each_rule(phrase):
    assert re.sub(r"\s+", " ", phrase) in _flat(SOURCE)


def test_the_four_phases_run_in_order():
    text = _flat(SOURCE)
    positions = [text.index(p) for p in REQUIRED_PHRASES[:4]]
    assert positions == sorted(positions)


def test_the_plugin_copy_exists():
    assert PLUGIN_COPY.is_file()
