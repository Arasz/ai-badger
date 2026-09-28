"""Vocabulary pin for the task/quick-task pipeline rewrite (plan S10; P3-C2 + R3-F10).

The rewrite retires the package vocabulary in favour of `step` across the task pipeline:
the plan is a `task-plan` whose `workflow` is a DAG of `step`s, built by
`task-decomposition` and recorded with the frozen 12-tool surface. This file is the pin —
one required phrase per rewritten row, every owned file carrying at least one row (a
silently skipped file fails), the DR12 legacy-plan sentence, the loop/effort axis
disambiguation, the quick-task boundary, and the forbidden strings: the retired vocabulary
and the four pre-freeze tool names that must never reappear as if callable.

Phrases are matched against whitespace-normalized text, so a row survives re-wrapping but
not silent removal.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "features" / "common" / "skills"
PERSONAS = ROOT / "features" / "common" / "personas"

# Every file the S10 rewrite owns. REWRITTEN_ROWS must cover this set exactly; a file that
# exists but has no row — a silently skipped row — fails test_every_owned_file_has_a_row.
OWNED_FILES = {
    "task/SKILL.md": SKILLS / "task" / "SKILL.md",
    "task/extensions/github/extension.md":
        SKILLS / "task" / "extensions" / "github" / "extension.md",
    "task/extensions/claude/extension.md":
        SKILLS / "task" / "extensions" / "claude" / "extension.md",
    "multi-agent-communication/SKILL.md":
        SKILLS / "multi-agent-communication" / "SKILL.md",
    "worktree-agent-isolation/SKILL.md":
        SKILLS / "worktree-agent-isolation" / "SKILL.md",
    "worktree-agent-isolation/references/shared-worktree-collisions.md":
        SKILLS / "worktree-agent-isolation" / "references" / "shared-worktree-collisions.md",
    "complete-project-scope-code-review/SKILL.md":
        SKILLS / "complete-project-scope-code-review" / "SKILL.md",
    "quick-task/SKILL.md": SKILLS / "quick-task" / "SKILL.md",
}

# (file, row, required phrase) — the P3-C2 rewrite map in document order, then the R3-F10
# loop/effort rows, the DR12 sentence, and the three boundary notes the map adds.
REWRITTEN_ROWS = [
    ("task/SKILL.md", ":7 description",
     "`task-decomposition` into a `task-plan` whose `workflow` is a DAG of `step`s"),
    ("task/SKILL.md", ":44 loop axis",
     "ask the user whether the task runs the low or high `loop`"),
    ("task/SKILL.md", ":58-59 integration step",
     "carries a join step when the `workflow` has more than one sink; it depends on every "
     "sink and carries the cross-step tests"),
    ("task/SKILL.md", ":67-68 plan step",
     "Every step has ACs; the plan AC: all steps' ACs checked+met"),
    ("task/SKILL.md", ":134 loop/effort axis sentence",
     "The task `loop` (low|high) chooses the orchestration loop; a step's `effort` "
     "(low|medium|high) drives model-tier selection"),
    ("task/SKILL.md", ":134 model-tier precedence",
     "explicit `model` > `level` > the step's `effort` used as the level > the session "
     "(or parent) default model"),
    ("task/SKILL.md", ":142-144 shared-file steps",
     "name shared-file steps, which serialise by a `depends_on` edge or a merge, versus "
     "disjoint steps, which parallelise"),
    ("task/SKILL.md", ":166 phase-1 exit",
     "Exit: loop chosen, tracker STARTED"),
    ("task/SKILL.md", ":169 determine the loop",
     "**Determine the loop.**"),
    ("task/SKILL.md", ":206 phase-2 exit",
     "Exit: reviewed `task-plan` recorded; every step carries criteria and a gate; "
     "shared-file steps serialised by an edge; join step present when >1 sink"),
    ("task/SKILL.md", ":212-216 decomposition paragraph",
     "Run `task-decomposition`; the result is one validated `task-plan` whose `workflow` "
     "is a DAG of `step`s"),
    ("task/SKILL.md", ":212-216 plan_create recording",
     "Record the plan with `plan_create`; with no server available, write the plan file "
     "by hand in the frozen shape and say the graph is off"),
    ("task/SKILL.md", ":212-216 depends_on order",
     "`depends_on` is the only ordering source"),
    ("task/SKILL.md", ":212-216 plan AC",
     "all steps' ACs are checked and met"),
    ("task/SKILL.md", "DR12 legacy sentence",
     "keeps its legacy plan file and manual checkboxes — never `plan_create` over an "
     "in-flight task"),
    ("task/SKILL.md", ":223-224 ready set/waves",
     "The server derives the ready set and waves via `steps_ready`"),
    ("task/SKILL.md", ":226-231 every step AC+gate",
     "Every step carries acceptance criteria and a quality gate"),
    ("task/SKILL.md", ":239-240 lane-brief serialisation",
     "steps sharing a file serialise (add a `depends_on` edge or merge them), the rest "
     "parallelise"),
    ("task/SKILL.md", ":257 commit per step",
     "Commit and push per step"),
    ("task/SKILL.md", ":262 phase-4 entry",
     "Entry: every step complete, all ACs checked and committed in the worktree"),
    ("task/SKILL.md", ":286 steps into one change",
     "steps into one change"),
    ("task/SKILL.md", ":364 checklist row",
     "Every step's acceptance gate ran; all step ACs checked; join step carried the "
     "cross-step tests"),
    ("task/SKILL.md", ":366 checklist loop",
     "Task `loop` (low or high) was determined before implementation began"),
    ("task/extensions/github/extension.md", ":38 per-step push",
     "Commit and push as each step lands"),
    ("task/extensions/claude/extension.md", ":49 step arbitration",
     "arbitration when two steps disagree about a contract"),
    ("multi-agent-communication/SKILL.md", ":40 step/join boundaries",
     "Broadcast at step/join boundaries"),
    ("worktree-agent-isolation/SKILL.md", ":228 after a step lands",
     "the first full-suite run after a step lands"),
    ("worktree-agent-isolation/references/shared-worktree-collisions.md", ":3 parallel steps",
     "parallel steps can still land in the SAME worktree"),
    ("complete-project-scope-code-review/SKILL.md", "handoff note",
     "A review work package becomes a `step` when the review plan is handed to `task`"),
    ("quick-task/SKILL.md", ":54-56 boundary sentence",
     "Do not call `task-decomposition` and do not create graph state — a quick-task has "
     "no plan artifact; a change needing decomposition is `task` work; escalate"),
]

# The pre-freeze tool names (DR11/R1-F5): a committed surface must never teach a call the
# server does not expose.
STALE_TOOLS = ("plan_build", "plan_progress", "ac_record", "plan_state")


def _text(key: str) -> str:
    path = OWNED_FILES[key]
    assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
    return path.read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class TestEveryRewrittenRowCarriesItsNewPhrase:
    """One assertion per rewritten row; a missing row, file or phrase cannot hide."""

    def test_every_owned_file_has_a_row(self):
        covered = {key for key, _row, _phrase in REWRITTEN_ROWS}
        missing = sorted(set(OWNED_FILES) - covered)

        assert not missing, f"owned files with no rewritten row (silently skipped): {missing}"

    @pytest.mark.parametrize(
        ("key", "row", "phrase"),
        REWRITTEN_ROWS,
        ids=[f"{key}:{row}" for key, row, _phrase in REWRITTEN_ROWS],
    )
    def test_row_carries_its_new_phrase(self, key, row, phrase):
        text = _normalized(_text(key))

        assert phrase in text, f"{key} [{row}]: missing required phrase {phrase!r}"


class TestRequiredVocabularyIsPresent:
    """The words the rewrite exists to install, pinned outside any single row."""

    def test_task_skill_names_the_skill_the_artifact_and_the_unit(self):
        text = _normalized(_text("task/SKILL.md"))

        for needle in ("task-decomposition", "task-plan", "step", "join step"):
            assert needle in text, f"task/SKILL.md never names {needle!r}"

    def test_loop_and_effort_axes_are_disambiguated(self):
        text = _normalized(_text("task/SKILL.md"))

        assert "The task `loop` (low|high) chooses the orchestration loop" in text
        assert "step's `effort` (low|medium|high) drives model-tier selection" in text

    def test_dr12_legacy_sentence_is_present(self):
        text = _normalized(_text("task/SKILL.md"))

        assert "keeps its legacy plan file and manual checkboxes — never `plan_create` " \
               "over an in-flight task" in text

    def test_quick_task_boundary_sentence_is_present(self):
        text = _normalized(_text("quick-task/SKILL.md"))

        assert "a quick-task has no plan artifact; a change needing decomposition is " \
               "`task` work; escalate" in text


class TestRetiredVocabularyAndStaleToolsAreGone:
    """The forbidden strings: a rewrite that leaves one behind has not retired anything."""

    def test_no_owned_file_says_subpackage(self):
        hits = sorted(key for key in OWNED_FILES if "subpackage" in _text(key).lower())

        assert not hits, f"subpackage survives in: {hits}"

    def test_task_skill_drops_the_package_vocabulary(self):
        # Every "package" occurrence in task/SKILL.md was a C2 row; the retired word must
        # be gone, and with it the named integration-package sentence.
        text = _normalized(_text("task/SKILL.md")).lower()

        assert not re.search(r"\bpackages?\b", text), "task/SKILL.md still says 'package'"
        assert "last package is the integration package" not in text

    def test_task_skill_has_no_legacy_P_heading(self):
        assert "**P<N>**" not in _text("task/SKILL.md")

    def test_no_stale_tool_name_in_any_owned_file(self):
        hits = []
        for key in sorted(OWNED_FILES):
            text = _text(key)
            hits.extend(f"{key}: {name}" for name in STALE_TOOLS if name in text)

        assert not hits, f"stale pre-freeze tool names: {hits}"
