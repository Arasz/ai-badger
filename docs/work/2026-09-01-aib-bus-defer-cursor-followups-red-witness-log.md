# aib-bus-defer-cursor-followups — red-witness log (honest shape, qa M4)

Compiled at join from the lanes' witnesses and re-run by the qa review lane (d-210),
which applied and reverted eight mutations against `origin/main`'s production code.
Two row types per the plan: **RED-FIRST** (fails against shipped pre-fix code) and
**PIN/GUARD** (green-before by construction; validated by a NAMED MUTATION instead).

| Test | Type | Red mechanism / killer mutation | Verified by |
|---|---|---|---|
| R1a `test_gated_first_delivery_without_project_never_sweeps_other_legs` | RED-FIRST | revert-leg-scope ⇒ global MAX landing (seeding 1:1 BEFORE broadcast avoids the S1 trap) | lane + qa run 1 |
| R1c `test_first_delivery_with_project_id_still_cursors_past_the_window` | GUARD | kills the over-tighten mutant (leg-scoped landing when all legs ran) | qa run 7 |
| `test_gated_first_read_leg_overflow_never_returns_but_other_legs_survive` | RED-FIRST | kills the too-low mutant "cursor = last delivered leg row" (qa MUST: the 16-cap × L1 quadrant) | qa mutation run |
| P3 `test_leaked_hold_env_without_armed_is_inert` | RED-FIRST | mutation: drop the arm gate ⇒ thread parks (daemon exits clean) | lane + qa run 2 |
| P3 `test_armed_hold_env_parks_until_release` | GUARD | killer is the OPPOSITE mutant env-hold-never-parks (qa run 3b: armed red, leak green) — one mutation per pin, not one for both | qa runs 3a/3b |
| P5 `test_first_pre_llm_call_consumes_and_injects_exactly_once` | **PIN/GUARD** (reclassified — qa run 5: green-before; the old `pre_llm_inject_context` also live-read first turn, and the test never fires the old start arm) | regression killer: `test_register_wires_the_delivery_callbacks_onto_their_events` (`starts == [drift_notice]`, red on old code) | qa runs 5 + reclass |
| P5 `test_a_session_that_never_reaches_pre_llm_call_consumes_nothing` | RED-FIRST (shape) | red via `hasattr(hooks, "_bus_pending")` wiring pin, not the consumption behaviour (the retired start arm can no longer be fired); the behavioural half is green-before | qa audit |
| P4 never-turns + context-once E2Es | RED-FIRST (wiring) | red via seam absence: `router.sessionStart === undefined`, missing `router.context` (4 of 11 JS tests fail on the old bridge) | qa audit |
| P9 `test_own_broadcast_never_re_delivers_across_id_drift` | RED-FIRST | env-revert: old env leg misses ⇒ ancestry resolves the task-tracked row ⇒ wrong sender ⇒ delivery half red too | lane + qa run 4 |
| P9 `test_session_env_vars_first_set_wins_in_tuple_order` | GUARD | kills reorder/dict mutants of `SESSION_ENVS` (two-env-set is the id-drift shape, not a corner) | qa MUST 2 |

Corrections recorded after qa's audit (d-210): the original lane note "drop-arm-gate ⇒
both hold pins red" was **wrong as stated** — each hold pin has its own killer mutant,
listed above. The P5 reclassification and the shape-vs-behaviour red mechanisms are
also reflected in the test docstrings amended in this commit.
