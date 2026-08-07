# Skills optimization audit — agentskills.io best practices vs the distributed corpus

**Date:** 2026-08-07
**Task:** opt-skills — check the distributed skills against agentskills.io best practices, produce general + individual improvement lists, then MoE plan → integrate → MoE review → present.

## Method

- Knowledge base: https://agentskills.io/skill-creation/best-practices (full page read, 8 practice areas).
- Corpus: all 23 distributed SKILL.md files (features/common/skills/ ×22 + features/claude/skills/auto-wm), 3,500 lines, read in full; plus metrics (lines, tokens, frontmatter, sections, linked dirs) measured by script.
- Measured with: `.venv/bin/python3` audit scripts over `features/**/skills/*/SKILL.md`, 2026-08-07.

## The knowledge base, condensed (agentskills.io best practices)

1. **Start from real expertise** — grounded in project-specific material; refine with real execution (execute-then-revise).
2. **Spend context wisely** — add what the agent lacks, omit what it knows ("would the agent get this wrong without this instruction?"); design coherent units; aim for moderate detail (concise stepwise + working example beats exhaustive docs); progressive disclosure: SKILL.md < 500 lines / < 5,000 tokens, details in `references/`, with explicit "read X if Y" conditions.
3. **Calibrate control** — match specificity to fragility; provide defaults, not menus; favor procedures over declarations.
4. **Patterns for instructions** — gotchas sections (highest-value content: concrete corrections to mistakes the agent would make; keep in SKILL.md); templates for output format; checklists for multi-step workflows; validation loops (do → validate → fix → repeat); plan-validate-execute for destructive ops; bundle reusable scripts.

## What the corpus already does well (measured)

- **Descriptions: excellent.** All 23 start "Use when" with concrete trigger phrases, 182–713 chars (spec: max 1024). `name` matches directory. This is the top practice and it is already met.
- **Size: all within the spec budget.** None exceeds 500 lines or 5k tokens. Largest: code-review-checklist 364/4375, mcp-index 266/3643, task 239/3829, call-behaviorist 236/3561, den-refresh 228/3598.
- **Procedures over declarations: strong** (task, den-refresh, welcome-ai-badger, create-task-spec, migrate-documentation are genuinely procedural).
- **Defaults, not menus: strong** (create-task-spec "propose options, never content"; auto-wm "partner (default)").
- **Gotcha-adjacent content exists in ~half the corpus** under 5+ different names (Pitfalls / Common mistakes / Common Pitfalls / Rationalizations / Red flags).
- **Validation loops and plan-validate-execute: strong** (create-task-spec spec_holes.py gate, den-refresh report-then-review, migrate-documentation drain gate, update-documentation evidence gate).
- **Scripts bundled: strong** (scripts/ in 14 skills).
- **Coherent units with explicit disambiguation: strong** ("When NOT to Use" / "What this skill is not" / "Not for X" sections in 10+ skills; `related_skills` metadata in 11).

## General improvements (structural, apply to the corpus as a whole)

### G1 — One gotchas convention, named "Gotchas", applied everywhere
The spec's highest-value content is a gotchas section: concrete corrections to mistakes the agent will make. Today the corpus has no uniform convention: auto-wm "Common mistakes", ai-raccoon-memory "Pitfalls", mcp-index "Common Pitfalls", differential-feature-refactor "Common Pitfalls", migrate-documentation "Rationalizations", plus "Red flags — STOP" sections that serve a *different* function (stop conditions). **Distinguish the two:** stop-conditions stay "Red flags — STOP"; environment-specific corrections get "## Gotchas". Skills lacking any gotcha content: task, welcome-ai-badger, den-refresh, feed-badger, commit-reminder, prompt-markers, maintain-agent-instructions, scaffold-documentation, update-documentation, evidence-first-research, explore-codebase, refactor-safely, review-changes, debug-issue. Many of these have hard-won corrections already embedded in prose (e.g. commit-reminder's "Migration" section, prompt-markers' caching rationale) — lift them into Gotchas.
*Gate:* every distributed skill either has a Gotchas section or a one-line "no environment-specific gotchas known" note.

### G2 — Explicit progressive-disclosure conditions ("read X if Y")
The spec: "Read references/api-errors.md if the API returns a non-200" beats "see references/". Corpus state: references/ exist in 10 skills; several list files at the end ("## Files") without loading conditions (evidence-first-research, owner-gate-review, maintain-agent-instructions), others condition by step (differential, create-task-spec). Standardize: every `references/` file mentioned in SKILL.md carries the condition that triggers reading it. Split the deepest reference tables of the four largest skills into `references/` with triggers (see I1–I4).
*Gate:* grep-check: every "references/..." mention in a SKILL.md body is preceded by or contains a when/if condition.

### G3 — Uniform frontmatter metadata
Only ~11 of 23 skills carry `version`/`author`/`license`/`platforms`/`metadata` (hermes tags + related_skills). The rest (auto-wm, commit-reminder, den-refresh, feed-badger, maintain-agent-instructions, prompt-markers, task, welcome-ai-badger) are bare name+description. The spec makes these optional, but for a *framework* distributing skills, uniform version + license + `metadata.hermes.tags` + `related_skills` makes the catalog machine-consumable (Hermes indexes tags; the mcp-index-style curation pattern applies to skills too).
*Gate:* validate.py (or a skills-lint) checks every feature skill carries the full frontmatter block; index_build emits tags.

### G4 — Machine gate: skills-lint in validate.py
The framework already has `tooling/validate.py` with jsonschema. Add a skills-lint check that enforces the agentskills.io conformance rules the corpus already meets, so drift is caught by CI rather than by reading: name grammar (lowercase-hyphen, ≤64, matches dir), description present + ≤1024 + starts "Use when", SKILL.md ≤500 lines / ≤5k tokens, references/ mentioned only with conditions (G2), frontmatter completeness (G3), gotchas presence (G1). This turns the best-practices page into a gate — the framework's own invariant culture ("Done means proven").
*Gate:* `validate.py --all` (or a new `skills` kind) fails on violations; a test pins each rule; the corpus passes.

### G5 — (CORRECTED) Root skills/ shapes are intentional; the improvement is operational, not structural
Measured then corrected against the source: root `skills/` is the Claude Code plugin distribution directory, **generated** by `tooling/sync_plugin_skills.py` from features/ — it is not drift. The two shapes are deliberate: non-bootstrap skills ship a pointer SKILL.md (frontmatter verbatim, body pointing at `SKILL.full.md`, which carries the full body) so the scaffolded `.ai-badger/` copy wins when present; the three full-copy skills (welcome-ai-badger, den-refresh, feed-badger) are `BOOTSTRAP_SKILLS` that must run before/independent of a scaffold (ADR-0011, version-boundary load-bearing). A `--check` mode and a pre-push gate (`tooling/sync_plugin_skills.py --check`, wired at `.lefthook/pre-push/verify.sh:96` under `plugin-skills`) already guarantee root↔features equality (verified: 0 diff today).
*Improvement:* no shape change. The plan requirement is that **every skill-content edit happens in features/ and is followed by `python3 tooling/sync_plugin_skills.py`** — the gate enforces it, but the plan should say so explicitly so skill edits and their plugin re-sync land in the same commit.
*Gate:* `.lefthook/pre-push/verify.sh` plugin-skills check stays green.

### G6 — Verification-checklist convention for workflow skills
Multi-step workflow skills should end with a verification checklist (spec's checklist pattern; already present in ai-raccoon-memory, mcp-index, differential-feature-refactor, owner-gate-review, evidence-first-research). Missing in the workflow skills: task, den-refresh, welcome-ai-badger, feed-badger, maintain-agent-instructions, commit-reminder, migrate-documentation (has gates, no final checklist), update-documentation (has postconditions per step).
*Gate:* every skill with 4+ procedural steps carries a final "## Verification Checklist".

## Individual improvements (skill → improvement → reason)

| # | Skill (size) | Improvement | Reason |
|---|---|---|---|
| I1 | code-review-checklist (364/4375) | Split Phase 3.3 security + Phase 4.3 observability tables into `references/security.md` / `references/observability.md`, loaded "if the diff touches security/observability surfaces" | Largest skill, at the size ceiling; the two tables are conditional by nature (generic OWASP/ops knowledge the agent has; the value is the checklist form). The rest of the phases stay inline — checklists must load whole. |
| I2 | mcp-index (266/3643) | Move the status-enum table and auto-tagging heuristics table to `references/`, "read when interpreting an `update` result" | Deep reference tables, only needed when a run misbehaves; SKILL.md keeps commands + completion criteria. Also add "When NOT to Use" (align with sibling skills). |
| I3 | call-behaviorist (236/3561) | Move record-key + event + finding tables to `references/`, "read when interpreting `tail`/`analyze` output" | Same shape as I2: dense tables needed only at interpretation time. Add a verification checklist. |
| I4 | den-refresh (228/3598) | Move the error-recovery table to `references/error-recovery.md` ("read when refresh.py exits non-zero"); add final verification checklist | The table is triggered only by failure; flow prose is the always-needed part. |
| I5 | task (239/3829) | Add "## Gotchas" (worktree `keptBecause`, `start` not persisting, hook-merge lessons — currently prose) and "When NOT to use" (a single-file change does not need the full pipeline) | The workflow skill is the most-loaded skill in the corpus; its corrections are buried in admonitions; disambiguation protects activation precision. |
| I6 | commit-reminder (136/1843) | Add "## Gotchas" (escalation bar = new highs not time; git stash clears the counter; hook-only-adds-context contract) | All three are hard-won corrections, currently embedded in prose sections ("Two consequences worth knowing", "Migration"). |
| I7 | feed-badger (100/1258) | Add gotchas (draft PR always; `--path` required; credential scan is a guard not proof) + verification checklist | No pitfalls/checklist today; error-recovery table covers scripts only, not agent judgement traps. |
| I8 | prompt-markers (94/1190) | Add "## Gotchas" (append-vs-prepend cache rationale; hook must be merged into existing arrays; audit is best-effort by design) | Three corrections exist as prose; the best-practice shape is a gotchas list. |
| I9 | welcome-ai-badger (153/2129) | Add final "## Verification Checklist" (scaffold matches stacks, no leakage, plugin commands relayed) | Multi-step flow with verify-step but no checklist artefact; G6's target list. |
| I10 | maintain-agent-instructions (81/882) | Add "## Verification Checklist" + "When NOT to use" (single-file typo fix does not need the model) | Smallest workflow skill; checklist pattern completes it. |
| I11 | ai-raccoon-memory (115/1323) | Add "When NOT to use" (one-off memory lookup vs watch ritual) | Has Pitfalls + checklist already; disambiguation is the remaining gap. |
| I12 | evidence-first-research (119/1501) | Add loading conditions to "## Files" (read provenance.md "when grading a finding", report-template.md "when writing the record") | G2's target: files listed without triggers. |
| I13 | auto-wm (99/2193) | No change needed (gotchas ✓, defaults ✓, checklist-ish ✓) | Control case — the corpus's best alignment with the practices. |
| I14 | differential-feature-refactor, migrate-documentation, update-documentation, owner-gate-review, create-task-spec, explore-codebase, refactor-safely, review-changes, scaffold-documentation, debug-issue | No structural change; migrate/differential get gotchas-convention rename only if G1 adopted wholesale | These already carry the practices (rationalizations, red flags, checklists, references). |

## Still open

- Does the 5k-token budget apply to trigger-specific operational skills (mcp-index, call-behaviorist load only when their question arises)? The spec recommends the budget; the corpus treats it as a ceiling. Decide whether G2-splits are mandatory or recommended.
- Is root `skills/` shipped by scaffold.py at all, or a dev-only convenience? **Answered during the audit (G5 correction):** root `skills/` is the Claude Code plugin distribution dir, generated by `tooling/sync_plugin_skills.py` and gated by the pre-push `plugin-skills` check. Skill edits must be synced after landing.
- Should G4's skills-lint be a new validate kind or part of index_build? (Affects changelog/version shape if released.)
- Corpus serves both Claude Code and Hermes; Hermes indexes `metadata.hermes.tags` — confirm G3 metadata survives scaffolding into `.ai-badger/skills/` (it does today; verify after any frontmatter edits).
