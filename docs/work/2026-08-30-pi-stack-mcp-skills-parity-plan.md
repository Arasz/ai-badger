# Implementation plan rev 3 (post-review) — pi stack parity: MCP config + skills discovery defined by the project scaffold

**Task:** aib-pi-stack-mcp-skills-parity (high-effort) · **Date:** 2026-08-30
**Rev 3 supersedes rev 2** by folding the plan-review MoE (api-engineer, qa, hermes-agent-author — all fresh faces vs the authoring lanes). Rev 2 had already folded the owner gate (5/5 APPROVE: `…feedback.md`) and the premortem/test-strategy corrections. Audit trail: `…plan.md` history + `…premortem.md` + `…test-strategy.md` + `…plan-review-{api,qa,scaffold}.md`.
**Repo names:** repo B = `ai-badger` (pytest) · repo A = `pi-badger-integration` (bun) · fork = `~/RiderProjects/pi-mcp-tools-fork` (vitest, 73 tests/6 files measured — gates say "existing suite green", never a count).

**Measured layout facts (orchestrator-verified, supersede rev 2 where they differ):**
- Canonical fork copy in repo A is **flat**: `extensions/pi-mcp-tools/*.ts` — no `src/`. The upstream `package.json` `main:"src/index.ts"` + `pi.extensions:["./src/index.ts"]` are **stale**; pi loads the directory `index.ts`. **Creating `src/` in the canonical copy would double-load the extension via the stale `pi.extensions` field** — P1 fixes the fork's package.json fields, P2 syncs them.
- The canonical adapter is repo A `features/pi/adjustments/adapter/` (index.ts, hook-bridge.ts, package.json) — vendored byte-identical into repo B at the same relative path; installs user-scope as `~/.pi/agent/extensions/ai-badger/`. There is no `extensions/ai-badger/` in repo A.
- The scaffold emits `${HOME}`-prefixed commands for user-tool-dir executables (`mcp_tools.py:444-451`, `expand_home=True` rows at :101) — `.mcp.json` in the wild can carry `command:"${HOME}/…"`.

---

## 0. Owner-gate outcomes (all APPROVE, 2026-08-30, no notes — binding)

| id | Decision |
|----|----------|
| D1 | `ctx.isProjectTrusted()`-only MCP trust gate, with the **measured** semantics (§M2). No auto-trust, no scaffold-written trust.json. |
| D2 | Adapter `resources_discover` skills contribution **ungated**. |
| D3 | Adjustments repurposed to migration-only removers — **shape-aware** + **version-gated**. |
| D4 | `mcpDisabledTools` stays global; `saveDisabledTools` gets the atomic temp+replace pattern (drive-by). |
| D5 | Converter maps claude `type:"http"/"sse"` → fork `type:"remote"`. |

## 0b. Plan-review outcomes folded into this revision

- **R1 (api):** the rev-2 "latent `/new` bug" is **false** — pi 0.84.4 re-invokes the extension factory on every session replacement (`loader.js:455-475`, fresh ResourceLoader per `createRuntime`). The restructure is still required (ctx access at config-load time; a factory throw ⇒ headless `exit(1)`, so init must be defensive). The duplicate-registration guard is **deleted** — registration is name-keyed `Map.set` overwrite into per-session Maps; no unregister API exists.
- **R2 (api):** converter adds `type:"stdio"`/absent-type → local, and `${HOME}` expansion (scaffold emits it; the fork spawning the literal string fails silently with ENOENT).
- **R3 (api):** `/mcp-status` (and the headless-reporting tool) render from the **merge ledger**, not `registry.getClients()` — skipped/untrusted servers have no client.
- **R4 (qa, blocker):** extension **commands throw when queued headless** (`agent-session.js:1018-1020`) — every headless P5 observation goes through the **`mcp_list_servers` tool** (tools work headless), extended in P1 to report per-server source + skipped count. Channel live-probed in P2's smoke, before P5 may run.
- **R5 (qa):** the claimed existing byte-identity gate (`test_framework_copies.py`) **does not exist** (it is the #109 cleanup module). Claim deleted; replaced by P2's canonical↔fork diff test + P5 step 1 as the authoritative check.
- **R6 (qa):** P1's lifecycle tests bind the hoisted `os.homedir` mock + SDK client mocks — the red run must never touch real `~/.pi` or spawn real servers.
- **R7 (qa):** honesty pins scoped to the pi row of `support.json` (selected by JSON path `agents.pi`, not line); **positive substrings carry the gate**; the rev-2 "lying phrases" list becomes full-phrase must-not-contain only where it is a literal substring.
- **R8 (scaffold):** version gate needs a **pinned mechanism** — package.json version ruled out (installed 1.1.6 == fork 1.1.6, upstream-owned). P1 ships a **capability marker file** per extension; the adjustments read markers, not versions.
- **R9 (scaffold):** the gate is **per-extension**: `adjust_mcp.py` gates on the *fork* marker; `adjust_skills.py` gates on the *adapter* having `resources_discover` (installed adapter has zero occurrences today — measured). One gate would strand pre-P2 machines' skills.
- **R10 (scaffold):** the shape matcher is concrete (§M5) — regenerate-from-declaration + deep-equal + shlex-or-literal command comparison (historical drift `c7d0d528`: split→shlex).

---

## 1. Chosen mechanisms

**M1 — Fork reads project `.mcp.json` at `session_start`, project-over-global merge.**
Converter (new `src/claudeMcpConfig.ts`):
- `command` string (+`args`) → `{type:"local", command:[...]}`; **`type:"stdio"` or absent `type` → local** (before unknown-type skip); `env`/`cwd` pass through.
- **`${HOME}` expanded in `command`/`cwd`** (exact prefix, `os.homedir()`); an entry carrying any *other* unexpanded `${VAR}` is skipped with a logged warning.
- **`tools:["*"]`/empty/absent → "no filtering"** — never `filterPatterns` (pass-through would throw `RegExp("*")` per tool and kill every tool of every scaffolded server, debug-only visible). Glob-ish patterns → anchored regex; **every `RegExp` try/caught — a poison pattern skips that tool with a warning, the server's other tools survive**.
- **`type:"http"/"sse"` + `url` → `{type:"remote", url}`** (D5; transports already shipped in `McpClient.ts`; measured live as the `rider` server in ai-raccoon + job-search-ai-assistant).
- Remote missing `url`, unknown `type` → entry skipped with logged warning, other entries still arm. **Unparseable `.mcp.json` ⇒ global-only fallback + warning, never a partial arm.**

**M2 — Trust gate `ctx.isProjectTrusted()`, measured semantics.** pi's trust-requiring resources are exactly `.pi/{settings.json,extensions,skills,prompts,themes,SYSTEM.md,APPEND_SYSTEM.md}` + ancestor `.agents/skills` (`trust-manager.js:8-17,150-166`; `.mcp.json`/`.ai-badger/`/`.pi/agents/` are NOT on the list); `projectTrusted = (!hasTrustRequiringResources || trustStore.get(cwd)===true)` (`main.js:571-582`). **Scaffolded projects resolve trusted in every mode including headless — project MCP arms day one, no `/trust`.** The gate bites only when a trust-requiring resource appears (silent headless flip: no trust.json, `ask`→false) — named in the ADR, pinned by tests in both directions, made visible in reporting. Restructure: config load moves from extension-init to `session_start` (ctx access); init is defensive (a factory throw exits headless pi — log-and-degrade, never throw). Per-session Maps make re-registration safe by construction (R1) — **no duplicate-registration guard**.

**M3 — Headless-visible reporting (R3+R4).** The merge ledger records, per server: `project:.mcp.json` / `global settings` / `skipped:unsupported-shape` / `skipped:unexpanded-var` / `untrusted-project`, plus a skipped count. **`mcp_list_servers` (a tool — callable headless) reports the ledger; `/mcp-status` renders the same ledger.** `session_start` notify strings name the merged source. Per-server failure visible without `--mcp-debug`.

**M4 — Adapter `resources_discover` skills contribution, ungated (D2).** Source-verified honored in all modes (`agent-session.js:1920-1941`); handler reads `event.cwd` (`runner.js:935-947`), returns `{skillPaths:[<cwd>/.ai-badger/skills]}` when the directory exists, absent-safe. ADR records: deliberate divergence from pi's gating of project skills, calibrated by the pre-existing hooks-shell-command channel (ADR-0022); effective trust decision = installing the adapter user-globally. Live smoke in P2 (source-verified ≠ machine-verified).

**M5 — Migration-only adjustments (D3), concrete.**
- **Shape matcher (R10):** for each declared name, regenerate the entry exactly as `_server_entry` would today; the global entry is removable iff deep-equal on `enabled/toolPrefix/type/url/env/cwd` AND `command` equal as `shlex.split` output or as literal (tolerating the historical split→shlex drift, `c7d0d528`). Non-matching same-named entries: warn-and-leave.
- **Per-extension version gates (R8+R9):** `adjust_mcp.py` removes only when `~/.pi/agent/extensions/pi-mcp-tools/.ai-badger-capability-project-scope-mcp` exists (P1 ships it); `adjust_skills.py` removes only when the installed adapter carries the resources_discover capability — marker file `.ai-badger-capability-resources-discover` shipped with P2's adapter. Marker absent ⇒ skip-with-warning (never remove).
- `pi_settings.py` gains `remove_mcp_servers`/`remove_skills_path` (atomic temp+replace, idempotent, unknown-key-preserving, unique temp name + cleanup). `--no-install` prints the removal proposal.

**M6 — `mcpDisabledTools` stays global (D4); `saveDisabledTools` atomic (unique temp + cleanup).**

**M7 — Sequencing.** pbi-move directory-packages work is on pbi main (verified); the in-flight pbi task (`task/pbi-interactive-background-subagent-delegation`) — P2 serialises with it if it touches `features/pi/adjustments/adapter/`. P1 independent, starts now. P3 disjoint, parallel; merges after pbi-move's repo-B surgery. P2 after P1. P5 last, on the real machine.

---

## 2. Packages in merge order

### P1 — Fork: project-scoped `.mcp.json` + lifecycle restructure + reporting (fork) — **in progress now**
- **Files:** `src/claudeMcpConfig.ts` (new, converter per M1), `src/ConfigLoader.ts` (+`loadProjectMcpJson(cwd)`; `saveDisabledTools` atomic per M6), `src/index.ts` (session_start lifecycle per M2; merge ledger + `mcp_list_servers` ledger reporting per M3; defensive init), `package.json` (**fix stale `main`/`pi.extensions` → `./index.ts`**), **`CAPABILITY_PROJECT_SCOPE_MCP` marker file** (shipped so the installed copy carries it — written by publish/install; simplest: the file exists in the repo and publish copies it), tests below.
- **Tests (red-first; every test binds the hoisted `os.homedir` mock + SDK mocks — R6):** `tests/claudeMcpConfig.test.ts` (table: stdio/absent-type, command+args, env/cwd, `${HOME}` expansion, other-`${VAR}` skip, `tools:["*"]`→no-filter, glob→regex, poison regex, http/sse→remote, remote-no-url skip, unknown-type skip, unparseable→null); `tests/ConfigLoader.test.ts` append (`loadProjectMcpJson`, precedence, no-partial-merge); `tests/lifecycle.test.ts` (session_start arms from `ctx.cwd`; teardown; second session re-arms; **cwd re-derived per session, never cached**; ledger reports source/skip counts). ~~duplicate-registration test~~ deleted (R1).
- **Gate:** `npx vitest run` (existing suite green) + `npx tsc --noEmit`. RED output for each new test file pasted in the lane report.

### P2 — Canonical sync + adapter skills handler (repo A) — **after P1**
- **Files:** `extensions/pi-mcp-tools/*` (flat↔flat sync from fork src; **never create `src/`**), `features/pi/adjustments/adapter/index.ts` (+ungated `resources_discover` per M4) + **`CAPABILITY_RESOURCES_DISCOVER` marker file** in the same dir (vendored with it), mirrored tests (+fork↔canonical diff test, loud-skip when the fork is absent), publish.ts already copies whole dirs (verify the marker files ride along).
- **AC:** repo A `bun test` + `bunx tsc --noEmit` green; **channel probe (R4): live `pi -p` calling `mcp_list_servers` shows the ledger incl. source labels**; skills two-sided probe (H1 last mile: scaffolded repo → design-tests heading found; scratch dir → MISSING). Probes pasted into the task's verification notes; **do not merge before both probes run**.
- **Coordination:** serialise with the in-flight pbi task if it touches `features/pi/adjustments/adapter/`.

### P3 — Migration-only adjustments (repo B) — **parallel with P1/P2; merges after pbi-move's repo-B surgery**
- **Files:** `features/pi/adjustments/adjust_mcp.py`, `adjust_skills.py`, `pi_settings.py`, **`features/common/support.json` + `features/pi/adjustments/adjustment.json` (P3 is the SOLE lane for these shared files this wave)**, `tests/test_pi_adjustments.py`, `tests/test_support_json_honesty.py`.
- **Tests:** G1/G2 install-path pins **flip merge→removal** (`test_adjust_skills_install_true_merges_skills_path` :537, `test_adjust_mcp_install_true_merges_into_settings` :566; proposal pin :92 → removal proposal); append: idempotent re-run; non-declared entries + unknown keys survive; shape matcher (matching entry removed; drifted same-named entry warn-and-leave — fixture per R10's historical drift); per-extension gates (marker absent ⇒ warn-and-leave, per R9, both directions); real-home guard extends to removal (:832). Honesty test (R7): JSON-path-scoped pi rows; positive substrings (M2 short-circuit sentence incl. "in all modes"; `http`/`sse` mapping; `resources_discover` ungated) carry the gate; full-phrase must-not-contain for the literal lies ("the scaffold merges into settings.json").
- **Precondition pin:** the scaffold writes no pi-trust-requiring resource into a project's `.pi/` (`.pi/agents/` only) — red the day the fragile case becomes common.
- **Gate:** repo B full pytest. RED proof: the flipped pins fail against HEAD for the right reason (already witnessed by the qa lane's throwaway probe).

### P4 — ADR-0023 + changelog + fork docs (repo B)
- **Files:** `docs/adr/0023-pi-project-scoped-mcp-and-skills.md` (Nygard): measured trust semantics + fragile-case flip; skills asymmetry (divergence + hooks precedent); auto-trust dead-code note; **no `/new`-stranding claim** (R1) — lifecycle semantics recorded as measured (factory re-invocation); ADR-0022 boundary holds (event-time read like `hooks.json`, no manifest pi keys); converter claude-format coupling. `CHANGELOG.md` entry (behavior change: global entries become legacy). Fork `README.md` (project `.mcp.json`, trust-gated, remote mapped, `${HOME}` expanded).
- **Gate:** review-only; merges with/after P1–P3.

### P5 — Integration (LAST, real machine) — **channel = `mcp_list_servers` tool (R4), never queued commands**
1. Snapshot `~/.pi/agent/settings.json` (diff target). 2. Ship-order proof: new fork + old global entries still arm via fallback. 3. Migration execution: this repo's scaffold removes exactly its 5 servers + skills path; user keys byte-identical; drifted entries (if any) warn-and-leave. 4. Minimal-project headless: `pi -p "call the mcp_list_servers tool and print its JSON"` → exactly the `.mcp.json` five, sourced `project:.mcp.json`, no trust bootstrap. 5. Fragile-case flip both directions (scratch project + `.pi/settings.json`). 6. Cross-project isolation + `rider` remote (ai-raccoon, job-search-ai-assistant). 7. Skills two-sided probe. 8. Lifecycle: interactive `/new` → tools still callable (factory re-invocation — corrected expectation). 9. Scaffold idempotence (byte-diff empty). 10. Version-gate live proof (remove marker files ⇒ entries left with warning; restore). 11. Honesty readback (support.json, ADR-0023, changelog). 12. All suites green (repo B pytest; repo A bun+tsc; fork vitest+tsc) + vendored byte-identity via `bun publish.ts --ai-badger` + `git status --porcelain features/pi/adjustments/adapter` clean.

---

## 3. support.json pi rows (asserted by P3; JSON-path scoped)

- **`mcpServers`:** fork reads project `.mcp.json` at `session_start` (claude→fork conversion; **`${HOME}` expanded**); **gated by pi project trust — scaffolded projects without pi-trust-requiring resources arm in all modes (short-circuit)**; local stdio + remote `http`/`sse`; global `mcp` = user-owned fallback, no longer scaffold-written.
- **`skills`:** adapter `resources_discover` contributes the project path, **ungated**, per ADR-0023's recorded asymmetry.

## 4. Migration plan (live state)

Measured today: global `mcp` = 5 servers, `skills` = one ai-badger path, no `mcpDisabledTools`, no trust.json, `defaultProjectTrust:"ask"`. Order: P1–P4 merged ⇒ per-project re-scaffold (shape-aware, marker-gated removal) ⇒ P5 verification. **No trust bootstrap step** (measured short-circuit). User-owned entries survive by construction (shape match makes it true for values). Other projects' residue survives until their re-scaffold — harmless (project entries win).

## 5. Risks (ranked)

1. Wrong trust semantics enshrined → M2 rewrite + both-direction pins + precondition pin. 2. Invisible divergence → M3 ledger + headless-visible tool reporting. 3. `tools:["*"]` trap → M1 converter + pinned tests. 4. Lifecycle semantics — factory re-invocation measured; defensive init so a converter error can never `exit(1)` headless. 5. Migration strands machines → per-extension marker gates + P5 step 10. 6. User-edit destruction → concrete shape matcher + byte-diff step. 7. support.json overclaim → §3 pins; D5 removes the stdio-only asterisk. 8. Stale `pi.extensions` double-load → P1 package.json fix + P2 flat sync.

## 6. Out of scope

ai-raccoon cwd→projectId resolver (state.next 1/3) · pbi tasks themselves · per-hook `pi` manifest keys (ADR-0022) · per-project `mcpDisabledTools` (D4) · scaffold-written trust.json (D1) · `.mcp.json` format/catalog/claude+copilot+hermes arming changes · pi core behavior (0.84.4 fixed).
