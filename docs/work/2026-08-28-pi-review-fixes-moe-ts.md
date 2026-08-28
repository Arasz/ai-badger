# Plan: TypeScript / pi-extension work packages — aib-pi-review-fixes

Architect lane plan for the features/pi TS deliverables. Covers F1 (missing hooks adapter),
F2 (broken cron extension), F5 (no_agent default), F7 + F3-doc-half (extension.md), and the
new away-mode scope item. Python-side fixes (`adjust_hooks.py`, `adjust_cron.py`,
`pi_session_source.py`, `tests/test_pi_adjustments.py`) belong to other lanes; this plan only
states the contracts they depend on.

## Verified facts (measured this session, Bun 1.4.0 / pi 0.84.3)

1. **`Bun.cron(path, schedule, title)` registers OS-level jobs and validates the path.**
   With an existing file: returns OK, creates `~/Library/LaunchAgents/bun.cron.<title>.plist`,
   `launchctl list` shows the agent. With a missing file: `TypeError: Failed to resolve path`
   (matches the orchestrator's witness). So today's `cron/index.ts:44` **throws at extension
   load** for every job, because `run-job.ts` does not exist.
2. **The fired-script contract is `default { scheduled(controller) }`** — witnessed from
   `/tmp/bun.cron.t.stderr.log` after a real launchd fire: the Bun runner executes
   `const mod = await import(path); const scheduled = (mod.default || mod).scheduled;`
   and throws `Module does not export default.scheduled()` otherwise. Top-level-only
   scripts fail. A plain `* * * * *` plist (empty `StartCalendarInterval` dict) fired twice
   within two minutes, so launchd firing itself works.
3. **pi runs under node, so the `Bun` global does not exist inside extensions.**
   pi's bin resolves to `dist/bundle/cli.js` with `#!/usr/bin/env node`;
   `typeof Bun` under node is `undefined`. `registerWithBun` can only work by shelling out
   to the bun binary (`bun -e 'await Bun.cron(...)'` — registration persists process exit
   because the job is OS-level).
4. **pi 0.84.3 extension API** (installed docs `docs/extensions.md` + `dist/core/extensions/types.d.ts`):
   `pi.on("tool_call", handler)` — `event.input` mutable, return `{ block: true, reason, terminate? }`
   to block, `undefined` to allow; handlers run in extension load order. `ctx.ui.confirm(title, message, opts?)`
   returns `Promise<boolean>`; dialog `opts.timeout` auto-dismisses to `false` (deny) and is
   caller-controlled. `ctx.hasUI` is `false` in `-p`/JSON mode. **There is no API for one
   extension to intercept or answer another extension's dialog** (checked: UI override APIs,
   dialog options, `pi.events` bus — the bus carries custom events, not UI calls).
5. **pi flags**: `--resume, -r` takes no argument ("Select a session to resume");
   `--session <path|id>` ("Use specific session file or partial UUID") and `--session-id <id>`
   are the correct forms. Extension auto-discovery: `~/.pi/agent/extensions/<name>/index.ts`.
6. `adjust_hooks.py` copies only `*.ts`/`*.json` from `ADAPTER_DIR` ("adapter");
   `adjust_cron.py` copies **every file** from `features/pi/cron/` (so a new `run-job.ts`
   needs no python change to be installed).

## Cross-lane contracts

- **python-adjustments lane**: after P1 lands, `features/pi/adjustments/adapter/` contains
  `index.ts` + `package.json` — exactly the `.ts`/`.json` copy filter expects. The lane's
  fail-loud change to `_install_user_extension` should error when `ADAPTER_DIR` is missing
  (it will not be missing after P1). Note: the entry file is `index.ts`, not the docstring's
  `adapter.ts`; the lane should align the `adjust_hooks.py` docstring (14-17) wording.
- **test-honesty lane**: `install: True` cases monkeypatching `USER_EXTENSIONS_DIR` are the
  regression net for F1/F2 on the python side; they go red before P1/P3 and green after.
- **extension.md ↔ pi_session_source.py**: P4 fixes `extension.md:21` to the same flag the
  python lane lands in `pi_session_source.py:30` (default plan: `pi -p --session {id}`);
  the two must not diverge. Recommend test-honesty add a consistency assertion.

## Package 1 — hooks adapter extension (F1, BLOCKER)

**Goal**: ship the adapter that `adjust_hooks.py` claims exists, so `adjust()` with
`install: True` actually installs a working extension into `~/.pi/agent/extensions/ai-badger/`.

**Files** (all new):
- `features/pi/adjustments/adapter/index.ts`
- `features/pi/adjustments/adapter/package.json` — `"pi": {"extensions": ["./index.ts"]}`,
  type-only import of `ExtensionAPI` (no runtime deps → nothing else to copy/install)
- `features/pi/adjustments/adapter/index.test.ts`

**Design**: default-factory extension. On `tool_call`: translate the pi event to the
Claude-shaped JSON `ai_badger_hooks.py` expects, shell out to
`python3 <ctx.cwd>/.ai-badger/hooks/ai_badger_hooks.py` via `pi.exec` (or `node:child_process`)
passing `PI_SESSION_ID` (pi exports it to subprocesses — verified in the findings preamble),
map the hook response back: deny → `{ block: true, reason }`; "ask" → `ctx.ui.confirm`
guarded by `ctx.hasUI` (no UI → block with reason, mirroring `permission-gate.ts`);
approve → `undefined`. Hooks missing at `ctx.cwd` → one-time `ctx.ui.notify` + fail-open
(these hooks are advisory instruction-layer tooling, not a security boundary).

**Implementer must first read** `features/common/hooks/ai_badger_hooks.py` and pin its
actual response JSON schema — do not invent the translation table. Abort propagation:
pass `ctx.signal` so an Esc-cancelled tool call kills the python subprocess.

**Red-first tests** (`bun test features/pi`):
- translation of a bash `tool_call` event → expected Claude JSON (pure function);
  red before `index.ts` exists (module-not-found is the witnessed failure).
- hook "deny" response → `{ block: true, reason }`; "ask" + `hasUI=false` → block;
  "approve" → `undefined`.
- gate is provably able to fail: delete `adapter/` → both python install:True test and
  the TS tests are red (this is exactly today's state).

**Acceptance**: `bun test features/pi` green; `bunx tsc --noEmit -p features/pi` clean;
with `install: True`, `~/.pi/agent/extensions/ai-badger/` contains `index.ts` +
`package.json` and `pi -e` loads it without error.

## Package 2 — away-mode (new scope; extends Package 1)

**Goal**: pi can run unattended by auto-answering the confirm dialogs raised in the
adapter's own `tool_call` handler.

**Same extension as P1, not a separate one.** Rationale: pi has no mechanism for one
extension to auto-answer another extension's `ctx.ui.confirm` (verified fact 4) — a
standalone away-mode extension could not reach the gate's dialog. The gate ("ask" branch)
and the away policy must share code, so they share a file. Third-party gates stay
unaffected — documented limitation, not silently ignored.

**Arming**: env var `AI_BADGER_PI_AWAY=1` (default OFF, mirroring `AI_BADGER_MEMORY_GRADE=1`)
as the initial state, read once at factory time; `/away` command (`pi.registerCommand`)
toggles the session-scoped flag live and reflects it via `ctx.ui.setStatus("ai-badger", ...)`.
Both flows are needed: orchestrator-launched unattended runs (`pi -p`) can only receive env
vars, while an interactive session the user walks away from can only be armed at runtime.
Config file rejected: a persisted ON state is a silent auto-approver left armed —
default-off per process is the safe shape.

**Behavior when armed**: "ask" decisions auto-approve — return `undefined` **without
calling `ctx.ui.confirm`**, plus `ctx.ui.notify("ai-badger: away-mode approved <tool>", "info")`
so the audit trail shows what ran unattended. Unarmed behavior unchanged from P1.

**Red-first tests**: fake `confirm` spy injected into the handler — armed: spy not called,
result `undefined`, notify emitted; unarmed: spy called; `hasUI=false` unarmed: block.
Red before the armed-state code exists.

**Acceptance**: tests above green; `PI_BADGER…`/`AI_BADGER_PI_AWAY` unset → no behavior
change vs P1 (default-off proven, not asserted); `extension.md` documents the flag (P4).

## Package 3 — cron extension repair (F2 BLOCKER + F5 MAJOR)

**Goal**: registered jobs actually fire; documented no_agent default becomes real.

**Files**:
- `features/pi/cron/index.ts` — rework registration path
- `features/pi/cron/run-job.ts` — new, the fired entry
- `features/pi/cron/launchd.ts` — new, plist + `StartCalendarInterval` translation (pure functions)
- `features/pi/cron/index.test.ts`, `run-job.test.ts`, `launchd.test.ts` — new

**Design**:
1. Registration ladder: `typeof Bun !== "undefined"` (pi under bun) → in-process
   `Bun.cron`; else bun on PATH → `execFile(bunPath, ["-e", registrationScript])` with
   JSON-quoted args (verified fact 3 — this is the only path that works under node);
   else launchd fallback. `HAS_BUN`'s `which bun` check conflates "bun installed" with
   "running under bun" — replace, don't reuse.
2. `run-job.ts` exports `default { scheduled(controller) }` (verified contract, fact 2).
   It loads `~/.config/ai-badger/cron.json` **fresh at fire time**, finds the job by title,
   runs `job.command` via `sh -c`, logs to the bun-provided stdout/stderr files.
3. **Job identity**: `Bun.CronController` is documented to expose only `cron/type/scheduledTime`
   (title exposure unverified — see recorded check). Default design: registration generates
   a per-job wrapper `<ext>/.generated/<safe-title>.ts` containing a 3-line default-export
   that delegates to `run-job.ts` with the original title. If the 5-minute probe (below)
   shows the title is reachable from the fired process (`process.argv`, env), drop the
   wrappers for a single `run-job.ts` — simpler wins.
4. Launchd fallback (no bun): keep `/bin/sh -c command` execution but (a) emit
   `StartCalendarInterval` dicts from the cron expression (expand ranges/lists/steps;
   `StartInterval` is load-relative and NOT equivalent), capping expansion (e.g. 366 dicts)
   with a skip+notify beyond it, and (b) XML-escape the interpolated command/paths — the
   current template breaks on `<`/`&`. Keep `RunAtLoad=false`/`KeepAlive=false`.
5. F5: schedulable set = `jobs.filter(j => j.noAgent !== false)` (docstring default true
   becomes real); `/cron-status` already distinguishes agent-attended jobs — keep.
6. Titles sanitized to `[A-Za-z0-9_-]` (Bun requirement); invalid → skip + notify, not
   silent. Stale-job prune at `session_start`: scan
   `~/Library/LaunchAgents/bun.cron.ai-badger-cron-*.plist`, `launchctl bootout` + unlink
   titles no longer in `cron.json` (documented uninstall commands; same-title
   re-registration overwrites in place, so only removals leak).

**Red-first tests** (`bun test features/pi`):
- `cronToCalendarIntervals("*/15 9-17 * * 1-5")` → exact dict list; `@daily` → one dict;
  over-cap pattern → throws. Red: `launchd.ts` doesn't exist.
- plist template with command `echo "<x>" &` → escaped output parses as XML.
- `schedulableJobs` selector: job without `noAgent` **is** included (F5 — red today:
  current filter drops it); explicit `noAgent: false` excluded.
- title `"my job!"` → rejected/sanitized, no throw.
- `run-job.ts` shape: `typeof (await import("./run-job.ts")).default.scheduled === "function"`
  (red today — file missing; this pins the witnessed fire contract).
- integration (witness, not CI): register a real `* * * * *` job against the real
  `run-job.ts` via the `bun -e` ladder, observe one fire within ~70 s writing a marker
  file, then bootout. Do once in the lane, record the witnessed stderr/log lines.

**Acceptance**: all tests green; tsc clean; the witnessed fire above recorded in the PR;
`adjust_cron.py`'s docstring claim and behavior agree (python lane's file).

## Package 4 — pi extension docs (F7 minor + F3 doc half + away-mode note)

**Files**: `skills/task/extensions/pi/extension.md` only.

1. Line 21: `pi --resume <session_id>` → `pi -p --session <session_id>` (or `--session-id <id>`
   for exact project session IDs); keep the line's other claims untouched; wording must
   match the python lane's `pi_session_source.py` fix.
2. Line 11: "Use the built-in subagent extension" → the subagent extension is an example
   requiring manual install from `examples/extensions/subagent/` in the pi package; state
   the install step and that nothing is installed by default.
3. Hook-integration section: add the away-mode line — `AI_BADGER_PI_AWAY=1` / `/away`,
   default off, auto-approves hook "ask" decisions and notifies. The event-translation
   table (lines 37-44) becomes true once P1 ships — leave the table, drop nothing.

**Gate**: doc drift is checked by the existing documentation instructions + the
test-honesty consistency assertion (cross-lane). A doc-only change has no runtime test;
the proof-of-done is the diff against the verified `--help` output (fact 5).

## Tooling note (applies to P1-P3)

The repo has no root package.json/tsconfig — TS gates must be created, minimally:
- `features/pi/tsconfig.json` (moduleResolution for the type-only pi import; noEmit) —
  makes `bunx tsc --noEmit -p features/pi` a real gate.
- `bun test features/pi` as the TS test command (bun 1.4 present; zero new dev-deps).
Whether the pre-push gate gains these two commands is an orchestrator decision (open
question); the lane must run both locally regardless and record output in the PR.

## Recorded simplification checks (probe first, then simplify)

- **CronController title exposure** (P3): if the fired process can see `--cron-title`
  (argv/env/controller), delete the per-job wrapper files. Probe before implementing.
- **`pi -p` most-recent-session claim** (extension.md line 21, outside finding scope):
  `--continue, -c` exists ("Continue previous session"); if the lane touches the line
  anyway, verify and prefer the explicit flag.

## Machine-state disclosure (this planning session)

Verification left artifacts the user declined to have cleaned: launchd agents
`bun.cron.t` (fires every minute, errors into `/tmp/bun.cron.t.*.log`) and
`bun.cron.sig-test` (Monday 03:00), one background `bun` process (pid 4752), and
`/tmp/buncron-test/` + `/tmp/bun.cron.*.log` files. Cleanup, if desired:
`launchctl bootout gui/$(id -u)/bun.cron.t; launchctl bootout gui/$(id -u)/bun.cron.sig-test`
then delete the matching `~/Library/LaunchAgents/bun.cron.*.plist` files and kill pid 4752.
