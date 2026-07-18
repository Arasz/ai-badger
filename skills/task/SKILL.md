---
name: task
description: >-
  Run one backlog task end-to-end as a cleanly separated, token-tracked unit of work with model
  delegation (a high-reasoning model plans/reviews; implementation models do the hands-on work).
  Use whenever the user wants to start, continue, or finish a backlog task — "/task <id>", "start
  task X", "work on the next task", "finish this task". Reads project specifics from
  .ai-badger/config.json; source-control/PR behavior comes from config-gated extensions.
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

Subagent prompts must be self-contained: scope, acceptance criteria, files/docs to read, the
project's TDD + code-style rules (point them at CLAUDE.md), and what to report back. Run
independent subagents in parallel.

## Phase 0 — Context hygiene

1. `python3 scripts/task_tracker.py status`. If a previous task is unfinished, finish or park it.
2. Confirm `.ai-badger/state.json` reflects the last finished task; repair if not.
3. If this session carries heavy history, tell the user to `/compact` (or start fresh) and
   re-invoke `/task <id>` on a clean context, then stop — unless autonomous.

## Phase 1 — Start

1. Resolve the task (an issue URL, or freeform text used as scope/title; cross-check the project
   board via the source-control extension if active). Read the referenced docs.
2. Register: `python3 scripts/task_tracker.py start <taskId> --title "<title>" --branch task/<taskId>-<slug>`.
3. Ask the user to rename the session to match the task (skip if autonomous).
4. Create/switch to the task branch.
5. Plan: delegate decomposition to a high-reasoning agent (the `architect` persona), feeding it
   the task body and doc excerpts. Use its plan to drive Phase 2.

## Phase 2 — Execute

1. Dispatch implementation subagents per `personaRouting`. Instruct every code subagent to write
   the failing test first (TDD).
2. Record each subagent's `total_tokens` on completion:
   `python3 scripts/task_tracker.py subagent <taskId> <total_tokens> --description "<what it did>"`.
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
4. Close tracking: `python3 scripts/task_tracker.py finish <taskId>`.
5. Ask the user to grade the skill 0–5: `python3 scripts/task_tracker.py grade <taskId> <0-5>`
   (skip/leave unset if autonomous).
6. Report the task's token cost and recommend `/compact` before the next task.

## Phase 5 — Documentation-gap audit

After integration, delegate a doc-audit agent (worktree-isolated) to check CLAUDE.md and the
project's docs against the merged code, fix small drift, and report gaps needing a decision.

## Recovery

`task_tracker.py` records each task's session id and resume command; a resume cron watches for
stalled sessions. If you wake in a resumed session mid-task, run
`python3 scripts/task_tracker.py reattach <taskId>` first, then continue.

> **Extensions:** source-control PR/issue/review-loop behavior is defined in
> `extensions/<name>/` and is embedded by `welcome-ai-badger` only when `config.json` supplies
> the required data. The base skill above stays platform- and stack-neutral.
