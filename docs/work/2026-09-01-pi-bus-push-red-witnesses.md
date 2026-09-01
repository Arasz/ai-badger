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
