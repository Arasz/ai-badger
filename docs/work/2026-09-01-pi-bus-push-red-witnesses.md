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
