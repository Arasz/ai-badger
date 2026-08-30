# Test strategy — pi stack parity: MCP config + skills discovery (aib-pi-stack-mcp-skills-parity, MoE lane 2)

**Date:** 2026-08-30 · **Owner:** test lane (tests only — no production changes flow from this document)
**Inputs verified this session, not trusted:** the [plan](2026-08-30-pi-stack-mcp-skills-parity-plan.md) (M1–M6, P1–P5), the [premortem](2026-08-30-pi-stack-mcp-skills-parity-premortem.md) (MUST-1–7, Q1′–Q4), the [research record](2026-08-30-pi-stack-mcp-skills-parity-research.md) (F1–F15, H1–H3, D1–D4), the worktree tests, the fork (`~/RiderProjects/pi-mcp-tools-fork`), and pi 0.84.4 dist source.
**Repo names per plan §0:** repo B = `ai-badger` (pytest), repo A = `pi-badger-integration` (bun test), fork = vitest. All worktree-relative paths below are under `.ai-badger/worktrees/aib-pi-stack-mcp-skills-parity/`.

## Measured corrections to the input documents (read first — tests inherit these)

1. **The fork suite is 73 tests / 6 files, not 46.** Ran `npx vitest run` in the fork this session: 73 passed across `ConfigLoader`(14), `McpClient`(17), `McpRegistry`(10), `SchemaConverter`(13), `McpToolAdapter`(13), `ToolFilter`(6). The plan (P1 AC, risk 1) and premortem (risk 1, H2) both say "46". Every gate below is phrased "existing suite green", never a count.
2. **`.mcp.json` is gitignored** (`.gitignore:36-37`; the worktree contains only `.mcp.json.example`). The plan's "live `.mcp.json` (measured, ai-badger repo)" is machine-local state, not a repo artifact. Consequence: **no repo-side test may read a checked-out project's `.mcp.json`** — every pytest/vitest fixture builds its own project directory. The live gate (§4) runs in the real checkout, which does have one (measured: 5 servers, every entry `{command: str, args?: [str], env?, tools: ["*"]}`).
3. **Trust semantics: the plan's narrative is superseded by the premortem's measured one (MUST-1).** Verified in pi dist this session: trust-requiring resources are exactly `.pi/{settings.json,extensions,skills,prompts,themes,SYSTEM.md,APPEND_SYSTEM.md}` + ancestor `.agents/skills` (`dist/core/trust-manager.js:8-17,150-166` — `.mcp.json`, `.ai-badger/`, `.pi/agents/` are **not** on the list), and `projectTrusted = (!hasTrustRequiringResources || trustStore.get(cwd) === true)` (`dist/main.js:573-579`). So a minimal scaffolded project is trusted **in every mode including headless `-p`**; the gate flips only when a trust-requiring resource appears. Tests pin **both** directions.
4. **H3 is false, confirmed at source:** `src/McpToolAdapter.ts:22-28` runs `new RegExp(pattern)` on `filterPatterns`; the scaffold writes `tools:["*"]` into **every** entry (measured, live `.mcp.json`), and `RegExp("*")` throws — the throw escapes the per-tool loop into the per-server catch, killing every tool of every scaffolded server, visible only under `--mcp-debug`. This is a pinned test, not a mitigation note (premortem MUST-3).
5. **Line-number drift in plan P3:** the plan cites "existing pins at :76–:130" in `tests/test_pi_adjustments.py`; the merge/proposal pins actually live at :92 (`test_adjust_mcp_proposes_servers`) and the G1/G2 install-path block at :469–:830 (`test_adjust_skills_install_true_merges_skills_path`:537, `test_adjust_mcp_install_true_merges_into_settings`:566, real-home guard `test_pi_settings_write_does_not_touch_real_home`:832). Cited by name below, not by line.
6. **Adapter baseline for red-proof:** `features/pi/adjustments/adapter/index.ts` subscribes to exactly `tool_call` (:247) and `tool_result` (:276) — **no `resources_discover` handler exists today**. A handler test has a clean red baseline.

---

## 1. Per-package test list (file · what it pins · red-proof obligation)

### P1 — fork `pi-mcp-tools-fork` (vitest · gate: `npx vitest run` + `npx tsc --noEmit`)

| File | What it pins | Red-proof obligation |
|---|---|---|
| `tests/ClaudeMcpConfig.test.ts` (new) | The claude→fork converter. Table cases, each derived from a measured `.mcp.json` shape: (a) `command:"npx", args:["-y","srv"]` → `{type:"local", command:["npx","-y","srv"]}`; (b) `env`/`cwd` pass through; (c) **`tools:["*"]` and empty/absent `tools` map to "no filtering"** — never reach `filterPatterns` (correction 4); (d) glob-ish hand edit (`tools:["mcp_foo_*"]`) translates to an anchored regex; (e) an invalid regex pattern is dropped with a warning while the server's other tools survive; (f) `{type:"http",url}` and `{type:"sse",url}` → `{type:"remote",url}` (§3.3); (g) remote shape missing `url`, or unknown `type` → entry skipped with logged warning, other entries still arm; (h) unparseable JSON → `null` (global-only fallback), never a partial arm (premortem D1a condition d). | Run the whole file against pre-P1 fork HEAD: every case is red because the module does not exist (`cannot find module ./src/claudeMcpConfig.js`) or the behavior is absent. Green only after the converter lands. |
| `tests/ConfigLoader.test.ts` (append) | `loadProjectMcpJson(cwd)` reads `<cwd>/.mcp.json`; merge precedence project-over-global for same-named entries, **no partial merge** when the gate is false; global-only when no project file. Reuses the file's existing `os.homedir` mock idiom so nothing touches real `~/.pi/`. | The new `loadProjectMcpJson` static does not exist on HEAD — TypeError red before implementation. |
| `tests/lifecycle.test.ts` (new) | Per-session lifecycle (the H2 spike, §2): `session_start` arms servers from `ctx.cwd`-derived config; `session_shutdown` tears down; a **second `session_start` re-arms** (pins the latent `/new` bug: today `index.ts:20-25` `clearModuleState()` runs at :153-157 with nothing rebuilding because init happened once at extension load); config is **re-derived from `ctx.cwd` each session, never cached** (the `/resume`-into-different-cwd case); `/mcp-status` reports per-server config source (`project:.mcp.json` / `global settings` / `skipped:unsupported-shape` / `untrusted-project`) plus a skipped count (MUST-2); a per-server failure is visible **without** `--mcp-debug` once a scaffold-generated file can cause it (MUST-3). | Against HEAD the whole file is red: config loads at extension-init (top of `export default`, `index.ts:33`), before any ctx exists — there is nothing to drive per-session. |
| `tests/McpToolAdapter.test.ts` (append) | `convertToPiTool` try/catches every `RegExp` construction: a poison pattern skips that tool with a warning instead of failing the server (defence-in-depth under the converter's (c)/(e)). | On HEAD, `convertToPiTool(["*"])` throws `SyntaxError` — the appended test is red before the fix. |

### P2 — repo A `pi-badger-integration` (bun test · gate: `bun test` + `bunx tsc --noEmit`, after `bun install` in `extensions/pi-mcp-tools/` per the pbi plan)

| File | What it pins | Red-proof obligation |
|---|---|---|
| `tests/pi-mcp-tools/` (mirrored suite) | The P1 conversion table re-expressed against the canonical directory package, plus a **fork↔canonical byte-identity check**: `extensions/pi-mcp-tools/src/*` ≡ fork `src/*` (diff empty) — the same guarantee `test_framework_copies.py` enforces for vendored adapter files in repo B. | Mirror tests red if the sync has not happened (canonical src still pre-P1). |
| adapter `resources_discover` handler test | The handler returns `{skillPaths:[<event.cwd>/.ai-badger/skills]}` **when the directory exists** and `[]`/undefined-when-absent; it reads `event.cwd` (the event pi actually delivers is `{type:"resources_discover", cwd, reason}` — verified `dist/core/extensions/runner.js:935-947`), never ctx; the contribution is **ungated** (no `isProjectTrusted` check — Q2 outcome). | On HEAD the adapter has no `resources_discover` handler (correction 6): a test asserting the skillPaths contract is red. |

### P3 — repo B `ai-badger` (pytest · gate: full suite incl. `test_framework_copies.py`)

| File | What it pins | Red-proof obligation |
|---|---|---|
| `tests/test_pi_adjustments.py` (flip + append) | The G1/G2 install-path pins (:537, :566) **flip from merge to removal**: `adjust_mcp.adjust()` removes exactly the declared names (minus `mcp_declined`) from global `mcp` and writes nothing new; `adjust_skills.adjust()` removes exactly this project's absolute skills path; second run is a no-op (idempotent); non-declared entries and unknown top-level keys survive (`lastChangelogVersion`/`theme` — the real file's content, per the existing preservation pins); `--no-install` prints the removal proposal without writing (the :92 proposal pin flips to a removal proposal); **shape-aware removal** — a same-named global entry whose shape does not match what `_server_entry` would generate is left with a warning, never deleted (MUST-5, premortem risk 6: all 8 scaffolded projects share the same 5 names); **version-gate** — when the installed `~/.pi/agent/extensions/pi-mcp-tools` build predates `.mcp.json` reading, removal is skipped with a warning (MUST-5, premortem risk 5); `pi_settings.remove_mcp_servers`/`remove_skills_path` keep the atomic/idempotent/unknown-key-preserving contract (mirror the existing `test_pi_settings_write_is_atomic_on_failure`); the real-home leak guard (:832) extends to the removal path. | Each flipped pin is red on HEAD because HEAD *merges* (the assertion `data["mcp"]["filesystem"]` exists after `adjust()` becomes "entry absent, everything else intact"). |
| `tests/test_support_json_honesty.py` (extend the existing honesty pin or add a pi row test) | MUST-4, asserted as exact substrings: `mcpServers` row must state (i) fork reads project `.mcp.json` at `session_start`, (ii) gated by pi project trust with the short-circuit sentence (scaffolded projects without pi-trust-requiring resources arm in **all modes**), (iii) local stdio + remote `http`/`sse` mapping; `skills` row must name `resources_discover`, ungated. Lying phrases fail the test: unqualified "same servers as Claude Code", "the scaffold merges into settings.json", "headless-safe" without the trust sentence, "trust-gated" on the skills row. | Red on HEAD: current row says "partial via global merge". |
| `tests/test_framework_copies.py` (no change needed — existing gate) | Vendored adapter ≡ canonical adapter (P2 must keep them in sync); the byte-identity property is already enforced here — P2's adapter edit is what it guards. | Existing green gate; it goes red if P2 edits only one copy. |

### P5 — integration (no new files; the checklist in §4 *is* its test list)

---

## 2. Spike specs (run before the package that depends on them)

### Spike H1 — `resources_discover` `skillPaths` honored in headless runs → feeds P2

**Status: source-verified, machine-unverified.** pi dist runs `extendResourcesFromExtensions` unconditionally after `session_start` with no mode/`hasUI` gate (`dist/core/agent-session.js:1920-1941`), and the event carries `cwd` (`dist/core/extensions/runner.js:935-947`). The premortem still requires the live smoke; this spike is it.

- **Command (positive probe), in the real ai-badger checkout after the P2 adapter is installed:**
  `cd /Users/arasz/RiderProjects/ai-badger && pi -p "Quote the exact first heading of the SKILL.md named design-tests. If you do not have that skill file, say MISSING."`
  **Expected observable:** output contains the design-tests heading. The probe asks for *file content*, not a model's self-report of "do you have skills", so only a genuinely loaded `skillPaths` entry can produce it.
- **Command (negative control, same probe):** in a scratch directory with no `.ai-badger/skills` (and no global `skills` entry — see §4 step 3 ordering) → expected observable: `MISSING`. If the negative control names the skill, the contribution is leaking globally — the exact F2/F4 bug this task exists to kill, resurfacing through the new channel.
- **Interpretation:** positive + clean negative ⇒ H1 closed, P2's live-smoke AC met. Positive fails ⇒ the documented fallback triggers (keep the global `skills` array route for pi, one deliberate residual in the ADR — plan risk 2). **Label: hypothesis at the machine level; do not let P2 merge before the probe runs.**

### Spike H2 — fork `session_start` restructure vs the vitest suite → feeds P1

**Status: hypothesis (premortem §5 keeps H2 open).**

- **Command (red first):** write `tests/lifecycle.test.ts` per §1 P1, then `cd ~/RiderProjects/pi-mcp-tools-fork && npx vitest run tests/lifecycle.test.ts` against pre-refactor HEAD.
  **Expected observable: RED** — because config loads once at extension-init (`index.ts:33`) and `session_shutdown` → `clearModuleState()` (:153-157) leaves nothing to rebuild a second session from. This red is itself the proof the latent `/new` bug is real.
- **Command (green):** after the restructure, `npx vitest run && npx tsc --noEmit`.
  **Expected observable:** all 73 existing tests + the new files green; typecheck clean. That conjunction is H2's answer. If reconnect/healthcheck semantics in `tests/McpClient.test.ts` regress, H2 is false and the restructure design returns to the plan before P1 merges.
- **Sub-spike (duplicate registration — unpinned pi behavior):** with the restructured fork installed, run `pi -p "call the mcp-status tool"` twice in one project, and interactively `/new` then re-check.
  **Expected observable:** `mcp-status` lists each declared tool exactly once, no duplicate-registration error, tools callable after `/new`. **Label: hypothesis about pi's `registerTool` on repeated `session_start` — live-only, cannot be pinned in vitest; if duplicates appear, the fix (deregister or registry-keyed guard) lands in P1 scope.**

---

## 3. Contract tests (the three properties the task's objective names)

### 3.1 Server-set equality vs Claude's `.mcp.json` — proven by construction, closed by fixture and live gate

The equality property can never be a runtime diff against Claude Code; it is proven in three layers:

1. **Generation surface (pytest, repo B, CI-safe):** a new pin asserting the scaffold's `.mcp.json` writer emits **only** `GENERATED_ENTRY_KEYS` entries (`features/common/skills/welcome-ai-badger/scripts/mcp_tools.py:38` — the same authorship test `only_generated_entries` performs), and that every such key shape has a case in the P1 converter table (§1). Anything the writer can emit, the converter is pinned to consume — parity holds by construction for scaffold-managed files.
2. **Conversion surface (vitest, fork):** a fixture `.mcp.json` recorded from the live ai-badger file (5 entries, all `tools:["*"]`, one with `env`, one with bare `command` no `args`) converts to an `McpConfig` whose **key set equals the fixture's** and whose `command` arrays match `command + args`. Plus the precedence pin: a same-named entry in both project file and global settings arms the **project** shape.
3. **Runtime closure (live-only, §4 step 4):** `mcp-status` in a headless run names exactly the `.mcp.json` keys — the only place Claude-vs-pi equality is observable end to end, including the claude-side fact that `.mcp.json` is not trust-gated while pi's gate is (corrected semantics, correction 3).

### 3.2 Untrusted-fragile-case pin (MUST-1 — both directions, different lanes)

- **Gate unit pin (vitest):** with `ctx.isProjectTrusted()` stubbed `true` → project servers arm; stubbed `false` → global `mcp` only, zero project entries, no partial merge. This pins *the fork's* contract.
- **Precondition pin (pytest, repo B, CI-safe):** the scaffold writes **no** pi-trust-requiring resource into a project's `.pi/` — its project-side writes are `.pi/agents/` personas only (research F12; the resource list is `trust-manager.js:8-17`). This is what makes "minimal project arms headless" true *by construction* rather than by hope, and it goes red the day the scaffold starts writing a project `.pi/settings.json` — the moment the fragile case becomes the common case.
- **Fragile-case pin (live-only, §4 step 5):** a scratch scaffolded project given a `.pi/settings.json` (one key, e.g. `theme`) with no `~/.pi/agent/trust.json` and `defaultProjectTrust:"ask"` must arm **global-only** headless, with `mcp-status` naming the source/untrusted cause (MUST-2) — and must arm project servers again once the file is removed. Both directions of the flip are the pin; a test that only checks the minimal case silently validates the plan's wrong trust model.

### 3.3 `type:http`/`sse` → `remote` mapping (premortem Q4 / D1a condition (a))

- **vitest (converter):** `{type:"http",url}` → `{type:"remote",url}`; `{type:"sse",url}` → same; `type` without `url` and unknown `type` values → skip with logged warning, remaining entries arm. Fixture source: the real `rider` server in `/Users/arasz/RiderProjects/ai-raccoon/.mcp.json` (`{"type":"http","url":"http://127.0.0.1:64482/stream"}` — measured this session).
- **vitest (transport):** the fork already ships `StreamableHTTPClientTransport`/`SSEClientTransport` (`src/McpClient.ts:1-4,88-100`); the converter test only has to prove the *mapping* lands in the `type:"remote"` shape `McpClient.test.ts` already exercises — no transport work is new. If the owner rejects Q4 mapping, this contract test is replaced by its honesty counterpart: support.json says "local stdio only" and §3.1's equality claim is scoped to stdio servers (the premortem's risk 7 overclaim guard).
- **Live closure (§4 step 6):** `pi -p` in the ai-raccoon checkout arms `rider` as a remote server alongside its stdio set.

---

## 4. Live machine-cutover gate (P5; runs last, on the real machine, in merge order)

Preconditions: P1–P4 merged; gates green (repo B pytest, repo A `bun test`/`tsc`, fork vitest/`tsc`); every step's observation recorded in the task's verification notes.

1. **Snapshot before touching anything:** copy `~/.pi/agent/settings.json` aside and record its key list (measured today: `mcp` = 5 servers, `skills` = one ai-badger path, no `mcpDisabledTools`, `defaultProjectTrust:"ask"`, no `~/.pi/agent/trust.json`; user keys `theme`, `defaultProvider`, `lastChangelogVersion`, …). The gate's diff target.
2. **Ship-order proof:** with the new fork installed (old global entries still present), run `pi -p` + `mcp-status` in this repo — the 5 servers must still arm (via global fallback). Removing global entries before the project-reading fork exists is the failure order the plan's migration step 1 forbids.
3. **Migration execution:** run the scaffold in this repo. Observable: global `mcp` entries for the 5 declared names and the ai-badger skills path are gone; **every user-owned key byte-identical to the snapshot**; non-declared entries (if any) untouched (shape-aware removal, MUST-5).
4. **Minimal-project headless arming (the MUST-1 first direction):** headless `pi -p` + `mcp-status` in this repo arms **exactly** the `.mcp.json` five, each sourced `project:.mcp.json` — no trust bootstrap performed, none needed (correction 3). This is the AC's "same server set as Claude Code" observed end to end.
5. **Fragile-case flip (the MUST-1 second direction):** in a scratch scaffolded copy, add `.pi/settings.json` (`{"theme":"dark"}`), no trust.json → headless `mcp-status` shows global-only/`untrusted-project`; remove the file → project servers arm again. Optionally then run `/trust` once interactively and observe `~/.pi/agent/trust.json` gain the canonical path and the flip survive — documents Q1′'s escape hatch without making it a prerequisite.
6. **Cross-project isolation + remote mapping:** headless run in the ai-raccoon checkout arms exactly its declared set **including the `rider` remote** and **no** server declared by ai-badger alone; repeat for one more scaffolded project (job-search-ai-assistant). No session sees another project's servers.
7. **Skills discovery headless (H1 last mile):** run §2 Spike H1's two-sided probe in this repo and the negative-control scratch dir.
8. **Lifecycle live check:** interactive session in this repo → `/new` → `mcp-status` still lists all servers (the latent-bug fix verified in the real binary; duplicates check from §2's sub-spike).
9. **Idempotence:** run the scaffold a second time in this repo — zero changes to `~/.pi/agent/settings.json` (byte-diff empty).
10. **Version-gate live proof:** point `~/.pi/agent/extensions/pi-mcp-tools` at a pre-P1 build, run the scaffold again — global entries must be **left in place with a warning**, not removed (MUST-5). Restore the new build afterwards.
11. **Honesty surfaces readback:** support.json pi rows match §3's substring pins; ADR-0023 exists with the Q1′/Q2/Q3a/Q3b/Q4 outcomes; changelog names the behavior change for existing users.
12. **Final gates:** repo B pytest (full suite), repo A `bun test` + `bunx tsc --noEmit`, fork `npx vitest run` + `npx tsc --noEmit` — all green, with the fork's suite counted, not assumed (correction 1).

---

## 5. CI vs live-only proofs

**CI-safe (no real `$HOME`, no pi binary, no network — must stay green on any machine):**
all repo B pytest (fixtures under `tmp_path`/mocked `SETTINGS_PATH`, guarded by the conftest `REAL_HOME` machinery and the :832 real-home pin); all fork vitest (`ConfigLoader.test.ts` already mocks `os.homedir`); all repo A bun test; byte-identity/vendored-sync checks; the source-contract pins that regex real files at test time (`tests/test_pi_hook_arm_coverage_contract.py` is the house style: derive from source, never from docstrings); support.json honesty substrings; the pytest precondition pin of §3.2 (scaffold writes no trust-requiring resource).

**Live-only (require the real machine, real `~/.pi`, real pi 0.84.4 binary, and — for remotes — real network):** the §4 checklist in full; Spike H1's two-sided probe; Spike H2's duplicate-registration sub-spike; the `/trust` persistence observation; the `rider` remote actually connecting; migration execution on real global state. Rationale: pi's event ordering (`session_start` → `registerTool` refresh, `resources_discover` after it), trust resolution, and the extension loader are only truthfully observable in the real binary — pi 0.84.4 is taken as fixed (plan §7), so the live gate is a one-time cutover proof, not a recurring CI lane; everything that can be made machine-independent must be, so the live surface stays as small as this list.

---

## Contradictions register (carried into the reply)

- Plan/premortem/research say 46 vitest tests; measured 73 (correction 1).
- Plan M1 cites "live `.mcp.json` measured" as if a repo artifact; it is gitignored and absent from worktrees (correction 2) — fixtures, not checkouts.
- Plan Q1/risk 3/migration step 4 ("headless arms nothing until `/trust`") vs premortem MUST-1's measured short-circuit — strategy follows the premortem and pins both trust directions (correction 3).
- Plan P3's ":76–:130" pin locations vs the file's actual G1/G2 block (correction 5).
