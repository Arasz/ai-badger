# Research consolidation — aib-bus-followups-independence

**Date:** 2026-09-01 · **Effort:** high · **Lanes:** A architect (resolver/scaffold, d-176), B test-engineer (store containment/doctor, d-177), C qa (bridge/hold/spec/docs, d-178) — all read-only, evidence in:
`research-a.md` (resolution + L1) · `research-b.md` (M2 + doctor) · `research-c.md` (defer + hold + spec + docs) — same directory.

## Owner rulings (final, from the 2026-09-01 owner gate)

| # | Item | Ruling |
|---|---|---|
| 1 | M2 | Per-family containment in `_open` **+** doctor/den-refresh detect-and-repair |
| 2 | D2/L1 | Resolver off the raccoon bank — "where there is `.ai-badger`, there is a project"; id minted at scaffold, **den-refresh backfills**; `AI_BADGER_PROJECT_ID` override wins; nested-`.ai-badger` ambiguity refuses; L1 cursor lands max-over-delivered-legs |
| 3 | D3/L2 | `_hold_at` consultation stays shipped; env hold honoured **only when a second arm env (test preconfiguration) is set** |
| 4 | D4/L4+L5 | Defer the start-spawn so read+inject coincide — pi **and** Hermes (C found Hermes' `pre_llm_call` return channel is the cheaper seam); pinned scenario "pi session start delivers" amended |
| 5 | D5/L6 | Copilot `sessionEnd` residual-risk line → changelog P5–P8 (:37-38) |
| 6 | D8/L8 | Machine-local trust boundary → changelog P3 (:25-28) + SKILL.full.md "Sender identity is mandatory" (:49) |
| 7 | D9/L7 | Copilot `adjust_hooks` emits the `if -f` guard (reuse `guarded()` shape from `hook_wiring.py:61-75`) |

## Hard constraints the plan must respect (cross-lane)

1. **Byte-equality copies**: `engine/badger_store.py` is canonical for `VENDORED_PATHS` (16 destinations) + 12 scaffolded mirrors (~33 total). No automated copier exists (vendorin pending); precedent is same-commit hand re-landing (c7424c6f) + `tooling/sync_plugin_skills.py` for skills/ mirrors; gate = `tests/test_badger_store_vendored.py:25-27`. Every store change re-lands all copies same-commit.
2. **Contract guardrails (containment)**: ADR-0024 D5c — "Silent divergence is never an option". Contained map/kvdoc/awm families may NOT degrade to silent DB-only reads + allowed writes; the condition must surface on access. Append-only kinds: the written contract says *re-import* (file-schemas.md:45, :265) — the code today is stricter than written (raises at :1334); the doctor may reconcile this. Existing task-family test survives iff family-scoped reads still raise.
3. **Arm-env constraints (hold)**: exactly two seams (`deliver.entry`, `deliver.after_read`); the E2E arms the **vendored** copy's `deliver.after_read`; six constraints from research-c §3 (arm env in `_child_env` + store-level arming test, all six strip lists, `_TEST_HOLDS` stays ungated, gate in both engine+vendored, seam-prefix check survives).
4. **Spec surfaces**: the `.feature` is gitignored (untracked) — amendments change it AND the tracked scenario-title mirror (`test_message_bus_integration.py:466-501`); Rule 8's Gherkin never names the registry, so D2 changes owning tests, not scenario text; Rule 7 sc.1's timing wording DOES change.
5. **L1**: fix only the `project_id=None` first-delivery branch (`:1766-1773`); keep global `MAX(id)` when all legs ran (pinned overflow guarantee `test_message_bus_store.py:545-559`); **no red test exists today** — TDD writes one first (seed broadcast + 1:1, deliver with `project_id=None`, re-deliver, expect the broadcast).
6. **Scaffold**: config.json is rewritten wholesale every run (`scaffold.py:740-742`), no read-back merge; schema `additionalProperties:false`; refresh does NOT rewrite config (#172) but validates it (`refresh.py:336-350`); backfill fits between `check_prerequisites` and `re_scaffold` (`refresh.py:191-230`). Id-less repos are a permanent fleet state — resolver behavior for "id absent" is a first-class case, not a migration window.
7. **Copilot guard**: quoted-path balance pinned (`bash.count('"') % 2 == 0`); ~10 pinning assertions in `test_adjust_hooks_copilot.py` need amending; shape (a) rewritten commands need the script path carried alongside the rewrite; shape (b) glob fallback already has `rel_path` in scope.
8. **pi defer delta**: removes `sessionStart` arm + `pendingStart` + held-consume branch; `beforeAgentStart` becomes an unconditional live read; a never-turned session consumes nothing. Five adapter tests amend (`pi_message_bus_adapter.test.mjs:97,:137,:193,:266,:293`). Hermes defer drops `on_session_start_message_delivery` + `_bus_pending`; first `pre_llm_call` becomes consume-and-inject; `on_session_end` keeps cursor deletion.
9. **L7 moot**: the `registry_snapshot` claim is absent from the on-disk changelog — no fix needed.

## Consolidated open decisions (plan proposes w/ rationale; owner-level ones flagged)

- **File shape for the minted id** — config.json field (schema+merge+hash churn, gated) vs dedicated `.ai-badger/project-id` file (zero churn, ungated). *Owner-relevant.*
- **Id format** (uuid4 vs derived) and mint location in `scaffold.py run()`. *Owner-relevant (format).*
- **"Id absent" behavior** — None (env-only delivery) vs refuse. *Owner-relevant.*
- **Walk policy** — nearest-`.ai-badger`-wins on the upward walk vs refuse when an ancestor also carries one; fate of `ProjectIdAmbiguous`.
- **Raccoon surface disposal** — delete outright vs one-release deprecation shim; three test files' bank fixtures.
- **Read-side containment semantics** per kind — refuse-on-access (keeps task-family test green) vs surfaced DB-only; write refusal shape (hard refuse + upgrade pointer).
- **Detector placement** — open-time detection recording per-family unavailable state vs per-accessor checks.
- **Doctor home** — `badger_store.py main()` subcommand (ships via copies) vs den-refresh script vs both; targets machine user root and/or project tracking root; auto-repair scope (re-import additive kinds vs inspect-only for map/kvdoc/awm); whether a `vendorin` copier lands with this change.
- **Arm env name**; gate placement (env branch only).
- **Rule 7 sc.1 wording** post-defer; whether Hermes defer is same-release or documented-only.
- **Guard reuse** — import/copy `guarded()`; whether the "skipped" systemMessage is wanted in Copilot JSON.
