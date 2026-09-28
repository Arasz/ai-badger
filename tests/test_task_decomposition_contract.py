"""Contract tests for the `task-decomposition` skill (plan S9; DR8/DR11/DR12/DR13).

The skill is the interface every planning lane reads: the five decomposition rules, the
join rule, the 12 frozen tool names, and the degraded path that must not be discovered
late. These tests pin the parts a future rewrite could silently drop — including the four
stale tool names the pre-freeze sections used, which must never reappear as if callable.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "features" / "common" / "skills" / "task-decomposition"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCE_DIR = SKILL_DIR / "references"
REFERENCES = ("decomposition-method.md", "plan-vocabulary.md", "mcp-plan-tools.md")

# §2's frozen 12-tool surface; the skill may only ever teach these.
FROZEN_TOOLS = (
    "plan_create", "plan_replace", "plan_get", "plan_export", "step_get", "step_start",
    "step_complete", "step_fail", "step_skip", "ac_check", "steps_ready",
    "progress_checklist",
)
# Pre-freeze names the section documents used. R1-F5: a committed skill must never tell an
# agent to call a tool the server does not expose.
STALE_TOOLS = ("plan_build", "plan_progress", "ac_record", "plan_state")

SECTION_HEADINGS = (
    "## When to Use",
    "## When NOT to Use",
    "## Inputs",
    "## The decomposition contract",
    "## Steps and the join rule",
    "## Recording the plan",
    "## Gotchas",
    "## Verification checklist",
)

RULE_PATTERNS = {
    "granularity": r"\bgranularity\b",
    "actionability": r"\bactionability\b",
    "error propagation": r"\berror[- ]propagation\b",
    "completeness": r"\bcompleteness\b",
    "stop rules": r"\bstop[- ]rules\b",
}

# §2's exact CLI form. Every gate string and every lane brief quotes this line.
CLI_COMMAND = ("uv run --script .ai-badger/skills/task-decomposition/scripts/"
               "task_graph_cli.py <tool-name> --json <args>")
DEGRADED_FILE = ".ai-badger/task-tracking/plans/<YYYY-MM-DD>-<taskId>.md"
HANDWRITTEN_BANNER = "hand-written — graph off"


def _skill_text() -> str:
    assert SKILL_MD.is_file(), f"{SKILL_MD.relative_to(ROOT)} does not exist"
    return SKILL_MD.read_text(encoding="utf-8")


def _reference_text(name: str) -> str:
    path = REFERENCE_DIR / name
    assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
    return path.read_text(encoding="utf-8")


class TestTheSkillIsACatalogDefault:
    """The skill must exist where the catalog discovers it and declare common default scope."""

    def test_the_skill_directory_and_skill_md_exist(self):
        assert SKILL_DIR.is_dir(), f"{SKILL_DIR.relative_to(ROOT)} is missing"
        assert SKILL_MD.is_file()

    def test_frontmatter_declares_the_frozen_identity(self, load_script):
        fields = load_script("gates/skills_lint.py").frontmatter_fields(_skill_text())

        assert fields is not None, "frontmatter does not parse with the lint's own reader"
        assert fields.get("name") == "task-decomposition"
        assert fields.get("scope") == "default"
        description = fields.get("description", "")
        assert description.startswith("Use when"), description[:80]
        assert len(description) <= 1024


class TestTheDecompositionContractIsNamed:
    """The five rules and the join rule are the method; unnamed rules do not survive a rewrite."""

    def test_the_five_rule_names_are_present(self):
        text = _skill_text()

        missing = [label for label, pattern in RULE_PATTERNS.items()
                   if not re.search(pattern, text, re.IGNORECASE)]

        assert not missing, f"SKILL.md never names: {', '.join(missing)}"

    def test_the_join_rule_and_derived_integration_flag_are_stated(self):
        text = _skill_text()

        assert "join step" in text
        assert "integration_ok" in text
        assert "derived" in text

    def test_every_contract_heading_is_present(self):
        text = _skill_text()

        missing = [heading for heading in SECTION_HEADINGS if heading not in text]

        assert not missing, f"SKILL.md is missing headings: {missing}"


class TestTheReferencesAreWiredWithConditions:
    """Each reference must exist and every mention must say when to read it (skills_lint rule 8)."""

    def test_the_three_reference_files_exist_and_are_not_empty(self):
        for name in REFERENCES:
            path = REFERENCE_DIR / name
            assert path.is_file(), f"references/{name} is missing"
            assert path.stat().st_size > 0, f"references/{name} is empty"

    def test_every_reference_mention_carries_a_when_condition(self, load_script):
        text = _skill_text()
        lint = load_script("gates/skills_lint.py")

        for name in REFERENCES:
            assert f"references/{name}" in text, f"SKILL.md never points at references/{name}"
        unguarded = lint.references_without_conditions(text.splitlines(), SKILL_DIR.name)

        assert unguarded == [], (
            f"references/ mentions without a when/if/before/after condition: {unguarded}")


class TestTheRecordingContractIsExplicit:
    """DR12's degraded path, the exact CLI form, and R-B's honest first-run wording."""

    def test_the_degraded_path_is_written_out(self):
        text = _skill_text()

        for needle in (DEGRADED_FILE, "**S<N>", "hand-written", HANDWRITTEN_BANNER,
                       "tracking.db", "graph is off"):
            assert needle in text, f"SKILL.md never states {needle!r}"

    def test_the_exact_cli_command_is_present(self):
        assert CLI_COMMAND in _skill_text()
        assert CLI_COMMAND in _reference_text("mcp-plan-tools.md")

    def test_the_first_run_uv_cache_note_is_honest(self):
        text = _skill_text()

        assert "cold" in text
        assert "pydantic" in text

    def test_the_spec_json_input_and_coverage_rule_are_stated(self):
        text = _skill_text()

        assert "spec.json" in text
        assert re.search(r"non-deferred", text, re.IGNORECASE), (
            "the DR13 coverage rule (every non-deferred spec scenario maps to a step AC) "
            "is not stated")


class TestTheFrozenToolSurface:
    """The tools reference names all 12 frozen tools; the whole skill teaches none of the stale."""

    def test_the_tools_reference_names_all_twelve(self):
        text = _reference_text("mcp-plan-tools.md")

        missing = [name for name in FROZEN_TOOLS if name not in text]

        assert not missing, f"references/mcp-plan-tools.md omits: {missing}"

    def test_no_stale_tool_name_survives_anywhere_in_the_skill(self):
        stale = []
        for path in sorted(SKILL_DIR.rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            stale.extend(f"{path.relative_to(SKILL_DIR)}: {name}"
                         for name in STALE_TOOLS if name in text)

        assert not stale, (
            "the skill names a tool the server does not expose: " + "; ".join(stale))


class TestTheMethodReferenceCarriesTheWorkedMethod:
    """The method reference, not just the SKILL summary, must carry the MoE handoff."""

    def test_the_moe_handoff_is_documented(self):
        text = _reference_text("decomposition-method.md")

        assert "panel" in text
        assert "synthesizer" in text
        assert "plan_create" in text
