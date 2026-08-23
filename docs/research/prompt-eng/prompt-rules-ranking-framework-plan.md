# Prompt-engineering best practices for this framework

This note fuses the three research files in this directory and filters the result down to the rules that have a clear payoff for short-horizon agent work. It also maps each rule to concrete application points in this repo's ai-badger framework.

## 1) Best-practice ranking after removing no-gain rules

These are the rules that remain after dropping neutral/low/negative patterns (generic personas, emotional framing, ungrounded self-critique, prompt-only JSON constraints, etc.).

| Rank | Name | Rule | Estimated gain / lose | Sources |
|---:|---|---|---|---|
| 1 | One-turn specification | Put the full task, constraints, data, and success criteria in the first prompt; keep the operative ask last. | Very high. Avoids the large multi-turn drop documented in short-horizon work; best lever for ≤5-message workflows. | Laban et al. 2025 (multi-turn loss), MT-Eval, cross-model synthesis |
| 2 | Consolidated restart | If a revision fails twice, restart with one merged prompt instead of continuing the same thread. | Very high. ~95% recovery vs ~15–20% for recap/restatement. | Laban et al. 2025 |
| 3 | Grounded feedback | Correct using tests, compiler output, validator output, retrieved facts, or source citations—not vague doubt or “try again.” | High. Grounded feedback works; self-critique without grounding often hurts. | Huang et al. 2024; Reflexion/CRITIC; Sharma et al. 2024 |
| 4 | Tool schema + success criteria beats persona | Spend more effort defining tool schemas, parameters, stop conditions, and outcome predicates than on role text. | High. Tool field edits can shift success by several points; missing param details can cost multiple points. | DocsChisel; Trace-Free+; τ-bench |
| 5 | Critical instruction placement | Put the most important instructions at the start and end; avoid burying them in the middle. | Moderate-high. Better stability; up to +6pp in some settings. | Liu et al. 2024; demos-at-start work |
| 6 | Reasoning scaffolding minimization | Remove “think step by step,” prescriptive CoT plans, and few-shot CoT on reasoning models. Use CoT only on math/symbolic standard-model tasks. | Moderate-high. Often neutral-to-positive on reasoning models; can help math but hurt otherwise. | Wei/Kojima; Sprague et al.; vendor docs |
| 7 | Schema for final output, free-form reasoning before finalization | Use API/schema enforcement for final structured output, but do not force reasoning to be compressed into prompt-only JSON. | Moderate-high. Avoids reasoning tax while preserving parsing guarantees. | Tam et al. 2024; OpenAI Structured Outputs |
| 8 | Positive constraints + machine validation | Prefer positive phrasing and enforce requirements with validators, regex, AST/test checks rather than long negative lists. | Moderate. Every added rule compounds and reduces compliance. | IFEval; promptfoo; SysBench |
| 9 | Few-shot only for format | Use one or two examples only when output format is the problem; place examples at the start. | Low to moderate. Often format-tuning, not capability. | Min et al. 2022; Golovneva et al.; POSIX |

## 2) Rejected rules: removed because the net gain is near zero or negative

| Rule | Why removed |
|---|---|
| Generic persona text | No reliable objective-task gain; can inject variance and degrade performance. |
| Emotional/incentive framing | Older model-era findings do not generalize; too unreliable for real frameworks. |
| Unassisted self-critique | Often reduces reasoning accuracy; vague doubt triggers sycophancy. |
| Prompt-only JSON everywhere | Useful for parseability but often harms reasoning; better via schema + free-form reasoning. |
| Long system prompt as a capability lever | No robust evidence; it dilutes attention and adds rule-count tax. |
| “Magic XML” as accuracy lever | Good for parsing, not proven for accuracy. |
| Heavy auto-optimization as default | Useful in some fixed pipelines, but not a general rule for short-horizon tasks. |

## 3) Rule-by-rule framework application plan

The ai-badger framework has four natural insertion points:

1. Always-loaded instruction files: `.ai-badger/CLAUDE.md`, `.ai-badger/copilot-instructions.md`, `.ai-badger/agent-instructions/*`
2. Skills: `.ai-badger/skills/*` and their `SKILL.md` docs
3. Hooks: `.ai-badger/hooks/hooks.json` + scripts under `.ai-badger/skills/.../scripts/`
4. Validation: repo-local checks or CI-style scripts for prompt quality and output constraints

Below, each rule maps to at least two application surfaces in the framework.

### Rule 1: One-turn specification

Why it matters:
- Short-horizon tasks degrade sharply across turns, even at 2 turns.
- Full specification early is the highest-value intervention.

Framework application ideas:
- A. Add a ritual to `.ai-badger/CLAUDE.md` / `.ai-badger/copilot-instructions.md`: “For any task, include objective, constraints, data inputs, and success criteria in the first user message. Place the final ask last.”
- B. Extend the `task` skill to enforce a preflight checklist before dispatching a prompt or agent: required fields = objective, constraints, known unknowns, output contract, stop condition.
- C. Add a `UserPromptSubmit` hook (or hook script in `prompt-markers`) that warns when a prompt is missing the task specification blocks or appears to be revision-heavy without a consolidated summary.
- D. Add a validation script in `.ai-badger/skills/maintain-agent-instructions/` or a task QA check that flags tasks with no success criteria.

Representative change in plain English:
- “Any prompt that does not contain objective + constraints + output contract + success criteria in the first turn is invalid until corrected.”

### Rule 2: Consolidated restart

Why it matters:
- Continued chat recovers poorly. Restart is substantially better than incremental correction.

Framework application ideas:
- A. Add a prompt marker `f:` or `i!:` behavior in `.ai-badger/skills/prompt-markers/` to explicitly say: if a task has already had two revision turns, restart with a merged prompt.
- B. Add a new skill such as `conversation-restart` or extend the existing `task` skill to detect a second revision turn and trigger a “rebuild prompt from source-of-truth” workflow.
- C. Add a small hook that compares the last two assistant turns and detects drift or repeated failure patterns; if triggered, it appends a system note: “restate the full task and restart.”
- D. Add an output rule in `CLAUDE.md`: “Never continue a failed multi-turn patch beyond two feedback rounds; consolidate and restart.”

Representative change:
- “Revision loop policy: max 2 targeted corrections; after that, rebuild a single merged prompt containing all prior requirements.”

### Rule 3: Grounded feedback

Why it matters:
- External evidence is the only reliable corrective signal.

Framework application ideas:
- A. Expand `prompt-markers` so `f:`/`feedback:` markers require a structured correction block: failing check, exact error, expected behavior, affected scope.
- B. Add a validation rule to the `task` skill: revision prompts must cite a specific failing evidence source (test name, log snippet, file line, or validator result).
- C. Add a hook around `Bash`/`Python` execution or test runs that automatically captures failure output and injects it into the correction prompt, reducing vague feedback.
- D. Add a rule in `CLAUDE.md` to prefer “source-backed” feedback over “I think” or “this seems wrong.”

Representative change:
- “Feedback turns must include a concrete failure artifact: failing test, error message, or source contradiction, and an explicit expected result.”

### Rule 4: Tool schema + success criteria > persona

Why it matters:
- Most of the quality in an agent sits in tools, stop conditions, and outcome checks, not in role prose.

Framework application ideas:
- A. Update `.ai-badger/agent-instructions/model.json` and the generated instruction files so tool descriptions, parameter rules, and stop conditions are explicit and non-optional.
- B. Improve `task` skill instructions to require an “operator contract” for each delegated agent: tool names, when-to-use, when-not-to-use, abort criteria, success predicate.
- C. Add a review check that compares tool descriptions to actual API signatures or actual tool availability; this can live in a script or validation gate under `.ai-badger/skills/maintain-agent-instructions/`.
- D. Add agent-specific implementation guidelines for each persona in `.ai-badger/agents/` or generated instruction files: preserve outcome predicates and tool parameters before writing role text.

Representative change:
- “Every agent definition must include: schema, success predicate, stop condition, and handoff conditions. Persona text is optional and should be one short line only.”

### Rule 5: Critical instruction placement

Why it matters:
- Position strongly affects what gets followed.

Framework application ideas:
- A. Add a canonical prompt template to `.ai-badger/CLAUDE.md` with fixed sections: role, objective, constraints, context, output contract, success criteria.
- B. Extend `prompt-markers` or `UserPromptSubmit` to append required restatements of critical constraints at the end of a revision prompt, keeping them near recency.
- C. Add a lint-like script to scan prompts for key constraints buried in the middle of long context blocks; flag them as low-priority or ask for reorder.
- D. Add a rule in any skill or task template to keep the final ask at the end and the “must not do” constraints near the top.

Representative change:
- “Prompt order: role -> objective -> constraints -> context -> output contract -> final ask. Critical requirements must be in the first or last block, never buried in middle context.”

### Rule 6: Reasoning scaffolding minimization

Why it matters:
- Many standard-model prompt tricks are obsolete or harmful on modern reasoning-capable models.

Framework application ideas:
- A. Add a default instruction in `.ai-badger/CLAUDE.md`: “Do not instruct reasoning models to ‘think step by step’ or to produce a prescriptive plan unless the task genuinely requires it.”
- B. Add a new validation rule or skill check to scan for strings like “think step by step,” “analyze this carefully,” and “produce a plan before responding,” and flag them when the target model is a reasoning model.
- C. Extend the `task` skill or a `reasoning-model-policy` prompt template so it distinguishes standard-model and reasoning-model prompting.
- D. Add a prompt-library file in the research folder or a docs note explaining when CoT is helpful vs harmful; keep it in the repo as a policy reference.

Representative change:
- “Reasoning-model prompts should state the goal, constraints, and success criteria; avoid process instructions and few-shot CoT unless you have a specific verified benefit.”

### Rule 7: Schema for final output, free-form reasoning before finalization

Why it matters:
- Strict prompt-only output encoding can suppress reasoning.

Framework application ideas:
- A. Add an output-contract rule in `.ai-badger/CLAUDE.md` and generated instruction files: reason in a free-form block, then return a validated schema or final answer at the end.
- B. Add a mini skill or template for structured outputs that defines `analysis`, `result`, `errors`, `unresolved`, and optional `confidence` fields with explicit ordering.
- C. Add a hook or validation step that catches output that mixes reasoning and final answer awkwardly or returns malformed JSON when the task is reasoning-heavy.
- D. Add examples in the `task` skill or an agent artifact showing the “reason first / validate second / emit result last” pattern.

Representative change:
- “If the task requires structure, emit the final schema last; do not require the model to compress its reasoning into the schema itself.”

### Rule 8: Positive constraints + machine validation

Why it matters:
- Long negative instruction lists and rule stacks are brittle.

Framework application ideas:
- A. Add guidance in `.ai-badger/CLAUDE.md` to always prefer positive phrasing: “state what must be true,” not “do not do X, Y, Z.”
- B. Create a validation skill or script that warns when more than N constraints are present in a prompt or task template and suggests collapsing or rephrasing them.
- C. Add hook-based checks around prompt submission to validate the presence of explicit success criteria and output contract, and to look for impossible or conflicting rules.
- D. Use `maintain-agent-instructions` or project validation scripts to ensure these templates stay aligned with the model and do not drift.

Representative change:
- “Keep the prompt to the minimum surviving constraints; prefer assertions and validators over long negative instruction lists.”

### Rule 9: Few-shot only for format

Why it matters:
- Examples help with form, not capability. They are often overused.

Framework application ideas:
- A. Add a “zero-shot preferred” rule in the base instruction files and task templates.
- B. Add a small template or skill that tells agents: “if examples are needed, include 1–3 format examples and place them at the start of the message, not after the task request.”
- C. Add a hook or script that detects excessive example-heavy prompts and suggests collapsing them into direct instructions.
- D. Add docs or a policy note in the research folder clarifying that examples should teach output shape, not model behavior.

Representative change:
- “Examples are a format tool, not a reasoning tool. Start zero-shot; add examples only when the output format is the critical failure mode.”

## 4) Recommended implementation priority for this repo

If we apply these to ai-badger itself, the highest-return sequence is:

1. Update the always-loaded instruction files first: `.ai-badger/CLAUDE.md`, `.ai-badger/copilot-instructions.md`, and `.ai-badger/agent-instructions/model.json`
2. Extend the `task` skill with a brief preflight checklist and revision-loop policy
3. Add a `UserPromptSubmit` hook or prompt marker behavior for grounded feedback and consolidated restart
4. Add a light validation script for prompt complexity, critical-instruction placement, and rule-count tax
5. Re-run the repo’s documentation/instruction validation and check for drift

This gives the framework a strong default prompt policy without bloating every prompt.

## 5) Final recommendation

The best rule set for ai-badger is not “be more verbose” or “add role-play.” It is:

- specify all requirements in one turn,
- prefer grounded corrections over vague critique,
- minimize reasoning scaffolding,
- enforce output contracts at the end,
- keep tool and success definitions explicit,
- and treat prompt length/rule count as a real cost center.

That is the strongest, most defensible strategy for a short-horizon, prompt-heavy framework like this one.
