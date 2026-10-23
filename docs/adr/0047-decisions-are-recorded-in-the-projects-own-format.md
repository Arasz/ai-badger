# ADR-0047 — Decisions are recorded before implementation, in the project's own format

**Date:** 2026-10-23
**Status:** Proposed
**Extends:** nothing.
**Supersedes:** nothing.
**Research:** [`docs/work/2026-10-23-decision-record-formats.md`](../work/2026-10-23-decision-record-formats.md)

## Context

The framework had no rule that a decision gets written down, and no skill that writes one.
`docs/adr/` here grew by hand. A consumer project might keep decisions in an ADR log, in a spec
framework (OpenSpec, Spec Kit, Kiro), in both, or nowhere. A skill that writes into the wrong one
puts the decision where nobody reads it. The research record measured OpenSpec 1.14.3 and read
MADR 4, adr-tools, log4brains, Spec Kit and Kiro (F1–F8). It found that each leaves a marker in
the tree. It also found that a CLI on PATH is no evidence of adoption: this machine has `openspec`
installed and this repo has never run `openspec init` (F9, F11).

Adding the rule as an invariant takes this repo's `CLAUDE.md` from 35 invariants to 36.
`constraint_count_lint.py` caps the section at 35. That cap was already raised once, from the
30 its plan proposed.

## Decision

1. **A `decision-record` skill** detects the format from the tree with `detect_formats.py`
   and writes into it. The markers are: a numbered record in an `adr`/`adrs`/`decisions`
   folder, `.adr-dir`, `.log4brains.yml`, `openspec/`, `.specify/` and `.kiro/specs/`.
   - An installed CLI decides only whether the record is written through it. The skill never
     initialises a framework or installs a tool.
   - Where the tree carries both an ADR log and a spec framework, the record is a linked pair:
     requirements in the spec change, rationale in the ADR, each linking to the other.
   - Where the tree carries neither, the record is a MADR 4 minimal file at `docs/decisions/`,
     MADR's documented default.
2. **A `record-decisions` invariant.** A change that adds a feature or meaningfully changes how
   something works gets a record before implementation. Bug fixes, behaviour-free refactors and
   docs are exempt.
3. **A `decision record` step** in both `task` loops, between plan review and implementation.
   `status-report`'s printed loop is tied to it by a test.
4. **The constraint-count cap moves from 35 to 36**, so the invariant can stand on its own, as
   requested.

## Considered options

- **Fold the rule into `proof-of-done`.** Both are artifacts named before work starts. This keeps
  the cap at 35, but it merges two rules a reader would look for separately, and it is not what
  was asked. Rejected for now. It is the first thing to try if the cap is to come back down.
- **Consolidate two prompt-engineering invariants to make room** (for example
  `few-shot-format-only` with `reasoning-scaffolding-minimization`). Rejected: it rewrites rules
  this change has no business with.
- **Skill and task step only, no invariant.** Rejected. A session that does not run `task` would
  never meet the rule. F13 records that prose alone is a weak mechanism, but having no rule at all is weaker.

## Consequences

- Good: a decision lands in the log a project already reads, and a combination project gets one
  rationale instead of two copies.
- Good: the record is written before the code, so review can see the reasoning before reviewing the diff.
- Bad: the invariant budget is one larger, and every consumer's `CLAUDE.md` carries one more line.
- Bad: nothing mechanically checks that a behaviour-changing PR carries a record (F13, *Still open*).
  "Meaningful" has no definition a script can evaluate.

## Confirmation

`tests/test_decision_record_detect.py` pins detection. Five mutations were each seen to turn it red
(numbered-record check, next number, CLI-as-adoption, vendored-folder skip, declared-log dedup).
`tests/test_status_report.py::TestTheLoopLineMatchesTheTaskSkill` pins the loop twin.
`tests/test_constraint_count_lint.py` pins the cap at 36. This record was itself written by
following the skill: `detect_formats.py .` reported `mode: adr`, `docs/adr`, next `0047`.
