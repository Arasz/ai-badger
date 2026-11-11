"""decision-record keeps the project's own format first and offers ai-raccoon as an extra.

ADR-0047 makes the project's format the primary record; ADR-0048 adds an optional second
write to ai-raccoon's `record_decision`, taken only when the tool is available and only
after the project-format record is written.
"""
from __future__ import annotations

from conftest import ROOT

SKILL = ROOT / "features/common/skills/decision-record/SKILL.md"
WRITE_STEP = "## Step 2 — Write, by mode"


def _body() -> str:
    return SKILL.read_text(encoding="utf-8")


def _paragraph_with(body: str, needle: str) -> str:
    """The blank-line-delimited block holding the first *needle*."""
    at = body.index(needle)
    start = body.rfind("\n\n", 0, at)
    end = body.find("\n\n", at)
    return body[start + 2 if start >= 0 else 0:end if end >= 0 else len(body)]


def test_decision_record_skill_names_record_decision_as_optional():
    """record_decision appears, and its own paragraph makes it conditional on availability."""
    body = _body()

    assert "record_decision" in body
    assert "when available" in _paragraph_with(body, "record_decision").lower()


def test_decision_record_skill_mentions_record_decision_after_the_project_write_step():
    """The ai-raccoon write comes after the project-format write, never before it."""
    body = _body()

    assert WRITE_STEP in body
    assert "record_decision" in body
    assert body.index("record_decision") > body.index(WRITE_STEP)


def test_decision_record_skill_keeps_the_project_format_primary():
    """The skill cites ADR-0047 and says the project's own record stays the primary one."""
    body = _body()

    assert "ADR-0047" in body
    assert "record_decision" in body
    assert "primary" in _paragraph_with(body, "record_decision").lower()
