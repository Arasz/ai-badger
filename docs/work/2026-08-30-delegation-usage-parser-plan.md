# Plan — aib-delegation-usage-parser-migration-note (architect draft)

Recovered from delegation d-1's subagent log (the run was aborted at the TUI after the
child had settled its turn; the full text only exists in ~/.pi/agent/subagent-logs/d-1.jsonl).
Head of the plan was streamed before the visible tail — this is the architect's complete
final message, verbatim.

---

All research is done — every unknown is resolved with evidence. Here is the plan.

---

# Implementation Plan — aib-delegation-usage-parser-migration-note

**Source:** follow-up ledger items 1–2 of `/Users/arasz/RiderProjects/pi-badger-integration/docs/plans/2026-interactive-subagent-delegation.md` §10 (read; both items are in this repo's scope — the pi-badger-integration repo itself is **not touched**).
**Effort:** low — single planner, no MoE. **Version:** expected `0.148.0` (minor — new parser feature); assigned at dispatch, not picked by lanes.
**Working tree:** this worktree, branch `task/aib-delegation-usage-parser-migration-note`. Lanes commit work packages; the planner session does not commit.

## 0. Verified ground (evidence, cited)

| Fact | Evidence |
|---|---|
| Consumer contract: `source["delegation_usage"](delegation_id)`; `None` → `"Refusing to record a fabricated number"`; keys read: `totalTokens`, `model`, `apiCalls` | `features/common/skills/task/scripts/task_tracker.py` ~L460–489 |
| Registration seam takes `delegation_usage=` param | `features/common/skills/task/scripts/tracker_lib.py` `register_session_source` ~L588 |
| Current pi stub: `delegation_usage=lambda delegation_id: None` (L53); module is scaffold-copied verbatim by `adjust_task.py` (`SESSION_SOURCE_SRC → .ai-badger/skills/task/scripts/pi_session_source.py`, L13–14) | `features/pi/adjustments/pi_session_source.py`; `features/pi/adjustments/adjust_task.py` |
| Hermes reference record: `{"totalTokens": input+output sum, "model": first non-null, "apiCalls": summed, "at": completion-ts}` or None (missing / not-completed / malformed / total==0) | `features/hermes/adjustments/hermes_session_source.py` `hermes_delegation_usage` ~L211–260 |
| Log format (R4 contract, do not change): `~/.pi/agent/subagent-logs/<runId>.jsonl`; line 1 `{"type":"run",…}` (runId, agent, persona, task, argv, cwd, pid?, startedAt, sessionId?); child stdout verbatim incl. `{"type":"message_end","message":{role:"assistant",content:[…],usage:{input,output,cacheRead,cacheWrite,cost.total,totalTokens}}}`; `{"type":"stderr",…}`; settle writes `"type":"exit"` (`exitCode`,`endedAt`,+`signal` on kill) **or** `"type":"spawnError"`; **TUI-side aborts (`settleAborted`) write NO exit line — the log just ends at `{"type":"agent_settled"}` (proven by d-1.jsonl)**; blank trailing lines occur (d-5); one `{"type":"tee-elided","droppedBytes":N}` marker when byte-capped (middle elided, header+tail survive) | `pi-badger-integration/extensions/subagent/delegation-runner.ts` L440–510 (`writeHeader`, `settleExit`), `delegation-core.ts` L1–120 + L499–519, `index.ts` L76 (`DEFAULT_LOG_DIR`) |
| runId format `d-<n>` (regex `/^d-(\d+)$/`, prefix `d-`) | `delegation-core.ts` L388–414 |
| **Unknown #1 resolved — model field EXISTS:** pi's `AssistantMessage` carries `api`, `provider: ProviderId`, `model: string`, `usage`; `message_end` contains the final authoritative message. Integration test fixtures omit it (their interfaces are deliberately loose) — so the parser must treat `model` as optional | `/Users/arasz/.bun/install/global/node_modules/@earendil-works/pi-ai/dist/types.d.ts` (`export interface AssistantMessage`); `pi-coding-agent/docs/json.md` (installed pi 0.84.4: `message_end`; `AgentMessage`) |
| **Unknown #2 resolved — test patterns:** `load_script` fixture loads by repo-relative path; module-level `Path.home()` constants are patched on the module object after load (idiom: `pi_sessions_dir` fixture + `_REAL_USAGE_MESSAGE` field-for-field real fixture; no test may touch the real home) | `tests/conftest.py` L508–527; `tests/test_pi_adjustments.py` L493–560 |
| **Unknown #3 resolved — sync gate EXISTS:** `gates/scaffold_freshness_guard.py` re-runs the scaffolder on a throwaway copy and fails when `features/**` edits were not followed by a scaffold regen of `.ai-badger/` (runs as the `scaffold` lane in `.lefthook/pre-push/verify.sh`, `$LANES` L61). Additionally the generated-file guard hook refuses hand edits to `.ai-badger/` copies | `gates/scaffold_freshness_guard.py` docstring; `tests/test_generated_file_guard.py`; `.lefthook/pre-push/verify.sh` |
| **Unknown #4 resolved — insertion points:** SKILL.md Phase 3 step 2 (L240–244, the `--delegation` paragraph) + Gotchas section (L333); `lane-dispatch-brief.md` post-template orchestrator guidance; `delegator.md` "Ledger" section | reads of the three files (all under `features/` — see P2 note on generated copies) |
| `totalTokens` semantics: hermes sums **input+output only** (cache excluded); pi's own `usage.totalTokens` includes cache (fixture: 449+23+701+0 = 1173). The tracker stores it as "what dispatches said about themselves" (`compute_usage`, `tracker_lib.py` L630–674) — cross-source consistency rules | `hermes_session_source.py` L247; `tests/test_pi_adjustments.py` `_REAL_USAGE_MESSAGE` |
| **Unknown #5 — settled-run policy: recommendation ACCEPTED** (see Ruling below) | — |

**Ruling (item 5 — mechanism corrected per plan review M1):** a record is produced iff the log shows a **settled marker — an `exit` line (with or without `signal`) OR an `agent_settled` line — and summed total > 0.** Rationale: `settleAborted` (the TUI-abort path, delegation-runner.ts L288/L494) writes no `exit` line — it sets `settled=true`, which also suppresses the close-event exit write — so requiring `exit` refused exactly the d-1-style aborted run that motivated cost recording. `spawnError` or neither marker → `None` (child never ran / genuinely lost). Tokens from aborted runs are real spend; the tracker's job is cost accounting, not success verification — no consumer misbehaves (`compute_usage` keeps `subagentTokens` advisory, excluded from `grandTotal`). Deviates from hermes's not-completed→None: hermes rows without completion carry no token data, pi logs always do. `at` = `exit.endedAt`, else last assistant `message_end.timestamp` (epoch ms — format note in docstring), else header `startedAt`. Written into the parser docstring.

**Scope statement:** no changes to `task_tracker.py` or `tracker_lib.py` — the consumer side is already source-agnostic and tested (`tests/test_task_tracker_hermes.py` covers the CLI flow). No changes to any pi-badger-integration file; the JSONL format is consumed read-only as a frozen contract.

---

## §Packages

### P1 — Parser: `pi_session_source.delegation_usage` (ledger item 2)

**Files owned:**
- `features/pi/adjustments/pi_session_source.py` — add `SUBAGENT_LOGS_DIR = Path.home() / ".pi" / "agent" / "subagent-logs"` (module constant, patchable like `SESSIONS_DIR`), implement `_delegation_usage(delegation_id) -> dict | None`, wire `delegation_usage=_delegation_usage` into `register()` (replacing the lambda), extend the module docstring with the R4 contract reference and the settled-run ruling.
- `features/pi/adjustments/adjust_task.py` — one-paragraph docstring fix (S3): its "Token tracking is not available for pi sessions — the tracker will report zeroes" claim is already false (G3 checkpoint reading) and more false after P1.
- `tests/test_pi_adjustments.py` — new `pi_subagent_logs_dir` fixture (mirror `pi_sessions_dir`: patch the module constant after `load_script`, never touch the real home) + the test list in §Test list.
- Regenerated `.ai-badger/skills/task/scripts/pi_session_source.py` is verified by local regen but **not committed by this lane** — P3 owns all committed regen (S1/S6).

**Subpackages:**
- **P1a — parser core (TDD):** failing tests first (§Test list T1–T13), then `_delegation_usage`.
- **P1b — wiring:** register() wiring + T11–T12 (wired end-to-end through `register` + `FakeTrackerLib`, mirroring `test_pi_session_source_checkpoint_uses_session_env_and_own_cwd`).

**Parser contract (spec, not code):**
1. Reject any `delegation_id` that is not a bare filename component (`""`, contains `/` or `\`, or is `.`/`..`) → `None` — path-traversal guard; real ids are `d-<n>`.
2. Read `SUBAGENT_LOGS_DIR / f"{delegation_id}.jsonl"`; missing file / `OSError` → `None`. Missing dir → `None` (dir legitimately absent on machines without the extension — the pre-release state of every machine today).
3. Parse line-by-line, tolerantly: malformed JSON lines are skipped individually (same tolerance as `_sum_usage`); `tee-elided` markers parse fine and are ignored — usage lines legitimately absent from an elided middle simply don't sum.
4. Accumulate over `type == "message_end"` with `message.role == "assistant"` and a dict `usage`: `total += usage.input + usage.output` (hermes parity — **not** pi's `usage.totalTokens`, which includes cache; documented in the docstring); `apiCalls` += 1 per assistant `message_end` (matches delegation-core's "turns"); `model` = first non-empty string `message.model` (pi's `AssistantMessage.model`), else `None`.
5. Settled policy per the Ruling (M1-corrected): settled marker = `exit` line (any exitCode, with/without `signal`) **or** `agent_settled` line; `spawnError` or neither marker → `None`; `total == 0` → `None`.
6. Return `{"totalTokens": total, "model": model, "apiCalls": apiCalls, "at": at}` — all four keys always present (the CLI reads the first three; `at` per the Ruling's fallback chain, kept for hermes shape parity).

**Acceptance criteria (each stranger-checkable):**

| # | AC | Proving command |
|---|---|---|
| AC1 | T1–T13 green, T1 witnessed RED first (RED output pasted in the lane report) | `PY -m pytest tests/test_pi_adjustments.py -q` |
| AC2 | Full suite stays green | `PY -m pytest -q` |
| AC3 | Parser module pylint-clean (tests are excluded from the repo's pylint gate by design) | `PY -m pylint features/pi/adjustments/pi_session_source.py` |
| AC4 | index.json still fresh (content edits don't stale it — no content hashes — but the gate must run) | `PY tooling/index_build.py --check` |
| AC5 | The scaffolded copy is regenerated, not hand-edited (guard refuses hand edits); P3 re-verifies tree-wide | regen via scaffolder in the lane's worktree; verified tree-wide by AC-I3 |

### P2 — Task-skill migration note (ledger item 1)

**Files owned (canonical `features/` copies — the `.ai-badger/` twins are generated and regenerated by the scaffolder, never hand-edited):**
- `features/common/skills/task/SKILL.md`
- `features/common/skills/task/references/lane-dispatch-brief.md`
- `features/common/personas/delegator.md`
- regenerated `.ai-badger/` copies (scaffolder output, committed)

**Subpackages:**
- **P2a — SKILL.md (M2 budget strategy — read first):** the task SKILL.md body sits at 19,993 chars ≈ 4,998.2 of the 5,000-token `skills_lint` cap — **7 characters of headroom**. Appending is impossible; the lane **rewrites the existing Phase 3 step 2 `--delegation` paragraph net-compact** (replace prose, don't add), names the receipt default, the `delegation-result` followUp with `details.usage` (input+output), `background:false`, and `--delegation <id>` in as few chars as possible, and runs `gates/skills_lint.py` after every edit. Detail rides the uncapped files (P2b). (ii) Gotchas — one short bullet: an interactive pi delegation returns a receipt, not the answer; the answer lands as a followUp — seam review happens as followUps land; the receipt id is what `--delegation` takes.
- **P2b — brief + persona + regen:** (iii) `lane-dispatch-brief.md` — short orchestrator-side note after the template: when dispatching from an interactive pi session, lanes complete as `delegation-result` followUps; record each lane's tokens from `details.usage` (input+output) or `--delegation <id>`; the receipt is not the lane's report. (iv) `delegator.md` Ledger section — each dispatch row also records the token count under pi (from the followUp's `details.usage` or `task_tracker subagent --delegation`), **input+output with cache excluded for cross-source parity (S5)**, so the ledger doubles as the cost audit. (v) regen is verified locally, committed by P3 only (S1).

**Acceptance criteria:**

| # | AC | Proving command |
|---|---|---|
| AC6 | SKILL.md names the receipt default, the `delegation-result` followUp, `details.usage` (input+output), `background:false` (spaced or not), and `--delegation <id>` in Phase 3 — **without breaching the skills_lint cap** | `grep -c "delegation-result" features/common/skills/task/SKILL.md` ≥ 1 and `grep -cE "background: ?false" features/common/skills/task/SKILL.md` ≥ 1 and `PY gates/skills_lint.py` green |
| AC7 | Gotchas carries the receipt-vs-answer bullet | `grep -n "receipt" features/common/skills/task/SKILL.md` hits the Gotchas section |
| AC8 | Brief and persona each carry the token-recording note | `grep -c "details.usage" features/common/skills/task/references/lane-dispatch-brief.md features/common/personas/delegator.md` — each ≥ 1 |
| AC9 | No doc names the JSONL field names as mutable or instructs touching pi-badger-integration | `grep -rn "subagent-logs" features/common/` hits only read-side references |
| AC10 | Docs gates pass | `PY gates/docs_guard.py && PY gates/skills_lint.py` (also run by the `docs` lane) |

### P3 — Integration (last package, mandatory)

**Files owned:** `VERSION`, `docs/changelog/0.148.1-<slug>.md` (**0.148.1 — main took 0.148.0 via #454 while this task was in flight**), regenerated `.ai-badger/` tree post-merge (S1: P3 owns ALL committed regen; lane-local regens are verification only), task tracker records.

**Subpackages:** P3a version+changelog (invariant: version-changelog-required); P3b gate roll-up + cross-consistency check.

**Acceptance criteria:**

| # | AC | Proving command |
|---|---|---|
| AC-I1 | VERSION bumped, changelog entry exists describing both ledger items | `cat VERSION` = 0.148.1; `ls docs/changelog/0.148.1-*.md` |
| AC-I2 | Parser and docs agree on the same numbers: the note's "input + output" matches the parser's `totalTokens` sum, and the id in the note is the receipt id the parser resolves | reading check: `grep -nE "input \+?output" features/common/skills/task/SKILL.md` + `grep -nE 'usage(\.get|\[)\"input\"' features/pi/adjustments/pi_session_source.py` — both present |
| AC-I3 | Scaffold freshness holds on the merged tree (P3 runs the one authoritative regen + commit) | `PY gates/scaffold_freshness_guard.py` |
| AC-I4 | Full local pre-push lane set green (CI-only lanes via CI) | `bash .lefthook/pre-push/verify.sh pre-push` (or `verify.sh all` minus CI-only lanes) |
| AC-I5 | Full pytest suite green from a clean state | `PY -m pytest -q` |

**Python resolver (S2, applies to every `PY` above):** worktrees carry no `.venv`; use the repo's resolver semantics — `$AIB_PYTHON` if set, else the **main checkout's** `.venv/bin/python3` (`/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3`), exactly what `verify.sh`'s `_resolve_python` does. Never bare `python3`.

---

## §Parallelism

| Lane | Files | Relation |
|---|---|---|
| **P1** (parser) | `features/pi/adjustments/pi_session_source.py`, `features/pi/adjustments/adjust_task.py` (docstring only), `tests/test_pi_adjustments.py` | **disjoint from P2 → parallel** |
| **P2** (docs) | `features/common/skills/task/SKILL.md`, `features/common/skills/task/references/lane-dispatch-brief.md`, `features/common/personas/delegator.md` | **disjoint from P1 → parallel** |
| **P3** (integration) | `VERSION`, changelog, regen | **serial, after P1 ∧ P2** |

- **Shared mutable state:** lanes regen **locally to verify** (idempotent, deterministic from `features/`) but commit no regenerated files; **P3 owns the one committed regen** and any `manifest.json`/`index.json` resolution (S1) — two lane-committed regen snapshots would conflict there. Only P3 owns `VERSION`/changelog — an unassigned version guarantees a collision (lane-dispatch-brief rule).
- **Concurrent session lane `aib-pi-stack-mcp-skills-parity`** — assumed MCP-parity files (`features/pi/adjustments/adjust_mcp.py`, pi MCP test files, `.ai-badger/mcp-tools.json`, `skills/mcp-index`). Named boundaries: **P1 owns `tests/test_pi_adjustments.py`** — if that lane's scope includes pi adjustment tests, serialise the two lanes on that file. Neither lane touches `adjust_mcp.py`/`pi_settings.py`.
- **Model lanes** (delegator's table): P1 → sonnet (spec exists: hermes reference + frozen contract); P2 → sonnet (wording judgment, no invention); P3 → sonnet (mechanical gates + roll-up). No lane dispatches sub-agents (two levels max, and nothing here needs depth 2).

## §Test list (failing-first order, P1a)

Fixture: `pi_subagent_logs_dir` (patch `SUBAGENT_LOGS_DIR` → `tmp_path/.pi/agent/subagent-logs`). Fixture builder writes JSONL runs from the R4 contract shapes; assistant `message_end` fixture carries pi's real field set (`model`, nested `cost.total`, `usage`) per the pi-ai type.

| # | Test (targets → mutation that proves it real) |
|---|---|
| T1 | Happy path: run header + 2 assistant `message_end` (usage) + `exit` → `{"totalTokens": i₁+o₁+i₂+o₂, "model": first model, "apiCalls": 2, "at": endedAt}` — pins the whole record shape; kills a stub that returns None/empty |
| T2 | No `exit` **and** no `agent_settled` line (header + events only) → `None` (unsettled) — kills a parser that records mid-run (M1 respec) |
| T3 | `spawnError` line → `None` — kills "any file counts" |
| T4 | `exit` **with** `signal`, usage > 0 → recorded — pins the aborted-spent ruling; kills a completed-only filter |
| T5 | No usage events, `exit` present → `total == 0 → None` — kills fabricated zeros; also covers the all-elided log |
| T6 | Malformed line between good lines → skipped, rest summed — kills abort-on-malformed |
| T7 | `tee-elided` marker present → parsed and ignored; tail usage still counted — kills abort-on-unknown-type |
| T8 | `delegation_id = "../d-1"` / `".."` / `""` → `None` and the traversal target's file is never opened (sentinel file at the target with usage) — kills a path join without a guard |
| T9 | Non-assistant `message_end` (user/tool) → not counted — kills role-blind summing |
| T10 | Assistant `message_end` without `model` → record returned with `model: None` — kills hard model dependency |
| T11 | Missing dir / missing file → `None` — kills raise-on-missing (pre-release machines have no dir) |
| T12 | Wired: `register(FakeTrackerLib)` → `calls[0].delegation_usage("d-1")` resolves through the patched dir end-to-end — kills a wiring that leaves the lambda stub |
| T13 | **The Ruling's witness (M1):** field-for-field fixture of the real d-1 log shape — header, message_end with usage, `agent_settled`, **no `exit` line**, trailing blank line → recorded with `at` = last assistant `message_end.timestamp` — kills the exit-line-only settled policy that would refuse real aborted runs |

RED protocol: T1 authored and witnessed RED before `_delegation_usage` exists; the rest follow the same loop per cluster (T2–T5 lifecycle, T6–T7 tolerance, T8–T10 guards, T11–T12 wiring, T13 the M1 witness).

## §Open risks

1. ~~**`model` in real child streams is type-verified, not runtime-verified**~~ **RESOLVED at plan-review time:** d-5's real settled log carries `model: "z-ai/glm-5.3-flash"`, `provider: "openrouter"` on the assistant `message_end` — the spec's `message.model` read is runtime-confirmed. T10 still pins graceful `model: None`.
2. **Aborted-spent deviation from hermes semantics** (T4 + T13) is deliberate, documented, and M1-corrected: the settled marker is `exit` OR `agent_settled`. Contained: one predicate in `_delegation_usage`.
3. **`tests/test_pi_adjustments.py` ownership** with the concurrent MCP-parity lane (see §Parallelism) — the only named overlap candidate; serialise on collision.
4. **`totalTokens` excludes cache tokens** (hermes parity) while pi's own `usage.totalTokens` includes them — cross-source consistency chosen over per-source completeness; if the tracker later wants cache-inclusive subagent totals, hermes and pi must change together.
5. **Scaffold regen writes user-global state** (Hermes plugin/skill namespaces); the freshness guard contains it in its own run, but a lane regenerating by hand should mirror the guard's env (`AI_BADGER_MCP_AVAILABILITY=all`, contained `HERMES_HOME`) — P3's AC-I3 is the authoritative check, so lane-level regen mistakes cannot reach a merge silently.