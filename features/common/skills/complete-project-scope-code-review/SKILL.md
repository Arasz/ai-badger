---
name: complete-project-scope-code-review
description: >-
  Use when the whole project — not a diff — is the review target and the result must survive being
  acted on: "review the entire codebase", "full quality review", "MoE review", "what is wrong with
  this project", "audit everything before the next release", or a review whose findings will
  become a plan someone implements. Runs ground-truth baseline, parallel expert lanes, integration,
  an adversarial pass that tries to falsify the findings, severity calibration against production
  reality, a reviewed plan, waved implementation in isolated worktrees, and a join review on every
  merge. Not for judging one diff or PR (that is review-changes plus code-review-checklist), one
  design document's gates (design-gate-audit), or one question (evidence-first-research).
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos]
scope: optIn
metadata:
  hermes:
    tags: [review, parallel, evidence, adversarial, planning]
    related_skills: [evidence-first-research, owner-gate-review, multi-lane-report-assembly, design-gate-audit, task]
---

# Complete project-scope code review

A review campaign, not a review. The output is a graded record, a reviewed plan, and merged work —
each stage gated by something that has been watched fail.

**This skill composes; it does not replace.** Each phase names the skill that owns its mechanics.
Load those rather than reimplementing them:

| Phase needs | Skill that owns it |
|---|---|
| Grade vocabulary, record shape, the `## Still open` discipline | `evidence-first-research` |
| Merging lane blocks into one record | `multi-lane-report-assembly` |
| Adversarially re-deriving a written record from its sources | `research-record-audit` |
| Tautology / fake-honesty hunting inside a lane | `code-review-evidence` |
| Mechanical per-diff gates inside a lane | `code-review-checklist` |
| Blast-radius ranking of a merge | `review-changes` |
| Verifying the diff base before judging it | `review-gate-diff-verification` |
| Auditing a plan's acceptance gates before anyone builds | `design-gate-audit` |
| Getting a human ruling per decision | `owner-gate-review` |
| Per-agent isolation | `worktree-agent-isolation` |
| Running one work package end to end | `task` (and `create-task-spec` when it needs a spec) |

<!-- MERGE_EXTENSIONS -->

## Phase 0 — Ground truth before anyone is dispatched

Measure, do not assume. Everything the lanes are told must be something you ran.

1. **Run the project's build, test and lint commands** from its config and record the exact
   numbers — counts, duration, warnings. A prior note saying "two flakes" is a claim about a
   different machine at a different commit; re-run it.
2. **Size the codebase**: production lines by layer, test lines, ratio. Write the number down
   before forming an opinion about it — a suspicion recorded as a hypothesis can be disconfirmed,
   and one held silently cannot.
3. **Verify every claim you plan to brief the lanes with**, at `path:line`. Plan documents, prior
   reviews and issue bodies go stale between writing and reading; paths move, counts drift,
   "N unused copies" is routinely 1 used copy.
4. **Name the base commit.** Every finding is against it. Lanes citing a moving ref cite nothing.

Brief the lanes with a labelled block — *"VERIFIED GROUND TRUTH (trust these over anything the
brief says)"* — so a lane knows which half of its input has been checked.

## Phase 1 — Parallel expert lanes

**Derive the lane roster from the repository, never from this list.** Read the project's own
stacks, personas and top-level directories, and open one lane per distinct expertise the code
actually demands. A fixed roster reviews the project you expected. A .NET service with a React
front end and Terraform infrastructure needs different lanes from a single-runtime library, and
both need lanes nobody would have guessed without looking.

Lanes that recur: architecture/layering, domain algorithm (retrieval, scoring, whatever the
product's hard part is), the primary language's code quality, data access, test-suite QA, the
consumer-facing surface (CLI, API, UI), and operations/infrastructure.

Each lane is **read-only**, gets **its own worktree and its own workspace id**, and is told:

- The verified ground truth, the base commit, and its own lens.
- **The lane contract:** one `### F<n> — <claim, present tense> [GRADE]` block per finding, grade
  from the closed set `MEASURED` / `READ` / `INFERRED` / `UNVERIFIED` at the end of the claim
  line, an `**Evidence:**` line carrying `path:line` for everything `READ` or `MEASURED`, a
  severity, a `## Still open` list, and its grade mix. This is `evidence-first-research`'s
  vocabulary; do not invent a second one.
- **Permission to disagree with the brief, in writing.** Say it: *"if a briefed finding is wrong,
  proving it wrong is a first-class result and worth more than confirming it."* The highest-value
  lane output on the session this skill comes from was a lane that proved a briefed feature had
  never worked at all. A brief that only invites confirmation gets confirmation.
- **Decision-ready owner questions**, one line each, so they can be routed without reformatting.

Run lanes concurrently up to your dispatch cap; where the cap bites, wave them and give the later
wave the integrated result of the earlier one to review rather than the same raw input.

## Phase 2 — Integration

Follow `multi-lane-report-assembly` for the mechanics — read it before assembling, because
renumbering, truncation at embedded `## ` headers and stale cross-references are where assembled
records break. On top of it:

- **Convergence raises confidence; lane count does not settle a fact.** Two lanes reaching the
  same finding independently is evidence. Two lanes disagreeing is not a vote — go read the code
  and settle it. The minority lane is right often enough that counting is not a method.
- **Re-verify at `path:line` every finding that drives expensive work** before it enters the
  record. Cheap findings can ride on their lane's grade; a finding that will cost a week cannot.
- Record what is **healthy**, explicitly, so a later simplification pass does not sweep it up.
- Record every **disconfirmed hypothesis** as plainly as the defects. "We suspected bloat; we
  measured it; the suspicion was wrong" is a finding.

## Phase 3 — Adversarial verification

Dispatch an independent reviewer **instructed to falsify the record**, with the sources but not
your reasoning. It re-derives every load-bearing claim, re-runs every `MEASURED` one, and checks
quotes verbatim at their cited lines — `research-record-audit` owns that procedure; read it when
briefing this pass.

Then publish what it changed, in the record, as a table: claim → refuted / corrected / softened /
reproduced. A reader must be able to see which way the errors ran. On the source session this
pass refuted or corrected six claims while every core conclusion survived — the failures were in
supporting numbers, which is exactly what gets quoted later.

**Attack before anyone implements.** A refuted number that reached a plan costs a work package.

## Phase 4 — Calibrate severity against production reality

A defect that is real in code and has never once fired in a deployment is still real — and it is
not a hotfix. Before ranking anything, query the live system read-only: does the table the defect
writes to have any rows? Has the flag it depends on ever been set? Is the feature reachable at all
in the shipped configuration?

State the result as *loaded, not fired* when that is what it is. This changes urgency and
sequencing; it must not change the finding. Two blockers on the source session had never fired in
production — which made the campaign a planned release rather than a hotfix, and surfaced a
sequencing constraint nobody had seen: *improving the broken filter's recall before the honest
write outcome landed would have converted a dormant defect into an active one.*

## Phase 5 — Plan, then review the plan

Package findings by **surface**, so everything touching one file lands in one change. Every
package carries acceptance criteria **and a gate that has been watched go red**.

Then put the plan through two independent reviews before implementation — an architect pass for
sequencing and blast radius, and an adversarial pass that attacks the plan's own claims and its
gates (`design-gate-audit` owns gate honesty; read it when auditing acceptance criteria). Fold
both into a revision, and **list what the revision changed** — a plan whose corrections are
invisible teaches nobody, and reviewers cannot tell a considered rejection from an overlooked one.

Sequencing rules worth writing down every time:

- **Name the serialisation points.** A file that five packages edit is not parallelisable, however
  independent the packages read.
- **The measurement chain runs backwards from what you want to prove.** If package C's ranking
  change must be measured on a corpus, and package A changes what the corpus contains, the order
  is A → corpus → C. Getting this backwards is easy and invisible until the numbers are useless.
- **Two packages that make each other worse in between ship as one change.** Deleting the last
  copy of some data in one package while another still fabricates success is strictly worse than
  the state you started in.

**Draw the module the plan changes, before and after.** Two diagrams in the repo's own diagram
convention: the current shape built from verified code facts, the proposed shape built from what
the review decided. A reviewer sees a restructuring in a picture that they will not see in a
finding table.

Route every question that needs a human through `owner-gate-review` — one decision, one ruling,
and generate its form programmatically from a decisions array rather than hand-editing the
template. Where no owner is available, decide, record the decision and the reason, and mark it
reversible.

## Phase 6 — Waved implementation

Each package runs through `task`, in its own worktree, TDD-first, with its named gate. Waves are
ordered by the sequencing rules; packages inside a wave run concurrently only where they share no
serialisation point.

Two hazards specific to running many lanes at once:

- **A lane holding unpushed work is a lane that has stalled invisibly.** Its branch looks absent
  from the integration side while its worktree holds everything. Require a push after every
  commit, and check for unpushed commits before concluding a lane produced nothing.
- **Every gate value that is a pin — a line count, a member count, a metric floor — carries a
  raise history on the constant.** A ratchet re-pinned silently is a ratchet that has been turned
  off. See the failure modes below.

## Phase 7 — Merge, and review every join

Defects that exist only where two individually-correct branches meet are the ones no lane can
find. On the source session at least five did. Verify the base first
(`review-gate-diff-verification`, read it before judging a merged diff), then on the **merged**
tree, not the branches:

- Re-run the build and the full suite. A per-branch green says nothing about the join.
- **Read what a mechanical conflict resolution dropped.** Taking one side wholesale silently
  removes anything the other side added that had no counterpart — a test, an assertion, a
  deliberately-changed constant. Diff each resolved file against *both* parents and account for
  every line that vanished.
- **Check that test infrastructure still does its job.** A helper that builds a pre-migration
  fixture stops being able to build it the moment another branch adds a constraint it does not
  know to drop; the test then fails in arrange, not assert.
- **Check the dispatch, not just the compile.** A method added on one side and a fake extended on
  the other can compile and still never be called. See the dotnet extension for the C# shape of
  this trap.
- Write the integration reasoning into the merge commit. It is the only place that survives.

## The failure modes this exists to catch

Each of these happened, most more than once. They are the reason for the phases above; read
`references/failure-modes.md` when you hit one, or before designing a benchmark or a gate.

1. **Circular benchmark.** A filter validated on a corpus built from the shape it matches scores
   perfectly by construction — and a later review reuses that rigged corpus to argue the opposite.
   **Control, required not advised: held-out evaluation by family.** Partition the corpus by the
   thing that generated it (tool family, source repo, operator, document type), train or tune on
   some families and evaluate on the held-out ones. A number that does not survive
   leave-one-family-out does not ship. An in-sample 0.946 AUC is a description of the corpus.
2. **Vacuous gate.** A metrics test reporting nDCG/MRR/recall of 0 for every query while asserting
   only "in range [0, 1]". A test comparing a column that is 0-of-2518 populated against a stale
   map: *always false equals always false*. Every gate is broken on purpose once and watched go
   red, before it is trusted.
3. **The specification encodes the defect.** A test or `.feature` file asserts the bug as required
   behaviour, so the fix turns it red and the reflex is to "restore" it. **Adjudicate, in the
   commit message**: is the assertion the contract, or a transcription of what the code did? Four
   separate cases on one session; every one was the second.
4. **Join defect.** See Phase 7.
5. **In-sample numbers.** Any metric produced on the data it was tuned on. Label it, and re-derive
   held-out before it justifies work.
6. **The finding that is a refutation.** The mechanism is usually silent: a parameter dropped
   because nothing matched it, a value written to a column that does not exist. A feature can pass
   review, an ADR, a benchmark and a full green suite while doing nothing. Treat a RED test that
   refuses to go red as evidence, not as a broken test.
7. **Ratchets re-pinned without a raise history**, and **lanes stalling with unpushed work**.
8. **Derive, don't pin.** Every expectation that mirrors something else — a tool list, a hash map,
   a set of statements, a fixture's contents — is derived from the source of truth at test time,
   or it is a second source of truth that drifts silently. A hand-maintained copy is a defect with
   a delay fuse.

## Gotchas

- **The base moves under you.** If the trunk merges during the review, the squashed result can
  differ from the head every lane read. Re-fetch, diff the reviewed head against the merged
  commit, re-run the gates on the merged state, and re-verify each finding against the merged file
  before accepting it.
- **Never weaken a gate to make a merge green.** Six retrieval failures on the source session were
  genuine ranking movement on a denser corpus; they were left failing and routed to the package
  that owned them. A gate lowered to pass is a gate deleted.
- **Characterization tests keep CI honest, not quiet.** When a finding cannot be fixed in this
  wave, pin the *current* behaviour with a test that names it as characterized-not-endorsed. It
  keeps the suite green without hiding the finding.
- **An attribution can be wrong while the finding is right.** A test blamed on one defect that
  still fails after that defect is fixed was mis-attributed — re-diagnose it rather than reopening
  the fix.
- **A refuted supporting number does not refute the conclusion.** Withdraw the number, keep the
  claim if its other legs hold, and say which leg was removed.

## Verification checklist

- [ ] Build/test/lint baseline measured at a named base commit, not quoted from a note
- [ ] Lane roster derived from this repository's own stacks and directories
- [ ] Every lane got the ground-truth block, the grade contract, and explicit permission to refute
- [ ] Adversarial pass ran, and its refutations are published in the record
- [ ] Severity calibrated against the live system; "loaded, not fired" stated where true
- [ ] Every work package has a gate that has been watched go red
- [ ] Every held-out claim is held-out; no in-sample number justifies a package
- [ ] Every merge re-ran the gates on the merged tree and accounted for lines a resolution dropped
- [ ] Every re-pinned ratchet carries its raise history
- [ ] `## Still open` is non-empty, or its emptiness is defended

## References

- `references/failure-modes.md` — worked cases for all eight, with the evidence and the control
  each one needs; read it before designing a benchmark, a corpus or a gate, or when a finding
  turns out to be a refutation.
- `references/lane-brief.md` — the dispatch brief template and the lane output contract; read it
  before dispatching the first lane.
