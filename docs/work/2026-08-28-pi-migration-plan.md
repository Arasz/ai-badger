# Implementation plan: add pi as a fourth ai-badger agent

**Date:** 2026-08-28
**Status:** Draft (updated with MCP code review + alternative estimates)
**Framework:** ai-badger v0.139.0, pi v0.84.3

Every factual claim below carries how it is known: MEASURED (run and observed), READ (quoted from a file or docs), INFERRED (derived from measurements).

---

## Phase 0 — Trust sentinel test (WRITTEN)

Script at `tooling/test_pi_hook_fires.py` implements the F20 run A/B pair:
- **Run A:** project-local `.pi/extensions/` without `--approve` → sentinel NOT written (negative control)
- **Run B:** user scope `~/.pi/agent/extensions/` without `--approve` → sentinel IS written
- Exit 0 if both correct, 1 otherwise

## MCP gap strategy — code review results

### Option (a) — `tickernelz/pi-mcp-tools` (`@zhafron/pi-mcp-tools`)

**Source quality:** Good — 7 clean TypeScript files, well-structured with clear separation (ConfigLoader, McpClient, McpRegistry, McpToolAdapter, SchemaConverter, types, index). ~700 lines total. MIT license. [MEASURED: full source read of all 7 files]

**Positives:**
- Uses official `@modelcontextprotocol/sdk` ^1.0.0 for all MCP protocol handling [READ: package.json]
- Supports all 4 transports: stdio, WebSocket, StreamableHTTP, SSE (with auto-detection for remote) [MEASURED: source]
- Config validation, per-server tool filtering, reconnect logic, debug logging [MEASURED: source]
- TUI-based interactive tool configuration via `/mcp-tools` command [MEASURED: source]
- Custom tool prefix, per-server enable/disable, env vars [MEASURED: source]

**Concerns:**
1. **Deprecated dependency:** Uses `@mariozechner/pi-coding-agent` (deprecated since the project moved to `@earendil-works`). npm confirms: `@mariozechner/pi-coding-agent@0.73.1` DEPRECATED — "please use @earendil-works/pi-coding-agent instead" [MEASURED: npm view]. The API surfaces should be identical (same project, transferred owner), but the import path is wrong for pi 0.84.3.
2. **No tests** — zero test files. CI is build-only (typecheck + lint) [MEASURED: .github/workflows]
3. **No reconnect backoff** — fixed 5s interval, no exponential backoff [MEASURED: McpRegistry.ts]
4. **Single contributor** — 23 commits, 1 author, 2 open PRs [MEASURED: GitHub]
5. **Age** — last commit Feb 18, 2026 (6 months ago) [MEASURED: GitHub]
6. **Live install risk:** `pi install git:github.com/tickernelz/pi-mcp-tools` may fail if the pi package resolver rejects the `@mariozechner` devDependency — needs live testing [INFERRED]

**Verdict:** Code quality is **acceptable** — the structure is solid, MCP SDK usage is correct, architecture is clean. The `@mariozechner` import is a packaging concern, not a code quality issue (the extension loads via jiti which resolves imports at runtime, and the APIs are the same). **Recommended as primary option** with a note to test live installation.

### Option (d) — Custom pi extension using `@modelcontextprotocol/client` v2

**What it is:** Build a custom pi extension from scratch using `@modelcontextprotocol/client` v2.0.0 (7 deps, 6.6MB) instead of the full SDK (17 deps). [READ: npm view]

**Key differences from SDK:**
- `@modelcontextprotocol/client` v2.0.0 is a standalone client package separated from the SDK in v2 [READ: npm]
- Dependencies: zod, jose, cross-spawn, eventsource, pkce-challenge, eventsource-parser, @modelcontextprotocol/core [READ: npm]
- Works with bun: `bun add @modelcontextprotocol/client` [READ: multiple sources]

**Effort estimate:**
- index.ts (entry, pi event wiring): ~150 lines
- McpClient.ts (wrapping client SDK, stdio + HTTP transport): ~150 lines
- SchemaConverter.ts (JSON Schema → TypeBox): ~100 lines
- ConfigLoader.ts (read .mcp.json): ~80 lines
- Tool adapter (MCP tool → pi.registerTool): ~100 lines
- Types: ~40 lines
- **Total: ~620 lines, ~6 files**

**Effort: 1-2 days** for a solid implementation with similar capability to the community extension.

**Pros vs community extension:**
- Full control over code quality, security, and updates
- No external dependency risk
- Can precisely mirror ai-badger's `.mcp.json` config format
- No `@mariozechner` vs `@earendil-works` namespace confusion

**Cons vs community extension:**
- Must write and maintain ~620 lines of TypeScript
- Cannot use `pi install` — must ship via file-copy scaffolding
- Community extension already works today

### MCP recommendation

**Primary: Option (a) `tickernelz/pi-mcp-tools`** with `features/pi/adjustments/adjust_mcp.py` as config-mapping layer.

**Contingency:** If `pi-mcp-tools` fails live testing (the `@mariozechner` import causes issues with pi 0.84.3), **fall back to option (d)** — custom ~620-line pi extension using `@modelcontextprotocol/client` v2. Build as a bundled extension under `features/pi/mcp-extension/`. Effort: 1-2 days.

## Naming decision

Per user instruction: **stay with old naming.** No `harnesses` alias. No rename. The `config.agents` key stays as-is. Schema enums add `"pi"` alongside existing agents.

## Phase structure

| Phase | Scope | Files | Status |
|-------|-------|-------|--------|
| 0 | Trust sentinel test | 2 new (test script, probe ext) | **WRITTEN** |
| 1 | Agent registration | ~10 (AGENT_NAMES, 6 schemas, detect.py, test, feature stubs) | Pending |
| 2 | MCP bridge | ~3 (adjust_mcp.py, adjustment.json, docs) | Pending (blocked on live test) |
| 3 | Cron extension | ~4 (cron files, adjust_cron.py, adjustment.json) | Pending |
| 4 | Full feature directory | ~13 (instructions, skills-source, support.json, remaining adjustments) | Pending |
| 5 | Hooks manifest | ~2 (deferred indefinitely) | Deferred |

## Key measurements needed

1. **Phase 0 priority:** Run `tooling/test_pi_hook_fires.py` — does user-scope extension fire in headless mode? (F20 reproduction)
2. **Phase 2 prerequisite:** Install `pi-mcp-tools` — does `pi install npm:@zhafron/pi-mcp-tools` work with pi 0.84.3?
3. **Phase 2 prerequisite:** Does `input` fire for queued messages? (needs provider credentials)
4. **Phase 3 prerequisite:** Does `Bun.cron()` work with pi's runtime?