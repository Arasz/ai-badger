"""Layer-2 doc tests: the model-tier skill contract prose (PKG-2).

The four canonical doc files carry the same three-clause contract in prose (never
byte-identical files, per S1 — the test checks substrings per file):

  (1) optional `level: low|medium|high` resolved via the registry preferred entry,
  (2) an explicit `model` wins over `level`,
  (3) neither `level` nor `model` inherits the session (or parent) default.

Coverage map (plan Layer 2):

  L2-1 (H2)  optionality wording lives IN the skill file, not only in an extension.
  L2-2 (F14) the skill points at `.ai-badger/delegation.md`; the pointer assertion
             lives here, not in another suite.
  L2-3       no price literals ($/MTok-style) in the four files; the one advisory
             $/task table lives in the changelog only.
  L2-4       the tiers prose names the reasoning-model dispatch section.
  Clauses    all three clauses appear in all four files (substring per file, S1).
  Registry   all four name `.ai-badger/model-groups.json` as the registry home.
  Effort     prose says "model tier" vs "effort", never bare "level" for effort.
  S11        the Claude lane table names tiers, never registry model IDs.
  Pi         the pi extension forwards `--level`/explicit and points at
             pi-badger-integration as normative for argv.

M2 stability: PKG-3 quotes one contract sentence verbatim. The three SUB*
constants below are those sentences' stable cores — keep them byte-stable once
green and flag any wording change loudly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TASK_SKILL = "features/common/skills/task/SKILL.md"
QUICK_SKILL = "features/common/skills/quick-task/SKILL.md"
CLAUDE_EXT = "features/common/skills/task/extensions/claude/extension.md"
PI_EXT = "features/common/skills/task/extensions/pi/extension.md"

FOUR_FILES = (TASK_SKILL, QUICK_SKILL, CLAUDE_EXT, PI_EXT)
SKILL_FILES = (TASK_SKILL, QUICK_SKILL)

# M2-stable cores: verbatim substrings of the canonical contract sentences.
SUB_LEVEL_OPTIONAL = "The `level` field is optional"
SUB_MODEL_WINS = "An explicit `model` always wins over `level`"
SUB_INHERIT = "inherits the session (or parent) default"
CLAUSES = (SUB_LEVEL_OPTIONAL, SUB_MODEL_WINS, SUB_INHERIT)

REGISTRY_PATH = ".ai-badger/model-groups.json"
DELEGATION_POINTER = ".ai-badger/delegation.md"

# $/MTok-style literals: a dollar glued to a number, or an MTok unit. The one
# advisory $/task table lives in the changelog, never in skill prose.
PRICE_RES = (
    re.compile(r"\$\s*\d"),
    re.compile(r"(?i)mtok"),
    re.compile(r"(?i)\$\s*/\s*task"),
)

EFFORT_LEVEL_RE = re.compile(r"(?i)effort[\s_-]level")


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ L2-1 optionality in the skill file (H2)
@pytest.mark.parametrize("rel", SKILL_FILES)
def test_l2_1_level_optionality_wording_lives_in_the_skill_file(root: Path, rel: str) -> None:
    """H2: `level` must read as optional inside SKILL.md, not only in an extension."""
    text = _read(root, rel)
    assert SUB_LEVEL_OPTIONAL in text, f"{rel}: missing {SUB_LEVEL_OPTIONAL!r}"
    for token in ("`low`", "`medium`", "`high`", "preferred"):
        assert token in text, f"{rel}: optionality clause must name {token}"


def test_l2_1_detector_sees_optionality() -> None:
    """The L2-1 predicate is not vacuous: it fires on the canonical sentence."""
    probe = "The `level` field is optional (`low`, `medium`, or `high`), resolved ok"
    assert SUB_LEVEL_OPTIONAL in probe
    assert SUB_LEVEL_OPTIONAL not in "level is required, pick one"


# ------------------------------------------------------------------ L2-2 delegation.md pointer (F14)
def test_l2_2_skill_points_at_delegation_md(root: Path) -> None:
    """F14: the pointer assertion lives here — the skill names delegation.md."""
    text = _read(root, TASK_SKILL)
    assert DELEGATION_POINTER in text, f"{TASK_SKILL}: missing {DELEGATION_POINTER!r}"


def test_l2_2_quick_task_points_at_delegation_md(root: Path) -> None:
    text = _read(root, QUICK_SKILL)
    assert DELEGATION_POINTER in text, f"{QUICK_SKILL}: missing {DELEGATION_POINTER!r}"


# ------------------------------------------------------------------ L2-3 no price literals
@pytest.mark.parametrize("rel", FOUR_FILES)
def test_l2_3_no_price_literals_in_skill_prose(root: Path, rel: str) -> None:
    text = _read(root, rel)
    for rx in PRICE_RES:
        assert not rx.search(text), f"{rel}: price literal matching {rx.pattern!r}"


def test_l2_3_detector_catches_dollar_and_mtok() -> None:
    """Prove the L2-3 check can fail: it must catch $/MTok-style literals."""
    assert PRICE_RES[0].search("costs $0.50 per task")
    assert PRICE_RES[1].search("0.50/MTok blended")
    assert PRICE_RES[2].search("advisory $/task table")
    assert not PRICE_RES[0].search("no prices here, per model mix")
    assert not PRICE_RES[1].search("per model is the durable half")


# ------------------------------------------------------------------ L2-4 reasoning-model section in tiers
def test_l2_4_tiers_prose_names_reasoning_model_dispatch(root: Path) -> None:
    text = _read(root, TASK_SKILL)
    assert "reasoning-model" in text, f"{TASK_SKILL}: tiers prose must name reasoning-model"


def test_l2_4_detector_sees_reasoning_model() -> None:
    assert "reasoning-model" in "See `.ai-badger/delegation.md` (reasoning-model dispatch)"
    assert "reasoning-model" not in "delegate to a high-reasoning agent"


# ------------------------------------------------- clauses in all four files (S1: substring, not identity)
@pytest.mark.parametrize("rel", FOUR_FILES)
@pytest.mark.parametrize("clause", CLAUSES)
def test_contract_clauses_appear_in_every_file(root: Path, rel: str, clause: str) -> None:
    """Each clause as a substring per file — never a byte-identity-4x comparison (S1)."""
    assert clause in _read(root, rel), f"{rel}: missing clause {clause!r}"


def test_clause_check_is_per_file_not_byte_identity() -> None:
    """S1 guard: two files can both carry the clauses yet differ elsewhere."""
    assert "alpha" != "alpha plus tail"
    assert "alpha" in "alpha" and "alpha" in "alpha plus tail"


# ------------------------------------------------------------------ registry home
@pytest.mark.parametrize("rel", FOUR_FILES)
def test_registry_lives_at_model_groups_json(root: Path, rel: str) -> None:
    assert REGISTRY_PATH in _read(root, rel), f"{rel}: missing {REGISTRY_PATH!r}"


# ------------------------------------------------------------------ effort vs model tier
@pytest.mark.parametrize("rel", FOUR_FILES)
def test_effort_vs_tier_wording(root: Path, rel: str) -> None:
    """Prose says 'model tier' vs 'effort', never bare 'level' for effort."""
    text = _read(root, rel)
    assert "model tier" in text, f"{rel}: must say 'model tier', not bare 'level'"
    assert not EFFORT_LEVEL_RE.search(text), f"{rel}: bare 'level' for effort"


def test_effort_detector_catches_effort_level() -> None:
    assert EFFORT_LEVEL_RE.search("two effort levels")
    assert EFFORT_LEVEL_RE.search("effort-level loops")
    assert not EFFORT_LEVEL_RE.search("`effort` (low/high) picks the loop")


# ------------------------------------------------------------------ S11: no registry model IDs in prose
@pytest.mark.parametrize("rel", FOUR_FILES)
def test_no_registry_model_ids_in_skill_prose(root: Path, rel: str) -> None:
    assert "openrouter/" not in _read(root, rel), f"{rel}: must name no registry model ID"


# ------------------------------------------------------------------ Claude lane to tier-default table
def test_claude_lane_to_tier_defaults(root: Path) -> None:
    text = _read(root, CLAUDE_EXT).lower()
    for lane, tier in (("planning", "`high`"), ("implementation", "`medium`"),
                       ("mechanical", "`low`")):
        assert lane in text, f"{CLAUDE_EXT}: missing lane {lane!r}"
        assert tier in text, f"{CLAUDE_EXT}: missing tier default {tier} for {lane}"


# ------------------------------------------------------------------ pi --level forwarding + pbi normative
def test_pi_level_and_explicit_forwarding(root: Path) -> None:
    text = _read(root, PI_EXT)
    assert "--level" in text, f"{PI_EXT}: must state --level forwarding"
    assert "explicit" in text.lower(), f"{PI_EXT}: must state explicit model forwarding"
    assert "pi-badger-integration" in text, f"{PI_EXT}: pbi is normative for argv"
