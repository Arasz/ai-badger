# Research record — pi stack parity: MCP config + skills discovery defined by the project scaffold

**Task:** aib-pi-stack-mcp-skills-parity (high-effort) · **Date:** 2026-08-30
**Scope (state.json next item 2, verbatim):** "pi stack parity (user e:, queued): pi discovers
the same ai-badger MCP tools as Claude Code — MCP config + skills discovery defined by the
project scaffold."

## Findings

Every finding carries its evidence grade: MEASURED (ran/observed it), READ (read source/docs),
INFERRED (labelled hypothesis below).

| # | Grade | Finding |
|---|-------|---------|
| F1 | READ | Current pi MCP arming: `features/pi/adjustments/adjust_mcp.py` maps declared servers to pi-mcp-tools format and merges them into **user-global** `~/.pi/agent/settings.json` under `mcp`. support.json `agents.pi.capabilities.mcpServers`: `supported: "partial"` — "that key has no consumer in pi core". |
| F2 | MEASURED | Live `~/.pi/agent/settings.json` holds 5 servers (ai-raccoon, code-review-graph, hermes, playwright, semantica) + skills array `["…/ai-badger/.ai-badger/skills"]` — one project's snapshot, globally applied. |
| F3 | READ | Current pi skills arming: `adjust_skills.py` merges the project's absolute `.ai-badger/skills/` path into the **user-global** settings `skills` array — chosen because it is "the one discovery route that is not trust-gated" (works headless). |
| F4 | INFERRED (from F1–F3 mechanisms) | Cross-project leak: the global `mcp` key merges same-named-overwrite across every scaffolded project; the global `skills` array accumulates one path per project. Every pi session sees every project's servers and skills. Claude Code compares: project `.mcp.json` (scaffold-managed) + `.claude/skills/`. This is the parity gap. |
| F5 | READ | Fork `pi-mcp-tools-fork/src/ConfigLoader.ts` reads **only** user-global settings, with a deliberate documented reason: "Project-local .pi/settings.json is deliberately NOT checked first: headless pi at default trust ignores project-local extensions, so preferring project config would silently load untrusted server config. User scope is the only safe default." |
| F6 | READ | Fork `index.ts` loads MCP config at **extension-init time** (top of `export default`), before any ctx exists — so `ctx.isProjectTrusted()` (docs extensions.md:996) is unavailable there. Restructuring to trust-aware project config requires moving config load to a session event. |
| F7 | READ | pi load order (extensions.md:280): `project_trust` → `session_start` → `resources_discover`. Trust is resolved before both session events; `ctx.isProjectTrusted()` is truthful there. |
| F8 | READ | `resources_discover` (extensions.md:376–385) lets a user/global extension contribute `skillPaths` (and prompt/theme paths) at startup/reload — the adapter could contribute `<cwd>/.ai-badger/skills` project-scoped, headless-safe (user-scope extensions run regardless of project trust). |
| F9 | READ | Headless trust on this machine: `defaultProjectTrust: "ask"`, **no** `~/.pi/agent/trust.json` → project resources (incl. `.pi/settings.json`) are ignored in `-p`/`--mode json`/`--mode rpc` runs. Claude's `.mcp.json` is **not** trust-gated. So a naively trust-gated project MCP config would be strictly weaker than claude in exactly the headless runs ai-badger exists for. Owner decision required (D1). |
| F10 | MEASURED | Fork repo `~/RiderProjects/pi-mcp-tools-fork` main @ 93dea86, clean (untracked `.ai-badger/task-tracking/` only). Vendored copy `pi-badger-integration/extensions/pi-mcp-tools/` src is **in sync** with the fork (only packaging files differ). |
| F11 | MEASURED | **Sequencing dependency (user-flagged f:):** `pi-badger-integration` worktree `.ai-badger/worktrees/pbi-move-extensions-to-dir-packages`, branch `task/pbi-move-extensions-to-dir-packages` @ 7c9e6e7 — reviewed plan (`docs/plans/2026-extension-directory-packages.md`), P1 of 6 committed, tree clean. It makes repo A the sole canonical extension owner/installer, converts extensions to directory packages, and (P5) strips repo B to a minimal pi layer (deletes `features/pi/cron/`, `features/pi/subagent/`, `adjust_cron.py`). It explicitly does NOT touch `adjust_mcp.py`/`adjust_skills.py`. This task's repo-A-side work must land **after** it; repo-B-side planning can proceed. |
| F12 | MEASURED | ai-badger repo's own `.pi/` holds only `agents/` (personas). No `.pi/settings.json`, no `.pi/skills/`. |
| F13 | READ | Per-tool toggles (`mcpDisabledTools`) are saved to **global** settings by the fork — a second, smaller cross-project leak (toggles from project A apply in project B). |
| F14 | READ | Scaffold side: per-agent `adjust_mcp.py` files exist (claude/copilot/hermes/pi); declarations come from `self.mcp.declarations_for_agent(agent)` (welcome-ai-badger scaffold.py:646). Claude's `.mcp.json` is a managed scaffold artifact (gates: `scaffold_freshness_guard.py`, `shipped_paths_guard.py` reference it). |
| F15 | READ | ai-raccoon ≥1.37.0 cwd→projectId contract (shared memory hash ce9cfa83) belongs to state.next items 1/3, **not** this task. Context only: pi sessions currently pass projectId explicitly; the resolver will later remove that. |

## Hypotheses (unverified — implementation must test first)

- H1: `resources_discover`'s ctx carries `cwd`/`isProjectTrusted` usable by the vendored adapter (example shows `_ctx` unused; event has `event.cwd`).
- H2: The fork can move config loading from extension-init to `session_start` without regressing its 46 vitest tests and reconnect/healthcheck semantics.
- H3: `.mcp.json`'s `tools: ["*"]` field maps cleanly onto the fork's `filterPatterns`.

## Decision space for the plan (D1–D4)

- **D1 — MCP project-scope source + trust gate.** Source: (a) read the project's `.mcp.json` directly — single source of truth, claude-parity by construction, zero new scaffold files; or (b) write a pi-format copy under `.pi/settings.json` `mcp` key. Trust gate: (i) `ctx.isProjectTrusted()` only (safe, but headless-at-`ask` = weaker than claude, F9); (ii) adapter `project_trust` handler auto-trusts scaffolded projects (`.ai-badger/config.json` present) with `remember: true` — security-relevant, owner call; (iii) settings opt-in (e.g. `mcpProjectScope: true`); (iv) accept the headless gap and document.
- **D2 — Skills discovery.** (a) adapter `resources_discover` contributes `<cwd>/.ai-badger/skills` (project-scoped, headless-safe); (b) project `.pi/settings.json` skills array (trust-gated); (c) keep the global array (status quo, leaks).
- **D3 — Migration.** What happens to the existing global entries (F2) and to `adjust_mcp.py`/`adjust_skills.py` (kept as fallback / proposal-only / deleted); `mcpDisabledTools` scoping (F13).
- **D4 — Sequencing.** Land `task/pbi-move-extensions-to-dir-packages` first (repo A restructure), then this task on top; repo-B-side work has no file overlap (F11).

## Preflight blocks (Rule 1)

- **Objective:** pi sessions discover exactly the MCP servers and skills the project scaffold declares — same server set as Claude Code, project-scoped, no global accumulation, headless where honest.
- **Constraints:** pi 0.84.4; fork is our own (changes welcome); adapter is vendored byte-identical into ai-badger; user-global settings are the user's real config (atomic, idempotent, unknown-key-preserving writes only); support.json honesty rows must track reality; ADR-0022 style — pi arming stays dynamic, no per-hook/per-server manifest `pi` keys unless wiring demands it.
- **Known unknowns:** H1–H3 above; the trust auto-arm decision (D1) needs the owner.
- **Output contract:** scaffold-defined MCP + skills discovery for pi, with tests (fork vitest + repo B pytest), support.json updated, migration of live global state, ADR recording the trust decision, changelog.
- **Stop condition:** all packages' ACs met, gates green (repo B pytest + repo A bun test/tsc + fork vitest), live pi session verifies discovery in a scaffolded project headless.
