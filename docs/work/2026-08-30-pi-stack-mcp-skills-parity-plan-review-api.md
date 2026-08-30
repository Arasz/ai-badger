# MoE plan review — lane 1 (FORK/TypeScript surface: P1 + P2 sync)

**Task:** aib-pi-stack-mcp-skills-parity · **Date:** 2026-08-30 · **Lane:** api-engineer (fresh reviewer; authoring lanes were architect/test-engineer/code-reviewer)
**Attacked:** plan rev 2 (`…plan.md`, M1/M2/M3/M6, P1, P2), premortem, test strategy — against fork source (`~/RiderProjects/pi-mcp-tools-fork/src/*`), canonical repo A (`~/RiderProjects/pi-badger-integration`), scaffold writer (`features/common/skills/welcome-ai-badger/scripts/mcp_tools.py` in the task worktree), and pi 0.84.4 dist (`~/.bun/install/global/node_modules/@earendil-works/pi-coding-agent/dist/`), all read this session.

**Headline:** the P1 restructure is implementable and needed, but two of its stated reasons are wrong at pi 0.84.4, and the P2 sync as specified would pass a byte-identity check against a path that does not exist. Separately, the converter table is missing two shapes — one of which the scaffold itself can emit (`${HOME}/…` commands) and one every hand-following-Claude-docs user will write (`type:"stdio"`).

---

## 1. Judge verdicts

### J1 — session_start restructure: **AGREE (implementable) / CHALLENGE (the motivating "/new bug" is false at 0.84.4)**

**Implementable — verified:**
- `registerTool` inside `session_start` is pi's documented dynamic path: *"pi.registerTool() works both during extension load and after startup. You can call it inside session_start, command handlers, or other event handlers. New tools are refreshed immediately in the same session"* (docs/extensions.md, `registerTool` section — the plan's :1369 reference).
- `ctx.cwd` and `ctx.isProjectTrusted()` both exist on the handler context (`dist/core/extensions/types.d.ts:209-217`; `dist/core/extensions/runner.js:503-533` `createContext()` — `cwd` is a live getter on the runner's session cwd, so `/resume`-into-different-cwd re-derivation works as the plan assumes).
- No un-rebuildable state exists. Module-level maps (`index.ts:7-18`: `registry`, `mcpConfig`, `enabledServers`, `initError`, `initStats`, `toolToServer`, `registeredTools`, `disabledTools`) are all derived per init. The SettingsList UI is ephemeral per `/mcp-tools` invocation (`index.ts:246-295` — created inside `ctx.ui.custom`, holds no state beyond the closure). Commands/flags land in fresh Maps (see J2).

**CHALLENGE — the plan's stated bug mechanism is false.** Plan §1 M1 and premortem risk 4 say the latent `/new` bug is *"init ran once at extension load, `session_shutdown`→`clearModuleState()` strands the extension."* That is not how pi 0.84.4 works:
- Every session replacement (`/new`, `/resume`, `/fork`, `/reload`) calls `createRuntime` (`dist/core/agent-session-runtime.js:113-184`), which builds a **fresh** `createAgentSessionServices` → **fresh** `DefaultResourceLoader` → `loadExtensionsCached` (`dist/main.js:569-664`; `dist/core/agent-session-services.js:53-63`; `dist/core/resource-loader.js:412,426,441`).
- `loadExtension` **always** re-invokes the factory: `initializeExtension` → `createExtension()` (fresh extension object, fresh `handlers/tools/commands/flags` Maps) → `await factory(api)` — unconditionally, every time (`dist/core/extensions/loader.js:455-475`). The only cache is the jiti **module factory** keyed by path+cwd+generation (`loader.js:116-130,410-425`); caching the factory does not skip the factory *call*.
- Therefore the fork's factory (`index.ts:31-…`) already re-runs on every `/new`: it reloads config, rebuilds the registry, reconnects servers, and re-registers tools on the fresh extension object. Today's `/new` does **not** strand the extension — it works, at the price of a full blocking reconnect at load time (`index.ts:82` awaits `registry.initialize()` inside the factory, up to 30 s). The premortem's "verified latent bug" was a misread of the loader (it modeled the factory as once-per-process).

Consequences the plan must absorb:
1. **Narrative hygiene:** the "/new strands the extension" story must not reach the ADR-0023, changelog, or any test rationale as a fixed defect. P5 step 8's expectation ("latent-bug fix verified in the real binary") is wrong-shaped: before the change `/new` works; after, it works with event-time-derived config. Reframe step 8 as *behavior-preservation + config re-derivation on reason:"new"*, not a bug fix.
2. **The restructure is still required**, for reasons the plan should state instead: (a) M1's project-scope read needs `ctx.cwd` and `ctx.isProjectTrusted()`, which the factory does not have — only the event context does; (b) factory-time awaits block extension loading and sit on a hard failure path: a throw from a factory → `load.discard()` → "Failed to load extension" diagnostic → **headless pi exits 1** (`dist/main.js` runtime-error path). Today's fork survives only because it swallows init errors (`index.ts:126-129`); event-time init is the correct seam regardless.
3. The test strategy's red-proof for `tests/lifecycle.test.ts` survives (there is no per-session init *seam* on HEAD, so the test is red) — but its *rationale* text ("nothing rebuilds because init happened once") should be corrected to "config/trust derivation from ctx does not exist as a seam on HEAD".

### J2 — duplicate `registerTool`/`registerCommand` across repeated `session_start`: **CHALLENGE — the plan's "duplicate-registration guard" is dead weight; pin the measured semantics instead**

Measured facts:
- **Same-name registration is `Map.set` overwrite**, not accumulation or error: `registerTool(tool) { extension.tools.set(tool.name, …) }`, `registerCommand(name) { extension.commands.set(name, …) }`, `registerFlag` likewise (`dist/core/extensions/loader.js:239-260`). Within a session, calling it twice is idempotent (last-wins).
- **Cross-session accumulation is structurally impossible**: each session replacement gets a fresh extension object with fresh Maps (J1; `loader.js:446-460`). Yesterday's registrations die with yesterday's extension object.
- **A deregister-based guard cannot be built**: the ExtensionAPI has no `unregisterTool`/`unregisterCommand` (only `unregisterProvider` exists — `loader.js:289-296`; API surface verified).
- **Stale tools across a cwd change are also impossible**: `/resume` into a different cwd discards the old session's extension object wholesale (J1); the new session registers only the new config's tools.

Correct guard shape: **none**. Keep the existing `registeredTools` Set purely as bookkeeping for `applyToolFilter` (`index.ts:14, 263-271`). P1 should (a) delete the "duplicate-registration guard" item from its file list, (b) pin the overwrite semantics with a test (register the same tool name twice in one session → one tool), and (c) record the semantics in ADR-0023 so risk 4 ("duplicate-`registerTool` behavior is unpinned in pi") is retired as *measured: idempotent by Map keying + fresh Maps per session*. The test strategy's live duplicate sub-spike (§2 H2) remains fine as cheap verification, not as a design unknown.

### J3 — converter completeness (M1): **CHALLENGE — the table misses two shapes, one scaffold-generated**

The scaffold's emission surface is confirmed: `GENERATED_ENTRY_KEYS = {command, args, cwd, env, tools}` (`mcp_tools.py:38`), `_render_entry` (`mcp_tools.py:423-441`) emits `command`(+`args`) always, `env` when declared, `tools:["*"]` always for `.mcp.json` (`all_tools=True`, :101), and never `type`/`url`. No current destination pins `cwd` (no `pin_cwd=True` anywhere), but `cwd` appears in the wild from older scaffolds — pass-through covers it. Against that surface and plausible hand edits:

- **MUST — `${HOME}`-prefixed commands.** The `.mcp.json` writer has `expand_home=True` (`mcp_tools.py:101`) and rewrites bare executables found in `~/.dotnet/tools` or `~/.local/bin` to `${HOME}/…` form (`USER_TOOL_DIRS` :29-33, `_home_relative_command` :444-463). Claude Code documents `${VAR}` expansion for `.mcp.json` (`mcp_tools.py:99` docstring). The fork does **no** expansion: `createStdioTransport` passes `command[0]` verbatim (`McpClient.ts:165-170`) → `spawn("${HOME}/…")` → ENOENT → server silently fails (visible only under `--mcp-debug`, the exact failure class the `tools:["*"]` trap was killed for). The converter must expand `${HOME}` — and define one policy for other `${VAR}` references (expand from `process.env`, warn-and-skip the entry when unset) — applied to `command`/`args`/`cwd`/`env` values. Neither plan M1 nor test-strategy table cases (a)–(h) mentions this. Add converter table rows.
- **MUST — explicit `type:"stdio"`.** Claude Code's documented `.mcp.json` format *requires* `"type":"stdio"` on local entries. The plan's own rule — *"remote shape … or unknown `type` → entry skipped with logged warning"* — would swallow every hand-written, docs-following stdio entry. The test-strategy table has no stdio-typed case (case (a) is a bare `command`). Rule must be: absent `type`, `"stdio"`, or bare `command` → local; `"http"`/`"sse"`+`url` → remote (D5); anything else → skip-with-warning.
- **SHOULD — `headers` pass-through.** Claude's `http`/`sse` entries may carry `headers`; the fork's `RemoteMcpServerConfig` already has `headers` (`types.ts:21`) and `McpClient` honors them on both transports (`McpClient.ts:57, 108-116, 160-172`). D5's mapping text (`{type:"http"/"sse"} + url → {type:"remote", url}`) omits headers; map them through or authed remote servers arm but fail at request time.
- **NIT — remote auto-detect cost:** a `type:"sse"` entry arm via `connectWithAutoDetect` tries streamable-HTTP first with a 2 s timeout (`McpClient.ts:110-133`) — every connect to an SSE-only server pays it unless the entry also sets `transport:"sse"`. Converter may pass `transport` through when claude someday has it; pre-existing behavior otherwise, accept.

### J4 — `/mcp-status` per-server source labels (M3): **AGREE, with one implementation requirement made explicit**

Nothing in the command structure blocks it: `mcp-status` renders freeform `ctx.ui.notify`/`setStatus` strings (`index.ts:160-197`), so appending a source label per line (`✓ name (project:.mcp.json)`) breaks no UI contract. The two `mcp-status` registrations (early-return minimal `index.ts:39-45`, main `:160`) are mutually exclusive per session — structure survives the restructure. **One requirement the plan should state:** skipped (`unsupported-shape`), `untrusted-project`, and not-armed entries have **no client** in `registry.getClients()`, but today's handler renders *from the registry* (`index.ts:167-173`). The per-server source ledger (merged-config decisions from `session_start`) must live in per-session module state and the command must render from that ledger — iterating the registry can never show the skipped/untrusted lines MUST-2 demands. The skipped-entry count comes from the same ledger.

### J5 — atomic `saveDisabledTools` drive-by inside P1: **AGREE — safe**

- Sole write path is the `/mcp-tools` SettingsList `onChange` (`index.ts:317`), mid-session TUI only. Current write is a bare `writeFileSync` read-modify-write of the whole settings file (`ConfigLoader.ts:47-63`) — a concurrent scaffold `os.replace` can interleave and the bare write can tear the file. Temp-file-in-same-directory + `renameSync` is atomic on macOS (`rename(2)`) and replaces-existing on Windows (Node `renameSync` uses `MOVEFILE_REPLACE_EXISTING`); it strictly improves the tear hazard. Atomicity does **not** make the read-modify-write transactional (a lost update against a concurrent scaffold write remains possible) — pre-existing, and D4 already accepts the scoping residual.
- `GLOBAL_SETTINGS_PATH` bails when settings.json is missing (`ConfigLoader.ts:49-52`); post-migration the file still exists (user keys), so toggles keep working. No P3 interaction.
- **SHOULD hardening:** unique temp name (pid+random), `unlink` the temp on failure. **NIT:** pi watches some config surfaces (theme watcher); a rename-triggered watch event is equivalent to an in-place change — no new hazard observed.

### J6 — P2 byte-identity sync: **CHALLENGE — the check as written targets a path that does not exist, and the plan names an adapter file that does not exist**

- **The canonical layout is flat; the fork is `src/`-based.** `~/RiderProjects/pi-badger-integration/extensions/pi-mcp-tools/` holds `index.ts`, `ConfigLoader.ts`, … at the package root — **no `src/`** (verified; the flat files are byte-identical to fork `src/*` today). The test strategy's byte-identity check ("`extensions/pi-mcp-tools/src/*` ≡ fork `src/*`") and plan P2's "port P1's fork src into canonical `extensions/pi-mcp-tools/src/*`" therefore name a nonexistent path. Worse: the canonical `package.json` says `"main": "src/index.ts"` and `pi.extensions: ["./src/index.ts"]` (`package.json:6, 56-60`) — **stale**; the extension currently loads only via the loader's fallback to `index.ts` when manifest entries don't exist (`loader.js:541-560` `resolveExtensionEntries`). If P2 follows the plan text and *creates* `src/`, the manifest starts resolving, pi loads `src/index.ts`, and the flat files become dead-but-shipped code — two entry points, silent divergence, and the (mis-pathed) identity check green. **MUST:** pick one layout explicitly. Recommended: keep flat (matches the installed `~/.pi/agent/extensions/pi-mcp-tools` layout — verified flat too), check `extensions/pi-mcp-tools/*.ts ≡ fork src/*.ts` excluding `package.json`/lockfiles, and correct the stale `main`/`pi.extensions` keys to `"./index.ts"` in the same PR.
- **Plan P2's adapter path is wrong.** `extensions/ai-badger/index.ts` does not exist in repo A; the adapter canonical is `features/pi/adjustments/adapter/index.ts` (verified; premortem's `adapter/index.ts:44,64-71,131-146` citations match it). P2's file list and AC must be corrected.
- **Packaging deps: low risk, verified.** P1's new converter needs only node builtins; canonical `package.json` deps already match the fork's (`@modelcontextprotocol/sdk`, `@sinclair/typebox`; `@earendil-works/pi-tui` is a devDep but resolves via pi's bundled `virtualModules` and the installed copy's `node_modules` — both verified present). No new deps flow from P1.
- **SHOULD:** name who syncs repo B's vendored adapter copy (`features/pi/adjustments/adapter/` — verified present) when P2 adds `resources_discover`; `test_framework_copies.py` will force it at P3's gate, but the plan should assign it. **NIT:** mirrored tests are `bun:test` (repo A) vs vitest (fork) — "extend mirrored tests" is re-expression, not copy; and repo A's existing rule never to import-exercise the real-`~/.pi`-hardcoding functions (`tests/pi-mcp-tools/config-loader.test.ts:1-13`) means the new atomic `saveDisabledTools` stays untestable in repo A unless the settings path becomes injectable (optional param) — worth doing while P1 touches the function.

---

## 2. Findings

**MUST**
1. **Converter: `${HOME}`/`${VAR}` expansion** for `command`/`args`/`cwd`/`env` values, with a defined unset-`${VAR}` policy (warn-and-skip). Scaffold-generated shape (`mcp_tools.py:29-33,101,444-463`); unexpanded it silently ENOENTs the server (`McpClient.ts:165-170`), debug-only visible. Add converter table rows + fixture (J3).
2. **Converter: `type:"stdio"` and absent-`type` → local** before the unknown-type skip rule, or every docs-conformant hand-written entry is dropped (J3). Pin in `tests/ClaudeMcpConfig.test.ts` alongside (a)–(h).
3. **P2: fix the byte-identity check path and decide the layout** — canonical is flat (`extensions/pi-mcp-tools/*.ts`), the plan/check say `src/*` (nonexistent), and the stale `pi.extensions`/`main` keys make a naive `src/` port resolve a second entry point (J6). Correct the stale keys in the same PR.
4. **P2: correct the adapter file path** — `features/pi/adjustments/adapter/index.ts`, not `extensions/ai-badger/index.ts` (J6).
5. **Drop the "duplicate-registration guard"; record the measured semantics** (fresh Maps per session, `Map.set` overwrite by name, no unregister API) in ADR-0023 and P1 tests; remove the guard item from P1's file list (J2). Rewrite the false "/new strands the extension" mechanism wherever it appears (plan §1 M1, risk 4, premortem risk 4/H2 rationale, test-strategy red-proof rationale, P5 step 8 framing, future ADR/changelog): the factory re-runs per session replacement at 0.84.4 (`loader.js:455-475`), so restructure is justified by ctx/cwd/trust access and the factory throw→headless-exit-1 path, not by a stranding bug (J1).

**SHOULD**
6. Map `headers` through on the `http`/`sse` → `remote` conversion (fork already supports it; D5 text omits it) (J3).
7. Name the owner for repo B's vendored adapter sync (`features/pi/adjustments/adapter/`) in P2/P3 (J6).
8. Atomic `saveDisabledTools`: unique temp name + temp cleanup on failure; consider an injectable settings-path param so repo A (bun, no module mocking) can test it (J5/J6).
9. `/mcp-status`: state explicitly that the command renders from the per-session merge ledger, not `registry.getClients()` — skipped/untrusted servers have no client (J4).
10. Rewrite `ConfigLoader.loadFromSettingsJson`'s docstring when P1 touches the file: its reasoning ("headless pi at default trust ignores project-local extensions…") is the superseded trust narrative M2 corrected; the new docstring must carry the measured short-circuit semantics (J1/M2).

**NIT**
11. SSE-only remotes pay a 2 s streamable-HTTP auto-detect timeout per connect (`McpClient.ts:110-133`) — pre-existing; acceptable; note in fork README.
12. Mirrored bun tests cannot byte-match vitest tests — re-expression only; keep repo A's real-home import-exclusion rule for the new modules (J6).
13. `saveDisabledTools`'s missing-file bail (`ConfigLoader.ts:49-52`) is pre-existing and fine post-migration; no action (J5).

---

## 3. Verified vs hypothesis

**Verified this session (read source / ran read-only commands):**
- pi 0.84.4: extension factory re-invoked per session replacement — fresh `ResourceLoader` per `createRuntime` (`main.js:569-664`; `agent-session-services.js:53-63`; `agent-session-runtime.js:113-184`), `initializeExtension` always `await factory(api)` with fresh Maps (`loader.js:446-475`); factory cache holds only the jiti module (`loader.js:410-425`).
- pi 0.84.4: `registerTool`/`registerCommand`/`registerFlag` are name-keyed `Map.set` overwrite (`loader.js:239-260`); no unregister API for tools/commands (`unregisterProvider` only, `loader.js:289-296`).
- pi 0.84.4: factory throw → extension load failure diagnostic → headless `process.exit(1)` (`main.js` runtime-error path); `session_start` event carries `reason`, not cwd — cwd comes from `ctx` (`types.d.ts:419-424`; `runner.js:503-533`); `ctx.isProjectTrusted()` bound per session; trust short-circuit `!hasTrustRequiringResources || trustStore.get(cwd) === true` confirmed in `main.js` `createRuntime` (matches M2).
- Fork: factory-time init + awaited connect (`index.ts:32,73,82`); `session_shutdown`→`clearModuleState` (`index.ts:153-157`); `RegExp` poison path (`McpToolAdapter.ts:24`, no try/catch; per-server catch `index.ts:119-123`); `saveDisabledTools` bare write (`ConfigLoader.ts:47-63`), sole caller the TUI toggle (`index.ts:317`); remote transports + `headers` support (`McpClient.ts:1-4,57,105-172`; `types.ts:14-27`).
- Scaffold: `GENERATED_ENTRY_KEYS` (`mcp_tools.py:38`), `_render_entry` shapes (:423-441), `${HOME}` expansion for `.mcp.json` (:29-33, :101, :444-463), `${VAR}` expansion documented for `.mcp.json` (:99); live ai-badger `.mcp.json` = 5 entries, all `tools:["*"]`, no `type`/`url`, no `cwd`.
- Repo A: canonical `extensions/pi-mcp-tools` flat (no `src/`), stale `main`/`pi.extensions` → `./src/index.ts` (`package.json:6,56-60`), flat files currently byte-identical to fork `src/*`; adapter canonical at `features/pi/adjustments/adapter/index.ts` (no `extensions/ai-badger/`); mirrored tests are `bun:test` with the real-home import exclusion (`tests/pi-mcp-tools/config-loader.test.ts:1-13`); repo B vendored adapter copy present in the task worktree.

**Still hypothesis (implementation must test):**
- Live `/new` + duplicate-registration behavior in the real binary (test-strategy sub-spike) — expected clean per the Map semantics above; still live-only.
- `${VAR}` expansion policy parity with Claude for arbitrary variables (docs read via `mcp_tools.py` docstring, not Claude's docs directly — verify against Claude Code docs when writing the converter).
- Whether pi watches `settings.json` for changes and how a rename interacts (no watcher found for settings in this pass; theme watcher exists) — observe during P5 step 9's idempotence run.
- H2/H1 last-mile live proofs as already scheduled (unchanged by this review).
