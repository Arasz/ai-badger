# Research-Based Prompt Refactor — ai-badger Framework Analysis

**Date:** 2026-08-23
**Scope:** ai-badger framework (features/common/, features/dotnet/, templates/, scaffold scripts)
**Source:** docs/research/ (4 documents, evidence-graded)

---

## Framework Architecture (how context files are assembled)

```
config.json (stacks, personaRouting, commands)
    ↓ scaffold.py
    ├── collect_invariants() → ALL stack invariants rendered as bullets
    ├── template_rendering.py → fills {{INVARIANTS}}, {{COMMANDS}}, etc.
    ├── CLAUDE.md.tmpl → .ai-badger/CLAUDE.md (copied to project root)
    ├── HERMES.md.tmpl → .ai-badger/HERMES.md
    ├── delegation.md.tmpl → .ai-badger/delegation.md
    └── agent_files.py → copies persona .md files to .ai-badger/agents/
```

**Key constraint:** The template puts ALL invariants into `{{INVARIANTS}}`. No tiering mechanism exists. Every project gets every invariant from every selected stack.

---

## Findings (mapped to framework files)

### 1. CLAUDE.md template — constraint-count tax [HIGH impact, WS evidence]

**File:** `features/common/templates/CLAUDE.md.tmpl`
**Problem:** Template puts ALL invariants at the top. IFEval research: per-constraint compliance compounds multiplicatively. 19 common invariants + stack-specific ones = 20-25 total. At 95% per rule: ~35% overall compliance.
**Fix:** Add a tiering mechanism. Option A: new `tier` field in invariant frontmatter (tier 1 = always loaded, tier 2 = contextual). Option B: split `{{INVARIANTS}}` into `{{CORE_INVARIANTS}}` + `{{CONTEXTUAL_INVARIANTS}}` with a note.
**Complexity:** Requires scaffold script changes.

### 2. CLAUDE.md template — position effects [MEDIUM impact, WS evidence]

**File:** `features/common/templates/CLAUDE.md.tmpl`
**Problem:** Template order: invariants → commands → paths → delegation → markers → MCP → framework. Ends with boilerplate ("Framework" section). Research: beginning and end are strongest positions.
**Fix:** Move a critical invariant or operational rule to the end. Or move MCP instructions above invariants (they're context, not constraints).
**Complexity:** Template-only change.

### 3. CLAUDE.md template — negative framing [MEDIUM impact, WS evidence]

**Files:** `features/common/invariants/no-hand-rolled-crypto.md`, `features/common/invariants/no-hardcoded-secrets.md`
**Problem:** "No hand-rolled crypto" and "No hardcoded secrets" use negative framing. Research: positive specs have higher compliance.
**Fix:** Rewrite as positive: "Use platform security APIs" and "Store secrets outside tracked files."
**Complexity:** Invariant file edits only.

### 4. Persona descriptions — length [MEDIUM impact, WS evidence]

**Files:** All 7 persona files in `features/common/personas/` and `features/dotnet/personas/`
**Problem:** Descriptions are 67-110 words. Research: "one short, task-naming line." Irrelevant details cause up to 30pp degradation.
**Fix:** Trim each to ~15-20 words (role line + one key constraint). Move "Use for..." guidance to the body.
**Complexity:** Frontmatter edits only.

### 5. code-reviewer — third-person framing [MEDIUM impact, WS evidence]

**File:** `features/common/personas/code-reviewer.md`
**Problem:** No third-person framing guidance. Research (SYCON Bench): third-person framing reduces sycophancy by up to 63.8%.
**Fix:** Add section: "Frame findings as objective criteria ('the spec requires X') rather than personal opinion."
**Complexity:** Body edit only.

### 6. code-reviewer — escalation rule [MEDIUM impact, WS evidence]

**File:** `features/common/personas/code-reviewer.md`
**Problem:** No restart-after-2-failed-rounds rule. Research (Laban et al.): consolidated restart recovers ~95% of single-turn quality.
**Fix:** Add escalation section.
**Complexity:** Body edit only.

### 7. delegation template — reasoning-model dispatch [MEDIUM impact, WS evidence]

**File:** `features/common/templates/delegation.md.tmpl`
**Problem:** No guidance for reasoning models. Research: CoT scaffolding, prescriptive steps, and few-shot examples are counterproductive on reasoning models.
**Fix:** Add a `## Reasoning-model dispatch` section to the template (after `{{PERSONA_ROUTING}}`).
**Complexity:** Template edit only.

### 8. documentation instructions — humanization [LOW-MEDIUM impact, S evidence]

**File:** `features/common/instructions/documentation.instructions.md`
**Problem:** No humanization rules. Research: AI text detection relies on burstiness, perplexity, vocabulary signatures.
**Fix:** Add humanization section (burstiness, banned vocabulary, active voice).
**Complexity:** Instruction file edit only.

### 9. Invariant files — positive framing for all [LOW impact, WS evidence]

**Files:** Several invariants use "Never" or "No" framing
**Problem:** Negative constraints have lower compliance (IFEval, SysBench).
**Fix:** Audit all 19 common invariants and rewrite negative ones as positive.
**Complexity:** Invariant file edits.

### 10. Template — MCP instructions position [LOW impact, WS evidence]

**File:** `features/common/templates/CLAUDE.md.tmpl`
**Problem:** MCP instructions are near the end, after invariants. They're context, not constraints.
**Fix:** Move `{{MCP_INSTRUCTIONS}}` above `## Non-negotiable invariants`.
**Complexity:** Template edit only.

---

## Implementation Plan

### Phase 1: Template + scaffold changes (framework-level)
1. Edit `CLAUDE.md.tmpl` — reorder sections, add position-effects note
2. Edit `HERMES.md.tmpl` — same reordering
3. Edit `delegation.md.tmpl` — add reasoning-model dispatch section

### Phase 2: Persona changes (framework-level)
4. Trim all 7 persona descriptions to ~15-20 words
5. Add third-person framing to code-reviewer
6. Add escalation rule to code-reviewer

### Phase 3: Invariant + instruction changes (framework-level)
7. Rewrite no-hand-rolled-crypto.md as positive
8. Rewrite no-hardcoded-secrets.md as positive
9. Add humanization rules to documentation.instructions.md

### Phase 4: Scaffold tiering (framework-level, larger change)
10. Add `tier` field to invariant frontmatter schema
11. Update `scaffold.py` to split core vs contextual invariants
12. Update template to render core invariants in CLAUDE.md, contextual in path-specific instructions

---

## What stays in ai-raccoon (project-local)

- `docs/research/research-synthesis-report.md` — the evidence report
- `tests/test_context_refactor.py` — validation tests (adapted for upstream)
