# Research lane C — bus follow-ups evidence record (2026-09-01)

Method: read-only evidence record. No tests executed, no mutation applied — every finding is read from source at the cited path:line in this worktree unless marked HYPOTHESIS. Gate discovery: `commands.test` = `python3 -m pytest -q` (source: .ai-badger/config.json); no stack QA persona beyond qa.md is scaffolded. Out of scope: production-code quality/security judgement, plan-writing, decisions. Paths are worktree-relative; absolute where the file lives in the main checkout. The memory-first gate hook could not be satisfied (memory_search is not in this session's toolset); repo text search proceeded under that exception.

## 1. pi bridge mechanics — what deferring start-spawn to before_agent_start changes

Where the session_start child spawns: `pi.on("session_start")` → `router.sessionStart(...)` (source: features/pi/adjustments/adapter/index.ts:379-384); the router arm spawns the delivery child and stores the promise in `pendingStart` (source: features/pi/adjustments/adapter/hook-bridge.ts:399-404, state :381). The spawn itself is `runDelivery`: `python3 <cwd>/.ai-badger/hooks/message_delivery_hook.py`, stdin payload, absent script = silent `empty` (source: index.ts:242-247, existsSync :246-247). The child maps `session_start` → `"SessionStart"`, a delivery event (source: hook-bridge.ts:277-285; features/common/hooks/message_delivery_hook.py:41) → `store.deliver_for_session` (source: message_delivery_hook.py:104-113) — one `BEGIN IMMEDIATE` that reads mail AND upserts the cursor (source: engine/badger_store.py:1758-1784, upsert :1779-1783). The cursor advances at session start even though pi cannot inject there (handler returns `undefined`; no result seam).

Held context: the child's promised outcome (`pendingStart`) is consumed by the first `before_agent_start` — a `context` outcome is returned as pi's injection message and the promise cleared; `empty`/`error` falls through to a live `UserPromptSubmit`-shaped read (source: hook-bridge.ts:406-423; injection shape :318-330; wiring index.ts:385-390).

The defer delta. Deferring the spawn to `before_agent_start` removes: the `sessionStart` router arm and `pendingStart` (hook-bridge.ts:381, :399-404), the held-consume branch (:406-419), and the `pi.on("session_start")` delivery wiring (index.ts:379-384); `beforeAgentStart` becomes an unconditional live read — read and inject coincide in the store's one transaction ("consume messages, not just read them"). A session that never reaches `before_agent_start` spawns nothing: no store hit, no cursor row, mail survives for a later session (the 30-minute gate re-applies). Today the opposite: the start child consumes and the mail is silently lost — TTL does not re-deliver a consumed message (source: qa-review plan L4, .ai-badger/task-tracking/plans/2026-09-01-aib-user-db-message-bus-qa-review.md:50-53). The L5 turn-1 skip (non-empty held context returns without a live read, so mail arriving between start-read and turn 1 waits until turn 2; source: plan L5 :54-57, code hook-bridge.ts:406-419) cannot occur post-defer: there is no held path, turn 1 always live-reads. Deferral delivers a superset within the 30-minute window (plan L4's recorded alternative).

Tests pinning today's pi shape (the defer amends these): tests/js/pi_message_bus_adapter.test.mjs:97 ("router hands the start-delivered mail to the first turn exactly once, then goes live"), :137 (fall-through on empty/errored), :193 (shutdown), :266 (Rule 7 sc.1 E2E through the real script), :293. The TS suite pins gates/payloads/away only — `createDeliveryRouter` and the three pi.on wirings have no unit test there (grep for `Delivery|router|session_start` in features/pi/tests: zero hits; test lists hook-bridge.test.ts:20-466, adapter-entry.test.ts:44-147).

Hermes — where the stash pops, and the seam. The plugin's start delivery `on_session_start_message_delivery` calls `store.deliver_for_session` in-process (cursor advances; source: features/common/hooks/ai_badger_hooks.py:984, :1009-1025) and stashes the rendered payload in the module-level `_bus_pending` dict keyed by session id (source: :957). The stash is popped by the FIRST `pre_llm_call`, not at session_end: `_bus_turn_context` pops `_bus_pending` (:1002) and also performs the per-turn live read (:1001), combining both (:1004-1006). `on_session_end_message_delivery` only deletes the cursor (`store.delete_cursor`, :1040); it never touches the stash. Registration :1152 (on_session_start), :1153 (pre_llm_call), :1157 (on_session_end). Loss shape is the same as pi's L4: a session dying before its first `pre_llm_call` consumed-at-start and never injected; the unpopped `_bus_pending` entry then lingers in the gateway process — HYPOTHESIS (static reading; Hermes gateway process model not verified in this lane). An equivalent defer seam EXISTS and is cheaper than pi's: `pre_llm_call` has a return channel (`{"context": ...}` injected into the user message; source: features/hermes/skills/hermes-plugin-development/SKILL.md:54-56), and `_bus_turn_context` already live-reads every turn — dropping the start delivery + stash entirely makes the first `pre_llm_call` consume-and-inject. Documentation is NOT the only remedy for Hermes. Plan L4's parenthetical "stash popped at session_end" (:50-53) is loose wording; the code pops at first pre_llm_call (ai_badger_hooks.py:1002).

## 2. Spec scenarios the refactor/defer would amend

File: /Users/arasz/RiderProjects/ai-badger/.ai-badger/task-tracking/specs/aib-user-db-message-bus.feature (179 lines; main checkout). Gitignored (source: .gitignore:7 `.ai-badger/task-tracking/`), NOT tracked; `git ls-files` finds no other .feature or message-bus spec in the repo (only the changelog matches). Nearest derived artifact: scenario-title keys duplicated in tracked tests/test_message_bus_integration.py:466, :485, :489, :494 (mutation flags :576, :579-581) — a hand-maintained mirror of a gitignored file (drift-prone; noted, not planned).

Rule 7 = "Every harness with hooks gets the delivery hook" (feature :110); its scenario 1, verbatim (:111-115):

> Scenario: pi session start delivers
>   Given the bus tables exist in the user DB
>   When a pi session starts in project "P" with unread project messages
>   Then the messages are injected into the pi session's context

D4 defer amends this scenario's timing (injection lands on the first turn, not literally at start) and its owning tests (map at tests/test_message_bus_integration.py:466-471: pi_message_bus_adapter.test.mjs E2E, test_pi_adjustments.py copy test, roundtrip test). Plan L4 records that the current design honours this scenario "literally" (:50-53).

Rule 8 = "Project identity comes from the cwd resolver only" (feature :126), verbatim (:127-141):

> Scenario: Same project directory matches
>   Given the sender and receiver resolve the same project directory
>   When the sender sends a project message
>   Then the receiver's hook selects it
>
> Scenario: Different directories resolving to one project id match
>   Given two working directories that resolve to the same project id
>   When a project message is sent from one
>   Then a session in the other receives it
>
> Scenario: A second derivation would miss messages (mutation)
>   Given the delivery hook derived project identity without the cwd resolver
>   When a project message is addressed by the resolver's project id
>   Then the hook's selection does not match and the message is missed

The resolver: cwd → projectId via the ai-raccoon registry, `AI_BADGER_PROJECT_ID` override, `AI_BADGER_RACCOON_DB` seam; unresolved project fails open to 1:1 (source: docs/changelog/0.156.0-user-db-message-bus.md:20-23; delivery-side resolution message_delivery_hook.py:106). Rule 8 never names the registry, so a D2 refactor of the resolver backend need not change the scenario text — it changes the owning tests named in the map (source: tests/test_message_bus_integration.py:485-497).

## 3. Hold seams and the exactly-once E2E's arming

Seams in engine/badger_store.py — exactly two call sites: `_hold_at("deliver.entry")` before `BEGIN IMMEDIATE` (:1758) and `_hold_at("deliver.after_read")` between the read and the cursor upsert (:1778). Definition `_hold_at` (:97-106): runs in-process callbacks registered in `_TEST_HOLDS` (:93, :99-100), then honours the env hold `AI_BADGER_TEST_HOLD="<seam>:<release-path>"` (:94, :101) by polling `while not release.exists(): time.sleep(0.005)` (:102-105). Seam names that exist: `deliver.entry`, `deliver.after_read` — nothing else (whole-file grep).

How the process-race E2E arms it today (tests/test_message_bus_integration.py): `HOLD_ENV = "AI_BADGER_TEST_HOLD"` (:63); the fixture strips it from the inherited env (:75); `_child_env` strips parent `AI_BADGER_PROJECT_ID`/HOLD/`CLAUDE_PROJECT_DIR` and sets `env[HOLD_ENV] = f"deliver.after_read:{release}"` (:191-198). It spawns TWO children of the SHIPPED script — `[sys.executable, str(ROOT / HOOK_PATH)]`, `HOOK_PATH = "features/common/hooks/message_delivery_hook.py"` (:50, :242-243) — each on a SessionStart payload for session S2 (:237-248). `_wait_for_parked_transaction` proves a child holds the write lock (busy_timeout=50 → "database is locked"; :201-209, called :249), then the parent releases with `release.touch()` (:250) and asserts exactly one child injected (:266-272). The shipped script imports the badger_store sibling beside itself (source: tests/test_message_delivery_hook.py:662-664), so the vendored features/common/hooks/badger_store.py copy is what the hold executes (its `_hold_at` matches engine's line-for-line today: :93-106, :1758, :1778).

Constraints an arm-env gate must respect so the existing E2E still passes (ruling D3: keep the `_hold_at` consultation in shipped code; honour the env hold only when a second arm env — set solely by test preconfiguration — is also present):
1. `_child_env` (test_message_bus_integration.py:197) must set the arm env too, else the hold is inert, no child parks, `_wait_for_parked_transaction` times out (15 s) and the E2E fails.
2. The other env-arming site — test_message_bus_store.py:852-865 (`monkeypatch.setenv("AI_BADGER_TEST_HOLD", f"deliver.after_read:{release}")`) — must set both as well.
3. Every env-strip list that removes HOLD_ENV from child envs must add the arm env (test_message_bus_integration.py:75, :194; test_message_bus_manifest.py:83, :411; test_message_delivery_hook.py:85, :671) or a leaked arm value re-enables holds in production-shaped children.
4. In-process `_TEST_HOLDS` callbacks must stay ungated — production never registers them (badger_store.py:91-92) and the store-level seam tests rely on them.
5. The gate must land in BOTH engine/badger_store.py and the vendored features/common/hooks/badger_store.py (the E2E exercises the vendored copy; shipped-pair byte-identity is pinned by tests/test_adjust_hooks_copilot.py:419).
6. The `spec.startswith(f"{seam}:")` prefix check (badger_store.py:102) survives; the arm env gates the whole env-hold consultation, not per seam.

## 4. Docs targets

Changelog — docs/changelog/0.156.0-user-db-message-bus.md. Structure: "## What changed" :9 (bus store P1 :11-18; resolver P2 :20-23; skill P3 :25-28; delivery hook P4 :29-33; wiring P5–P8 :35-42; P9 :44-46), "## Consumer impact" :49-58.

- D5 (Copilot sessionEnd residual risk): belongs on the Copilot sentence in the P5–P8 wiring bullet — "including `sessionEnd` for cursor cleanup (the close-event verdict: the event exists — …)" at :37-38. Risk text per plan L6 (:58-61): the verdict rests on in-tree sources plus a self-executed generated-artifact E2E, unlike Claude's observed real `claude -p` firing.
- D6 (machine-local trust boundary): the P3 sender-identity bullet :25-28 is the changelog home (identity is asserted not authenticated; the `AI_BADGER_PROJECT_ID` override is the mechanism, :20-23); plan L8 (:66-69) says "the trust boundary should be stated in the SKILL/changelog".
- registry_snapshot verification: the changelog on disk makes NO registry_snapshot claim — it says "`messages` and `cursors` tables are born through `UPGRADE_HOOKS[1]`" (:11-12), which matches the DDL: `_BUS_DDL` creates only `messages`, `cursors`, two indexes (engine/badger_store.py:55-78), applied by `_upgrade_v1_to_v2` (:81-84); `registry_snapshot` appears nowhere in the code (greps of engine/ and docs/: zero hits). Plan L7 (:62-65) recorded the claim against an older revision — it appears already amended. Adjacent one-line factual fix: MOOT on disk today (flagged per instructions; not planned).

skills/send-message — the repo-root SKILL.md is a 24-line pointer whose procedure lives in SKILL.full.md (:17-19: "The full procedure is in `SKILL.full.md` beside this file"). SKILL.full.md sections: Usage :25, "Sender identity is mandatory" :49, Gotchas :68. The trust-boundary text belongs under **"Sender identity is mandatory"** (:49) of SKILL.full.md — and of the scaffolded .ai-badger/skills/send-message/SKILL.md, whose head is identical to SKILL.full.md (diff of first 20 lines: identical; same section line numbers 19/25/49/68). HYPOTHESIS: the scaffolded SKILL.md is derived from SKILL.full.md at scaffold time (content head verified identical; derivation mechanism not traced).

Copilot hook rows and the missing existence guard. The adjuster emits two shapes: (a) rewritten source command — `cmd = _rewrite_command(...)` then `hook_entry = {"type": "command", "bash": cmd, "timeoutSec": 10}` (source: features/copilot/adjustments/adjust_hooks.py:125-131); (b) skill-glob fallback — `"bash": f"python3 {rel_path.as_posix()}"` (:156). Neither wraps a guard. The generated .github/hooks/ai-badger-hooks.json rows are all bare — sessionStart drift row :10-14, the three delivery rows (:15-16, :24-27, sessionEnd cleanup :31-34), every postToolUse row (:36-64) — each just `python3 "<path>"` with no `if -f`. Claude's side emits the guard via `guarded()` in features/common/skills/welcome-ai-badger/scripts/hook_wiring.py:61-75: `if [ -f "$CLAUDE_PROJECT_DIR/<script>" ]; then <command>; elif [ -f "<script>" ]; then <relative>; else echo '{"systemMessage": "ai-badger: <script> not found - hook skipped"}'; fi`, applied at :288 and :322.

What the guard requires in the Copilot adjuster: `guarded()` takes the command AND the script path, but the Copilot emitter holds only the assembled command string — for shape (a) the script path must be extracted from the rewritten command (the adjuster already tail-parses via `cmd.rstrip('"').rsplit("/", 1)[-1]`, adjust_hooks.py:34, :109) or the rewrite must carry the path alongside; for shape (b) `rel_path` is already in scope (:150-156) so the guard is a straightforward string build around it. Quoted paths must stay balanced — a pin asserts `bash.count('"') % 2 == 0` (test_adjust_hooks_copilot.py:210, :384). Tests pinning the generated shape (all would need amending): exact-equality pins test_adjust_hooks_copilot.py:209 (`'python3 ".ai-badger/skills/task/scripts/drift_notice_hook.py"'`) and :411-412 (`'python3 ".ai-badger/hooks/message_delivery_hook.py"'`); tail-extraction pins :58-59, :99-101, :143-145, :171-172, :253-257, :292-295, :383-385; the artifact E2E runs the generated string directly under `bash -c` (:562) and still passes with a guard provided the shipped file exists (:413-414).

## Open design decisions for the plan

- Whether the D4 defer removes the `sessionStart` arm from the router interface entirely (and its pi.on wiring) or keeps a no-op for compatibility with older callers.
- Whether Hermes adopts the same defer (drop `on_session_start_message_delivery` + `_bus_pending`, rely on the first `pre_llm_call` live read) or only pi changes.
- What text Rule 7 sc.1 ("pi session start delivers") becomes if timing moves to the first turn — reword the scenario, or keep the Gherkin and document the timing.
- What the arm env for the D3 hold gate is named, whether the in-process `_TEST_HOLDS` path stays ungated, and whether the gate lives only in the env branch of `_hold_at`.
- Whether the D2 resolver refactor changes the owning tests of Rule 8 (and the scenario-title mirror in test_message_bus_integration.py:466-501) without touching the Gherkin text.
- Whether the Copilot `if -f` guard reuses `guarded()` from hook_wiring.py (import or copy) and whether the guard's "skipped" systemMessage is wanted in the Copilot JSON.
- Where the D6 trust-boundary paragraph lands in both docs (changelog P3 bullet vs Consumer impact; SKILL.full.md "Sender identity is mandatory" vs Gotchas) and whether the scaffolded SKILL.md regeneration picks it up.
