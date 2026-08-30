# QA review — pi stack parity plan rev 2: test surface (honesty, achievability, gaps)

**Date:** 2026-08-30 · **Lane:** MoE plan-review 2/3 (QA) · **Target:** `2026-08-30-pi-stack-mcp-skills-parity-plan.md` (rev 2) + `…test-strategy.md` + `…premortem.md`
**Fresh reviewer;** authoring lanes were architect/test-engineer/code-reviewer. Scope: the plan's TEST SURFACE only — production-code security/layering/performance out of scope (`code-reviewer`'s artifact). P2 (repo A bun) and P4 (ADR) were audited only where a test claim touches them.

**Worktree audited:** `.ai-badger/worktrees/aib-pi-stack-mcp-skills-parity/` ("repo B"), `~/RiderProjects/pi-mcp-tools-fork/` ("fork"), pi dist `~/.bun/install/global/node_modules/@earendil-works/pi-coding-agent/dist/`.

---

## Verdict table

| id | file:line | rule | severity | the mutation | run? | what it means |
|----|-----------|------|----------|--------------|------|---------------|
| QA-1 | plan §2 P5 + test-strategy §4 steps 2/4/5/6/8 | T0-01/T0-08 | **blocker** | Ran the gate's own observation verb (`pi -p "/mcp-status"`) against pi dist source: extension commands **throw** when queued (`agent-session.js:1018-1020`); no `-p` path named | applied+reverted (source probe; live run not possible pre-P1) | 5 of 12 P5 steps have **no verified headless observation channel** for `mcp-status` source labels — a fresh session either blocks or fudges the observation; a fudged run silently passes against the wrong model (the rev-1 trust-story failure mode, exactly) |
| QA-2 | test-strategy §1 P3 row + plan §2 P2 ("the same guarantee `test_framework_copies.py` enforces") | T0-05 | **major** | Grepped `test_framework_copies.py` for `adapter|vendored|byte|pi-mcp-tools` → **0 hits**; grepped all of `tests/*.py` for the `features/pi/adjustments/adapter ≡ extensions/ai-badger` pair → **no pin exists** | applied+reverted (grep, deterministic) | The claimed existing byte-identity gate **does not exist** — `test_framework_copies.py` is the framework-tree cleanup module (#109, its docstring lines 1–4). P2's edit to `extensions/ai-badger/index.ts` can ship an unsynced vendored hooks adapter in repo B and **no planned test goes red** |
| QA-3 | test-strategy §1 P1 lifecycle row | T0-06 | **major** | Red the planned `lifecycle.test.ts` basis: on HEAD the extension body's first statement calls `ConfigLoader.loadFromSettingsJson()` (`fork src/index.ts:32`) and `registry.initialize()` spawns real servers (`:82`) | unverified (static reasoning) for the run itself; file:line claims **read-verified** | Without the hoisted `os.homedir` mock — which the strategy binds **only** to `ConfigLoader.test.ts` — the red run reads the developer's **real** `~/.pi/agent/settings.json` and connects the real 5 servers (network, npx spawns). The plan's own red-proof step would sample the environment |
| QA-4 | plan §3 + test-strategy §1 P3 honesty row | T0-03 | **major** | Tried to express "headless-safe without the trust sentence" as a substring assertion — it is a **conditional**, not a literal; also `features/common/support.json` carries **four** `mcpServers` rows (:55 claude, :121 hermes, :204 copilot, :272 pi) | applied+reverted (spec-comprehension probe against the real file) | As written the lying-phrase list mixes checkable literals with untestable conditionals; unscoped, the test false-fails on other agents' rows. The red-basis is real (pi row :272-277 says "partial"/"settings.json mcp key") — the assertion shape needs one rewrite pass |
| QA-5 | test-strategy §1 P1 ConfigLoader row | T0-02 | major | Inserted a per-cwd config cache into the planned implementation shape — it passes every pinned case (cwd re-derivation on session change) while `.mcp.json` **content** edited between `/new` and `/resume` at the same cwd goes stale | unverified (static reasoning) | The plan pins cwd re-derivation but never pins **file re-reading**; "config re-derived from ctx.cwd" is ambiguous between the two |
| QA-6 | plan §2 P1 files (`saveDisabledTools` → atomic) vs §2 P1 test list | T0-02 | major | Searched the planned test list for an atomicity pin of the temp+replace rewrite → none; only existing pin is warn-on-missing (`fork tests/ConfigLoader.test.ts:117-127`) | applied+reverted (grep) | The drive-by fix the premortem motivated (race vs scaffold's `os.replace`, premortem D3-d) ships **untested** — a regression back to bare `writeFileSync` (`ConfigLoader.ts:62`) passes the planned gate |
| QA-7 | plan §2 P3 append list | T0-07 | minor | — | unverified (static reasoning) | Fate of the surviving merge pins unstated: `test_pi_settings_merge_skills_path_*` / `merge_preserves_unknown_keys` (`tests/test_pi_adjustments.py:489-533`) keep pinning merge behavior the adjustments will no longer perform — stale pins next to flipped pins is a diagnosis-cost trap |
| QA-8 | plan §2 P5 steps 2/8/10 | T0-01 | minor | — | unverified (static reasoning) | No build/install command named for the fork ("point `~/.pi/agent/extensions/pi-mcp-tools` at a pre-P1 build"), no restore step if the gate aborts at step 10 (machine left on pre-P1 build), no scratch-project creation command (step 5) |
| QA-9 | test-strategy §2 H1 probe | T0-04 | minor | — | unverified (static reasoning) | "Quote the exact first heading" can be produced by a capable model that never read the file (oracle partly model-supplied); the negative control catches leakage, not hallucination |
| QA-10 | plan §2 P3 / M5 | T0-07 | minor | — | unverified (static reasoning) | `result["applied"]` semantics for removal-nothing-to-remove (fresh machine) unpinned; `mcp_declined`-minus-removal is in M5's prose but absent from the P3 append list |

**Score: 1 blocker, 5 major, 4 minor.** The plan's evidence discipline is unusually good — every line-number citation I checked was accurate (a first for a plan of this size) — but the P5 gate's observation channel (QA-1) and the phantom byte-identity gate (QA-2) must be fixed before implementation lanes start.

---

## Q1 — Red-proof obligations: is each claimed-red state actually red on HEAD?

**Flip pins (merge → removal): VERIFIED RED, applied and reverted.** The flip targets exist and behave as described: `test_adjust_skills_install_true_merges_skills_path` (`tests/test_pi_adjustments.py:537`), `test_adjust_mcp_install_true_merges_into_settings` (:566), proposal pin `test_adjust_mcp_proposes_servers` (:92), real-home guard `test_pi_settings_write_does_not_touch_real_home` (:832) — the test-strategy's correction-5 line numbers are exact. I then ran the flip itself: a throwaway probe (`tests/test_qa_tmp_flip_probe.py`, deleted after) asserting the **removal** semantics the flipped pins will assert, against HEAD:

- `test_mcp_removal_semantics` — **FAILED** ("HEAD still merges")
- `test_skills_removal_semantics` — **FAILED** ("HEAD still merges")

3 existing merge/proposal pins passed in the same session (`pytest -k "install_true_merges or proposes_servers"` → 3 passed). So the flip goes red on HEAD **for the right reason**, and the G1/G2 pins are green as merge-pins until flipped. This red-proof is real.

**Lifecycle test ("red because config loads at extension-init"): read-verified basis, unverified run — and one hazard (QA-3).** The structural claim is accurate: `mcpConfig = ConfigLoader.loadFromSettingsJson()` is the first statement of the extension body (`fork src/index.ts:32`; strategy says :33 — off by one, same statement), `session_shutdown` → `clearModuleState()` at :153-157 with nothing rebuilding (init happened once at :82), and no existing fork test imports `src/index.js` — the lifecycle file would be the first. Red is therefore structurally certain. But two achievability facts the plan omits:

1. **The homedir mock must be hoisted before `import "../src/index.js"`**, exactly as `tests/ConfigLoader.test.ts:14-19` does for ConfigLoader. On HEAD, driving the default export without it reads the real `~/.pi/agent/settings.json` and `registry.initialize()` (:82) connects the real 5 servers — real processes, real network, in the red run. The strategy's "no test touches the real `~/.pi`" claim (§5 CI-safe column) is currently honored by idiom, not by the plan text, for this file.
2. **The `ExtensionAPI` mock must be built from scratch** — no existing test drives the default export — and the SDK must be mocked per `tests/McpClient.test.ts:12-40` (which already mocks stdio/SSE/streamable-http transports) so the red run doesn't spawn servers even with a fake home. Neither requirement appears in the P1 test row. Cheap to fix, expensive to discover mid-lane.

**Converter table + adapter poison-pattern: red-basis verified by read.** `McpToolAdapter.ts:24` runs `new RegExp(pattern)` with no try/catch; the throw escapes into the per-server catch (`index.ts:107-114` → `failedServers.push`, notify only under `--mcp-debug` :135-141). Strategy correction 4 is accurate; the appended test is red on HEAD (`convertToPiTool(["*"])` throws). Converter-table red ("module does not exist") is trivially real.

## Q2 — The live machine-cutover gate (P5, 12 steps)

**Executable as written by a fresh session:** steps 1 (snapshot), 3 (scaffold run — though the scaffold command is never named), 9 (repeat scaffold, byte-diff), 11 (file readback), 12 (three suites). Step 7 is executable but see QA-9.

**Ambiguous / missing a command:** steps 2, 8, 10 all presuppose "the new fork installed" / "point `~/.pi/agent/extensions/pi-mcp-tools` at a pre-P1 build" — **no build or install command exists anywhere in the plan** (npm run build? cp dist where? git checkout of a tag?). Step 5's "scratch scaffolded copy" has no creation command. Step 10 has no restore step if the gate aborts after the swap — the machine is left on a pre-P1 build, which would make a *later* re-run of step 4 silently fail (QA-8). Each is a one-line fix; none is optional for a gate whose contract is "no step assumed."

**Could silently pass against the wrong model (QA-1, blocker):** the gate's steps 2/4/5/6/8 all read per-server **source labels** from `/mcp-status` headless. I probed pi dist for how that observation happens: extension commands **cannot be queued** — `steer`/`followUp` throw on any prompt starting with `/` that names an extension command (`dist/core/agent-session.js:1018-1020`), and there is no documented `-p` path for invoking `registerCommand` handlers. On HEAD the session_start surface is `ctx.ui.setStatus` (a TUI status line — invisible headless) with `notify` only under `--mcp-debug` (`index.ts:135-141`). Unless M3 is amended to put the source labels on a headless-visible surface (unconditional `notify` — and a verified probe that notify reaches stdout in `-p` mode — or registering `mcp_status` as a **tool**, which `-p` can call), a fresh session executing step 4 has nothing to observe. The failure mode is precisely the rev-1 trust-story one: the executor, unable to observe, "records" the expected string; the 5 servers arm anyway (via global fallback if step 3 half-failed, or via project path), and steps 2 and 4 pass identically under the **old** fork. The gate must name its observation channel and prove it with one live probe **before** P5, or five steps are decoration.

Step 2 additionally deserves a logic note: "5 servers still arm via global fallback" is true under the old fork too — it proves ship order only in combination with step 4's source labels. Fine once the channel exists; worth one sentence in the plan.

## Q3 — Coverage gaps: user-visible behavior of the new fork path with no pinned test

- **`.mcp.json` re-read between sessions at the same cwd (QA-5, major).** The lifecycle pins cover cwd *change*; nothing pins content *change*. One added case: arm session 1, rewrite `.mcp.json` (drop a server), `session_shutdown` + `session_start` at the same cwd → dropped server's tools gone.
- **`saveDisabledTools` atomicity (QA-6, major).** The plan changes the implementation (M6, temp+replace) and plans zero tests for it. Mirror `test_pi_settings_write_is_atomic_on_failure` (`tests/test_pi_adjustments.py:481-502`) in vitest.
- **Unparseable project `.mcp.json` at loader level (minor).** Converter case (h) pins unparseable→`null`; the ConfigLoader append pins "global-only when no project file" — absent ≠ unparseable. One line: `loadProjectMcpJson` returning null (throw or parse error) → global-only merge, never partial.
- **Partial-merge prevention:** covered (ConfigLoader append, both-directions trust pins in §3.2). **Concurrent scaffold + running pi:** accepted as a live-only residual via the atomic-write fix; no test can pin the race in CI — acceptable, but say so in the plan rather than leaving it implicit. **Duplicate `registerTool` on `/new`:** correctly scoped live-only (pi behavior unpinnable in vitest).
- **Fresh-machine removal no-op + `mcp_declined` (QA-10):** one pin each, both cheap, both in M5's prose but not the append list.

## Q4 — Are the support.json honesty substring pins testable as written?

Partly. The positive-substring half is testable and well-anchored: house style exists (`tests/test_pi_hook_arm_coverage_contract.py:38-46` derives assertions from real source at test time), and the pi row's current text (`features/common/support.json:272-277`: supported `"partial"`, mechanism "settings.json mcp key") makes the red-basis real. Three corrections needed (QA-4):

1. **Conditionals are not substrings.** "headless-safe without the trust sentence" and "unqualified 'same servers as Claude Code'" cannot be expressed as `substring in row` / `substring not in row` — they need `if phrase in row: assert trust_sentence in row` logic. The plan should split the lying list into (a) forbidden literals — `"the scaffold merges into settings.json"`, `"trust-gated"` on the skills row — which are pure negative-substring pins, and (b) conditional co-occurrence rules, which are one `if` each.
2. **Scope per row.** Four `mcpServers` rows exist; a whole-file grep false-fails on claude's (:55) or hermes' (:121) legitimate text. Pin `agents["pi"]["capabilities"]["mcpServers"]["mechanism"]` specifically.
3. **Say the real gate is the positive list.** Negative literals can never be exhaustive against paraphrase drift; the mandatory trust sentence and `resources_discover`+ungated substrings are what actually enforce honesty. One sentence in §3 prevents someone implementing only the negative half.

## Q5 — Does anything in the plan's test list write the developer's real `~/.pi` or a real checkout file?

One hole, otherwise clean:

- **QA-3 (major):** the planned red run of `tests/lifecycle.test.ts` against HEAD, executed without the hoisted `os.homedir` mock, reads the real `~/.pi/agent/settings.json` (`index.ts:32`) and spawns the real 5 servers (`index.ts:82`). The idiom exists (`ConfigLoader.test.ts:14-19`) and the strategy even states the invariant ("no test touches the real `~/.pi`") — but the P1 lifecycle row never binds it. Add to the row: "hoisted `os.homedir` mock + SDK mocks per `McpClient.test.ts:12-40`, before importing `../src/index.js`."
- Verified safe: all pytest G1/G2 fixtures monkeypatch `SETTINGS_PATH` (`tests/test_pi_adjustments.py:57-71`) under the conftest `REAL_HOME` machinery, with the :832 leak-guard — and the plan correctly extends that guard to the removal path. The `.mcp.json` gitignore rule (`.gitignore:36-37`) is honored: every planned fixture builds its own project dir; the converter fixture is a recorded copy, not a checkout read. P5's real-`~/.pi` mutation is live-only by design and explicitly gated — with the QA-8 restore-point caveat.

---

## Verified vs hypothesis (this session)

**Verified (ran or read source):** flip-target pins exist and pass as merge-pins (3 passed); removal-semantics probe red on HEAD (2 failed, probe reverted, `tests/` and `.venv` left clean); `test_framework_copies.py` contains no adapter/byte/vendored check (grep + docstring read); no repo-B test pins the `features/pi/adjustments/adapter ≡ extensions/ai-badger` pair; fork `index.ts:32,82,108,114,153-157` and `McpToolAdapter.ts:24` match the strategy's claims; `ConfigLoader.ts:62` bare `writeFileSync`; `ConfigLoader.test.ts:14-19` hoisted homedir mock; `McpClient.test.ts:12-40` SDK transport mocks; pi dist trust list + short-circuit (`trust-manager.js:8-17`, `main.js:571-582` — re-confirmed the premortem's MUST-1 reading); extension-command throw in steer/followUp (`agent-session.js:1018-1020`); support.json four mcpServers rows (:55/:121/:204/:272); `.gitignore:36-37`.

**Hypothesis (labeled, not run):** the lifecycle test's red *run* (file doesn't exist yet — structural basis verified only); all live P5 observations (pre-P1, by definition); H1's machine-level probe; whether `notify` reaches stdout in `-p` mode (the QA-1 fix must probe this first).

## MUST / SHOULD / NIT

- **MUST-1 (QA-1):** before P5, name and live-probe the headless observation channel for per-server source labels (unconditional notify, or an `mcp_status` tool). Without it, steps 2/4/5/6/8 are unexecutable as written and fudge-prone.
- **MUST-2 (QA-2):** delete the "already enforced by `test_framework_copies.py`" claim from both documents; add a real byte-identity pin for `features/pi/adjustments/adapter/* ≡ extensions/ai-badger/*` (repo B pytest, trivial filecmp) to P2's AC — P2 edits the canonical adapter and nothing planned today guards the vendored copy.
- **MUST-3 (QA-3):** bind the hoisted `os.homedir` mock + SDK transport mocks to the P1 lifecycle test row explicitly; the red-proof run must not touch the real home.
- **MUST-4 (QA-4):** re-spec the honesty test as (a) mandatory positive substrings on the pi row only, (b) closed negative-literal list, (c) two conditional co-occurrence rules; drop the pretense that conditionals are substring checks.
- **SHOULD:** pin `.mcp.json` content re-read between sessions (QA-5); pin `saveDisabledTools` atomicity (QA-6); state the fate of the surviving merge pins in P3 (QA-7); add fork build/install/restore commands + a scratch-project command to P5 (QA-8); make the H1 probe model-proof (QA-9); pin removal-no-op semantics and `mcp_declined` (QA-10).
- **NIT:** loader-level unparseable→global-only pin; one sentence in step 2 acknowledging it passes under both forks.

The plan's red-proof discipline is real where it matters most (the flip), the measured-corrections loop (premortem → strategy → plan) left no line-number drift I could find — fix the gate's eyes (QA-1) and the phantom guard (QA-2) before lanes start.
