# Plan: aib-pi-review-fixes — pi review fixes + full usable pi support (rev 1)

**Task:** `aib-pi-review-fixes` · branch `task/aib-pi-review-fixes` @ `9d2d0ce0` · worktree `.ai-badger/worktrees/aib-pi-review-fixes`.
**Scope (owner-corrected, 2026-08-28):** fix all 18 review findings, and deliver a **simple, usable form of every feature the owner uses daily and that ai-badger needs** in pi. Full parity with claude/hermes/copilot is explicitly out of scope; every deferred-parity item is justified in the gap audit (`docs/work/2026-08-28-pi-full-support-gaps.md`).
**Owner signal (2026-08-28):** *pi is ready and intended to **replace hermes** as the daily harness* — this resolves the ADR-0016 swap recommendation in pi's favor. Consequence for this plan: the integration package (§4 E) gains a **machine-cutover gate** — the finished extensions are installed user-scope on this machine (`~/.pi/agent/extensions/`, currently empty) and the daily loop (skills, hooks, MCP, cron, task tracking) is verified live in pi. Features ai-badger delivers to hermes that have no simple pi form are replacement blockers — the gap audit lists them first.
**Companion repo:** pi-mcp-tools fork `/Users/arasz/RiderProjects/pi-mcp-tools-fork` @ `b07d425` — separate branch + PR (F11–F18).
**Lane plans (rev-1 MoE snapshots — where they and this plan disagree, this plan wins):**

- `docs/work/2026-08-28-pi-review-fixes-moe-ts.md` (TS lane)
- `docs/work/2026-08-28-aib-pi-review-fixes-moe-python.md` (python lane)
- `docs/work/2026-08-28-pi-review-fixes-test-strategy.md` (test lane)
- `docs/work/2026-08-28-pi-review-fixes-fork-plan.md` (fork lane — copy into the worktree from the main checkout's `docs/work/2026-08-28-pi-review-fixes-fork-plan.md` at commit time; the fork lane wrote it to the main tree by mistake)
- `docs/work/2026-08-28-pi-full-support-gaps.md` (gap audit — written by the orchestrator after two lane attempts failed; evidence cited in-doc)

## 1. Questions the task asked, answered up front

| Question | Answer | Evidence |
|---|---|---|
| Can the two blockers ship as-is? | No. The adapter extension does not exist (silent `[]` install), and cron can neither load (missing `run-job.ts` throws at registration) nor fire (plist has no scheduling key). | F1/F2 verified in-tree; Bun.cron path-validation witnessed (`ERR_INVALID_ARG_TYPE` on missing file) |
| Does `Bun.cron(path, schedule, title)` work? | Yes — registers an OS-level launchd job; signature is correct. But pi runs under **node** (no `Bun` global), so the in-process path can never fire inside an extension; a `bun -e` shell-out ladder or launchd fallback is required. | TS lane: registration probe OK, launchd agent listed; pi bin is `#!/usr/bin/env node`, `typeof Bun === "undefined"` |
| What does a fired Bun.cron script export? | `default { scheduled(controller) }`; top-level-only scripts fail with "Module does not export default.scheduled()". | TS lane: witnessed stderr from a real launchd fire |
| What is the correct pi resume flag? | `--resume, -r` takes NO argument (interactive selector). Resume by id: `pi -p --session <path\|id>`. `--session-id <id>` demands an exact project session id (creates one when missing — wrong semantics). `--continue, -c` continues most recent. | pi 0.84.3 `--help`, re-measured by two lanes |
| How does pi discover skills? | `~/.pi/agent/skills/`, `~/.agents/skills/` (global), `.pi/skills/`, `.agents/skills/` (project, only after project trust), package dirs, settings `skills` array, `--skill <path>`. It does NOT read `.claude/skills/`. ai-badger delivers skills to `.ai-badger/skills/` — so pi gets **no skills today**. | python lane V4/V5, pi `docs/skills.md` |
| Is there an away/auto-approve mode in pi? | No. Closest: `-p`/JSON modes skip the *project-trust* prompt; tool-approval gates can only be implemented **by extensions** via `ctx.ui.confirm` in `tool_call` handlers. No API exists for one extension to answer another extension's dialog → away-mode must live in the same extension as the adapter. | review "explicit answers"; TS lane API audit |
| What does pi's headless mode give the tracker? | `ctx.hasUI = false` in `-p`/JSON mode; JSON mode emits usage data. Real token checkpoints are possible in principle — gap audit decides if a simple usable form exists or zeroes stay. | TS lane facts; audit pending |

## 2. Verified-facts table (grades: MEASURED this session unless noted)

| # | Fact | Source |
|---|---|---|
| V1 | F1–F18 all reproduce as reported; F18b's ConfigLoader citation is `:9–14` (not `:16–18`) | orchestrator + fork lane |
| V2 | `adjust_hooks._install_user_extension` silently `[]` on missing adapter dir; production default `install=True` (scaffold.py:822,639) — the untested branch is the mainline (F6 root cause) | python lane V1; test lane §0 |
| V3 | pi event count is unstable across counting conventions (33/34/36); all six adapter events exist | python lane V10 |
| V4 | `support.json` schema semantics: `aiBadgerSupport` = "whether ai-badger scaffolds anything for it"; hermes `mcpServers` precedent: proposal-only ⇒ `false` | python lane V7, schema:76-108 |
| V5 | MCP SDK 1.26.0: public `onclose`/`onerror`; `callTool(params, schema?, options?.signal)`; `Protocol.close()` clears `_transport`, so same-Client reconnect-after-close may actually work — fork's "unusable client" comment may be stale; live verification flagged (fork Q1) | fork lane, node_modules d.ts |
| V6 | Machine state: `~/.pi/agent/settings.json` = `{lastChangelogVersion, theme}` only; `extensions/` empty; no `skills/`/`agents/` dirs. Writing pi settings keys = merging into a fresh file; merge-semantics still required | orchestrator, 2026-08-28 |
| V7 | Fork baseline: 46/46 vitest green, tests live in `tests/` (not `src/`); husky pre-commit does NOT run vitest; `npm test` / `npm run build` = `vitest run` / `tsc --noEmit` | fork lane + orchestrator |
| V8 | Repo test baseline: 14/14 `tests/test_pi_adjustments.py` via `.venv/bin/python3 -m pytest -q`, 1.70s @ 9d2d0ce0 | test lane §0 |

## 3. Decisions

| # | Decision | Provenance |
|---|---|---|
| D1 | Hooks adapter ships at `features/pi/adjustments/adapter/` as `index.ts` + `package.json` (entry `index.ts`, not the docstring's `adapter.ts` — adjust_hooks docstring reworded). Default-factory extension; `tool_call` → Claude-shaped JSON → `python3 <cwd>/.ai-badger/hooks/ai_badger_hooks.py` (schema pinned from the actual hook source, not invented); deny→`{block:true,reason}`, ask→`ctx.ui.confirm` guarded by `ctx.hasUI`, approve→`undefined`; hooks missing at cwd → one-time notify + fail-open (advisory layer, not a security boundary); `ctx.signal` propagated to the subprocess. | TS P1; F1 |
| D2 | Away-mode = same extension as the adapter (no cross-extension confirm API). `AI_BADGER_PI_AWAY=1` env (default OFF, `AI_BADGER_MEMORY_GRADE` precedent) + `/away` command toggling session-scoped state. Armed: "ask" auto-approved without calling `confirm` + notify per approval. No persisted config (a persisted ON state is a silent auto-approver left armed). | TS P2 |
| D3 | Cron registration ladder: under bun → in-process `Bun.cron`; bun on PATH → `execFile(bunPath, ["-e", …])`; else launchd fallback with `StartCalendarInterval` translation (ranges/lists/steps, cap 366 + skip+notify, XML-escape interpolation). `run-job.ts` exports `default { scheduled(controller) }`, loads `cron.json` fresh at fire time. Per-job generated wrappers unless the 5-min probe shows the title is reachable in the fired process — then one `run-job.ts` (probe first, simpler wins). Titles sanitized `[A-Za-z0-9_-]`; stale-job prune on `session_start`. | TS P3; F2, F5 |
| D4 | `noAgent` default becomes real: schedulable = `jobs.filter(j => j.noAgent !== false)`. | TS P3; F5 |
| D5 | adjust_hooks fail-loud keeps partial-success semantics: missing adapter ⇒ `ERROR:` note naming the dir, `applied = bool(files or installed)` (raising would lose recorded hook copies — scaffold catches exceptions before manifest records). `install=False` stays a documented no-op. | python WP1; V11 |
| D6 | Resume = `pi -p --session {session_id}` in `pi_session_source.py`; no shell-quoting (UUID-shaped ids, matches sibling sources' shape). | python WP3 |
| D7 | adjust_mcp: `shlex.split`; unbalanced quotes raise `ValueError` (reported per-adjustment by the scaffold — loud, zero code). | python WP2; D3-lane |
| D8 | support.json honesty: `pi.skills` → `aiBadgerSupport: false` + mechanism naming pi's real discovery paths + `scaffoldedBy` stating the operator step (hermes `mcpServers` precedent), superseded by the skills-delivery package (G1) which flips it back true when the scaffold writes the entry. `pi.hooks.mechanism` → name the six adapter events + pointer to pi docs, drop the disputed count and "superset" claim. | python WP4; F4, F10 |
| D9 | Doc fixes edit `features/common/skills/task/extensions/pi/extension.md` **source only** (scaffold copy regenerated); line 21 also loses the false "or `pi -p` (most recent)" clause (`--continue, -c` is the real form). | python WP5; TS P4 |
| D10 | Dead helpers deleted (pi copies only): `adjust_hooks._framework_version`, `adjust_mcp._yaml_block`. | python WP1/WP2; F9 |
| D11 | Fork F12: track a `closed` flag; `connect()` rebuilds a fresh SDK Client when closed (`createClient()` helper shared with constructor). Pin the implementation contract (constructor count), not SDK-internal semantics; throw-after-close mock validated live before merge (Q1). | fork WP1 |
| D12 | Fork F11: `McpClient.onDisconnected` fires once per connect cycle, **unexpected closes only** (`intentionalClose` guard); wired in `McpRegistry.initialize()` AND on the replacement Client inside the reconnect timer; `shuttingDown` flag makes teardown/toggle reconnect-free. New `tests/McpRegistry.test.ts` — 10 designed cases minimum. | fork WP2 |
| D13 | Fork F15: healthCheck races `listTools()` against `HEALTH_CHECK_TIMEOUT_MS = 5s`; timeout takes the existing `scheduleReconnect` path. | fork WP3 |
| D14 | Fork F13: `McpClient.callTool(name, args, signal?)` forwards `{signal}` as SDK options; AbortError maps to the existing cancelled-result shape. | fork WP4 |
| D15 | Fork F14+F18a: pure `toolFilter.ts` helpers — `enabledToolNames(…)` by registeredTools membership; `countEnabledTools` = intersection (never negative; `Math.max` rejected as drift-hiding). | fork WP5/WP7 |
| D16 | Fork F16: `saveDisabledTools` warns when settings.json missing (creating the file rejected — the command surface only exists when the file existed at startup; mid-session deletion is the reachable path). F17: honor explicit `transport` (construct exactly that transport, no auto-detect fall-through) rather than narrowing the published type surface. F18b comment: self-contained rationale replaces internal F20-F22 ids. | fork WP6/WP7 |
| D17 | Versioning: ai-badger → **0.142.0** (new shipped surfaces: adapter+away extension, cron repair, skills delivery); fork → **1.1.6** (no changelog file exists in the fork — bump only). Assigned centrally; lanes do not pick versions. | repo invariant |
| D18 | TS gates are created minimally: `features/pi/tsconfig.json` (noEmit) + `bun test features/pi`; whether they join the pre-push gate is deferred to the integration package (gate additions need their own red-proof). | TS tooling note |

## 4. Work packages — ai-badger (this repo, branch `task/aib-pi-review-fixes`)

### A. Test-first commit (test lane) — FIRST, born-RED against 9d2d0ce0
Fixture `pi_user_extensions` (complete two-module `USER_EXTENSIONS_DIR` monkeypatch; all writes to `tmp_path`) + T1–T6 from `test-strategy-aib-pi-review-fixes.md` §3: install-copies-adapter (T1), install-copies-cron-incl-run-job (T2), missing-adapter-fails-loud invariant (T3), plist scheduling keys (T4), noAgent default (T5), resume flag (T6). Six RED runs pasted. Optional T8 (shlex) + T9 (`tests/test_support_scaffolded_by.py` derive-or-delete gate, after auditing other agents' `scaffoldedBy` rows). AC: ≥6 witnessed-RED tests; zero writes outside tmp_path; conftest observers silent.

### B. Python adjustments (python lane; serial with A's tests going green one at a time)
WP1 fail-loud adjust_hooks + delete `_framework_version` (D5, D10) · WP2 shlex + delete `_yaml_block` (D7, D10) · WP3 resume `--session` (D6) · WP4 support.json honesty (D8) · WP5 extension.md source fixes (D9). Each: named RED test → fix → green. AC: per-lane proof-of-done lines; suite green.

### C. TS extensions (TS lane)
P1 adapter extension (D1) · P2 away-mode (D2) · P3 cron repair (D3, D4) · P4 extension.md doc truths. Gates: `bun test features/pi` green; `bunx tsc --noEmit -p features/pi` clean; one witnessed cron fire recorded in the PR; the real-adapter install test (T1) green. T5/T4 pin the source contracts; live-pi behaviors stay manual E2E, stated.

### D. Full-support gaps (gap audit lane) — §7 PENDING audit return
Skills delivery, MCP apply-vs-propose, persona agents, real token checkpoints, missing hook arms, away-mode ceiling, drift/den-refresh surfaces — each as a simple-usable-form package with owner decisions separated.

### E. Integration package (orchestrator; last)
1. Fold lane outputs; resolve cross-lane seams (adapter entry name vs adjust_hooks docstring; extension.md wording vs pi_session_source resume string — consistency assertion if T-lane adds it).
2. Scaffold/regeneration sweep: plugin skill copies, `.ai-badger/` self-scaffold, index (`tooling/index_build.py --check`), skills-copy skew.
3. Release: VERSION 0.142.0, `docs/changelog/0.142.0-*.md`, changelog index, config frameworkVersion.
4. PR (non-draft per owner preference) + "Ready to review" comment; gates: full suite, pylint, build check; CI watched to green.

## 5. Work packages — pi-mcp-tools fork (separate repo)

Branch `fix/mcp-review-findings-11-18` from `b07d425`; one commit per WP, `npx vitest run` + `npx tsc --noEmit` per commit (husky does not run vitest): WP1 closed-client reuse (D11) → WP2 reconnect wiring + registry tests (D12) → WP3 healthcheck timeout (D13) → draft PR after WP3 → WP4 abort (D14) → WP5 toolFilter (D15) → WP6 ConfigLoader (D16) → WP7 transport + intersection (D16) → WP8 version 1.1.6 + PR-ready (D17). PR body maps findings 11–18 to commits + evidence. Live stdio-server verification once, for Q1/Q-fork reconnect semantics.

## 6. Sequencing & parallelism

- Wave 0 (now): A (test commit) — born-RED.
- Wave 1 (parallel, isolated lanes): B (python) · C (TS) · fork WPs 1–3. B and C share only `tests/test_pi_adjustments.py` (test lane owns it; B/C only make tests pass — no edits to that file from B/C lanes).
- Wave 2: D (gaps) — packages sequenced by the audit's dependency rows; fork WPs 4–8.
- Wave 3: E integration (single tree, serial).
- Every dispatch names its model; lanes get their own worktree/workspace id; shared-file sections serialise per `lane-dispatch-brief.md`.

## 7. Full-support gap packages (see `2026-08-28-pi-full-support-gaps.md` for full detail)

Four replacement blockers (hooks, skills, MCP, unattended) close via the planned adapter/away/cron packages plus three new gap packages:

| # | Package | Effort | Mechanism (simple usable form) | Wave |
|---|---|---|---|---|
| G1 | skills delivery | S/M | `adjust_skills.py` merges project `.ai-badger/skills/` into pi settings `skills` array (settings entries are NOT trust-gated → works headless); `support.json` pi.skills flips true | 1 (python lane) |
| G2 | MCP apply | S | `adjust_mcp.py` merges servers into settings `mcp` key when `install=True` (shared `pi_settings.py` helper); snippet kept for `--no-install` | 1 (python lane) |
| G3 | real token checkpoints | M, timeboxed | `pi_session_source` reads usage from `~/.pi/agent/sessions/<id>` if the format exposes it; else documented zeroes | 2 |
| G4 | hook-arm coverage contract | S | coverage table in adapter docstring + 1 pytest pinning adapter events vs manifest arms (new arm ⇒ visible decision) | 1/2 |
| G5 | persona agent files | DEFERRED | user-global agents dir collides per-project; usable path already exists (delegation map + `pi -p --mode json` child procs) | — |

Deferred-parity rows and per-item justifications: gap audit §2 checklist.

## 8. Owner decisions (G0)

1. support.json `aiBadgerSupport` flip for `pi.skills` (D8) lands honest-now, flips true when G1 ships — confirm.
2. D18: do TS gates (`bun test features/pi`, tsc) join the pre-push gate in this task or a follow-up?
3. Gap-audit decisions (defaults proposed, owner may override): (a) G1+G2 write `~/.pi/agent/settings.json` directly (claude/hermes precedent, merge semantics) vs proposal-only; (b) G3 timebox attempt real checkpoints vs accept documented zeroes; (c) G5 deferral accepted.
4. Fork Q1/Q3/Q4/Q5/Q6 — ANSWERED autonomously (see fork plan; Q1 live-verify, Q3 warn, Q4 5s, Q5 bump-only, Q6 no upstream offer).

## 9. Risks

- Boolean flip (D8) changes a published matrix — called out in the PR, reverted by G1.
- TS/py seam: `adapter/index.ts` name vs docstring's `adapter.ts` — D1 fixes the docstring; integration sweep catches stragglers.
- Line-number drift across lanes — locate by content (function/constant names), not file:line.
- `red_proof.py` journal (`.design-tests/`) is NOT gitignored (orchestrator verified `git check-ignore` misses) — the test lane's first commit adds the ignore entry alongside the fixture, before any red-proof run.
- Live-SDK reconnect semantics may contradict the fork's comment (V5) — WP1 pins the implementation contract, so the test survives either outcome.

## 10. Gates summary

| Gate | Command | Where |
|---|---|---|
| Repo suite | `.venv/bin/python3 -m pytest -q` | worktree |
| Lint | `python3 -m pylint $(git ls-files '*.py' \| grep -v '^tests/')` | worktree |
| Build/index | `python3 tooling/index_build.py --check` | worktree |
| TS tests | `bun test features/pi` | worktree |
| TS types | `bunx tsc --noEmit -p features/pi` | worktree |
| Fork suite | `npx vitest run` + `npx tsc --noEmit` | fork repo |
| Red-proof | every new test witnessed RED (natural or `red_proof.py`) | per package |

**G0:** owner approval pending — no implementation dispatch before §7 is folded and §8 answered (autonomous-session rule: owner f:-corrections serve as approval signals; this plan proceeds to review-lanes now, implementation waits for the review round to close).
