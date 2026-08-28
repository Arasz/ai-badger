# Plan: pi-mcp-tools fork fixes for review findings 11–18

Task: `aib-pi-review-fixes` (lane 4 of 4 — the pi-mcp-tools fork lane; lanes 1–3 cover ai-badger fixes).
Repo: `/Users/arasz/RiderProjects/pi-mcp-tools-fork`, branch `main` @ `b07d425`, merge-base `373dfe7`, version 1.1.5.
Deliverable: one fork branch → one PR on `origin` (`Arasz/pi-mcp-tools`). This document plans the work; it contains no code.

## Baseline (verified this session, not taken from the review)

- `npx vitest run`: **46/46 green across 4 files** (tests live in `tests/`, not `src/` — the review cited mock content correctly but the task brief's `src/McpClient.test.ts` path is wrong; actual: `tests/McpClient.test.ts`).
- `npx tsc --noEmit` clean (reviewer-verified; not re-run).
- Tests: `tests/ConfigLoader.test.ts`, `tests/McpClient.test.ts` (9), `tests/McpToolAdapter.test.ts`, `tests/SchemaConverter.test.ts` (13). **No `McpRegistry` test file** — confirmed.
- Gates: `npm test` = `vitest run`; `npm run build` = `tsc --noEmit`; husky pre-commit runs `npm run format:check && npm run build` — **pre-commit does not run vitest**, so vitest must be run explicitly per commit.
- SDK: `@modelcontextprotocol/sdk` **1.26.0** (installed). Note: the MCP client SDK and the pi host package (`@earendil-works/pi-coding-agent` ^0.84.3, type-only imports) are separate dependencies; the review's "SDK Client supports onclose/onerror" refers to the MCP SDK and was verified below.

### SDK facts verified in installed node_modules (1.26.0)

- `Protocol` exposes public `onclose?: () => void` (protocol.d.ts:251) and `onerror?: (error: Error) => void` (:257) — settable any time; `connect()` wraps the *transport's* handlers, not the client's own fields.
- `callTool(params, resultSchema?, options?: RequestOptions)` (client/index.d.ts:429); `RequestOptions.signal` cancels an in-flight request and raises `AbortError` (protocol.d.ts:61–70).
- `Protocol.close()` = `await this._transport?.close()`; the internal `_onclose()` then clears `_transport`, **aborts all in-flight request handlers** (McpError `ConnectionClosed`), and fires the public `onclose`.
- Consequence: after a real close, `connect()` on the *same* Client would not hit the 'Already connected' guard (`_transport` is undefined) — so the fork's own comment "Client.close() makes the client unusable" (McpClient.ts:74–75) may be stale for 1.26.0. The fix below proceeds regardless (make the invariant explicit, not accidental); the throw-after-close mock is flagged for live verification (see open questions).

### Review-claim spot-checks (all confirmed)

- `McpRegistry.scheduleReconnect` private (McpRegistry.ts:86), only caller `healthCheck()` (:152); bounded retry `MAX_RECONNECT_ATTEMPTS` at :91–98; `healthCheck` calls unbounded `client.listTools()` (:145); initial-connect failures are never stored in `clients` (:38–39) so they are not auto-retried today.
- `McpClient`: local `connect()` reuses `this.client` (:32–34); remote path swaps in fresh `attemptClient` (:76, :89); `disconnect()` closes the client (:147); `reconnect()` = disconnect+connect (:158–161); transport branch honors only websocket (:54), `sse`/`streamable-http` values fall through to auto-detect (:61–70).
- `McpToolAdapter`: `signal` received (:47) and pre-checked (:49) but `client.callTool(name, params)` at :65 forwards nothing; registered names `${prefix}_${tool.name}` (:32–33).
- `index.ts`: `applyToolFilter` gates on `name.startsWith("mcp_")` (:363); status math `registeredTools.size - disabledTools.size` (:130); `/mcp-toggle` intentionally disconnects (:229–230); `registry.initialize()` called at :81 and a fresh registry from `/mcp-reconnect` at :197–198; `saveDisabledTools` invoked from the `/mcp-tools` toggle handler (:316).
- `ConfigLoader`: silent return when `settings.json` missing (:52–55); the F20–F22 citation is in the doc comment at **:9–14 (ID at :12)**, not :16–18 as the review said.
- `types.ts:20`: `transport?: "sse" | "streamable-http" | "websocket"` — the config surface already exists.

## Work packages

Ordering: riskiest and most coupled first (WP1–WP3 share McpClient/McpRegistry), then independent fixes. One commit per package; draft PR opened after WP3 (both MAJORs + the unbounded-probe fix are then in). Each package: red-proof the new test against unmodified code before the fix (prove-the-check-fails), then implement, then `npx vitest run && npx tsc --noEmit`.

### WP1 — Recreate the SDK Client on reconnect (F12, MAJOR)

Files: `src/McpClient.ts`, `tests/McpClient.test.ts`

Change shape: track a private `closed` flag set in `disconnect()`; at the top of `connect()`, when `closed`, replace `this.client` with a freshly constructed Client (extract a small `createClient()` helper shared by constructor and connect). Local path then always connects a fresh Client over its already-fresh `StdioClientTransport`; the remote auto-detect path keeps its `attemptClient` swap.

Tests (design-first; red before fix):
| Test | Failure mode targeted | Mutation that makes it red |
|---|---|---|
| `reconnect() constructs a fresh SDK Client after disconnect` (assert Client constructor call count via mock factory) | closed-client reuse for local servers | revert the recreation in `connect()` → count stays 1 |
| `connect() after disconnect() succeeds with a mock that throws on connect-after-close` | the fork-documented unusable-client semantics leaking into the local path | same mutation |

Pin the *implementation contract* (new Client constructed), not SDK-internal reconnect semantics — the constructor-count test stays valid regardless of what 1.26.0 happens to tolerate. The throw-after-close mock is a secondary pin, validated live before merge (open question Q1).

### WP2 — Wire unexpected closes to auto-reconnect (F11, MAJOR)

Files: `src/McpClient.ts`, `src/McpRegistry.ts`, `tests/McpClient.test.ts`, `tests/McpRegistry.test.ts` (new)

Change shape:
- `McpClient`: add `onDisconnected?: (error?: Error) => void`; on successful `connect()` attach `onclose`/`onerror` handlers that flip `connected = false` and fire `onDisconnected` once per connect cycle, **only for unexpected closes** — `disconnect()` sets an `intentionalClose` flag first; handlers reset it on the next successful connect. Single-fire dedupe because `onclose` and `onerror` can both fire for one death.
- `McpRegistry`: attach `client.onDisconnected = () => scheduleReconnect(name, config)` inside `initialize()` for every connected client **and** on the replacement Client created inside `scheduleReconnect`'s timer (otherwise the first reconnect loses the watch). Add a `shuttingDown` flag set at the top of `shutdown()` that makes the handler a no-op, so session teardown and `/mcp-toggle`'s deliberate `disconnect()` never trigger reconnects.

Tests (new `tests/McpRegistry.test.ts`, `vi.useFakeTimers()`; McpClient module mocked so close events are simulatable):
| Test | Failure mode targeted | Mutation |
|---|---|---|
| unexpected close schedules a reconnect after `reconnectInterval` | unwired auto-reconnect (the finding) | remove the `onDisconnected` attach in `initialize()` |
| gives up after `MAX_RECONNECT_ATTEMPTS` with the give-up log | unbounded retry loop | remove the cap check (:92–98) |
| attempt counter resets after a successful reconnect | permanent lockout after one recovery | remove `reconnectAttempts.delete` on success |
| `autoReconnect=false` suppresses scheduling | config ignored | force `scheduleReconnect` |
| `shutdown()` cancels pending timers and suppresses onDisconnected | reconnect storm during teardown | remove `shuttingDown` guard |
| repeated close events replace, not stack, the timer | duplicate reconnect loops | remove `clearTimeout` of existing timer (:100–103) |
| healthCheck failure schedules reconnect (existing path) | regression while refactoring | remove the healthCheck call (:152) |
| the replacement Client from a reconnect is watched too | silent after first recovery | skip attach in the timer path |
| (client-level) intentional `disconnect()` does not fire `onDisconnected` | `/mcp-toggle` off triggers reconnect fight | remove `intentionalClose` guard |
| (client-level) `onclose`+`onerror` both firing → single callback | double schedules | remove dedupe |

This file is currently the riskiest untested code in the diff; these ten rows are the minimum bar, judged again by `review-tests` before the PR (tests-are-designed-and-reviewed).

### WP3 — Bound healthCheck's listTools (F15, MINOR)

Files: `src/McpRegistry.ts`, `tests/McpRegistry.test.ts`

Change shape: per client, race `client.listTools()` against a named `HEALTH_CHECK_TIMEOUT_MS` constant (5s — between init's per-attempt 10s and auto-detect's 2s; tunable, see Q4). Timeout → mark unhealthy and take the existing `scheduleReconnect` path, mirroring `initialize()`'s race pattern.

Tests: hung `listTools` → `healthCheck()` resolves within the fake-timer budget with `false` (mutation: remove the race → test times out red); fast `listTools` → `true` (sanity).

### WP4 — Propagate tool-call abort to the MCP request (F13, MINOR)

Files: `src/McpClient.ts`, `src/McpToolAdapter.ts`, `tests/McpToolAdapter.test.ts`, `tests/McpClient.test.ts`

Change shape: `McpClient.callTool(name, args, signal?: AbortSignal)` passes `{ signal }` as the SDK's third argument (SDK support verified: client/index.d.ts:429 + RequestOptions.signal). `McpToolAdapter` forwards its received `signal` at the call site. Map an `AbortError` rejection to the existing "Tool call cancelled" result shape (:49–54) so user-initiated cancels don't surface as MCP errors.

Tests: adapter forwards the signal (assert the mock client received it in the options arg; mutation: drop forwarding); `callTool` passes `{ signal }` as third arg (mutation: revert signature); aborted-after-start rejection surfaces as the cancelled result (mutation: remove the AbortError mapping).

### WP5 — Disable filter by registeredTools membership (F14, MINOR)

Files: `src/index.ts`, `src/toolFilter.ts` (new, pure helper), `tests/ToolFilter.test.ts` (new)

Change shape: replace the `startsWith("mcp_")` gate with membership in `registeredTools` — a name is removed only if it is a registered MCP tool **and** in `disabledTools`. Extract the one pure function (`enabledToolNames(allNames, registered, disabled)`) so it is unit-testable; `applyToolFilter` becomes a thin caller. This also protects non-MCP tools from a colliding user-global `disabledTools` entry.

Tests: custom-prefix (`gh_x`) disabled entry is excluded (mutation: restore `startsWith` → red, exactly the finding's scenario); non-MCP tool with a colliding name in `disabledTools` is kept (mutation: drop the membership guard); default `mcp_<server>_` behavior unchanged (regression).

### WP6 — ConfigLoader: warn on missing settings + self-contained comment (F16, F18b, MINOR/NIT)

Files: `src/ConfigLoader.ts`, `tests/ConfigLoader.test.ts`

Change shape: `saveDisabledTools` logs a warning (same `[pi-mcp-tools]` console.error style as the adjacent catch) when `settings.json` is missing, instead of silently returning. Creating the file was rejected: `/mcp-tools` only exists when settings.json existed at startup (index.ts:34–45 early-return), so the missing-file path is reachable mainly via mid-session deletion, and inventing a fresh settings.json could clobber pi's expectations — warn is the cheaper, safer fix (see Q3). Replace the `(F20-F22)` citation at :12 with the self-contained rationale it abbreviates ("headless pi at default trust ignores project-local extensions, so preferring project config would silently load untrusted server config").

Tests: missing-file save emits the warning and does not throw (mutation: restore silent return). Comment change is doc-only — no test, covered by review.

### WP7 — Honor explicit transport selection + intersection status math (F17, F18a, NIT)

Files: `src/McpClient.ts`, `src/index.ts`, `src/toolFilter.ts`, `tests/McpClient.test.ts`, `tests/ToolFilter.test.ts`

Change shape:
- F17 — **honor** the explicit `transport` value rather than narrowing the type: when `config.transport` is set, construct exactly that transport (websocket branch already exists; add direct sse / streamable-http construction with headers and the 2s attempt timeout) and do **not** fall through to auto-detect. Auto-detect remains the default when `transport` is absent. Narrowing to `"websocket"` was rejected: it deletes a published config surface (types.ts:20) for no behavior gain.
- F18a — compute the enabled count as the intersection of `registeredTools` and `disabledTools` (add `countEnabledTools(registered, disabled)` next to the WP5 helper; never negative). `Math.max(0, …)` was rejected as it hides the drift the intersection names honestly.

Tests: explicit `'sse'` constructs only `SSEClientTransport` (mock constructors, assert no streamable-http attempt; mutation: restore auto-detect order); no explicit transport preserves auto-detect order (regression); `countEnabledTools` equals the intersection size and never goes negative (mutation: restore raw subtraction → red).

### WP8 — Release prep + PR

Files: `package.json`

Bump version 1.1.5 → 1.1.6 (patch; all items are behavior fixes). The fork has no CHANGELOG.md and no changelog section in README (verified), so no changelog file is added (Q5). PR to `origin`/`main` with body mapping each finding 11–18 to its commit and test evidence; draft PR after WP3, marked ready after WP8. Branch: `fix/mcp-review-findings-11-18`.

## Gates (every package)

1. `npx vitest run` — green, with the package's new tests proven red before its fix.
2. `npx tsc --noEmit` — clean.
3. Husky pre-commit (`format:check` + `build`) runs automatically on commit; vitest does **not** run there, so step 1 is on the implementer.
4. Before PR-ready: `review-tests` pass over the new/changed suites (something other than the author asks whether each could have gone red).

## Non-goals

- No retry of failed *initial* connects (client never enters the registry map today; review didn't flag it — Q2).
- No live-MCP-server test harness in the suite; live verification is a one-off manual step (Q1).
- No change to the `transport` config type surface, no new config keys, no dependency bumps beyond none.
- No upstream PR to `tickernelz/pi-mcp-tools` in this task (Q6).

## Open questions

1. **Live SDK semantics (Q1, blocks merge of WP1's throw-after-close mock):** 1.26.0's `Protocol._onclose()` clears `_transport`, so same-Client connect-after-close may actually work — contradicting the fork's own comment (written against an older SDK) and the reviewer's assumption. Verify once against a real stdio server (e.g. a trivial script server): kill the child, observe `onclose`, then reconnect. The constructor-count test (WP1) is safe either way; drop or keep the throw-mock based on what the live run shows.
2. Should failed initial connects also be auto-retried (they are silently dropped today, registry map never gets the client)? Review didn't flag it; recommend leaving out of scope.
3. F16: warn (this plan) vs create settings.json — owner preference; warn chosen because the command surface only exists when the file existed at startup.
4. F15: health-check timeout value — 5s proposed (between init's 10s and auto-detect's 2s); owner may prefer 2s for snappy `/mcp-status`.
5. F18b/versioning: fork keeps no changelog — acceptable to bump `package.json` only, or add a README changelog section?
6. Should these fixes also be offered upstream to `tickernelz/pi-mcp-tools`? Affects commit-message conventions (conventional commits) and whether the PR description is written fork-internally or for an upstream audience.
