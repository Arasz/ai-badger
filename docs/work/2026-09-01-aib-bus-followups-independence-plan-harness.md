# Plan — harness packages (MoE lane: harness author) — aib-bus-followups-independence

2026-09-01 · Evidence: research-c.md (primary), research-a/b (context), source read in this worktree.
Owner rulings: R4 (defer start-spawn, pi **and** Hermes), R3 (env hold needs a second arm env),
R5 (Copilot sessionEnd residual risk → changelog), R6 (machine-local trust boundary → changelog
P3 + SKILL.full.md), R7 (Copilot emits the `if -f` guard). Every edit names: file, shape, pinned
test that must stay green (after any amendment).

## 1. D4 pi defer — read+inject coincide at `before_agent_start`

Files: `features/pi/adjustments/adapter/hook-bridge.ts`, `features/pi/adjustments/adapter/index.ts`.

Router-interface decision — **remove `sessionStart` entirely, no no-op stub.** The interface has
exactly one caller (`index.ts`), no TS unit test, and no external consumer; a stub would be dead
code asserting "start consumes nothing" while existing. Removal is compile-enforced.

Edits (hook-bridge.ts):
1. Delete the `pendingStart` state (:381) and the `sessionStart` arm of the returned router
   (:399-404). Delete `sessionStart` from the `DeliveryRouter` interface (:347-352).
2. Delete the held-consume branch in `beforeAgentStart` (:406-419); the method body becomes one
   `return liveTurn(ctx)` — `liveTurn` (:348-364) is unchanged: context→injection, error→notice,
   empty→nothing.
3. Remove `"session_start"` from `PiDeliveryEvent` and `PI_DELIVERY_EVENT_MAP` (:279-287); the map
   becomes `{before_agent_start: "UserPromptSubmit", session_shutdown: "SessionEnd"}`. The Claude
   spelling `SessionStart` stays real for Claude/Copilot — only pi's map shrinks.
4. Rewrite the state-machine doc comment above `createDeliveryRouter` (:354-373): start-spawn is
   deferred; a never-turned session spawns nothing, so no cursor row is written and mail survives
   for a later session (30-minute gate re-applies). Today the start child consumes and a dead
   session silently loses the mail (TTL does not re-deliver).

Edits (index.ts): delete the `pi.on("session_start")` delivery wiring (:379-384) and update the
comment above the delivery block (:373-378). `before_agent_start` (:385-390) and
`session_shutdown` wirings stay as-is.

Behavior preserved unchanged: absent-script silent-empty (`runDelivery` `existsSync`, index.ts
:246-247 — unwired project = silent no-op, never a notice); away-mode and payload gates (they live
in the `tool_call` path and `createAwayState`, untouched); shutdown cursor cleanup.

Amended pins: `tests/js/pi_message_bus_adapter.test.mjs` :97 (rewrite: first turn live-reads and
injects exactly once — no SessionStart seen event), :137 (empty-start fall-through is moot;
rewrite as live-read-empty), :193 (shutdown, mechanical), :266 E2E (fire the `UserPromptSubmit`
spelling — the adapter's first injection-bearing event — rest of the E2E survives), :293.
**Found beyond research-c:** `tests/test_pi_hook_arm_coverage_contract.py` :237 pins the map's
exact three keys (→ two) and :262 pins the three `pi.on` delivery subscriptions (→ two), keeping
the bridge-seam references.

## 2. D4 Hermes defer — first `pre_llm_call` consumes-and-injects

File: `features/common/hooks/ai_badger_hooks.py` (+ `features/common/hooks/hooks-manifest.json`).

Edits:
1. Delete the module-level `_bus_pending` dict and its comment (:956-958).
2. Delete `on_session_start_message_delivery` (:1011-1027).
3. `_bus_turn_context` (:1002-1009): drop the `stashed = _bus_pending.pop(...)` line and the
   stash/live merge; body becomes the live read + render it already does. The consumption channel
   already exists: `pre_llm_inject_context` (:635) calls `_bus_turn_context` and returns the text
   through the `pre_llm_call` return channel (Hermes prepends it to the user message) — so the
   FIRST `pre_llm_call` reads mail, advances the cursor, and injects in one store transaction.
4. `on_session_end_message_delivery` (:1029-1045): remove the `_bus_pending.pop` line only;
   `delete_cursor` stays.
5. `register()` (:1150-1157): remove `ctx.register_hook("on_session_start",
   on_session_start_message_delivery)`; the drift notice stays on `on_session_start`.
6. hooks-manifest.json: drop the hermes arm `{"method": "on_session_start"}` from the
   session-start row (row keeps claude + copilot).
Session that never reaches `pre_llm_call`: nothing is consumed — no store hit, no cursor row, mail
survives the 30-minute gate for a later session. Today it is consumed-at-start and lost until the
4-day TTL prune. Bonus: the `_bus_pending` leak in the gateway process disappears.

Amended pins: `tests/test_message_bus_hermes.py` :90-91 (start-firing helper becomes a
first-`pre_llm_call` delivery), :169-172 (registration set loses the delivery hook), :182+
(exactly-once test: first pre_llm_call delivers, second is empty), :299/:404/:409/:442
(`_bus_pending` assertions deleted with the dict). `tests/test_message_bus_manifest.py`
:171-200 (:178-179 hermes arm removed), :374, :386.

## 3. D3 arm-env — `_hold_at` env branch gated, `_TEST_HOLDS` ungated

Env name — **`AI_BADGER_TEST_HOLD_ARMED`** (prefix-consistent with `_TEST_HOLD_ENV`, plain
meaning; set-and-non-blank arms, tests set `"1"`).
Edit `engine/badger_store.py`: add `_TEST_HOLD_ARM_ENV` beside `_TEST_HOLD_ENV` (:94); in
`_hold_at` (:97-106) gate the env branch only:

```python
armed = os.environ.get(_TEST_HOLD_ARM_ENV)
spec = os.environ.get(_TEST_HOLD_ENV)
if armed and spec and spec.startswith(f"{seam}:"):
    release = Path(spec.split(":", 1)[1])
    while not release.exists():
        time.sleep(0.005)
```

The `_TEST_HOLDS` callback loop (:99-100) stays first and ungated — production never registers,
store-level seam tests rely on it. The `startswith(f"{seam}:")` prefix check survives; the arm
gates the whole env consultation, not per seam.

Sites that must set/strip it (research-c §3's six constraints):
1. `tests/test_message_bus_integration.py:197` — `_child_env` sets BOTH `HOLD_ENV` and
   `env["AI_BADGER_TEST_HOLD_ARMED"] = "1"`; strip lists at :75 and :194 add the arm env.
2. `tests/test_message_bus_store.py:852-865` — `monkeypatch.setenv` both.
3. Every env-strip list gains the arm env: test_message_bus_integration.py :75, :194;
   test_message_bus_manifest.py :83, :411; test_message_delivery_hook.py :85, :671.
4. Gate lands in BOTH copies: the E2E exercises the vendored `features/common/hooks/badger_store.py`
   (the shipped hook imports its sibling); byte-identity (constraint 5) makes one edit + re-land
   suffice.

Vendored-copy re-landing duty: `engine/badger_store.py` is canonical for `VENDORED_PATHS`
(16 destinations) + 12 scaffolded `.ai-badger/` mirrors (~33 copies), hand re-landed same-commit
(c7424c6f precedent): byte-copy the canonical over every destination, run `python3
tooling/sync_plugin_skills.py` for skills/ mirrors, re-land `.ai-badger/` mirrors; gate =
`tests/test_badger_store_vendored.py:25-27` (report `[]`).

## 4. D7 Copilot guard — `if -f` wrap in `adjust_hooks.py`

File: `features/copilot/adjustments/adjust_hooks.py`.

Reuse vs copy — **copy the shape, do not import `guarded()`.** Two reasons: (a) hook_wiring.py's
`guarded()` (:61-75) is parameterized on `${CLAUDE_PROJECT_DIR}` and `project_script()`'s
skill-path markers; Copilot's commands are relative paths (`.ai-badger/...`) with no marker and
no substitution, so the imported function would return the command unguarded — a silent skip of
the guard itself; (b) it lives in the welcome-ai-badger bootstrap skill, imports
`scaffold_context`, and is not on adjust-time `sys.path` — an import couples the Copilot
adjustment to a skill-script module graph. Add a local `_guarded(cmd, script_rel)`:

```
if [ -f "<script_rel>" ]; then <cmd>; else echo '{"systemMessage": "ai-badger: <script_rel> not found - hook skipped"}'; fi
```

Single existence branch — Copilot runs hook commands with cwd = project root, so Claude's
worktree fallback arm has no analog here. **systemMessage-on-skip: keep** — the skip must be
visible rather than silently inert (the F1 rationale hook_wiring.py records), and the output is
valid JSON either way.
Shape (a) — rewritten commands carry their script path: extend `_rewrite_command` (:48-71) to
return `(cmd, script_rel)`; it already computes the rewritten path (the `hooks_marker` branch),
so no re-parsing. `adjust()` passes both into `_guarded`. `scripts_to_ship` accrual is unchanged.
Shape (b) — glob fallback (:150-156): `rel_path` is in scope; build
`_guarded(f"python3 {rel_path.as_posix()}", rel_path.as_posix())`.

Quoted-path balance: every inserted path is double-quoted; `bash.count('"') % 2 == 0` pins
(test_adjust_hooks_copilot.py :210, :384) still hold.

Amended pins (test_adjust_hooks_copilot.py): exact-equality :209 and :411-412 expect the guarded
string; tail-extraction/ship pins :58-59, :99-101, :143-145, :171-172, :253-257, :292-295,
:383-385 survive (ship-set mechanics unchanged); artifact E2E :555-565 runs the generated string
under `bash -c` and still passes — the script exists, the guard passes through, delivery JSON
stays parseable.

## 5. D5+D6 docs — exact sentences

Changelog `docs/changelog/0.156.0-user-db-message-bus.md`:

- **D5** — P5–P8 Copilot sentence (:37-38) gains the residual-risk clause: "Copilot the camelCase
  spellings including `sessionEnd` for cursor cleanup (the close-event verdict: the event exists —
  the hypothesis that it did not was falsified; unlike Claude's, which was observed firing in a
  real `claude -p` run, Copilot's rests on in-tree sources plus a generated-artifact E2E);"
- **D6** — P3 sender-identity bullet (:25-28) gains: "Sender identity is asserted from
  machine-local state, not authenticated: anything running on this machine can send as any
  session. The bus's trust boundary is the machine, not the bus."
- Consistency edit the same change forces: P4 (:29-33) says "`AI_BADGER_TEST_HOLD` arms
  deterministic seams" — post-D3 that is true only when the arm env is also set; amend to name
  both envs (`AI_BADGER_TEST_HOLD` + `AI_BADGER_TEST_HOLD_ARMED`).
Skill `features/common/skills/send-message/SKILL.md`, end of "Sender identity is mandatory"
(:49 section), ≤3 lines: "Sender identity is asserted, not authenticated: it is derived from
machine-local state (environment variables, the sessions store, the working directory), so
anything with access to this machine can send as any session or project. Treat a sender as a
claim the local software made, not proof of authorship — the trust boundary is the machine,
not the bus."
**Mirror regeneration — research-c's HYPOTHESIS resolved.** The scaffolded
`.ai-badger/skills/send-message/SKILL.md` is a verbatim copy of the catalog
`features/common/skills/send-message/SKILL.md` (diff verified identical in this worktree),
written at scaffold time — it is NOT derived from `SKILL.full.md`. `skills/<name>/SKILL.full.md`
is `tooling/sync_plugin_skills.py`'s verbatim copy of that same catalog body
(`render_into` writes `FULL_BODY_NAME` = source, replaces the plugin `SKILL.md` with the
pointer). Edit chain: (1) edit the features/ catalog SKILL.md; (2) `python3
tooling/sync_plugin_skills.py`; (3) re-land this repo's own `.ai-badger/skills/send-message/`
mirror same-commit (hand copy, c7424c6f precedent, or den-refresh). Gates:
`sync_plugin_skills.py --check`, `tests/test_sync_plugin_skills.py`.

## Kept-green checklist

Pinned tests that must not break (after named amendments), by area:

- **D4 pi**: tests/js/pi_message_bus_adapter.test.mjs :97, :137, :193, :266, :293 (amended);
  tests/test_pi_hook_arm_coverage_contract.py :90-236 (subscribes-to-at-least-one, stamp,
  not-a-manifest-arm — untouched and green), :237 and :262 (amended to the two-event shape);
  tests/test_pi_adjustments.py :1559-1584 (delivery-script + badger_store copy list — unchanged).
- **D4 Hermes**: tests/test_message_bus_hermes.py (amended as §2); tests/test_message_bus_manifest.py
  :171-200, :374, :386 (amended); tests/test_hermes_plugin_payloads.py (registration smoke — must
  stay green with the trimmed register()).
- **D3 arm-env**: tests/test_message_bus_integration.py (exactly-once E2E with both envs set);
  tests/test_message_bus_store.py (seam tests via ungated `_TEST_HOLDS`; :545-559 overflow
  guarantee untouched); tests/test_message_delivery_hook.py; tests/test_badger_store_vendored.py
  :25-27 (byte-equality after the ~33-copy re-landing, same commit).
- **D7 Copilot**: tests/test_adjust_hooks_copilot.py — amended pins §4; balance pins :210/:384
  green; artifact E2E :555-565 green unmodified.
- **D5+D6**: tests/test_sync_plugin_skills.py and `--check` green after the skills re-render;
  tests/test_changelog_index.py (changelog format); tests/test_skill_bodies_carry_procedure_not_evidence.py
  (SKILL.md prose lint) green.
- **Cross-lane invariants respected**: spec Rule 7 sc.1 "pi session start delivers" timing
  wording amends in the gitignored .feature AND its tracked mirror (tests/test_message_bus_integration.py
  :466-501) — scenario-title mirror stays in sync; Claude's SessionStart wiring and manifest arms
  are untouched by this lane.
