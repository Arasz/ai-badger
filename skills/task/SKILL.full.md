---
name: task
description: >-
  Use when the user wants to start, continue, or finish a backlog task — "/task <id>", "start
  task X", "work on the next task", "finish this task". Runs it end-to-end as a cleanly
  separated, token-tracked unit of work with model delegation: a high-reasoning model plans and
  reviews, implementation models do the hands-on work. Project specifics come from
  .ai-badger/config.json; source-control and PR behaviour from config-gated extensions.
platforms: [linux, macos]
---

# task orchestration skill

Runs one backlog task as a separated, token-tracked unit of work. High-leverage thinking —
planning and the final quality gate — is delegated to a high-reasoning model; implementation
models do the hands-on work; the orchestrating session integrates and tracks everything so a
dead session can be resumed.

**All project specifics come from `.ai-badger/config.json`** — never hardcode a build command,
a persona name, or a repository. Tracking data lives in `.ai-badger/task-tracking/` (gitignored).
Scripts live in this skill's `scripts/`.

## Config contract (read first)

From `.ai-badger/config.json`:
- `commands.build` / `commands.test` / `commands.lint` — the verification commands for Phase 3.
- `personaRouting` — maps kinds of work to the scaffolded personas; drives Phase 2 dispatch.
- `sourceControl` — platform + repo/project URLs; **gates the source-control extension** (PR
  flow, review loop, issue/board integration). If `sourceControl.platform == "github"` and a
  `repoUrl` is present, this skill's `extensions/github/` fragment is active — follow it for the
  PR/review-loop steps below. Otherwise commit locally and integrate per your platform.

## Model & delegation policy

Spend high-reasoning capacity on plans, decomposition, and review — not on typing
implementations. The orchestrating session obtains that reasoning by explicit delegation, not by
assuming its own model.

- **Delegate to a high-reasoning agent** (planning/decomposition in Phase 1; the final
  correctness + architecture gate in Phase 3). Prefix such calls' description to keep the model
  visible at a glance.
- **Delegate to implementation agents** matched to the work, using the personas from
  `config.json`'s `personaRouting`. TDD is mandatory for code.
- **Delegate trivial mechanical work** (doc/comment updates, rote refactors, test backfills) to a
  cheap model.
- **The orchestrating session does directly:** fetch the task, read docs, record token usage, the
  lightweight per-subagent completion check, run the configured build/test, and tiny surgical
  fixes found during the quality gate.

These are roles, not models. Which concrete model fills each role — and why the subscription's
metering makes that the cheap choice rather than merely the fast one — is bound by the
agent-specific extension for your coding agent (`extensions/claude/` for Claude).

Subagent prompts must be self-contained: scope, acceptance criteria, files/docs to read, the
project's TDD + code-style rules (point them at CLAUDE.md), and what to report back. Run
independent subagents in parallel.

**Known display artifact — do not misdiagnose as a dispatch bug:** the live agent panel's
per-task `model` field (and any custom status line reading it) can transiently show a stale
value — e.g. showing the parent session's model for a subagent that was actually dispatched with
a different `model` override. Root cause: the panel field comes from an async live-status feed, a
separate code path from the `resolvedModel` Claude Code writes into the session transcript's
tool-result metadata at call completion. The transcript is ground truth; the panel is a snapshot
that can lag it. If a dispatch's actual model is ever in doubt, grep the session's `.jsonl`
transcript for the `Agent` tool_use whose `description` matches, and check its paired
`tool_result`'s `toolUseResult.resolvedModel` rather than trusting the panel. Don't spend time
re-investigating this as a dispatch-code problem unless the transcript itself shows the wrong
`resolvedModel`.

**Cache-aware dispatch:** every agent's request prefix includes your project's always-loaded
context (CLAUDE.md/AGENTS.md-equivalent instructions, `.ai-badger/state.json`, and any other
files your project loads on every turn) — keep them byte-stable within a task (never rewrite them
mid-task; the finish protocol writes state *between* tasks) so they serve as cache reads at
roughly a tenth of the cost instead of a fresh write. Subagent caches are independent cold starts
on a ~5-minute TTL, so: prefer one multi-turn subagent over many one-shot dispatches for a
cluster of related steps (amortises the cold start), and use `/rewind` rather than `/compact` to
backtrack within a task (rewind reuses the cached prefix; compact pays for a fresh summary
write). Compact only at task boundaries (Phase 0).

**Where subagent work actually lives.** Not in the main transcript: measured over 171 real
transcripts, *no record carries `isSidechain: true`*. Claude Code writes each dispatch to
`<transcript-dir>/<session-id>/subagents/agent-<id>.jsonl`, with a paired `agent-<id>.meta.json`
naming its `agentType`, `description`, `spawnDepth` and `model`. `parse_transcript_usage` reads
both, so a **per-dispatch** split is available — it needs no `parentUuid` chasing, and does not
depend on the completion notification, which exposes only `total_tokens`. Treat `meta.json` as
the undocumented CLI artefact it is: a format change must degrade to `unknown`, never to zero,
or it reads as a delegation collapse that never happened.

**Judge a task by its model mix, not its cache efficiency.** `token-usage.json` records both.
`cacheEfficiency` (cache_read ÷ (cache_read + cache_creation)) turns out not to discriminate:
measured over 1250 real sessions it sits at 0.975-0.986 on every one, including the most
expensive. It is worth watching only for a *collapse*, which means the prefix is churning.

`modelMix` is the number that moves. Over those same sessions the expensive and mid tiers
produced comparable output volume — 23.7M vs 20.6M tokens — at **3.1× the cost**, so which model
did a task's output is the largest lever available, and it is precisely what the delegation
policy above steers. `python3 .ai-badger/skills/task/scripts/task_tracker.py status` shows the
dominant model and its share (`mix=opus-5:69%`); `outputByModel` carries the full split.

Read it as the **delegation ratio** — the share produced by the mid and cheap tiers — over the
main transcript *and* its subagents together. Those are different numbers and only the combined
one means anything: on one real session the main thread alone reads 2.3% while the true figure
is 23.8%. `dispatches` carries the other half of the picture: how many dispatches ran, how many
named no model — one that names none takes the `model:` lane in its persona's frontmatter, and
the dispatch gate denies one whose persona has no lane — and which agent types they went to. A
run where most dispatches are `general-purpose` is not routing to the personas this project
scaffolds, whatever `personaRouting` says.

No prices are recorded. They change, and a stale hardcoded rate would be a confidently wrong
number; output tokens per model is the durable half, and a reader applies today's rates.

**If you cannot spawn subagents** (you are running as a subagent yourself, or the Agent tool is
unavailable), do the work directly in-session at whatever model is available — the workflow's
tracking and finish protocol still apply, but note in your summary that planning/review ran at
reduced rigor since high-reasoning delegation wasn't possible.

## Phase 0 — Context hygiene

1. `python3 .ai-badger/skills/task/scripts/task_tracker.py status`. If a previous task is unfinished, finish or park it.
2. Confirm `.ai-badger/state.json` reflects the last finished task; repair if not.
3. If this session carries heavy history, tell the user to `/compact` (or start fresh) and
   re-invoke `/task <id>` on a clean context, then stop — unless autonomous.

## Phase 1 — Start

1. Resolve the task (an issue URL, or freeform text used as scope/title; cross-check the project
   board via the source-control extension if active). Read the referenced docs.
   **If the argument is a path to a `spec.json` written by `create-task-spec`,** read it and its
   companion `.feature` file instead of treating the path as a title: the manifest supplies the
   scope, out-of-scope, constraints and deferred decisions, and the spec supplies the acceptance
   criteria. Feed both to the planning agent in step 5, and hold the non-deferred scenarios as
   Phase 3's pass condition.
2. Register: `python3 .ai-badger/skills/task/scripts/task_tracker.py start <taskId> --title "<title>" --branch task/<taskId>-<slug>`.
3. Ask the user to rename the session to match the task (skip if autonomous).
4. Create/switch to the task branch.
5. Plan: delegate decomposition to a high-reasoning agent (the `architect` persona), feeding it
   the task body and doc excerpts. Use its plan to drive Phase 2.

## Phase 2 — Execute

1. Dispatch implementation subagents per `personaRouting`. Instruct every code subagent to write
   the failing test first (TDD).
2. Record each subagent's `total_tokens` on completion:
   `python3 .ai-badger/skills/task/scripts/task_tracker.py subagent <taskId> <total_tokens> --description "<what it did>"`.
3. Review each result at the seams (matches plan? acceptance criteria?). Send follow-ups back
   rather than rewriting, unless the fix is a few lines.
4. Commit and push per work package (small commits). If the source-control extension is active,
   open a draft PR early per `extensions/github/`.

## Phase 3 — Quality gate

Run the configured `commands.build` and `commands.test` yourself and capture output. Then
delegate a review to a high-reasoning agent (the `code-reviewer` persona) with the diff,
acceptance criteria, relevant architecture docs, and the build/test output. Ask it to judge
implementation correctness (logic, edge cases, test honesty) and architecture (layer purity,
consistency with docs). Fix findings (trivial yourself, substantial via a subagent), re-run
build/test, then proceed.

## Phase 4 — Finish protocol

1. If the source-control extension is active, follow `extensions/github/` for PR-ready, the
   review-round loop, and squash-merge. Otherwise integrate per your platform.
2. **Update state files:** prepend the finished task's lean entry to `.ai-badger/state.json`'s
   `completedTasks`, refresh `next`/`lastUpdated`; write verbose notes/decisions to the
   project's notes file.
3. Compaction check on CLAUDE.md if the project tracks one.
4. Close tracking: `python3 .ai-badger/skills/task/scripts/task_tracker.py finish <taskId>`.
5. Ask the user to grade the skill 0–5: `python3 .ai-badger/skills/task/scripts/task_tracker.py grade <taskId> <0-5>`
   (skip/leave unset if autonomous).
6. Report the task's token cost and recommend `/compact` or a fresh session before the next
   task — this is the default ending. **Authorized auto-continue** (alternative path, only when
   an observable condition holds: the `auto-wm` skill's autonomic/partner mode is active, or the
   user's original invocation explicitly said to continue to the next task): after Phase 5
   completes, compact per Phase 0 guidance, read the next task from `.ai-badger/state.json`'s
   `next` field (or the next unclaimed item on your configured backlog source), and invoke this
   skill again for that task. If neither condition holds and no user is available, start a fresh
   session and tell the user to re-invoke the skill so the next task starts on a clean context.

## Phase 5 — Documentation-gap audit

After integration, delegate a doc-audit agent (worktree-isolated) to check CLAUDE.md and the
project's docs against the merged code, fix small drift, and report gaps needing a decision.

## Recovery

`task_tracker.py` records each task's session id and resume command. Pass `--cron` to `start` to
also install a resume cron that watches for stalled sessions — it is opt-in, since it writes to
your crontab. If you wake in a resumed session mid-task, run
`python3 .ai-badger/skills/task/scripts/task_tracker.py reattach <taskId>` first, then continue.

> **Extensions:** source-control PR/issue/review-loop behavior and agent-specific model lanes
> are defined in `extensions/<name>/` and are embedded by `welcome-ai-badger` only when
> `config.json` supplies the required data. The base skill above stays platform-, stack- and
> model-neutral.
