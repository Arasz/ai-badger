# rbr-p2: Prompt Rules Phase 2 — Hooks & Validation Scripts

## Objective
Implement the remaining automation from the prompt-rules-ranking-framework-plan: hooks and
validation scripts for rules 2, 3, 5, 6, and 8.

## Constraints
- Stdlib-only Python (no new dependencies)
- Hooks must be silent on failure (never block a prompt)
- Every hook/script must have tests (TDD)
- Must pass scaffold-freshness-guard (source files in features/, not .ai-badger/)
- Follow existing patterns from user_prompt_hook.py

## Work items

### W1: Consolidated restart detection (Rule 2B/2C)
**What**: Extend user_prompt_hook.py to count consecutive `f:` feedback markers in the
session's marker-state.json. When 2+ consecutive feedback turns are detected, inject a
consolidated restart advisory via additionalContext.
**Why**: The plan says "after two failed revision turns, restart with one merged prompt."
Currently this is documentation-only; the hook makes it automatic.
**How**: Read marker-state.json, count trailing `f:` entries, inject restart advisory.
**Acceptance**: Test that 1 feedback = no advisory, 2 consecutive = advisory injected.
**Files**: features/common/skills/prompt-markers/scripts/user_prompt_hook.py,
tests/test_user_prompt_hook.py

### W2: Reasoning scaffolding linter (Rule 6B)
**What**: A standalone validation script that scans instruction files and skill docs for
reasoning-model anti-patterns: "think step by step", "analyze this carefully", "produce a
plan before responding", "let's think step by step". Reports matches with file:line.
**Why**: Prevents accidentally adding CoT scaffolding to reasoning-model prompts.
**How**: Stdlib-only Python script, scans .md/.json files, regex-based, returns exit 1 on
match. Can be run as a CI gate or manually.
**Acceptance**: Test that clean files pass, files with anti-patterns fail with correct locations.
**Files**: features/common/skills/maintain-agent-instructions/scripts/reasoning_scaffold_lint.py,
tests/test_reasoning_scaffold_lint.py

### W3: Constraint count validator (Rule 8B)
**What**: A standalone validation script that counts constraint/instruction items in
CLAUDE.md and copilot-instructions.md. Warns when count exceeds a threshold (default 30).
**Why**: Long negative instruction lists are brittle; this surfaces when the list has grown
too large.
**How**: Stdlib-only Python, counts bullet points under "Non-negotiable invariants" sections,
compares to threshold, returns exit 1 on exceed.
**Acceptance**: Test that under-threshold passes, over-threshold fails with count.
**Files**: features/common/skills/maintain-agent-instructions/scripts/constraint_count_lint.py,
tests/test_constraint_count_lint.py

### Threshold note
The constraint-count threshold is **35**, raised from the plan's original 30 after the
nine new prompt-policy invariants pushed this repo's own CLAUDE.md to 31 items. The
implementation and changelog use 35.

### W4: Grounded feedback PostToolUse hook (Rule 3C)
**What**: A PostToolUse hook on Bash that detects non-zero exit codes and captures the
last N lines of stderr/stdout as additionalContext, so the agent has concrete failure
evidence in its next turn instead of relying on vague recollection.
**Why**: Makes grounded feedback automatic — the failure output is injected without the
user having to paste it.
**How**: New hook script, registered in hooks.json for PostToolUse with matcher "Bash".
Reads the tool result from stdin, checks exit code, extracts output tail.
**Acceptance**: Test that zero-exit = silent, non-zero = output captured and injected.
**Files**: features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py,
features/common/hooks/hooks.json,
tests/test_grounded_feedback_hook.py

### W5 (DEFERRED — not in this phase): Critical constraints re-appender (Rule 5B)
**What**: A UserPromptSubmit hook that detects revision turns and appends critical
constraints from the project's invariant list. Deferred: W1 covers the highest-value
revision case; revisit if placement drift proves to be a real problem.
**Status**: Deferred — not part of this phase's scope.

## Parallelism
- W1, W2, W3 are independent (different files, no shared state)
- W4 is serialized after them (hooks.json registration)

## Sequence
1. W1 + W2 + W3 in parallel (independent)
2. W4 (hooks.json change)
3. Re-scaffold, sync, full test suite
4. Commit
