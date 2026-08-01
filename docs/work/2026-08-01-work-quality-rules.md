# Sixteen working rules: where each one belongs

**Date:** 2026-08-01
**Question:** Sixteen rules about how work should be planned, delegated and checked were proposed
as invariants. Which of them actually are invariants, and where do the rest go?

This is a work record, not a design document. It is true of its date and describes work in
flight; when the four packages below have merged, its conclusions live in the catalog and this
file leaves `work/`.

## What an invariant is here

A file of three to six lines — a `# Title` and one paragraph — rendered into every scaffolded
project's `CLAUDE.md` under **Non-negotiable invariants**. Two consequences decide everything
below.

**It reaches every subagent.** The `task` skill states that each agent's request prefix carries
the project's always-loaded context, `CLAUDE.md` included. So an invariant propagates to
subagents by construction. That is the answer to "these rules must always be passed to
subagents": make them invariants and no dispatch has to remember.

**Every word costs tokens on every turn, forever.** Which is why the format is one paragraph, and
why a rule that only applies during a `task` run does not belong here — it would be loaded by
every project that never runs one.

## The split

A reader applies an invariant to a **diff**. Six of the sixteen describe a **task lifecycle**
instead, and filing session choreography under "non-negotiable invariants" dilutes the list
agents check code against.

| Rules | Home |
|---|---|
| proof of done · plain names · check sources not yourself · measure only what pays · ask if simpler | new `common` invariants |
| review plan first · gather before planning · plan in sections · integration review per step · execute the plan rather than re-checking it | `features/common/skills/task/SKILL.md` phases |
| split work so it can run in parallel · cap dispatch depth at root → sub → sub · reach for any tool that simplifies | `task` model & delegation policy |
| limited automatic gates · the agent decides when the full suite runs | a `--risk` switch on `task start` |

## Two rules that were already implemented

Checked against the source rather than assumed, which is the discipline one of the new invariants
states.

**"Prefer sonnet for implementation" already exists.** `features/common/skills/task/extensions/claude/extension.md`
binds it: *"Sonnet — implementation, by default … pass `model: "sonnet"` explicitly rather than
relying on the default, so the lane survives a change of session model."* Adding it again would
create two places to disagree.

**"Run subagents in parallel" already exists** in the skill body. What is missing is the
instruction to *split work so that it can be* — the parallelism was assumed to arrive on its own.

## The packages, and what each has to prove

Each carries acceptance criteria and a gate, because one of the new invariants demands exactly
that of any planned work.

| Package | Done when | Gate |
|---|---|---|
| **A** — five invariants | each is ≤6 lines with one heading; all five reach a scaffolded `CLAUDE.md` | `index_build --check`, `scaffold_freshness_guard`, a test asserting delivery, and a mechanical house-style guard on the directory |
| **B+D** — lifecycle and delegation | phases name the review-plan-first order and the integration review; policy names parallel splitting, the depth cap and the tool posture | `test_skill_docs`, and the guard that keeps evidence out of a skill body |
| **C** — `--risk` | recorded on `start`, surfaced by `status`, absent by default, survives a resume | tests that distinguish the flag from its absence — a flag no test can tell from nothing is decoration |
| **E** — integration | the four merged together | full suite, six gates, pylint, and a scaffolded `CLAUDE.md` rendering all fourteen invariants |

A and C are independent. B+D and C both edit `features/common/skills/task/SKILL.md`, so B+D waits rather than racing it.

## Still open

- **"Minimize time spent double-checking" against the day's evidence.** Six checks that could not
  fail were found on 2026-08-01, three of them written that same hour, and each was caught by
  re-verification. The rule is being written as *execute the plan; re-verify after integration
  where there is a reason to*, with the source-checking exception intact. That reading may be
  softer than intended.
- **Whether `--risk` is the right name.** It is the requested one and it states the trade
  honestly, which matters more than elegance: a reduced-gate mode that reads as costless is the
  kind that gets left on.
