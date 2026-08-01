"""A SKILL.md is read to decide what to do; evidence for why belongs one file away (F1).

Progressive disclosure: an agent loads a skill's body every turn the skill is under
consideration, and acts on the procedure in it. Measurement evidence — the browser-capability
matrix, the transcript-format findings — is read once, when something is being debugged or
questioned. Carrying it inline taxes every turn to serve the rare one.

The rule is not "keep skills short". `code-review-checklist` is 363 lines and every one of them
is procedure. The rule is that a *measurement* lives where measurements live: `references/` for
agent-neutral evidence, `extensions/<agent>/` where the measurement is about one agent's
internals.

Both directories ship with the skill (`SKILL_EXCLUDE_PATTERNS` does not touch them), so nothing
is lost — the evidence is one Read away and the body says where.
"""
from __future__ import annotations

import re

import pytest

# A verified/unverified matrix: the shape that says "this is a measurement, not an instruction".
EVIDENCE_TABLE_RE = re.compile(r"^\|\s*(Fact|Claim|Measurement)\s*\|", re.MULTILINE)
EVIDENCE_HEADING_RE = re.compile(r"^\*\*(Verified|Unverified)\b", re.MULTILINE)


def _skill_bodies(root):
    for path in sorted(root.glob("features/*/skills/*/SKILL.md")):
        yield path


def _rel(root, path):
    return str(path.relative_to(root))


class TestNoBodyCarriesAMeasurementMatrix:
    """The table shape is mechanical, so this is enforceable rather than advisory."""

    def test_no_skill_body_has_an_evidence_table(self, root):
        offenders = []
        for path in _skill_bodies(root):
            text = path.read_text(encoding="utf-8")
            if EVIDENCE_TABLE_RE.search(text) or EVIDENCE_HEADING_RE.search(text):
                offenders.append(_rel(root, path))

        assert not offenders, (
            "measurement evidence belongs in references/ or extensions/<agent>/, not in a body "
            f"read on every turn: {offenders}"
        )


class TestTheEvidenceStillShips:
    """Moving it out must not mean losing it — the body has to name where it went."""

    MOVED = {
        "owner-gate-review": "references/browser-capabilities.md",
        "task": "extensions/claude/extension.md",
    }

    @pytest.mark.parametrize("skill,target", sorted(MOVED.items()))
    def test_the_target_exists_and_is_not_empty(self, root, skill, target):
        path = root / "features" / "common" / "skills" / skill / target

        assert path.is_file(), f"{skill}: {target} is missing"
        assert len(path.read_text(encoding="utf-8").strip()) > 500, \
            f"{skill}: {target} is too small to be holding the evidence"

    @pytest.mark.parametrize("skill,target", sorted(MOVED.items()))
    def test_the_body_names_where_the_evidence_went(self, root, skill, target):
        body = (root / "features" / "common" / "skills" / skill / "SKILL.md") \
            .read_text(encoding="utf-8")

        assert target in body, f"{skill}: body does not point at {target}"

    def test_the_browser_evidence_kept_its_measurements(self, root):
        """A move that drops the numbers is a deletion wearing a move's clothes."""
        moved = (root / "features" / "common" / "skills" / "owner-gate-review"
                 / "references" / "browser-capabilities.md").read_text(encoding="utf-8")

        for measurement in ("Chrome 150", "showSaveFilePicker", "WellKnownDirectory",
                            "isSecureContext", "AbortError"):
            assert measurement in moved, f"browser-capabilities.md lost: {measurement}"

    def test_the_dispatch_evidence_kept_its_measurements(self, root):
        moved = (root / "features" / "common" / "skills" / "task"
                 / "extensions" / "claude" / "extension.md").read_text(encoding="utf-8")

        for measurement in ("resolvedModel", "isSidechain", "1250", "171"):
            assert measurement in moved, f"claude extension lost: {measurement}"


class TestTheGuardCouldFail:
    """Each matcher above must actually match something; a dead regex proves nothing."""

    def test_a_fact_table_is_caught(self):
        assert EVIDENCE_TABLE_RE.search("| Fact | Result |\n|---|---|\n")

    def test_a_claim_table_is_caught(self):
        assert EVIDENCE_TABLE_RE.search("| Claim | Check that would settle it |\n")

    def test_an_unverified_heading_is_caught(self):
        assert EVIDENCE_HEADING_RE.search("**Unverified — say so rather than assert:**\n")

    def test_an_ordinary_table_is_not_caught(self):
        """Procedure tables are the point of a skill; only measurement matrices move."""
        assert not EVIDENCE_TABLE_RE.search("| Variant | Reviewer does |\n|---|---|\n")
        assert not EVIDENCE_HEADING_RE.search("**Why this exists.** Prose feedback loses it.\n")

    def test_the_catalog_is_actually_being_scanned(self, root):
        """An empty offender list has to mean 'none present', not 'the glob found nothing'."""
        assert len(list(_skill_bodies(root))) >= 15
