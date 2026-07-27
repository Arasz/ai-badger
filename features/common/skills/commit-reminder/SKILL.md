---
name: commit-reminder
description: >-
  Use when a project has accumulated uncommitted changes and nobody has said so out loud —
  several edits in a row with no commit in between. A PostToolUse hook watches the live
  `git status --porcelain` count after every edit-shaped tool call and nudges once it crosses a
  threshold, then stays quiet until the count drops and climbs again.
---

# Commit reminder

A small nudge, not a gate: this hook only ever adds `additionalContext` to a `PostToolUse`
event. It never blocks, denies, or otherwise gates the tool call that triggered it — no
`decision`, no `permissionDecision`, no `continue` field, on any code path. That distinction is
load-bearing for this project: `docs/changelog/0.33.0-no-third-party-tool-call-interception.md`
records ripping out a third-party plugin that hooked every `Write`/`Edit`/`Bash` call and forced
an OAuth login before letting it through. This skill exists to never repeat that mistake.

## What triggers it

After every `Write`/`Edit`/`MultiEdit`/`NotebookEdit` (or a Hermes edit-shaped tool call), the
hook runs `git status --porcelain` in the project root and counts the files it lists. There is no
separately tracked file list — the live count *is* the signal — so the moment a commit happens,
the count drops on its own and the hook needs no cleanup step to notice.

## The debounce ratchet

A per-project marker is persisted between calls. The hook fires once when the count first
crosses the threshold, then stays silent on every subsequent call at the same or a higher count
— otherwise it would nag on every single edit past the threshold. As soon as the count drops
below the stored marker (a commit happened), the marker ratchets down immediately, so climbing
back past the threshold later fires the reminder again. It is a re-arming debounce, not a
one-time flag.

## Configuration

- `AI_BADGER_COMMIT_REMINDER_THRESHOLD` — uncommitted-file count that triggers the nudge.
  Defaults to `5`. A non-numeric value falls back to the default rather than erroring.
- `AI_BADGER_COMMIT_REMINDER_IMPACT=graph` — opt into a richer impact estimate backed by the
  `code-review-graph` CLI instead of the cheap default (file count + directory spread). This is
  slower (roughly 15-20 seconds observed per call), so it only runs once the cheap check has
  already decided to fire — never on every edit — and it falls back to the cheap estimate
  silently if the graph call fails or isn't available.

## Observability

Every run logs to the `debug_log`/`call-behaviorist` audit trail under component name
`commit_reminder_hook` (a no-op unless that facility is switched on): `skip` when the hook exits
early, `checked` after computing the uncommitted count, and `fire` when the reminder is actually
emitted. Use the `call-behaviorist` skill to enable logging and inspect what this hook has done.

## Files

- `scripts/commit_reminder.py` — pure logic: parsing `git status --porcelain`, recognizing an
  edit-shaped tool, and the debounce ratchet itself.
- `scripts/impact_estimator.py` — the cheap default and optional graph-backed impact summary.
- `scripts/commit_reminder_hook.py` — the `PostToolUse` entry point wiring the above together.
- `scripts/debug_log.py` — a vendored, byte-identical copy of the framework's debug logger (hooks
  run from several deployment shapes and must not depend on the framework being importable).
