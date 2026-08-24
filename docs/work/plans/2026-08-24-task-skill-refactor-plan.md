# task-skill-refactor — plan v2 (review findings folded)

**Date:** 2026-08-24
**Worktree:** .ai-badger/worktrees/task-skill-refactor (branch task/task-skill-refactor, rebased on 37568c04)
**Research base:** docs/research/prompt-eng/ (4 docs), 2-lane research MoE, 2-lane review MoE (both APPROVE-WITH-FIXES; all MUST/SHOULD findings folded below).

## Objective

Restructure `features/common/skills/task/SKILL.md` so the pipeline reads
research → PLANNING (plan + plan review) → implement → review → qa,
with per-phase entry/exit conditions, delegation to specialized skills instead of
inlined prose, and a new `git-work` skill covering PR/push/CI-failure cases not owned
by existing skills. All language grounded in docs/research/prompt-eng/.

## Constraints

- gates/skills_lint.py: body ≤ 5000 proxy (chars/4), ≤ 500 lines; description starts
  "Use when", ≤1024 chars; references/ mentions carry a condition word within ±1 line;
  common-stack skills need `scope:`; Gotchas section required.
- Do not duplicate material owned by worktree-agent-isolation, pre-push-gate-debugging,
  or the github extension.
- Never rewrite always-loaded context files mid-task (state.json edits only at finish).
- Version + changelog required for release (VERSION bump on the PR branch).

## Review-driven plan changes (v1 → v2)

1. **No new top-level RESEARCH phase** (architect NIT 6, ask-if-simpler): the existing
   "Review before you plan" step in Phase 1 is *promoted* to a named Research stage with
   an exit gate (research record citing sources), and PLANNING becomes its own phase.
   Phase count grows by one, not two. Renumbering blast radius handled in U2 sweep.
2. **Budget arithmetic corrected** (architect MUST-FIX 1): real U1 savings ≈ 1,450 chars
   (~360 proxy), not ~1,100. Additional extraction required: "The slow suites" section
   and the cache-aware dispatch paragraph move to `references/prompting-rules.md` too.
   U2 additions capped at ~1,800 chars. A1 gate: body ≤ 4,700 proxy post-U2.
3. **git-work scope: default, not optIn** (architect SHOULD-FIX 3,
   tests/test_skill_groups.py:137-142 precedent): task will cite it from Finish;
   citing an opt-in sibling from a default skill is a dangling pointer.
4. **QA stays conditional on test files existing/changing** (architect SHOULD-FIX 4):
   docs-only tasks and no-CI projects get explicit pass paths instead of a false
   "unconditional".
5. **One checklist, not two** (architect SHOULD-FIX 5, derive-or-delete): per-phase
   Entry:/Exit: lines are THE checklist; the end-of-file Verification Checklist is
   rewritten to reference them rather than mirror their content.
6. **Renumbering sweep unit added** (both reviewers' top finding): every hardcoded phase
   reference must change in the same PR:
   - SKILL.md l.40 ("Phase 3"), l.42 ("Phase 2"), l.151, l.267
   - task_tracker.py:335 REMINDER string (pin Phase 1 step numbering)
   - extensions/github/extension.md headings (Phase 2→Execute, Phase 4×2)
   - extensions/copilot/extension.md:13,36 · extensions/claude/extension.md:46
   - references/file-schemas.md:123,174 (ships via SKILL.full.md sync)
7. **Machine gates specified exactly** (test-engineer MUST-FIX 2):
   - A2 = grep '^## Phase [0-9] — ' ordering check + '^## Phase 3 — PLANNING'
     (witness RED against pre-change file before implementing).
   - Every new references/ pointer carries when/if/before within ±1 line
     (existing corpus lint test enforces).
   - Consolidated-checklist tracker mentions keep full script paths
     (TestTaskTrackerIsReachable).
8. **New repo checks stay reviewer commands** for now (test-engineer SHOULD-FIX 4);
   promoting any to gates/ requires REGISTRY provocation per test_every_check_can_fail.py.
9. **Merged-budget test extension** (test-engineer SHOULD-FIX 3): add "task" to
   test_merged_skill_stays_in_budget.py SKILL_NAMES.
10. **Evals declared out of scope but run manually once** (test-engineer NIT 6).
11. **U4 names generated files**: skills/git-work/* mirror, index.json, plugin/marketplace
    version stamps, changelog README row.

## Units

- **U1 extract** (task/SKILL.md + references/prompting-rules.md): ten prompting-rule
  bullets → references file; compress isolation deep-dive 1,243→~600 chars;
  trim --risk blockquote; move slow-suites + cache paragraphs to references.
  Target body ≤ 17,000 chars (≤ 4,250 proxy) after U1.
- **U2 restructure** (same files as U1 — serial): promote Research stage inside Start;
  new PLANNING phase (plan → plan-review step); QA conditional wording fixed;
  per-phase Entry:/Exit: single-line pairs; end checklist derived not duplicated;
  full cross-reference sweep per item 6. Post-U2 budget cap: 4,700 proxy.
- **U3 git-work** (parallel-safe, own directory): features/common/skills/git-work/,
  scope: default, description starts "Use when", sections per lane B outline
  (push failures w/o gate cause / CI triage / PR lifecycle / merge & squash /
  join conflicts / Gotchas / references/case-playbooks.md). Scope-boundary paragraph
  routes to pre-push-gate-debugging and worktree-agent-isolation.
- **U4 wiring & release**: index_build, sync_plugin_skills (creates skills/git-work
  mirror), self-scaffold freshness commit, VERSION → 0.136.0 (minor: new skill +
  behavior), changelog entry + README row, marketplace/plugin stamps,
  merged-budget test extension.

## Acceptance criteria & gates (updated)

| # | Criterion | Gate |
|---|---|---|
| A1 | Body ≤ 4,700 proxy after U2; git-work ≤ 5000 | skills_lint corpus test |
| A2 | Phase order + PLANNING heading present | exact greps witnessed RED first |
| A3 | Entry/Exit lines present each phase; end checklist derived not duplicated | code-reviewer MoE |
| A4 | git-work ships by default; scope boundaries route correctly | skills_lint + test_no_skill_cites_a_sibling |
| A5 | No duplication of isolation/gate-debugging material | code-reviewer MoE + n-gram aid |
| A6 | Language grounded in research docs; positive constraints | review vs docs/research/prompt-eng/ |
| A7 | Full suite green; scaffold freshness; merged-budget incl. task | pytest, verify.sh lanes |

## Parallelism

U1 → U2 serial (same file). U3 parallel with both. U4 last.

## Stop condition

A1–A7 green; Copilot review round clean; squash-merged; state.json updated at finish.
