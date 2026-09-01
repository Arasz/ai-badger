# aib-bus-defer-cursor-followups — continuation scope (2026-09-01)

Continuation of `aib-bus-followups-independence` (PR #463, merged as 0.157.0). The plan of
record is `docs/work/2026-09-01-aib-bus-followups-independence-plan.md` **rev 2.1**
(MoE-authored, MoE-reviewed: all sections DISPATCH-READY-WITH-CHANGES, 9 MUSTs folded) —
its remaining, unshipped packages are this task's scope:

| Pkg | Content | Store commit? | Execution |
|---|---|---|---|
| L1 | Leg-scoped cursor (max-over-delivered-legs) in `_read_addressed` region (:1766-1773); R1a seeds 1:1 BEFORE broadcast; R1b/R1c semantics + R3a/R3c/R3d mutation pins | yes | in-orchestrator, TDD red-first |
| P3 | D3 arm-env gate: `AI_BADGER_TEST_HOLD` honoured only when `AI_BADGER_TEST_HOLD_ARMED` also set (`_hold_at` env branch only; `_TEST_HOLDS` ungated) | yes (same commit) | in-orchestrator |
| P4 | pi defer start-spawn: `before_agent_start` + per-turn `context` event (docs/extensions.md :285-318) so mail lands between tasks | no | subagent |
| P5 | Hermes defer: first `pre_llm_call` reads mail, transaction semantics preserved | no | subagent |
| P9 | Self-delivery fix: send-side derivation in `send_message.py` (NOT vendored); red test: own broadcast never re-delivers across id drift (d9e90bb1 vs 01a05c6d, msg id 11) | no | subagent |
| P8 | Integration: defer + cursor + containment cross-package tests | yes | in-orchestrator |

Rulings carried from the owner gate (FIXED, no re-litigation): D3 env-pair shape; D4
defer-start-spawn on pi AND Hermes; R9/P9 send-side fix. Plan rev 2.1 appendices are
superseded where they contradict it.

Store-ceremony invariant (one commit): any `engine/badger_store.py` change re-lands all 16
`VENDORED_PATHS` copies + `python3 tooling/sync_plugin_skills.py` + re-scaffold of this
repo's own mirrors + re-runs `tests/test_badger_store_vendored.py` (`vendored_copies_report()`
== []). Pre-commit scaffold-freshness guard blocks commits that skip it.

Lanes: pytest via `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest`
(worktrees have no .venv). The memory-first-gate hook notice at lane start is non-fatal.
Delegation reduction note: L1+P3 run in-orchestrator (rehearsed ceremony, prior lane stall
cost ~300k tokens); P4/P5/P9 still dispatch to isolated subagents; Phase 4 MoE review + QA
unchanged.
