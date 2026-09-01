# RED witnesses — aib-pi-message-bus-push-delivery P2 (store summary + failure marker + wrap guard + hook-error message)

Lane: P2 · Worktree: `.ai-badger/worktrees/aib-pi-message-bus-push-delivery-p2` ·
Branch: `task/aib-pi-message-bus-push-delivery-p2` · Base: `b65e6427` · 2026-09-01

Every gate below was run RED-first against the tree it was introduced into, then
implemented, then re-run green. Gate order: B6 → B7 → B4/B5 → B8 (plan rev 2, P2;
test specs per qa QA-2/QA-3/QA-10/QA-11 and the test-engineer proposal).

Baseline (pre-change): `tests/test_message_bus_store.py tests/test_message_delivery_hook.py
tests/test_message_bus_integration.py tests/test_send_message_skill.py
tests/test_badger_store_vendored.py tests/test_message_bus_manifest.py
tests/test_message_bus_hermes.py` → **117 passed**.

Interpreter: `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest`.

---

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
