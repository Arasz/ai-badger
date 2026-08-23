# Skills

This page catalogs 43 skills — everything under `features/common/skills/` and
`features/claude/skills/`.
42 live under `features/common/skills/` and split by the `scope:` each declares in its own
`SKILL.md` frontmatter ([ADR-0018](adr/0018-where-the-skill-routing-declaration-lives.md)):
**20 are `default`** and arrive in every scaffolded project without being asked for, and
**22 are `optIn`** — catalogued, but written only when a project names them. The last one,
`auto-wm`, sits under `features/claude/skills/`, stack-local to the `claude` agent
([ADR-0010](adr/0010-stack-local-skill-discovery.md)) and therefore **claude-only**: it does not
reach a Copilot or Hermes project.

**These 41 are not the whole tree.** `features/*/skills/*/SKILL.md` matches **57** files:
the 43 above plus 15 more that belong to a single stack and arrive only with it — 11 under
`features/dotnet/skills/`, 2 under `features/hermes/skills/`, 1 under `features/mcp/skills/` and 1 under `features/ai-raccoon/skills/`.
Those 15 have no row below and are documented by their own `SKILL.md`. Derive the number rather
than trusting this sentence: `python3 gates/skills_lint.py` prints how many `SKILL.md` files the
catalog holds.

Those four numbers, and every row of the table below, are checked against the declared scopes by
`tests/test_docs_match_the_catalog.py`. A skill added to the catalog without a row here fails
that test, and so does a row naming a skill the catalog no longer has — **but only for the
common and `claude` stacks**: that test's `STACK_LOCAL_SKILL_DIRS` names `claude` alone, so the
15 stack-local skills are outside its reach and their absence here fails nothing.

An `optIn` skill is asked for by name in `.ai-badger/config.json`:

```jsonc
{
  "include": { "skills": ["update-documentation"] }
}
```

Some skills cannot do their job alone and are installed as a group. The three documentation
skills read each other's `references/` in place, so naming any one of them delivers all three —
and `"skills": ["documentation"]` asks for the capability without naming them individually:

```jsonc
{
  "include": { "skills": ["documentation"] }   // scaffold- + update- + migrate-documentation
}
```

Groups are declared in `badger_lib.SKILL_GROUPS`. They group in configuration only: the delivered
layout stays flat, because a skills directory registers exactly one nesting level and a directory
without a `SKILL.md` is silently ignored — a nested `documentation/` would be invisible to every
agent.

`welcome-ai-badger` and `den-refresh` both honour it, a `config.json` edit is drift so the next
refresh delivers the skill on its own, and every report lists the `optIn` skills a project has
not installed with the exact edit that adds each. The mechanism — and what to weigh when
declaring a new skill's scope — is in
[`authoring-a-feature.md`](authoring-a-feature.md#default-or-optin).

Most skills are **invoked by name** — a slash command or a phrase the agent recognizes from the
`SKILL.md` frontmatter description, run when someone decides to run it. A few are **hook-backed**
— wired into `.claude/settings.json` (or the Hermes equivalent) at scaffold time and fire on
their own, on every matching event, whether or not anyone asked. The table below names which is
which and which arrive unasked; the per-skill sections say what changes on disk either way.

## At a glance

`Ships` is the scope: **default** arrives unasked, **opt-in** only when `config.include.skills`
names it, **claude-only** when the stack decides.

| Skill | Purpose | Ships | Invoked how |
|---|---|---|---|
| [welcome-ai-badger](#welcome-ai-badger) | Scaffold `.ai-badger/` into a repo for the first time | default | by name |
| [den-refresh](#den-refresh) | Pull framework updates into an already-scaffolded repo | default | by name |
| [feed-badger](#feed-badger) | Contribute project-agnostic improvements back to the catalog | default | by name |
| [humanizer](#humanizer) | Strip AI writing artifacts, apply research-grounded humanization levers, and adopt a natural voice | default | by name |
| [task](#task) | Run one backlog task end to end with model delegation | default | by name (`/task <id>`) |
| [git-work](#git-work) | Recover push failures, triage red CI, and run the PR lifecycle outside a tracked task | default | by name |
| [create-task-spec](#create-task-spec) | Interrogate an idea into a Gherkin specification plus a manifest `task` consumes | default | by name |
| [owner-gate-review](#owner-gate-review) | Turn a document's open decisions into a per-decision review form | default | by name |
| [differential-feature-refactor](#differential-feature-refactor) | Reconcile a drifted feature against its ratified design before refactoring | default | by name |
| [design-tests](#design-tests) | Design and write tests to a fail-under-a-plausible-bug standard, target named or not | default | by name |
| [review-tests](#review-tests) | Judge tests that already exist against one shared ruleset and hand back an improvement plan | default | by name |
| [code-review-checklist](#code-review-checklist) | Aviation-style pass/fail checklist for a PR or diff | default | by name (a reference to work through) |
| [prompt-markers](#prompt-markers) | Detect `h:`/`f:`/`e:` prefixes and inject the matching behaviour | default | hook (`UserPromptSubmit`) |
| [commit-reminder](#commit-reminder) | Command a commit once uncommitted work crosses a threshold | default | hook (`PostToolUse`) |
| [call-behaviorist](#call-behaviorist) | Off-by-default audit log for ai-badger's own hooks | default | by name |
| [maintain-agent-instructions](#maintain-agent-instructions) | Reconcile CLAUDE.md/Copilot/Hermes instruction files against one model | default | by name (or CI) |
| [mcp-index](#mcp-index) | Curate the MCP tool index a hook uses to recommend tools per turn | default | by name; feeds a `pre_llm_call` hook |
| [ai-raccoon-memory](#ai-raccoon-memory) | Project memory server: search memory first, write durable facts with source paths, watch a docs directory | default | by name |
| [semantica-knowledge-graph](#semantica-knowledge-graph) | Session-scoped knowledge graph: record decisions with provenance, trace causal chains, extract entities from conversations | default | by name |
| [browser-usage](#browser-usage) | Universal browser automation and manual E2E verification via Playwright MCP | default | by name |
| [auto-wm](#auto-wm) | Auto-approve tool calls in partner/away mode | claude-only | by name (`/auto-wm`); installs a `PreToolUse` hook once enabled |
| [scaffold-documentation](#scaffold-documentation) | Create the canonical `docs/` tree in a repo that has none | opt-in | by name |
| [update-documentation](#update-documentation) | Change documentation to match something that already changed | opt-in | by name |
| [migrate-documentation](#migrate-documentation) | Reorganise an existing documentation tree wholesale | opt-in | by name |
| [review-changes](#review-changes) | Rank a diff's changed units by blast radius and check the riskiest are tested | opt-in | by name |
| [explore-codebase](#explore-codebase) | Orient in an unfamiliar codebase before reading it file by file | opt-in | by name |
| [debug-issue](#debug-issue) | Trace the call chain from a symptom to its entry point before hypothesizing | opt-in | by name |
| [refactor-safely](#refactor-safely) | Enumerate every affected location before a rename, extraction, or removal | opt-in | by name |
| [evidence-first-research](#evidence-first-research) | Produce a dated research record whose findings are graded by how they are known | opt-in | by name |
| [research-record-audit](#research-record-audit) | Re-derive a written record's claims from its cited sources | opt-in | by name |
| [multi-lane-report-assembly](#multi-lane-report-assembly) | Assemble parallel research or review lanes into one evidence-graded record | opt-in | by name |
| [complete-project-scope-code-review](#complete-project-scope-code-review) | Review a whole project through parallel expert lanes, an adversarial pass, and a waved plan | opt-in | by name |
| [code-review-evidence](#code-review-evidence) | Catch claims about wrapped libraries and tests that assert their own input | opt-in | by name |
| [review-gate-diff-verification](#review-gate-diff-verification) | Establish a branch diff's true base before a gate judges it | opt-in | by name |
| [design-gate-audit](#design-gate-audit) | Audit a design doc's acceptance gates before anyone builds against them | opt-in | by name |
| [artifact-verification](#artifact-verification) | Verify specs, docs, manifests and packages that no code test covers | opt-in | by name |
| [documentation-drift-audit](#documentation-drift-audit) | Audit documentation against the real tree and fix only what is verifiably false | opt-in | by name |
| [spec-driven-refactoring](#spec-driven-refactoring) | Gate a large multi-file refactor on a spec, before and after | opt-in | by name |
| [scripts-tooling-refactor](#scripts-tooling-refactor) | Convert a `scripts/` directory into a tested, tooling-language-native layout | opt-in | by name |
| [worktree-agent-isolation](#worktree-agent-isolation) | Give each parallel agent its own git worktree and integrate via PRs | opt-in | by name |
| [pre-push-gate-debugging](#pre-push-gate-debugging) | Debug a blocked pre-push quality gate one lane at a time | opt-in | by name |
| [sqlite-schema-review](#sqlite-schema-review) | Review SQLite DDL and migrations against scratch-database evidence | opt-in | by name |
| [sqlite-bank-space-diagnosis](#sqlite-bank-space-diagnosis) | Diagnose a bloated SQLite file and its WAL read-only before reclaiming | opt-in | by name |

---

## Setting up and staying current

### welcome-ai-badger

[`SKILL.md`](../features/common/skills/welcome-ai-badger/SKILL.md)

**What it is.** The first-run skill: turns an unscaffolded repository into one with a
project-tailored slice of the ai-badger catalog.

**What it does.** `detect.py` proposes a config from the repo's package/project files and agent
traces; the agent authors `project.summary`, `project.domain`, and `personaRouting` into it;
`validate.py` checks it against `schemas/config.schema.json`; `scaffold.py` then writes
`.ai-badger/` (`config.json`, `manifest.json`, `CLAUDE.md`, `agents/`, `instructions/`,
`invariants/`, `skills/`, `agent-instructions/`, `state.json`) and copies the agent-discovery
files each coding agent looks for (`CLAUDE.md`, `.github/copilot-instructions.md`,
`HERMES.md`) to their conventional locations.

**When to use it.** A repository has never been scaffolded — "welcome-ai-badger", "scaffold this
project", "add agent instructions here", "onboard this repo".

### den-refresh

[`SKILL.md`](../features/common/skills/den-refresh/SKILL.md)

**What it is.** The update direction of the framework, for a repo `welcome-ai-badger` already
ran on.

**What it does.** `refresh.py` validates `config.json`/`manifest.json`, runs drift detection
against the framework's current catalog, and — if anything drifted — re-scaffolds using the
existing config (no re-detection, no questions). It backs up `.ai-badger/` first and prints a
JSON report (`drift.changed`, `drift.removed`, `drift.orphaned`, `drift.newItems`,
`skillUsage`, …). Seed-once files (`state.json`, `markers-context.json`, `model.json`) and
content between `<!-- ai-badger:keep-start -->`/`<!-- ai-badger:keep-end -->` markers survive
the re-scaffold.

**When to use it.** A `SessionStart` drift notice appeared, a new ai-badger version shipped, or
someone asks to "refresh"/"update ai-badger".

### feed-badger

[`SKILL.md`](../features/common/skills/feed-badger/SKILL.md)

**What it is.** The reverse of `welcome-ai-badger`: harvests project-local improvements back
into the framework catalog.

**What it does.** `detect_additions.py` diffs `.ai-badger/` against `manifest.json` to list
`new` and `changed` candidates; the agent classifies each as agnostic, generalizable, or
project-specific, generalizes the keepers (strips repo names, domain nouns, absolute paths),
and writes them into a framework checkout under `features/{stack}/{feature}/`. `open_pr.py`
then scans every declared path for credential-shaped literals and — if clean — opens a **draft**
PR (`git` branch/commit/push plus `gh pr create --draft`).

**When to use it.** Something learned in this repo — a new skill, persona, invariant,
instruction, or fix — is project-agnostic and worth contributing back.

### humanizer

[`SKILL.md`](../features/common/skills/humanizer/SKILL.md)

**What it is.** Anti-AI writing and natural voice editing skill grounded in empirical text detection research.

**What it does.** Applies 9 humanization levers (burstiness injection, anti-vocabulary/n-gram purge, zero em-dash rule, active clause conversion, structural flattening, specificity insertion) and a two-pass self-audit protocol to make AI-generated or edited prose sound natural, human, and direct.

**When to use it.** Writing or editing documentation, READMEs, tutorials, how-tos, release notes, or PR descriptions.

---

## Running work

### task

[`SKILL.md`](../features/common/skills/task/SKILL.md)

**What it is.** The day-to-day orchestration skill: runs one backlog task end to end as a
cleanly separated, token-tracked unit of work, delegating planning and review to a
high-reasoning model and implementation to persona-routed agents.

**What it does.** `task_tracker.py` records phase transitions to `.ai-badger/task-tracking/`
(gitignored) so a dead session can be resumed. The skill dispatches implementation subagents per
`personaRouting` in `config.json`, runs the configured `commands.build`/`test`/`lint`, and — when
`sourceControl.platform == "github"` — follows `extensions/github/` for PR-open, review-loop, and
squash-merge.

**When to use it.** "/task \<id\>", "start task X", "work on the next task", "finish this task".

### create-task-spec

[`SKILL.md`](../features/common/skills/create-task-spec/SKILL.md)

**What it is.** Turns a rough idea into an exact specification by interrogating the person for
what they know, rather than drafting something plausible for them to approve. The structure is
Gherkin, and that is load-bearing: the grammar decides which questions must be asked, and an
empty required slot is a question rather than a blank to fill.

Because incompleteness is structural — a `Rule` with no example, an example with no steps —
`scripts/spec_holes.py` can count the outstanding questions, so the loop stops when the document
is complete rather than when the conversation feels finished. Unresolved points go to
`owner-gate-review`; nothing is emitted while a decision card is unanswered.

It emits two files that cannot be derived from one another: a `.feature` behavioural contract,
and a `spec.json` manifest carrying scope, constraints, gate verdicts and deferrals. `task`
accepts the manifest path in place of freeform text. `scripts/render_spec.py` renders either into
a self-contained page for review, with the holes shown rather than merely counted.

Reasoning and prior-art comparison: [`references/why-elicitation.md`](../features/common/skills/create-task-spec/references/why-elicitation.md).

**When to use it.** "spec this out", "create a task spec", "turn this idea into requirements",
"what exactly should we build" — before planning anything too big to describe in one sentence.

### owner-gate-review

[`SKILL.md`](../features/common/skills/owner-gate-review/SKILL.md)

**What it is.** Turns a document's open decisions into a per-decision review form, so a
reviewer's answers come back bound to the decision they belong to instead of as an
unattributable wall of prose.

**What it does.** Writes an HTML review form (from `references/form-template.html`) beside the
document it reviews — one card per decision, with an APPROVE / CHANGE / REJECT / DEFER control
and a notes box. The agent starts a capped, backgrounded watch for the result file the reviewer
saves, then reads it back: every verdict and note matched to its card by id, never by paragraph
order.

**When to use it.** A design, refactor, or review document has decisions that must each be
approved, changed, rejected, or deferred before work is scoped — or pasting a long document into
chat has produced a reply that cannot be matched back to its questions.

![Generated dark-themed review page titled "Fourteen open decisions from the night's work". Each decision is a card with an id such as G1 or W1, a summary of the trade-off, a row of APPROVE / CHANGE / REJECT / DEFER buttons, and a notes textarea. A sticky footer reads "0 of 14 answered" with SAVE FEEDBACK, COPY FEEDBACK, SHOW AS TEXT, and CLEAR ALL buttons.](screenshots/owner-gate-review.png)

*The generated review form for a differential-refactor document: one card per decision, a
verdict row, and a running answered count in the sticky footer.*

### differential-feature-refactor

[`SKILL.md`](../features/common/skills/differential-feature-refactor/SKILL.md)

**What it is.** Produces a **differential document** — what a feature currently has versus what
it will have — before scoping a refactor of something that has drifted from, or was never
reconciled with, its intended design.

**What it does.** Writes `docs/work/YYYY-MM-DD-<feature>-differential.md` from
`references/differential-template.md`, with current-state claims cited `path:line` and one
Undefined-Point (`UP-N`) block per open question, each with exactly three lettered propositions.
It invokes `owner-gate-review` to collect rulings on those points as a generated form, then feeds
the resolved answers into `superpowers:brainstorming` (a refactor specification) and
`superpowers:writing-plans` (an implementation plan) — the differential document is a midpoint,
not the deliverable.

**When to use it.** Two parallel implementations of the same thing exist, code reads as dead but
may be a ratified extension point, an architecture nobody can tell from accumulated cruft, or a
refactor is about to be scoped off review documents instead of decisions.

### design-tests

[`SKILL.md`](../features/common/skills/design-tests/SKILL.md)

**What it is.** Gets a test suite designed and written to one standard — a test earns its place
by failing under a plausible bug — whether or not a target is named, and finishes green rather
than stopping at the first red.

**What it does.** Stage 0 works out a target when none is named (an uncommitted change, a bug
report, a coverage artifact, or a risk-ranked candidate set); Stages 1–4 fix the contract, the
behaviour list, the oracle, and the isolation plan; Stage 5 writes one test at a time, watched
failing before it is made to pass, using `scripts/red_proof.py` to prove RED against existing
production code; Stage 6 self-reviews the result with `review-tests`' own walk and
`scripts/scan_uncontrolled_resources.py`. It shares one ruleset
(`../review-tests/references/`) with `review-tests` rather than duplicating it.

**When to use it.** "write tests for X", "add coverage here", "what should I test", a new
behaviour with no test yet, a bug that needs a reproduction test, or a bare "write some tests"
with nothing named. Not for judging tests that already exist (`review-tests`) or diagnosing one
already-flaky failure (`dotnet-flaky-test-diagnosis`).

### review-tests

[`SKILL.md`](../features/common/skills/review-tests/SKILL.md)

**What it is.** Judges tests that already exist against one shared ruleset and hands back an
improvement plan — green is the symptom, not the verdict — and never writes a fix itself.

**What it does.** Resolves its scope from a directory, a file list, a diff/PR/branch, or a named
symbol, and refuses to run with nothing named. Walks the suite cheapest-falsifier-first across
nine passes (0–8): can the suite claim anything, can any test fail, determinism, name-vs-body,
oracles, doubles, states/wiring, cost/hygiene, then the verdict. Reads
`references/walk-review.md` and the matching `kind-*.md`/`stack-*.md` files only when a pass or
a finding needs them, and writes one fixed-column improvement plan per
`references/plan-format.md`.

**When to use it.** Reviewing a PR or diff that changes test files, checking whether an existing
test suite actually covers its contract, finding flaky/non-deterministic tests, or converting
vague "we need better tests" requests into actionable improvement tasks. Not for designing a
new suite from scratch (`design-tests`) or writing the production fixes.

### code-review-checklist

[`SKILL.md`](../features/common/skills/code-review-checklist/SKILL.md)

**What it is.** An aviation-style preflight checklist for reviewing a PR or diff: sequential
phases, each item a concrete pass/fail check rather than an impression.

**What it does.** The `SKILL.md` itself is the checklist — pre-takeoff gates (build, test, lint,
no hardcoded secrets, VERSION bumped), architecture and layering, TDD compliance, security,
client-server contract alignment, accessibility, and a post-merge smoke test. A
`<!-- MERGE_EXTENSIONS -->` marker lets `scaffold.py` merge in stack-specific phases from
`extensions/<stack>/` (dotnet, react, cosmos, azure, ts, mcp); project-specific checks go in a
seed-once `project-local.md`.

**When to use it.** Reviewing a PR before approving, a milestone or sprint review, self-review
before `git push`, or checking a subagent's output before merging.

---

## Keeping the agent honest

### prompt-markers

[`SKILL.md`](../features/common/skills/prompt-markers/SKILL.md)

**What it is.** A small set of one- or two-word prefixes — `h:`/`hint:`, `f:`/`feedback:`,
`e:`/`extension:` — a person can put at the start of a prompt to give the agent an explicit,
machine-detectable signal instead of relying on it to infer intent from phrasing.

**What it does.** A `UserPromptSubmit` hook (`scripts/user_prompt_hook.py`) reads the prompt,
matches it case-insensitively against the prefixes declared in `markers-context.json`, and — on
a match — appends the marker's instruction text via the hook's `additionalContext` field (never
prepends or rewrites, so prompt caching stays intact). When a `.ai-badger/` directory exists
above the prompt's `cwd`, the detection is also logged to
`.ai-badger/prompt-markers/marker-state.json`.

**When to use it.** A prompt starts with one of the three prefixes, or someone asks to add,
change, or inspect a marker.

### commit-reminder

[`SKILL.md`](../features/common/skills/commit-reminder/SKILL.md)

**What it is.** A command, not a gate: watches uncommitted work accumulate and tells the agent
to commit before it is lost — it never blocks or denies the tool call that triggered it.

**What it does.** A `PostToolUse` hook (`commit_reminder_hook.py`) runs `git status --porcelain`
after every edit-shaped tool call and fires once the file count first crosses a threshold
(`AI_BADGER_COMMIT_REMINDER_THRESHOLD`, default 5) and again on each new high. After three
unanswered firings the project's entry is marked at risk; `scripts/ensure_committed.py` reports
every at-risk project — path, session, and how long — to a parent session that can take over,
commit, or stop the agent.

**When to use it.** Several edits have landed with no commit in between, or a subagent may be
stuck and about to lose its work — "did that agent commit?", "is anything at risk?".

### call-behaviorist

[`SKILL.md`](../features/common/skills/call-behaviorist/SKILL.md)

**What it is.** An off-by-default audit log for ai-badger's own machinery, so "did that hook
fire?" has an answer instead of a guess.

**What it does.** `python3 .../behaviorist.py on [DURATION]` switches on logging for up to 24h;
every wired ai-badger hook then appends a compact JSON record (`component`, `event`, `version`,
`project`) to `~/.ai-badger/debug/audit.jsonl`. `behaviorist.py analyze --json` compares what a
project **registers** (`.claude/settings.json`, `.ai-badger/hooks/hooks.json`) against what was
**observed**, and returns findings — `never_observed`, `version_skew`, `always_skipped`,
`unexpected_component` — plus a health verdict of `ok`/`warn`/`degraded`/`unknown`.

**When to use it.** "Did that hook even run?", "why is the drift notice silent?", "enable debug
logging" — or producing a health report on ai-badger's own hooks in this project.

### auto-wm

[`SKILL.md`](../features/claude/skills/auto-wm/SKILL.md) — **claude-only**

**What it is.** Autonomic Work Mode: auto-approves most tool calls, in two variants — **partner**
(someone is at the keyboard, questions are left alone) and **away** (nobody is, questions are
denied outright).

**What it does.** `/auto-wm [partner|away DURATION|off|status|forget]` writes an entry in
`~/.claude/awm/state.json` for the project it was run in (mode, expiry, capped at 12h). A
`PreToolUse` hook (`awm_gate.py`) then auto-approves calls inside that project, except a denylist
(destructive shell commands, force-pushes, network egress, writes outside the project) which
always falls through to the normal permission prompt; every decision is logged to
`~/.claude/awm/decisions.jsonl`.

`forget [PATH] [--force]` (0.75.0) removes an entry outright — `disable` only flips one off, so
without it `state.json` accumulates an entry for every directory AWM was ever enabled in,
including deleted worktrees. It refuses a live window unless forced.

**State is per project** (0.74.0). Each entry carries its own mode and its own clock, so two
checkouts can be armed at once and `off` in one leaves the other running. Before that a single
scope meant enabling AWM in a second repo silently disarmed the first — and the `UserPromptSubmit`
banner ignored scope entirely, announcing away mode in projects where the gate denied every call
(#296). Both hooks now read the same entry.

The state **file** is machine-wide, not project-scaffolded — the skill files are versioned per
project so `den-refresh` updates them, but they must be copied to `~/.claude/skills/auto-wm/` by
hand once, and re-copied after an update that touches `hooks/`.

**When to use it.** "Enable autonomic/autonomous work mode", "/auto-wm", "partner mode", "work
by yourself for N hours", "no one will be around to approve/answer" — or to check status, switch
modes, or turn it off.

---

## Keeping the instructions true

### maintain-agent-instructions

[`SKILL.md`](../features/common/skills/maintain-agent-instructions/SKILL.md)

**What it is.** Reconciles agent instruction files — `CLAUDE.md`, `copilot-instructions.md`,
`AGENTS.md`, path-scoped instruction files — against each other and against a machine-readable
policy model, instead of hand-editing each one and letting them drift.

**What it does.** `node scripts/validate-agent-instructions.mjs` and
`scripts/check-agent-drift.mjs` (stdlib Node 18+, no dependencies) read the model at
`.ai-badger/agent-instructions/model.json` and report precise file/rule failures. The agent then
updates the model if policy changed, edits the smallest affected instruction file, and reruns
both scripts until they pass.

**When to use it.** Agent instruction files have drifted from each other or from the policy
model, or validation/drift checks fail in CI.

### mcp-index

[`SKILL.md`](../features/common/skills/mcp-index/SKILL.md)

**What it is.** Manages the MCP tool index — which tools exist, their tags, and their
intent — that a hook reads to recommend tools per turn instead of every MCP server's full tool
list bloating the system prompt.

**What it does.** `mcp_index.py init`/`update`/`tag`/`intent`/`list`/`validate`/`migrate` write
and curate `.ai-badger/mcp-tools.json`: each tool's tags (from a closed taxonomy), a one-sentence
intent, and each server's `status` (`ok`, `disabled`, `empty`, `unauthenticated`, …). The
`ai_badger_hooks.py` plugin's `pre_llm_call` hook reads that file, extracts terms from the user's
message, and injects the top-matching tool recommendations as context on the next turn.

**When to use it.** The agent keeps picking the wrong MCP tool, server tool definitions are
bloating the prompt, or MCP servers were just added or removed.

---

### ai-raccoon-memory

[`SKILL.md`](../features/common/skills/ai-raccoon-memory/SKILL.md)

**What it is.** The AiRaccoon memory server (`arasz.ai-raccoon`, MCP stdio): semantic search
over committed project memory and a shared promotion tier, durable-fact writes that carry
source paths, workspace outboxes for in-progress notes, and directory watching that mirrors a
docs tree into memory.

**What it does.** The watch-on-docs ritual runs first — `memory_watch_status(project_id)`, and
`memory_watch_add` when the docs directory is not watched — then search-first:
`memory_search(project_id, scope=all)` with 2-3 formulations before web search, code search,
or asking the user. Results escalate by outcome: a decisive hit is cited as evidence, a
partial hit gets one targeted external search, and a miss gets an external search followed by
a `memory_write` of the finding (source path included). Durable cross-project facts are
promoted with `memory_share`, never automatically.

**When to use it.** Any session in a project that has the server installed — the MCP entry is
declared when `ai-raccoon` is on PATH. Install it with
`dotnet tool install -g arasz.ai-raccoon`.

---

### semantica-knowledge-graph

[`SKILL.md`](../features/common/skills/semantica-knowledge-graph/SKILL.md)

**What it is.** Semantica (MIT, v0.6.5+) is a session-scoped knowledge graph MCP server
(`semantica-mcp`). It records decisions with W3C PROV-O provenance,
extracts entities and relations from text, traces causal chains, and runs forward-chaining
reasoning over an in-memory graph that accumulates across tool calls within a session.

**What it does.** The graph is session-scoped — no import mechanism exists, so `export_graph`
produces archival snapshots only. Durable facts go to AiRaccoon (`memory_write`). Four
workflows: decision recording (record rationale + link to affected components), entity
extraction from documents (needs torch/transformers for full NLP), decision archaeology
(query past decisions and trace causal ancestry), and graph export for audit trails.

**When to use it.** Reasoning over structured project knowledge — a decision was made and
its rationale should be traceable, entities need extracting from a document, or a causal
chain answers "why did we do this?". Install with `pip install semantica`.

### browser-usage

[`SKILL.md`](../features/common/skills/browser-usage/SKILL.md)

**What it is.** Universal browser automation and manual E2E verification skill using Playwright MCP (`@playwright/mcp`).

**What it does.** Employs a text-first architecture based on structured accessibility tree snapshots and element reference tokens (`[ref=eN]`), enabling LLMs to navigate, click, fill forms, handle dialogs, take screenshots, monitor network requests, and execute custom Playwright scripts without requiring vision models.

**When to use it.** Interacting with live web applications, running manual E2E verification journeys, reproducing browser-specific issues, inspecting network traffic/console errors, and asserting accessibility landmarks across UI states.

---

## Asked for, not shipped (`optIn`)

None of the 22 below is written into a project until `config.include.skills` names it — see the
opening of this page for the edit, and
[`authoring-a-feature.md`](authoring-a-feature.md#default-or-optin) for the mechanism. Every
scaffold and refresh report lists the ones a project has not installed, so nobody has to know
they exist in advance.

### scaffold-documentation

[`SKILL.md`](../features/common/skills/scaffold-documentation/SKILL.md)

**What it is.** The first-run half of the documentation workflow: it creates the canonical
`docs/` tree, not any document in it.

**When to use it.** A repository has no documentation tree, the layout is missing or incomplete,
or a structure check reports absent directories. Not for adding or editing a document.

### update-documentation

[`SKILL.md`](../features/common/skills/update-documentation/SKILL.md)

**What it is.** The steady-state half: documentation changes to match something that already
changed, and every new page gets decided a home before it is written.

**When to use it.** After a code change, ADR, schema change or PR lands; when a doc contradicts
the code; when a fact nobody can source needs one; before creating any new document.

### migrate-documentation

[`SKILL.md`](../features/common/skills/migrate-documentation/SKILL.md)

**What it is.** The one-off half: an existing documentation tree reorganised wholesale, with
accuracy established before anyone relies on it. Resumable — a migration in progress is picked
up where it stopped.

**When to use it.** Hundreds of files with no structure, documents that contradict each other, or
a `docs/` directory nobody can navigate.

### review-changes

[`SKILL.md`](../features/common/skills/review-changes/SKILL.md)

**What it is.** Risk prioritization for a diff: rank changed units by blast radius, then check
whether the riskiest ones are actually covered. It composes with `code-review-checklist` rather
than replacing it — the checklist runs the mechanical gates, this decides where attention goes.

**When to use it.** "Is this safe to merge", "what's the blast radius", "did anything untested
change".

### explore-codebase

[`SKILL.md`](../features/common/skills/explore-codebase/SKILL.md)

**What it is.** Orientation: establish the shape, the module boundaries and the entry points,
then follow one real path end to end before reading anything else.

**When to use it.** Arriving at an unfamiliar codebase, or an unfamiliar region of a known one,
where the question is *what is here* rather than *where is this specific thing*.

### debug-issue

[`SKILL.md`](../features/common/skills/debug-issue/SKILL.md)

**What it is.** The tracing step of debugging: walk the call chain from symptom to entry point
before forming a hypothesis.

**When to use it.** A bug report or failing test names a symptom and the code path producing it
is not yet known.

### refactor-safely

[`SKILL.md`](../features/common/skills/refactor-safely/SKILL.md)

**What it is.** Preview, apply, verify: enumerate every affected location before the first edit,
and confirm a removal has zero *reachable* callers rather than zero grep hits.

**When to use it.** A rename that spans call sites, an extraction that changes a signature, or a
removal that might delete something still in use.

Each of those last three names an accelerated path through a code-graph MCP server and a
baseline that needs none. Their workflows derive from the skill templates the
`code-review-graph` project auto-installs (MIT, © 2026 Tirth Kanani), rewritten to be
tool-agnostic — which is also why they are `optIn`: a project already running that tool receives
its own copies, and ai-badger does not contend for the same files uninvited.

### evidence-first-research

[`SKILL.md`](../features/common/skills/evidence-first-research/SKILL.md)

**What it does.** Produces a dated research record under `docs/work/` where every finding is
graded by *how it is known* — `MEASURED`, `READ`, `INFERRED`, `UNVERIFIED` — plus a
self-contained HTML view rendered outside the repository.

**What it actually changes on disk.** One markdown record you commit, and one HTML file in a temp
directory that you do not. `scripts/render_report.py` refuses a target inside the repo: the record
is the artefact, and a committed view becomes a second source of truth nobody can date.

**When to use it.** A question whose answer someone will act on or quote — a benchmark, an option
comparison, "is this worth doing". Not for locating code (`explore-codebase`), tracing one symptom
(`debug-issue`), or judging a diff (`review-changes`).

**Why the grading is enforced rather than encouraged.** The renderer refuses a record with an
ungraded finding, an unknown grade, or a `MEASURED`/`READ` claim carrying no `**Evidence:**` line —
so a clean render is itself a check. `UNVERIFIED` deliberately requires nothing: every requirement
attached there makes silence cheaper than admission, and a gap that simply goes unmentioned reads
to the next person as a gap nobody had a concern about.

Five chart kinds (`provenance`, `bars`, `line`, `matrix`, `range`) render as inline SVG with no
external hosts. The provenance chart is drawn first and always, including grades with zero
findings — a mix of one `MEASURED` and nine `INFERRED` is a hypothesis, not a finding, and the
reader needs to see that before the conclusion.

### research-record-audit

[`SKILL.md`](../features/common/skills/research-record-audit/SKILL.md)

**What it is.** The adversarial counterpart to `evidence-first-research`: it re-derives every
load-bearing claim in a written record from the cited primary sources instead of trusting the
record's own account of them. Quotes are checked verbatim, `MEASURED` claims are re-run, and the
grades themselves are audited for honesty.

**When to use it.** A research record, findings document, review write-up or incident report is
about to be acted on or quoted, and nobody has checked it against its sources.

### multi-lane-report-assembly

[`SKILL.md`](../features/common/skills/multi-lane-report-assembly/SKILL.md)

**What it is.** Merges the output of parallel research or review lanes into one graded record. It
lifts each `### F# — <claim> [GRADE]` block verbatim from the lane's authoritative full summary
rather than the truncated delegation transcript, truncates at an embedded `## Still open` header,
dedupes cross-cutting themes, and renumbers with a pass over the stale cross-references.

**When to use it.** Two or more dispatched lanes have each returned graded finding blocks that
have to become a single deliverable a strict renderer will parse.

### complete-project-scope-code-review

[`SKILL.md`](../features/common/skills/complete-project-scope-code-review/SKILL.md)

**What it is.** A review campaign for a whole codebase rather than a diff. It measures a
ground-truth baseline, derives its lane roster from the repository instead of a fixed list,
dispatches read-only expert lanes on the evidence-first grade contract, integrates them, then
runs an adversarial pass whose job is to falsify the record and publish what it refuted.
Severity is calibrated against the live system — a defect that has never fired is real but is
not a hotfix — and the plan that follows is itself reviewed twice before anyone builds. Its
`references/` carry the eight failure modes it exists to catch: circular benchmarks, vacuous
gates, specifications that encode the defect, join defects, in-sample numbers, findings that
turn out to be refutations, silent ratchets, and expectations pinned where they should be
derived. Stack, agent and platform specifics arrive from config-gated extensions.

**When to use it.** The whole project is the target and the findings will become work someone
implements. For one diff, use `review-changes` with `code-review-checklist`; for one design
document's gates, `design-gate-audit`.

**Replaces `parallel-expert-review`,** whose lane-dispatch job is this skill's Phase 1 and whose
plan-review variant is its Phase 5.

### code-review-evidence

[`SKILL.md`](../features/common/skills/code-review-evidence/SKILL.md)

**What it is.** A companion to `code-review-checklist` and `review-changes` aimed at one question:
is this claim evidence, or is it a restatement? It catches behaviour claims about wrapped
third-party code — native extensions, SDKs, CLIs — taken from the wrapper's own comments or from
the feature spec, and integration tests that assert values the method under test constructed.

**When to use it.** Reviewing code that wraps an external library, SDK or CLI, or judging whether
a test harness would actually catch a regression.

### review-gate-diff-verification

[`SKILL.md`](../features/common/skills/review-gate-diff-verification/SKILL.md)

**What it is.** Establishes that a branch diff is real before a review gate judges its contents.
A moved `origin/main` produces phantom `D`/`M` rows; `git show --name-status` greps that are not
anchored after the status tab match the wrong thing; build output under `bin`/`obj` pollutes
symbol greps; and a committed plan document can differ from the amended version that was accepted.

**When to use it.** Immediately before a code-review, phase or plan-versus-implementation gate
reads a diff.

### design-gate-audit

[`SKILL.md`](../features/common/skills/design-gate-audit/SKILL.md)

**What it is.** Audits a design document's acceptance-criteria table before implementation starts.
Each gate row answers two questions: would it fail if the feature were broken (honest), and does
the test file, framework or seam it names actually exist (feasible) — established by reading the
real test project, never taken from the document.

**When to use it.** A design document's gates need checking for vacuous negatives, timing-window
vacuity, port races, environment poisoning or unprovable real-time halves.

### artifact-verification

[`SKILL.md`](../features/common/skills/artifact-verification/SKILL.md)

**What it is.** The verification playbook for work products no code test covers — specs,
documents, manifests, generated files, published packages. It reaches for the workflow's own
checker first (`spec_holes.py` for a `create-task-spec` spec, for instance) rather than inventing
a parallel one, reviews manual fresh-install protocols against a false-pass checklist, and
separates a mid-workflow red that is expected from a real failure.

**When to use it.** Something claims to be done, the evidence matters, and `pytest` or
`dotnet test` does not apply to it.

### documentation-drift-audit

[`SKILL.md`](../features/common/skills/documentation-drift-audit/SKILL.md)

**What it is.** Audits documentation against the tree it describes — scaffolder behaviour,
manifests, hook registration, config schemas — and sorts every claim into exactly one bucket:
verifiably false, design position, ambiguous, or historical record. Only the verifiably false
bucket is edited; the rest are reported for a person to rule on.

**When to use it.** A feature just merged and the user docs or `CLAUDE.md` need checking against
it, or a document claims something about what the code does or ships.

### spec-driven-refactoring

[`SKILL.md`](../features/common/skills/spec-driven-refactoring/SKILL.md)

**What it is.** Two review gates around a large refactor: before implementation, that the written
spec is internally consistent and matches the real codebase; after it, a consistency and quality
review. Schema migrations, concept renames and structural reorganisations carry more surface area
for a stale assumption than a normal feature does.

**When to use it.** A refactor, migration or codebase-wide rename, or any change touching five or
more files across schemas, scripts, tests and documentation.

### scripts-tooling-refactor

[`SKILL.md`](../features/common/skills/scripts-tooling-refactor/SKILL.md)

**What it is.** Turns an accumulated `scripts/` directory into a maintained one: non-native
scripts converted to the repo's own tooling language, logic moved into `src/` behind thin wrappers
that keep the call sites working, tests written first, and dead scripts pruned only on usage
evidence — every reference classified live or historical before anything is deleted.

**When to use it.** Converting shell scripts, splitting logic out of a monolithic entrypoint, or
removing scripts nothing appears to reference any more.

### worktree-agent-isolation

[`SKILL.md`](../features/common/skills/worktree-agent-isolation/SKILL.md)

**What it is.** Runs several coding agents in parallel, each in its own git worktree branched from
`origin/main`, integrating through pull requests. The main checkout stays read-only, so agents
neither collide on shared build artefacts nor race each other's edits.

**When to use it.** Multiple independent tasks can run at once, or the instruction is "worktrees
only", "agent isolation", "parallel workstreams" or "don't touch main".

### pre-push-gate-debugging

[`SKILL.md`](../features/common/skills/pre-push-gate-debugging/SKILL.md)

**What it is.** An operating guide for a heavy local pre-push gate — a lefthook hook running docs,
unit, end-to-end, infrastructure and frontend lanes. Read the gate's own logs before anything
else, reproduce one lane at a time rather than the whole gate, and build a manual repro harness
when a lane's buffered output hides the real error.

**When to use it.** A pre-push quality gate is blocking `git push`, or one lane fails and the hook
output does not say why.

### git-work

[`SKILL.md`](../features/common/skills/git-work/SKILL.md)

**What it is.** Git work outside the quality gate: non-fast-forward push recovery with the
force-with-lease decision, branch-protection and auth rejections, crashed-hook replay, CI failure
triage (`gh run view --log-failed`, reproduce-vs-rerun, env-only failures, flake attribution), the
draft-to-squash PR lifecycle with reviewer-quota fallback, squash-merge conventions, and
join-time conflict resolution on plain branches — with worked cases from this repo's history in
`references/case-playbooks.md`.

**When to use it.** A push fails for a reason the quality gate did not cause, CI goes red on a
pushed branch, or a PR moves through review and merge outside the tracked-task flow.

### sqlite-schema-review

[`SKILL.md`](../features/common/skills/sqlite-schema-review/SKILL.md)

**What it is.** Review for SQLite DDL, on-open migrations, unique indexes and insert-path dedup
logic, under one rule: every claim about semantics — `ON CONFLICT` scope, `last_insert_rowid`
staleness, when a trigger fires and what a failure inside one does, how a UNIQUE index treats
`NULL` — is verified against a scratch database rather than accepted from the plan, the PR or the
documentation.

**When to use it.** A change touches SQLite schema, a migration that runs on open, a unique index,
or the dedup logic on an insert path.

### sqlite-bank-space-diagnosis

[`SKILL.md`](../features/common/skills/sqlite-bank-space-diagnosis/SKILL.md)

**What it is.** Diagnoses a bloated SQLite file or write-ahead log read-only first: snapshot the
file, measure per-table space with `sqlite3_analyzer`, run `PRAGMA wal_checkpoint(TRUNCATE)` on
the snapshot to size the checkpoint debt, and `VACUUM INTO` to quantify what the freelist would
give back — all before the live file is touched. It also covers WAL growth under connection
pooling and the `vec0` chunk `count(*)` trap.

**When to use it.** A SQLite bank file or its WAL has grown large and neither the cause nor a safe
way to reclaim the space is established.

---

## Related docs

- [`framework-architecture.md`](framework-architecture.md) — the catalog model these skills are
  filed under, and the script-vs-agent split each one follows.
- [`getting-started.md`](getting-started.md) — `welcome-ai-badger` and `den-refresh` walked end
  to end with real command output.
- [`README.md`](README.md) — the full documentation map.
