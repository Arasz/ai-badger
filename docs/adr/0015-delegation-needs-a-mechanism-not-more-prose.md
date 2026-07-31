# ADR-0015 — Delegation needs a mechanism, not more prose

**Date:** 2026-07-31
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude
**Supersedes:** Nothing.

## Context

A delegation policy already exists in this repository, written out in two places: the
**"Model & delegation policy"** section of `features/common/skills/task/SKILL.md`, and the model
lanes in `features/common/skills/task/extensions/claude/extension.md`. The persona routing table
from `.ai-badger/config.json` renders into four discovery files on top of that.

Then the dispatches were measured. Method, 2026-07-31: parsed 171 main `.jsonl` transcripts plus
8 session directories holding `subagents/agent-<id>.jsonl` with paired `agent-<id>.meta.json`,
under `~/.claude/projects`, Claude Code 2.1.220 — **205 real dispatches**, dated 2026-07-26 to
2026-07-31.

1. **101 of 205 dispatches (49%) named no model at all.** 82 of them silently inherited opus.
   Not one dispatch in the whole set ever declared haiku.
2. **0 of 205 dispatches went to a scaffolded persona.** Not `architect`, not `code-reviewer`,
   not `test-engineer`, not `api-engineer`, not `hermes-agent-author` — the five this repo
   scaffolds and routes. 170 of 205 (83%) went to `general-purpose`.
3. **The delegation ratio is 14.8%** — sonnet+haiku output over all output, main transcripts plus
   subagents. Split out: 2.3% on the main transcripts, 28.1% inside subagents. Main sessions carry
   51.5% of all session output.

Two documents state the policy. 205 dispatches ignored both. The lesson is the whole reason this
ADR exists: **prose changes intent; only a mechanism changes behaviour.** Writing the policy a
third time is the intervention that has already failed twice.

## Decision

**Ship three mechanisms, in cost order — cheapest and most binding first. The persona is third,
and shipping it alone would regress.**

1. **A `model:` lane in each persona's frontmatter.** `features/claude/adjustments/adjust_agents.py`
   emits only `CLAUDE_KEYS = ("name", "description", "tools", "disallowedTools")`, so a persona
   carrying `model: sonnet` never reaches `.claude/agents/`. Add `"model"` to that tuple and set a
   lane on each catalog persona. Every dispatch to a named persona then gets the right lane with
   nobody deciding anything, and it survives `/compact` and forgetting. The Copilot adjuster
   (`features/copilot/adjustments/adjust_agents.py`) **deliberately drops the key** rather than
   mapping it — one host's model names are not another's.
2. **A `PreToolUse` hook, matcher `"Agent"`, that denies an undeclared dispatch.** When the tool
   input names no `model` and the `subagent_type` has no frontmatter lane, the hook refuses. That
   is the 82-dispatch leak, closed mechanically rather than asked for politely.
3. **The `delegator` persona** (`features/common/personas/delegator.md`) **plus a scaffold-generated
   briefing at `.ai-badger/delegation.md`.** Levers 1 and 2 fix *how* a dispatch is made; neither
   can make a session break work into dispatchable packages in the first place. That is judgment,
   and judgment is what a persona is for. The briefing carries the project's volatile data —
   stacks, personas present, routing, verifier commands, MCP servers.
4. **The hook denies; it does not inject a default.** A hook can rewrite tool input via
   `updatedInput`, and injecting `model` there was the tempting version. It is rejected: Claude's
   documented resolution order puts a per-invocation `model` **above** the agent definition's
   frontmatter lane. An injected default would therefore silently override lever 1 on every
   dispatch — the cheap, durable mechanism beaten by the expensive one on every call. Denying
   leaves lever 1 authoritative and pushes the choice back to the caller, where it belongs.

Documentation facts this rests on, verified 2026-07-31 against `code.claude.com/docs/en/hooks` and
`/sub-agents` rather than taken from memory:

- the subagent-dispatch matcher string is `"Agent"`;
- a denial is `hookSpecificOutput.permissionDecision: "deny"` with `permissionDecisionReason`,
  which is shown to the model — so the refusal can teach the correct call;
- frontmatter `model` accepts `sonnet`, `opus`, `haiku`, `fable`, a full model ID, or `inherit`,
  and defaults to `inherit`.

## Consequences

The claim "this made delegation happen" is checkable, and the plan is fixed before the build so
the numbers cannot be chosen afterwards.

**Unit of observation:** one completed `/task` run. Not a project-day — a handful of sessions carry
most of the cost, so a daily aggregate is one or two sessions wearing a trenchcoat.

**Primary outcome:** delegation ratio = (sonnet + haiku output tokens) ÷ (all output tokens), over
the main transcript **plus** that session's `subagents/*.jsonl`.

**Baselines (measured 2026-07-31, method in Context):** 14.8% combined; 2.3% main-only;
101/205 dispatches undeclared; 83% `general-purpose` share; main session 51.5% of session output.

**Targets:** combined ratio ≥ 45%; undeclared dispatches = 0 (hook-enforced); `general-purpose`
share < 30%; main-session share of output < 25%.

**Design:** interrupted time series over ≥10 consecutive `/task` runs before and ≥10 after — not a
two-point before/after.

**Six confounds that would invalidate the measurement:**

1. **Fable is not a cheap lane.** A naive "share of output from non-top-tier models" counts fable
   as delegation, but fable costs **$317/M output against opus's $213/M** — the metric would reward
   the single most expensive lane. Not hypothetical: main transcripts already hold 437,923 fable
   output tokens, 5.4% of main output. The numerator is therefore **sonnet + haiku only**, with
   fable reported as its own line.
2. **`meta.json` is an undocumented CLI artefact** of Claude Code 2.1.220. An upgrade can move or
   drop it. The parser **must degrade to `"unknown"`, never to zero** — otherwise a format change
   reads as a delegation collapse and someone re-litigates a solved problem.
3. **Task-mix shift.** The ratio rises on its own when the work is more mechanical. Record task
   type per run and compare within type, or refuse the comparison.
4. **Session-model drift.** If the session default changes, the denominator changes meaning. Key on
   the model string and exclude windows where it shifted mid-period.
5. **The observer.** The operator knows the experiment, and one haiku dispatch writing 500K tokens
   of nothing wins the metric. Pair it with a quality gate: post-period PRs must not show a higher
   follow-up-fix rate.
6. **Data availability.** Per-dispatch attribution exists **only from 2026-07-26** (205 dispatches,
   8 sessions). No pre-2026-07-26 dispatch baseline may be published; only the session-level split
   covers history.

Accepted costs: a frontmatter key now crosses the host-adjuster boundary, so the two adjusters
diverge on purpose and that divergence must stay documented; a new hook event can refuse work, so
a wrong matcher blocks dispatching entirely; and `.ai-badger/delegation.md` is one more generated
artefact that must be regenerated on every scaffold.

## Alternatives considered

**How the delegator learns what this project contains** — four options, compared on prompt cost,
staleness and new machinery:

| option | prompt cost | staleness | new machinery |
|---|---|---|---|
| **A.** Static persona, reads config/agents/mcp-tools at runtime | ~10–12K tokens of cold-start reads per session | none | none |
| **B.** Persona body generated at scaffold time, inventory baked in | small, free in the system prompt | stale on any config edit | forks the byte-copy path into a template path |
| **C.** Static persona + one generated briefing file | one read, ~1–1.5K tokens | refreshed every scaffold | one `.tmpl` + one slot set, existing renderer |
| **D.** One line in `CLAUDE.md`'s existing `{{PERSONA_ROUTING}}` slot | free, already in the cached prefix | refreshed every scaffold | one edit to `compute_doc_slots` |

**Chosen: C, plus a one-line D.** **B is rejected** specifically: personas are emitted to
`.ai-badger/agents/`, then re-emitted independently by the Claude and Copilot adjusters, so baking
volatile data into the body creates **three copies that go stale independently** — and this repo
already had to build `scaffold_freshness_guard` (#206/#214) to fight exactly that class of drift.
C keeps the volatile data in one generated file all three copies reference by path. A is rejected
on cold-start cost paid every session for data that changes rarely. The D line is *one* line, not
three: `HERMES.md` currently sits at 150 lines against a `maxLines` of 160.

**More `task`-skill prose instead of a persona.** Rejected on a checked mechanism, not a
preference: `claude --help` exposes `--agent <agent>` — *"Agent for the current session"* — so a
persona can be the session's standing posture. A persona body is system-prompt-resident and
load-bearing on every dispatch decision for the session's lifetime; a skill body is read once and
is 200 turns stale by the time it matters. The `task` skill's policy also only applies inside
`/task`, and much of the 82-dispatch leak happened outside one. The two keep no duplicated content:
the persona owns the posture, `SKILL.md` keeps the workflow, and the Claude extension stays the
single place where roles bind to concrete models.

**One delegator per stack.** Rejected: the decision procedure carries no stack idioms, and
`description` drives dispatch — a project with two stacks would scaffold two delegators whose
descriptions both claim the session, with no tie-break.
