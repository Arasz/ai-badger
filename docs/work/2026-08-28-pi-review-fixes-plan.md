# Plan: aib-pi-review-fixes — pi review fixes + full usable pi support (rev 2)

**Task:** `aib-pi-review-fixes` · branch `task/aib-pi-review-fixes` · worktree `.ai-badger/worktrees/aib-pi-review-fixes`.
**Rev 2 disposition (MoE plan review, architecture lens, APPROVE-WITH-CHANGES):** B-MUST-1→D17/§4E, B-MUST-2→G5/§8.3c, B-SHOULD-3→D3, B-SHOULD-4→D1, B-SHOULD-5→G2/§4E, B-SHOULD-6→G3, B-SHOULD-7→G4/T9, B-SHOULD-8→§4A/TS-P1, B-SHOULD-9→§4C, B-NIT-10→D3, B-NIT-11→§9. Safety-lens coverage (lane died on API timeouts; orchestrator folded its targets directly): away-mode default-off provability → D2; settings-write atomicity/idempotency → G1/G2; cutover-gate precision → §10 checklist.

**Scope (owner-corrected, 2026-08-28):** fix all 18 review findings, and deliver a **simple, usable form of every feature the owner uses daily and that ai-badger needs** in pi. Full parity with claude/hermes/copilot is explicitly out of scope; every deferred-parity item is justified in the gap audit (`2026-08-28-pi-full-support-gaps.md`).
**Owner signal (2026-08-28):** *pi is ready and intended to **replace hermes** as the daily harness* — this resolves the ADR-0016 swap recommendation in pi's favor. Consequence: the integration package (§4 E) carries a **machine-cutover gate** (§10) — extensions installed user-scope on this machine and the daily loop verified live in pi. Features ai-badger delivers to hermes that have no simple pi form are replacement blockers — the gap audit lists them first.
**Owner instruction (f:, 2026-08-28):** after the plan is done, dump it to a .md file **on main** and return the path with the task id — done at the end of this revision.
**Companion repo:** pi-mcp-tools fork `/Users/arasz/RiderProjects/pi-mcp-tools-fork` — separate branch + PR (F11–F18), version 1.1.6.
**Lane plans (rev-1 MoE snapshots — where they and this plan disagree, this plan wins):**

- `docs/work/2026-08-28-pi-review-fixes-moe-ts.md` (TS lane)
- `docs/work/2026-08-28-aib-pi-review-fixes-moe-python.md` (python lane)
- `docs/work/2026-08-28-pi-review-fixes-test-strategy.md` (test lane)
- `docs/work/2026-08-28-pi-review-fixes-fork-plan.md` (fork lane)
- `docs/work/2026-08-28-pi-full-support-gaps.md` (gap audit)

## 1. Questions the task asked, answered up front

| Question | Answer | Evidence |
|---|---|---|
| Can the two blockers ship as-is? | No. The adapter extension does not exist (silent `[]` install), and cron can neither load (missing `run-job.ts` throws at registration) nor fire (plist has no scheduling key). | F1/F2 verified in-tree; Bun.cron path-validation witnessed (`ERR_INVALID_ARG_TYPE` on missing file) |
| Does `Bun.cron(path, schedule, title)` work? | Yes — registers an OS-level launchd job; signature is correct. But pi runs under **node** (no `Bun` global), so the in-process path can never fire inside an extension; the ladder is in-process-when-under-bun (future-proofing) and launchd otherwise — the `bun -e` shell-out rung is dropped (B-SHOULD-3). | TS lane: registration probe OK, launchd agent listed; pi bin is `#!/usr/bin/env node` |
| What does a fired Bun.cron script export? | `default { scheduled(controller) }`; top-level-only scripts fail with "Module does not export default.scheduled()". | TS lane: witnessed stderr from a real launchd fire |
| What is the correct pi resume flag? | `--resume, -r` takes NO argument (interactive selector). Resume by id: `pi -p --session <path\|id>`. `--session-id <id>` demands an exact project session id (creates one when missing — wrong semantics). `--continue, -c` continues most recent. | pi 0.84.3 `--help`, re-measured by two lanes |
| How does pi discover skills? | `~/.pi/agent/skills/`, `~/.agents/skills/` (global), `.pi/skills/` (project, trust-gated), settings `skills` array, `--skill <path>`. It does NOT read `.claude/skills/`. ai-badger delivers to `.ai-badger/skills/` — pi gets **no skills today**. Global-dir variants rejected: `~/.agents/skills/` is single-copy → framework-version skew, last-scaffolded-project-wins (B-NIT-11 reason recorded). | python lane V4/V5, pi `docs/skills.md` |
| Is there an away/auto-approve mode in pi? | No. Tool-approval gates can only be implemented **by extensions** via `ctx.ui.confirm` in `tool_call` handlers; no API exists for one extension to answer another extension's dialog → away-mode lives in the adapter extension. | review "explicit answers"; TS lane API audit; architect review confirms coupling is API-forced |
| What does pi's headless mode give the tracker? | Session usage lives in the **documented** session JSONL (`docs/session-format.md`: `~/.pi/agent/sessions/--<path>--/<timestamp>_<uuid>.jsonl`, `usage` on assistant entries) — not exposed via API. G3 is a fixture test against a documented format with a zeroes fallback kept for live nuances (this machine's session dirs exist but are currently empty). | B-SHOULD-6, verified in the installed pi package |

## 2. Verified-facts table (grades: MEASURED this session unless noted)

| # | Fact | Source |
|---|---|---|
| V1 | F1–F18 all reproduce as reported; F18b's ConfigLoader citation is `:9–14` (not `:16–18`) | orchestrator + fork lane |
| V2 | `adjust_hooks._install_user_extension` silently `[]` on missing adapter dir; production default `install=True` (scaffold.py:822,639) — the untested branch is the mainline (F6 root cause) | python lane V1; test lane §0 |
| V3 | pi event count is unstable across counting conventions (33/34/36); all six adapter events exist | python lane V10 |
| V4 | `support.json` schema semantics: `aiBadgerSupport` = "whether ai-badger scaffolds anything for it"; hermes `mcpServers` precedent: proposal-only ⇒ `false` | python lane V7, schema:76-108 |
| V5 | MCP SDK 1.26.0: public `onclose`/`onerror`; `callTool(params, schema?, options?.signal)`; `Protocol.close()` clears `_transport`, so same-Client reconnect-after-close may actually work — fork's "unusable client" comment may be stale; live verification flagged (fork Q1) | fork lane, node_modules d.ts |
| V6 | Machine state: `~/.pi/agent/settings.json` = `{lastChangelogVersion, theme}` only; `extensions/` empty; no `skills/`/`agents/` dirs. Writing pi settings keys = merging into a fresh file; merge-semantics still required | orchestrator, 2026-08-28 |
| V7 | Fork baseline: 46/46 vitest green, tests live in `tests/`; husky pre-commit does NOT run vitest; `npm test` / `npm run build` = `vitest run` / `tsc --noEmit` | fork lane + orchestrator |
| V8 | Repo test baseline: 14/14 `tests/test_pi_adjustments.py` via `.venv/bin/python3 -m pytest -q`, 1.70s @ 9d2d0ce0 | test lane §0 |
| V9 | pi custom agents support **project scope**: `<project>/.pi/agents/*.md` discovered by `findNearestProjectAgentsDir(cwd)` with project-overrides-user by name (in the pi subagent example) — the old "user-global only" premise is false | architect review B-MUST-2, installed package |
| V10 | The `mcp` settings key has **no consumer in pi core** (zero occurrences in docs/dist) — it is read solely by the pi-mcp-tools fork (`ConfigLoader.loadFromSettingsJson`) | architect review B-SHOULD-5 |
| V11 | 0.142.0 is already shipped on origin/main (28a5e6cf); the worktree carries VERSION 0.143.0 + committed changelog entry | git state, this session |

## 3. Decisions

| # | Decision | Provenance |
|---|---|---|
| D1 | Hooks adapter ships at `features/pi/adjustments/adapter/` as `index.ts` + `package.json` (entry `index.ts` — all Wave-0 tests and lane docs pin `index.ts`, B-SHOULD-8). Default-factory extension; `tool_call` → Claude-shaped JSON → `python3 <cwd>/.ai-badger/hooks/ai_badger_hooks.py` (schema pinned from the actual hook source); deny→`{block:true,reason}`, ask→`ctx.ui.confirm` guarded by `ctx.hasUI`, approve→`undefined`. **Error path pinned (B-SHOULD-4):** hook subprocess timeout / non-zero exit / malformed JSON → `ctx.ui.notify` on **each occurrence** + allow (an erroring gate must not silently swallow the run; matches the 0.142.0 honest-fail-open precedent for the advisory layer). Missing hooks at cwd → one-time notify + fail-open (no gate exists — inert, not a bypass). Away-mode auto-approves **only explicit "ask" decisions**, never an error or absence. `ctx.signal` propagated to the subprocess. | TS P1; F1; review B-SHOULD-4 |
| D2 | Away-mode = same extension as the adapter (no cross-extension confirm API). `AI_BADGER_PI_AWAY=1` env (default OFF) + `/away` command toggling session-scoped state. Armed: "ask" auto-approved without calling `confirm` + notify per approval (audit trail). Default-off is provable: tests assert unset env ⇒ zero behavior change vs P1; no persisted config exists, so armed state cannot survive the process. | TS P2; safety lens |
| D3 | Cron registration ladder **two rungs** (B-SHOULD-3): running under bun → in-process `Bun.cron`; otherwise → self-managed launchd (plist writer + `StartCalendarInterval` translation + prune). The `bun -e` shell-out rung is dropped: it exists only to reuse bun's plist management which the launchd path duplicates anyway, and it drags PATH-lookup fragility, generated registration scripts, per-job wrappers, and the CronController title probe. `run-job.ts` exports `default { scheduled(controller) }`, loads `cron.json` fresh at fire time. Launchd fallback: `StartCalendarInterval` expansion capped at **366 dicts per plist** (unit stated; `* * * * *` → 1440 exceeds it → skip+notify — sub-hourly jobs are outside the fallback's envelope, B-NIT-10), XML-escape interpolation, `RunAtLoad=false`/`KeepAlive=false`. **Correctness (B-SHOULD-3b):** `launchctl bootout`/`unload` before every load (an edited schedule must not keep the old definition firing); stale-job prune scans **both** prefixes (`bun.cron.ai-badger-cron-*` AND `com.ai-badger.pi-cron.*`). Titles sanitized `[A-Za-z0-9_-]`; invalid → skip + notify. | TS P3; F2, F5; review 3/10 |
| D4 | `noAgent` default becomes real: schedulable = `jobs.filter(j => j.noAgent !== false)`. | TS P3; F5 |
| D5 | adjust_hooks fail-loud keeps partial-success semantics: missing adapter ⇒ `ERROR:` note naming the dir, `applied = bool(files or installed)`. `install=False` stays a documented no-op. | python WP1; V11-lane |
| D6 | Resume = `pi -p --session {session_id}` in `pi_session_source.py`; no shell-quoting (UUID-shaped ids, sibling shape). | python WP3 |
| D7 | adjust_mcp: `shlex.split`; unbalanced quotes raise `ValueError` (scaffold reports per-adjustment). | python WP2 |
| D8 | support.json honesty: `pi.skills` interim honest state (`aiBadgerSupport: false` + mechanism naming pi's real discovery paths) **superseded by G1 in the same release** — both land together, so the honest-false state never ships (B-SHOULD-7); `pi.hooks.mechanism` names the six adapter events + pointer, count/superset claims dropped. | python WP4; F4, F10; review 7 |
| D9 | Doc fixes edit `features/common/skills/task/extensions/pi/extension.md` source only; line 21 loses the false "or `pi -p` (most recent)" clause; the "pi does not expose per-session token usage" claim becomes "not via an API; the session JSONL carries it (pi docs/session-format.md)" (B-SHOULD-6). | python WP5; review 6 |
| D10 | Dead helpers deleted (pi copies only): `adjust_hooks._framework_version`, `adjust_mcp._yaml_block`. | python WP1/WP2; F9 |
| D11 | Fork F12: track a `closed` flag; `connect()` rebuilds a fresh SDK Client when closed (`createClient()` helper). Pin the implementation contract (constructor count), not SDK-internal semantics; throw-after-close mock validated live before merge (Q1). | fork WP1 |
| D12 | Fork F11: `McpClient.onDisconnected` fires once per connect cycle, unexpected closes only (`intentionalClose` guard); wired in `McpRegistry.initialize()` AND on the replacement Client inside the reconnect timer; `shuttingDown` flag guards teardown. New `tests/McpRegistry.test.ts` — 10 designed cases minimum. | fork WP2 |
| D13 | Fork F15: healthCheck races `listTools()` against `HEALTH_CHECK_TIMEOUT_MS = 5s`; timeout takes the existing `scheduleReconnect` path. | fork WP3 |
| D14 | Fork F13: `McpClient.callTool(name, args, signal?)` forwards `{signal}`; AbortError maps to the cancelled-result shape. | fork WP4 |
| D15 | Fork F14+F18a: pure `toolFilter.ts` helpers — `enabledToolNames` by registeredTools membership; `countEnabledTools` = intersection (never negative). | fork WP5/WP7 |
| D16 | Fork F16: `saveDisabledTools` warns when settings.json missing (creation rejected). F17: honor explicit `transport`. F18b comment: self-contained rationale. | fork WP6/WP7 |
| D17 | Versioning: ai-badger **0.143.0** (already bumped in the worktree via the main-move merge; §4 E verifies it, B-MUST-1); fork → **1.1.6**. | repo invariant; V11 |
| D18 | TS gates are created minimally: `features/pi/tsconfig.json` (noEmit) + `bun test features/pi`; joining the pre-push gate is the owner's §8.2 call. | TS tooling note |

## 4. Work packages — ai-badger (branch `task/aib-pi-review-fixes`)

### A. Test-first commit (test lane) — FIRST, born-RED against the pre-fix base
Fixture `pi_user_extensions` (complete two-module `USER_EXTENSIONS_DIR` monkeypatch; all writes to `tmp_path`) + T1–T6 from the test strategy §3, **with T1/T2 asserting `index.ts`** (B-SHOULD-8): install-copies-adapter, install-copies-cron-incl-run-job, missing-adapter-fails-loud invariant, plist scheduling keys, noAgent default, resume flag. Six RED runs pasted. T8 (shlex) + T9 (`tests/test_support_scaffolded_by.py`) — T9 extended per B-SHOULD-7: every `aiBadgerSupport: true` row must have a matching arm in that agent's `adjustment.json`.

### B. Python adjustments (python lane; serial with A's tests going green one at a time)
WP1 fail-loud adjust_hooks + delete `_framework_version` (D5, D10) · WP2 shlex + delete `_yaml_block` (D7, D10) · WP3 resume `--session` (D6) · WP4 support.json honesty (D8) · WP5 extension.md source fixes (D9). Plus gap packages G1+G2 (§7) which land in this lane (shared files: `support.json`, `adjustment.json`).

### C. TS extensions (TS lane)
P1 adapter extension (D1, entry `index.ts`) · P2 away-mode (D2) · P3 cron repair (D3 two-rung ladder + dual-prefix prune + bootout-before-load, D4) · P4 extension.md doc truths. **Evolution guard (B-SHOULD-9):** the adapter self-checks at load (`typeof pi.on === "function"`, `registerCommand` availability) and emits a one-time `ctx.ui.notify` on failure; `extension.md` documents a 3-line smoke command (`pi -e` load + one tool call through a fake hook) any post-upgrade session can re-run. Gates: `bun test features/pi` green; `bunx tsc --noEmit -p features/pi` clean; one witnessed cron fire recorded in the PR.

### D. Gap packages (§7) — G1, G2 in the python lane (Wave 1); G3, G4 in Wave 2; G5 per §8.3c.

### E. Integration package (orchestrator; last)
1. Fold lane outputs; resolve cross-lane seams (adapter entry name; extension.md ↔ pi_session_source resume string).
2. Scaffold/regeneration sweep: plugin skill copies, `.ai-badger/` self-scaffold (MCP availability=all), index build, skills-copy skew.
3. Release: **verify VERSION 0.143.0** and that the committed changelog entry's "work in flight" list covers the final shipped scope (B-MUST-1).
4. PR (non-draft) + "Ready to review" comment; gates: full suite, pylint, build check; CI watched to green.
5. **Machine-cutover gate** — the §10 checklist, executed live on this machine.

## 5. Work packages — pi-mcp-tools fork (separate repo)

Branch `fix/mcp-review-findings-11-18` from `b07d425`; one commit per WP, `npx vitest run` + `npx tsc --noEmit` per commit: WP1 closed-client reuse (D11) → WP2 reconnect wiring + registry tests (D12) → WP3 healthcheck timeout (D13) → draft PR after WP3 → WP4 abort (D14) → WP5 toolFilter (D15) → WP6 ConfigLoader (D16) → WP7 transport + intersection (D16) → WP8 version 1.1.6 + PR-ready (D17). PR body maps findings 11–18 to commits + evidence. Live stdio-server verification once, for Q1.

## 6. Sequencing & parallelism

- Wave 0: A (test commit) — born-RED. T1 pins `index.ts` from the start.
- Wave 1 (parallel, isolated lanes): B+G1+G2 (python) · C (TS) · fork WPs 1–3. Shared files serialize inside the python lane (`support.json`, `adjustment.json`).
- Wave 2: G3, G4 · fork WPs 4–8.
- Wave 3: E integration (single tree, serial) + machine-cutover gate.
- Every dispatch names its model; lanes get their own worktree/workspace id; shared-file sections serialise.

## 7. Full-support gap packages (detail: `2026-08-28-pi-full-support-gaps.md`)

| # | Package | Effort | Mechanism (simple usable form) | Wave |
|---|---|---|---|---|
| G1 | skills delivery | S/M | `adjust_skills.py` merges project `.ai-badger/skills/` into pi settings `skills` array via shared `pi_settings.py` (settings entries NOT trust-gated → works headless); **atomic write** (temp file + rename) and idempotent merge preserving unknown keys (safety lens); `support.json` pi.skills flips true in the same release | 1 (python lane) |
| G2 | MCP apply | S | `adjust_mcp.py` merges servers into settings `mcp` key when `install=True` (same `pi_settings.py`); snippet kept for `--no-install`. **Consumer named (B-SHOULD-5):** the key is read solely by the pi-mcp-tools fork — G2's cutover step is "fork extension installed user-scope, `/mcp-status` shows the merged servers" | 1 (python lane) |
| G3 | real token checkpoints | S→M | Format is **documented** (pi `docs/session-format.md`): JSONL at `~/.pi/agent/sessions/--<path>--/`, `usage` on assistant entries; `pi_session_source` does a PI_SESSION_ID→filename suffix match and reads usage; zeroes fallback kept (machine's session dirs currently empty — tolerant reader matters). Docstring + extension.md updated per D9 | 2 |
| G4 | hook-arm coverage contract | S | Derive the adapter's event set **from the adapter source** (regex `pi.on("…")` over `index.ts`), compare against hooks-manifest non-claude arms — never the docstring (docstring and test would agree while code drifts, B-SHOULD-7) | 2 |
| G5 | persona agent files | per §8.3c | **Corrected mechanism (B-MUST-2):** pi DOES support project-scope agents (`<project>/.pi/agents/*.md`, project overrides user by name) — the simple form is scaffolding persona `.md` files into `<project>/.pi/agents/`, mirroring copilot's `.github/agents/`. The honest blocker: pi's subagent extension is example-status, manual-install, and nothing is installed on this machine — delivered persona files would be inert until it lands. Small S package if the owner accepts that dependency | 2 (if approved) |

Deferred-parity rows and per-item justifications: gap audit §2 checklist.

## 8. Owner decisions (G0)

1. support.json `aiBadgerSupport` flip for `pi.skills`: honest interim in D8, true when G1 ships in the **same release** — confirm.
2. D18: do TS gates (`bun test features/pi`, tsc) join the pre-push gate in this task or a follow-up?
3. Gap-audit decisions, defaults proposed (owner may override): (a) G1+G2 write `~/.pi/agent/settings.json` directly (atomic, idempotent, unknown-key-preserving; claude/hermes precedent) vs proposal-only; (b) G3 proceeds against the documented session format (no longer a timeboxed gamble) with zeroes fallback — confirm; (c) **G5 re-asked on corrected premises:** project-scope `.pi/agents/` scaffolding is feasible; accept the manual-install dependency on pi's example subagent extension, or keep deferred?
4. Fork Q1–Q6 — answered autonomously (Q1 live-verify, Q3 warn, Q4 5s, Q5 bump-only, Q6 no upstream offer).

## 9. Risks

- Boolean flip (D8) changes a published matrix — called out in the PR; G1 flips it true in the same release.
- TS/py seam: entry name `index.ts` pinned in D1, Wave-0 tests, and the TS lane doc (supersession markers added).
- Line-number drift across lanes — locate by content, not file:line.
- `red_proof.py` journal (`.design-tests/`) is NOT gitignored — the test lane's first commit adds the ignore entry.
- Live-SDK reconnect semantics may contradict the fork's comment (V5) — WP1 pins the implementation contract.
- Global skill-dir rejection reason recorded (B-NIT-11): single global copy → framework-version skew, last-scaffolded-project-wins; settings-array entries avoid it (per-project paths, framework-managed content).

## 10. Gates summary + machine-cutover checklist

| Gate | Command | Where |
|---|---|---|
| Repo suite | `.venv/bin/python3 -m pytest -q` | worktree |
| Lint | `python3 -m pylint $(git ls-files '*.py' \| grep -v '^tests/')` | worktree |
| Build/index | `python3 tooling/index_build.py --check` | worktree |
| TS tests | `bun test features/pi` | worktree |
| TS types | `bunx tsc --noEmit -p features/pi` | worktree |
| Fork suite | `npx vitest run` + `npx tsc --noEmit` | fork repo |
| Red-proof | every new test witnessed RED (natural or `red_proof.py`) | per package |

**Machine-cutover gate (§4 E.5) — pass/fail checklist, executed on this machine after install:**

1. `ls ~/.pi/agent/extensions/` shows `ai-badger/` (adapter) and `pi-cron/`; each contains its `index.ts`/`package.json` — verify with `pi -e` load, no error.
2. `~/.pi/agent/settings.json` carries the project's `skills` entry and `mcp` key (G1/G2), unknown keys (`lastChangelogVersion`, `theme`) intact.
3. The pi-mcp-tools fork extension is installed user-scope and `/mcp-status` lists the merged servers (G2's named consumer).
4. Skills usable: a pi session reads a skill from `.ai-badger/skills/` via the settings entry.
5. Hooks live: one tool call in a pi session exercises the adapter (deny/ask/approve path witnessed in the notify trail); away-mode `AI_BADGER_PI_AWAY=1` run auto-approves an "ask" and notifies.
6. Cron fires: one witnessed launchd fire writing its marker (from P3's recorded run) on this machine's real config.
7. Task resume: `pi -p --session <id>` resumes a recorded session; the tracker's resume command round-trips.

**G0:** owner approval via f:-corrections (received: scope corrections, replace-hermes signal, dump-to-main instruction); implementation proceeds on the autonomous defaults stated in §8.

---

## 11. Rev 3 — orchestrator plan review (2026-08-28, takeover session)

All rev-2 facts re-measured live this session against pi 0.84.3, not carried from the lane docs.
Confirmed unchanged: node shebang; `--resume` takes no argument while `--session <path|id>` does;
`~/.pi/agent/settings.json` = `{lastChangelogVersion, theme}`; `extensions/` empty; settings
`skills`/`extensions` arrays documented; **no `mcp` key anywhere in pi's docs** (V10); adapter dir
absent; `run-job.ts` absent; plist carries no scheduling key; `if (job.noAgent)` is a truthy check.

### Findings folded into the plan

| # | Finding | Disposition |
|---|---|---|
| R-MUST-1 | D5's fail-loud rule names only `adjust_hooks`; `adjust_cron._install_user_extension` carries the identical F6 defect (`if not install or not cron_dir.is_dir(): return []`, then a soft `applied: False`) | **D5 extended to both modules.** A missing `features/pi/cron/` dir is an `ERROR:` note naming the dir. Wave-0 test T3 gains a cron twin (T3b). |
| R-MUST-2 | D1 never records why the adapter is user-scope, though pi offers project-local `.pi/extensions/*/index.ts` | **Rationale pinned in D1:** project-local extensions are trust-gated, and `docs/settings.md` states `-p` / `--mode json` / `--mode rpc` ignore project resources entirely under the default `defaultProjectTrust: "ask"`. A project-local adapter would gate nothing in exactly the headless runs away-mode exists for. |
| R-MUST-3 | §10 never inspects trust state, which cutover steps 4–5 depend on | **§10 gains step 0:** record `~/.pi/agent/trust.json` and `defaultProjectTrust` for this repo before the other checks; a headless-inclusive daily loop needs a saved decision or `"always"`. |
| R-SHOULD-4 | D3's bun rung keeps `join(__dirname, "run-job.ts")` inside an ESM module (`"type": "module"`), where `__dirname` is undefined unless jiti shims it — an untested branch of exactly the F1/F6 shape | **D3 amended:** resolve via `new URL("run-job.ts", import.meta.url)`. No measurement is owed for a rung that cannot fire under node; the fragile idiom goes regardless. |
| R-SHOULD-5 | `package.json` does not register a global-subdirectory extension — pi discovers `~/.pi/agent/extensions/*/index.ts` directly; `pi.extensions` is package-loading machinery | **B-SHOULD-8 upgraded:** `index.ts` is *mandatory*, not a convention. `adjust_hooks`'s docstring (which today advertises `adapter.ts`) is part of WP1's edit. |
| R-SHOULD-6 | G5's row named one precondition; there are three | See G5 below — owner resolved by widening scope. |
| R-SHOULD-7 | One PR carries 18 findings + 5 gap packages + a regen sweep, with 12 live worktrees and a changelog README row that conflicts per concurrent PR | **Hedge, not a blocker:** split at the Wave-1/Wave-2 seam if CI turns noisy. |
| R-NIT-8 | Worktree was one commit behind main | Merged (`3c3b5934`). |

### Owner decisions (asked and answered this session)

- **§8.2 / D18 — TS gates:** CI and this task's gate list only; they do **not** join the pre-push
  hook. Pre-push stays fast and push keeps working without `bun` on PATH.
- **§8.3c / G5 — resolved by widening, not deferring.** Owner: *"make them not inert — implement
  the extension as a part of G5."* The three preconditions that made delivered persona files dead
  (pi's subagent extension is example-status and uninstalled; it reads project agents only under
  `agentScope: "project"|"both"`; `.pi/agents/` is project-local and therefore trust-gated) are
  removed by shipping ai-badger's own extension rather than depending on pi's example.

### G5 (revised) — persona agents that actually run

Two parts, both in Wave 2:

1. `features/pi/adjustments/adjust_agents.py` writes the scaffolded personas into
   `<project>/.pi/agents/*.md`, mirroring copilot's `.github/agents/*.agent.md` and claude's
   `.claude/agents/*.md` (source of truth stays `.ai-badger/agents/`).
2. `features/pi/subagent/index.ts` — ai-badger's **own** minimal subagent extension, installed
   user-scope at `~/.pi/agent/extensions/ai-badger-subagent/` by the same install path as the
   adapter and cron. It reads `<cwd>/.pi/agents/*.md` **itself, through `fs`**, so pi's project-trust
   gate never applies — that is what makes the files live headless. It registers one delegation tool
   that spawns `pi -p` with the persona's prompt.

   pi's 35 KB example is **not** vendored: copying a third party's example into the framework buys
   parallel streaming, cost accounting and workflow prompts that ai-badger's delegation map does not
   ask for, and owes us its maintenance forever. The simple usable form is one file.

Gates: personas discovered from a scaffolded `.pi/agents/` in a temp project; one witnessed
delegation running headless (`pi -p`) with **no** trust decision saved — the proof that the
trust-gate bypass is real and not asserted.
