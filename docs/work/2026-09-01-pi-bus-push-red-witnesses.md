# aib-pi-message-bus-push-delivery — red-witness log (merge gate)

Compiled per plan rev 2's merge gate: every new gate RED-first, with the output
pasted. Two row types, per the defer-cursor log's precedent: **RED-FIRST** (fails
against shipped pre-fix code) and **PIN/GUARD** (green-before by construction;
validated by a NAMED MUTATION instead).

## P1 — send-side target validation (lane: task/aib-pi-message-bus-push-delivery-p1)

RED-first run: 2026-09-01, against the untouched script at base b65e6427,
`.venv/bin/python3 -m pytest -q tests/test_send_message_skill.py -k "unresolvable or
resolvable_target or env_override_target or dual_flag or self_project_target or
discovered_ids or scan_budget"` → `3 failed, 4 passed` (the four accept pins are
PIN/GUARD — see table; the full output is in the P1 lane report).

| Test | Type | Red mechanism / killer mutation | Witnessed |
|---|---|---|---|
| B1 `test_unresolvable_project_target_is_refused_before_anything_is_written` | RED-FIRST | no validation existed: the unresolvable target stored a row (`sent 1`, rc 0) instead of refusing | lane RED run |
| B3 `test_refusal_names_the_discovered_ids_but_never_the_message_content` | RED-FIRST | no validation existed: rc 0, empty stderr | lane RED run |
| depth `test_scan_budget_is_four_directory_levels_below_the_scan_root` (beyond half) | RED-FIRST | no validation existed: depth-5 target stored (`sent 2`, rc 0) | lane RED run |
| B2a `test_resolvable_target_is_accepted_and_the_right_project_matched` | PIN/GUARD | kills the over-refusal mutant (scan root ignores the redirected user root) — see M4 below | mutation M4 |
| B2b `test_env_override_target_is_accepted_without_a_planted_project` | PIN/GUARD | kills a mutant dropping the env-override leg (target unresolvable without a plant) | by construction (leg 2 only path: nothing planted) |
| B2c `test_dual_flag_send_stores_one_to_one_and_skips_target_validation` | PIN/GUARD | kills the mutant `if args.project_id:` (fires on dual-flag sends) | mutation M2 below |
| B2d `test_self_project_target_resolves_from_the_sender_cwd_walk` | PIN/GUARD | kills a mutant dropping leg 1 (sender's own resolution) | by construction (same tree shape as B2a, but resolution via cwd walk) |
| depth (within half) | PIN/GUARD | kills the under-budget mutant (`_WALK_DEPTH` 4→3) | M1's mirror half |

### Mutation runs (break on purpose → red → restore → green)

- **M1** `_WALK_DEPTH = 5` → `test_scan_budget_is_four_directory_levels_below_the_scan_root` FAILED; restored → passed.
- **M2** fire condition `args.project_id and not args.session_id` → `args.project_id` → `test_dual_flag_send_stores_one_to_one_and_skips_target_validation` FAILED; restored → passed.
- **M3** candidate segment suppressed (`if found_ids and False:`) → `test_refusal_names_the_discovered_ids_but_never_the_message_content` FAILED; restored → passed.
- **M4** scan root = literal `badger_store._DEFAULT_HOME` always (the ruling's letter, ignoring `AI_BADGER_USER_ROOT`) → `test_resolvable_target_is_accepted_and_the_right_project_matched` + `test_scan_budget_is_four_directory_levels_below_the_scan_root` FAILED. NOT restored by revert — this documents the plan deviation (see the lane report): the pytest process freezes `badger_store._DEFAULT_HOME` at collection time to the REAL home (measured: `PROBE _DEFAULT_HOME: /Users/arasz` vs redirected `Path.home()`), so the literal walk scans the developer's machine under test and breaks the in-process integration roundtrip. Production semantics are unchanged by the deviation: `AI_BADGER_USER_ROOT` is never set by production code (grep-verified across `features/`, `skills/`, `.ai-badger/skills/`), so `_scan_root()` returns `badger_store._DEFAULT_HOME` exactly as ruled.

### RED output (B1, pasted verbatim)

```
>       assert proc.returncode == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = CompletedProcess(args=['...python3', '...send_message.py', '--content',
           'undeliverable by construction', '--project-id', 'job-search-ai-assistant',
           '--sender-session', 'sess-sender', '--sender-project', 'proj-sender'],
           returncode=0, stdout='sent 1\n', stderr='').returncode
```

## Gate 1 — B6: delivery summary contract (C2) + C2b failure marker — RED

New: `test_delivery_summary_counts_the_delivered_batch_exactly`,
`test_delivery_summary_tracks_the_live_read_batch`,
`test_delivery_summary_excludes_gated_cap_own_and_unrun_leg_rows`,
`test_delivery_summary_is_zero_zero_when_nothing_is_delivered` (store);
`test_clean_empty_stays_exactly_empty_at_the_wire` (regression pin — green by
construction, as planned), `test_failure_marker_on_a_forced_store_open_failure` (wire);
amended to the C2b marker shape: `test_corrupt_user_db_fails_open`,
`test_registry_explosion_fails_open`, `test_malformed_stdin_is_a_no_op`.

```
$ python3 -m pytest -q tests/test_message_bus_store.py -k "delivery_summary" \
    tests/test_message_delivery_hook.py -k "delivery_summary or failure_marker or clean_empty or corrupt_user_db or registry_explosion"
...
FAILED tests/test_message_bus_store.py::test_delivery_summary_counts_the_delivered_batch_exactly
FAILED tests/test_message_bus_store.py::test_delivery_summary_tracks_the_live_read_batch
FAILED tests/test_message_bus_store.py::test_delivery_summary_excludes_gated_cap_own_and_unrun_leg_rows
FAILED tests/test_message_bus_store.py::test_delivery_summary_is_zero_zero_when_nothing_is_delivered
FAILED tests/test_message_delivery_hook.py::test_corrupt_user_db_fails_open
FAILED tests/test_message_delivery_hook.py::test_registry_explosion_fails_open
FAILED tests/test_message_delivery_hook.py::test_failure_marker_on_a_forced_store_open_failure
7 failed, 1 passed, 62 deselected in 0.62s
```

The store-level failures are the tuple-unpack shape (pre-guard `deliver_for_session`
returns a bare list):

```
E           ValueError: too many values to unpack (expected 2)
tests/test_message_bus_store.py:1030: ValueError
```

The wire failures show the pre-guard failure path printing a bare `{}` where C2b
demands the marker:

```
E       AssertionError: assert {} == {'hookSpecificOutput': {'aiBadgerBus': {'error': True}}}
E         Right contains 1 more item:
E         {'hookSpecificOutput': {'aiBadgerBus': {'error': True}}}
```

GREEN after implementing C2 (`(messages, summary)` + `_read_addressed` target columns,
QA-11) + C2b (guarded_main prints the marker) + the deliberate call-site amendment of
every `deliver_for_session` call site in the test suite (QA-3, one named commit) and the
hermes plugin's `_deliver_bus_messages` consumer:

```
tests/test_message_bus_store.py tests/test_message_delivery_hook.py
tests/test_message_bus_integration.py tests/test_send_message_skill.py
tests/test_badger_store_vendored.py tests/test_message_bus_manifest.py
tests/test_message_bus_hermes.py tests/test_new_schemas.py
tests/test_containment_bus_coexistence.py tests/test_badger_store_session_families.py
→ 211 passed
```

---

## Gate 2 — B7: cursor-wrap guard (C9) — RED

New: `test_cursor_above_max_id_reads_as_cursor_less_for_that_read` (wrap healing) and
`test_a_caught_up_cursor_is_never_treated_as_wrapped` (strict-`>` boundary companion —
green by construction; its kill is the `>=` mutant, witnessed below).

```
$ python3 -m pytest -q tests/test_message_bus_store.py::test_cursor_above_max_id_reads_as_cursor_less_for_that_read \
    tests/test_message_bus_store.py::test_a_caught_up_cursor_is_never_treated_as_wrapped
...
>           assert [m["content"] for m in messages] == ["restored 1", "restored 2"]
E           AssertionError: assert [] == ['restored 1', 'restored 2']
E             Right contains 2 more items, first extra item: 'restored 1'
FAILED tests/test_message_bus_store.py::test_cursor_above_max_id_reads_as_cursor_less_for_that_read
1 failed, 1 passed in 1.63s
```

The pre-guard shape is exactly QA-3's prediction: ids 1, 2 re-minted below a surviving
cursor 3 are unreadable — `deliver returns []` on every read.

GREEN after implementing C9 (cursor > COALESCE(MAX(id),0) inside the same
BEGIN IMMEDIATE ⇒ cursor-less FOR THIS READ: 30-min gate + 16-cap + leg-scoped landing
re-apply):

```
tests/test_message_bus_store.py (full file) → 42 passed
```

### Mutation witness — the strict-`>` boundary

The guard flipped to `>=` → the boundary companion AND the existing caught-up pin
(`test_concurrent_deliveries_inject_exactly_once`'s caught-up read) both go red:

```
MUTANT: engine/badger_store.py, guard comparison `>` → `>=`
FAILED tests/test_message_bus_store.py::test_a_caught_up_cursor_is_never_treated_as_wrapped
FAILED tests/test_message_bus_store.py::test_concurrent_deliveries_inject_exactly_once
2 failed in 1.80s
(mutant reverted; clean tree re-verified green)
```

---

## Gate 3 — B4/B5: hook-error log gains the message + leak guard (C8) — RED

New: `test_hook_error_log_gains_the_exception_message` (B4-i),
`test_hook_error_log_never_leaks_payload_derived_substrings` (B4-ii),
`test_guarded_main_still_fails_open_when_the_log_path_throws` (B5).

```
$ python3 -m pytest -q tests/test_message_delivery_hook.py \
    -k "error_log or fails_open_when_the_log"
FAILED tests/test_message_delivery_hook.py::test_hook_error_log_gains_the_exception_message
FAILED tests/test_message_delivery_hook.py::test_hook_error_log_never_leaks_payload_derived_substrings
FAILED tests/test_message_delivery_hook.py::test_guarded_main_still_fails_open_when_the_log_path_throws
3 failed in 1.87s
```

The B5 red is the pre-C8 shape exactly: `record_hook_failure(...)` unprotected in
`guarded_main` → the forced OSError escapes and NOTHING reaches stdout (the net drops
the response). The B4 reds show type+location-only log lines (no message, no redaction).

GREEN after implementing C8: `record_hook_failure` gains the sanitized message
(`_redact_payload_text` over payload-derived candidates — whole text, lines, tokens,
JSON string values and their tokens), `guarded_main` captures the raw stdin text,
passes it through, and guards the log call.

### Mutation witnesses (each killed by exactly its owning test)

```
M1 revert-to-type+location  → test_hook_error_log_gains_the_exception_message RED
M2 raw-str-no-redaction     → test_hook_error_log_never_leaks_payload_derived_substrings RED
M3 unguarded-log-call       → test_guarded_main_still_fails_open_when_the_log_path_throws RED
(mutants reverted; clean file re-verified: 33 passed)
```

---

## Gate 4 — B8: the full guarded_main wire response — RED

New: `test_wire_response_is_advisory_plus_bus_summary_exactly` (full-response exact
equality, in-process), `test_the_bus_summary_never_occupies_a_host_acted_key` (CR-N6
pin — green by construction, a guard), and the deployment-shape pin in
`tests/test_message_bus_integration.py::test_the_deployed_child_carries_the_bus_summary_on_the_full_response`
(real child process + clean-empty follow-up).

```
$ python3 -m pytest -q tests/test_message_delivery_hook.py -k "wire_response or host_acted" \
    tests/test_message_bus_integration.py::test_the_deployed_child_carries_the_bus_summary_on_the_full_response
FAILED tests/test_message_delivery_hook.py::test_wire_response_is_advisory_plus_bus_summary_exactly
FAILED tests/test_message_delivery_hook.py::test_the_bus_summary_never_occupies_a_host_acted_key
2 failed, 34 deselected in 1.79s

separately:
FAILED tests/test_message_bus_integration.py::test_the_deployed_child_carries_the_bus_summary_on_the_full_response
```

The red shape: the wire response carries hookEventName + additionalContext but NO
aiBadgerBus — the _deliver merge (C2's construction point, after build_response) does
not exist yet.

GREEN after implementing the merge; mutation witness (merge dropped → both the
in-process pin AND the child-process pin red):

```
merge-dropped mutant: ['FAILED ...test_wire_response_is_advisory_plus_bus_summary_exactly',
 'FAILED ...test_the_deployed_child_carries_the_bus_summary_on_the_full_response']
(mutant reverted; clean tree re-verified: 41 passed)
```

## P3 + fix wave — adapter push delivery (bun suite)

**Provenance note (honest).** The P3 lane committed its gates without pasting
their RED-first outputs into this log (a lane-discipline miss the impl-review
qa lane caught as its B-2). The record below is therefore NOT the lane's own
RED paste: it is the independent mutation evidence the qa implementation-review
lane produced against the merged tree — seven production mutations, each
applied, run, and reverted with a green re-run — which witnesses the same
property the red-first pastes would have (full transcripts:
`docs/work/2026-09-01-pi-bus-push-impl-review-qa.md`). The B1 retry gate and
the CR-M3 discriminating fixture were added by the fix wave and their first
runs are recorded directly.

| Gate | Property | Killer mutation | Result |
|---|---|---|---|
| A3 watermark property | skip only on exact MAX **and** COUNT equality | drop `f.count === clean.count` from the skip gate | RED: `A3 … MAX equal but COUNT differs ⇒ spawn` — reverted, green |
| A9 advance rule | failure marker / error / timeout never advance; clean `{}` does | `advanceAllowed` → `return true` | RED ×6 across both levels (incl. the CR-M1 retry path, `deliverCalls` 2 after two ticks) — reverted, green |
| C9 wrap boundary | strict `>`: caught-up cursor never treated as wrapped | `>` → `>=` in `badger_store.py:1923` | RED ×2: `test_concurrent_deliveries_inject_exactly_once`, `test_a_caught_up_cursor_is_never_treated_as_wrapped` — reverted, green |
| A12 notice latch | probe errors notify once per streak | notice-latch reset removed | RED (A12 both cases) — reverted, green |
| wake routing | summary-driven routing, no bypass | parse→`mailSummary`→`wakeRoute` chain shortcut | RED on the A8 matrix cases — reverted, green |
| CR-M3 advance value | watermark = tick-time capture, never a post-spawn re-read | `spawnAndSettle` re-probes post-spawn and advances the re-read | RED via the A10 probe-count assertions (incidentally, per qa S-3) — reverted, green; the discriminating fixture below now pins it directly |
| B1 compensation retry (fix wave) | non-stale wake throw retries once as `nextTurn`, no `triggerTurn`; stale throws never retry; a failing retry stays at one notice | remove the retry block | RED: `B1: a non-stale sendMessage throw retries once…` (`wakes` 2→1) + the no-second-notice case — first run of the new gate, committed red-paste-equivalent: `bun test features/pi/tests/adapter-bus.test.ts` → 32 pass before the fix wave, 34 pass after |

The discriminating CR-M3 fixture (qa S-3): probe sequence fp(7,7) at tick time
then fp(8,8) — a post-spawn re-read would advance to fp(8,8) and strand the
mid-txn row; the tick-time capture forces the next tick to spawn. Pinned in
`adapter-bus.test.ts` as `A9/CR-M3 discriminating fixture`.
