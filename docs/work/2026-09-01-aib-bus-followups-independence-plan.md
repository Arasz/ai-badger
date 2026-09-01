# Plan — aib-bus-followups-independence

**Date:** 2026-09-01 · **Effort:** high · **PR:** #463 (draft) · **Branch:** `task/aib-bus-followups-independence`
**Basis:** owner gate 2026-09-01 (7/7 ruled; reconciliation in main tree `docs/work/`) + research lanes A/B/C + plan-authoring MoE (architect / test-engineer / harness-author — their files are appendices beside this one).
**Gates (repo):** `python3 -m pytest -q` · `python3 tooling/index_build.py --check` · `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')` · `bun test features/pi && bun test tests/js/` · `python3 tooling/sync_plugin_skills.py --check`.

## Decision register (authoring MoE resolutions; ⚑ = owner confirmation requested)

| Decision | Resolution | Rationale (one line) |
|---|---|---|
| ⚑ File shape | Dedicated `.ai-badger/project-id` file | config.json is rewritten wholesale (scaffold.py:740-742) with `additionalProperties:false` — field ⇒ schema+merge+hash churn; file ⇒ zero churn, survives config deletion |
| ⚑ Id format | uuid4, minted in `scaffold.py run()` before the config write | repoAlias-derived ids collide across clones |
| ⚑ Id absent | Return None (fail open to 1:1/env-only) | id-less repos are a permanent fleet state; hooks already fail open (D8) |
| ⚑ Walk policy | **Nearest `.ai-badger` wins on the upward walk; no ancestor refusal** | refuse-on-ancestor would break every worktree session (worktree `.ai-badger` inside repo `.ai-badger`); nearest is deterministic, not a guess — the owner's "nested ambiguity refuses" ruled the raccoon-registry overlap, which has no analog here; `ProjectIdAmbiguous` retires with the registry |
| Raccoon disposal | Delete outright: `raccoon_registry_surface`, `RACCOON_BANK_ENV`, `AI_BADGER_RACCOON_DB`; reader tests 11-13 deleted | no caller survives D2; a shim keeps dead code + three bank fixtures alive for nothing |
| Containment semantics | Refuse-on-access uniformly for all non-store kinds; open-time detection records per-family unavailable state, accessors consult it | satisfies D5c "surface on access"; keeps test_badger_store_task_family.py:411-422 green unamended; one semantic instead of six |
| Doctor | `doctor` subcommand in `badger_store.py main()` (`--user` default, `--project PATH`); den-refresh runs `doctor --status` pre-flight; repair re-imports additive kinds (jsonl/recent/file-sets), inspect-only for map/kvdoc/awm; no `vendorin` copier this change | rides the vendored copies to user machines; reconciles code with file-schemas.md:45/:265 |
| Arm env | **`AI_BADGER_TEST_HOLD_ARMED`** (authoring variant `…_ARM` superseded); gate in `_hold_at`'s env branch only; `_TEST_HOLDS` ungated | prefix-consistent with `_TEST_HOLD_ENV`; scope matches ruling 3 exactly |
| Rule 7 sc.1 | Reword: "pi delivers on the first agent turn" — `.feature` + tracked mirror (:466-501) | stale Gherkin would contradict shipped behavior |
| Hermes defer | Same release as pi | ruling 4 names both; Hermes' `pre_llm_call` seam is cheaper, not riskier |
| Copilot guard | Copy the guarded shape (`_guarded(cmd, script_rel)`), single existence branch, systemMessage-on-skip kept; `_rewrite_command` returns `(cmd, script_rel)` | imported `guarded()` is `${CLAUDE_PROJECT_DIR}`-parameterized and would silently skip; features/ ship independently |

## Packages

**Serial store lane — strictly ordered (all touch `engine/badger_store.py`; every store commit re-lands ~33 byte-identical copies + `sync_plugin_skills.py`, c7424c6f precedent):**

- **P1 — Store containment + doctor (M2).** `_open` records per-family unavailable state instead of aborting store-wide; accessors of a contained family raise the resurrection error (upgrade pointer); neighbours exactly as today. `doctor --status/--repair` verb (read-only `prune --status` pattern, :2060-2094).
  Red-first (plan-tests §2): rename both fail-closed tests to contained-open shapes (:597-619, :347-361); tier-1 parametrized neighbour sweep derived from the family registries (derive-or-delete); tier-2 per-kind-group tests (map, kvdoc/awm, jsonl/recent, tasks/usage/sessions, file-set ×5) each asserting a neighbour observable; untouched pins: task_family:411-422, test_p4_integration.py:310-345.
  ACs: contained map family ⇒ open succeeds, `kv_get` raises with upgrade pointer, `kv_set` refuses, neighbour families normal (per kind group); `doctor --status` names family/stamp/mtime without creating or migrating; `doctor --repair` re-imports a jsonl family idempotently and is inspect-only for map; vendored report empty.
  Gate: full pytest + pylint + vendored gate. **Subagent lane.**
- **P2 — Resolver independence + mint + backfill + L1 (D2/L1).** ⚑-gated start. Resolver walks up to the nearest `.ai-badger`, reads the id; env override wins; id absent → None; `ProjectIdAmbiguous` retires. Scaffold mints uuid4 pre-config-write; den-refresh backfills between `check_prerequisites` (:191-199) and `re_scaffold` (:213-230). L1: the `row is None` + `project_id is None` branch lands the cursor at max-over-delivered-legs (:1766-1773); global MAX(id) kept when all legs ran.
  Red-first (plan-tests §1/§3): R1a/R1b/R1c (None-cursor red test + cursor observable + over-tightening guard); R3d sibling walk mutation-killer; R3c id-absent; override-wins via throwing-walker fake; bank-fixture conversions per file (registry 1-10 convert, 11-13 delete; send CLI :382; manifest :33/:68/:140-150; hermes :345/:362 mechanism-only).
  ACs: R1a green (broadcast survives a None first delivery, re-surfaces on second); pinned overflow :545-559 + gate-once :492-510 stay green; nearest-wins + sibling-refusal + id-absent + override cases green; scaffold mint preserved across re-scaffold; den-refresh backfills an id-less repo; raccoon surface symbols gone (assertion test).
  Gate: full pytest + vendored gate + `sync_plugin_skills.py --check`. **Subagent lane.**
- **P3 — Arm-env hold gate (D3).** `_hold_at` env branch gated on `AI_BADGER_TEST_HOLD_ARMED`; `_TEST_HOLDS` ungated; seam-prefix check survives.
  Edits/tests (plan-tests §4, harness §3): `_child_env` sets both; store arming test :852-865 sets both; strip lists :75/:194, manifest :83/:411, hook :85/:671 gain the arm env; NEW leak witness `test_a_leaked_hold_env_without_the_arm_env_does_not_park`; E2E still parks and releases through the **vendored** copy; shipped-pair identity pin :419 green.
  Gate: bus-store + integration suites, then full pytest. **In-orchestrator (one branch + strip lists).**

**Parallel lanes — disjoint files, start immediately:**

- **P4 (lane X) — pi defer (D4).** Remove `sessionStart` from the router interface entirely (single caller, compile-enforced); delete `pendingStart`, held-consume branch, `pi.on("session_start")` wiring, `"session_start"` from the event map; `beforeAgentStart` = one unconditional `liveTurn`; state-machine docstring rewritten; absent-script silent-empty + away/payload gates preserved.
  Red-first (plan-tests §5): five adapter test amendments (:97/:137/:193/:266/:293) + NEW never-turned-session-consumes-nothing (no spawn, no cursor row, mail intact); `test_pi_hook_arm_coverage_contract.py` :237/:262 amended to the two-event shape, :90-236 untouched.
  Gate: `bun test tests/js/pi_message_bus_adapter.test.mjs && bun test features/pi && bunx tsc --noEmit -p features/pi` + pytest pi/integration files. **Subagent lane.** Merge after P3 (shared test file, disjoint hunks).
- **P5 (lane Y) — Hermes defer (D4).** Drop `_bus_pending` + `on_session_start_message_delivery`; `_bus_turn_context` becomes live-read-only injected via the `pre_llm_call` return channel; `on_session_end` keeps cursor deletion; manifest hermes session-start arm removed; register() trims the delivery hook (drift notice stays).
  Red-first (plan-tests §5): first-`pre_llm_call` consume-and-inject (context contains mail, cursor row once, turn 2 live-only); NEW never-reaches-`pre_llm_call`-consumes-nothing (no cursor row, no stash leak); close-event pin untouched; :345/:362 fail-open shapes kept.
  Amended pins per harness §2 (:90-91, :169-172, :182+, :299/:404/:409/:442, manifest :171-200/:374/:386); `test_hermes_plugin_payloads.py` stays green.
  Gate: `python3 -m pytest -q tests/test_message_bus_hermes.py tests/test_message_bus_manifest.py` then full. **Subagent lane.** Merge after P2 (shared test file, disjoint regions).
- **P6 (lane Z) — Docs (D5/D6).** Exact sentences drafted (harness §5): changelog P5–P8 Copilot `sessionEnd` residual-risk clause; P3 machine-local trust-boundary lines; P4 consistency amendment (hold sentence names both envs); SKILL.md "Sender identity is mandatory" paragraph in the features/ catalog → `sync_plugin_skills.py` → re-land this repo's `.ai-badger/skills/send-message/` mirror same-commit. D9/L7 dropped as moot.
  Gate: `sync_plugin_skills.py --check` + `tests/test_sync_plugin_skills.py` + changelog/skill lint tests. **In-orchestrator (prose).**
- **P7 (lane W) — Copilot `if -f` guard (D7).** `_guarded` wrap for both emission shapes; `_rewrite_command` → `(cmd, script_rel)`; balance pins :210/:384 and artifact E2E :555-565 stay green; ~10 pins amended (plan-tests §6 list); NEW `test_guarded_command_skips_cleanly_when_the_script_is_absent` (exit 0, skipped systemMessage).
  Gate: `python3 -m pytest -q tests/test_adjust_hooks_copilot.py`. **Subagent lane.**

**P8 — Integration (last, no production edits).** New `test_project_id_lifecycle.py` (scaffold → mint → resolve; strip id → den-refresh backfill → resolve; env override wins); new `test_containment_bus_coexistence.py` (resurrected marker-state ⇒ bus send/receive works, family refuses on access, `doctor --status` names it); E2E race re-run with the arm-env gate through the vendored copy; spec-mirror reconciliation (sc.1 timing, Rule 8 titles + mutation-flag repoint :576/:579-581); VERSION bump + new changelog entry.
Full gate sweep: pytest, index_build --check, pylint, bun suites, sync --check. **In-orchestrator.**

## Parallelism & order

P1 → P2 → P3 serial (shared file + copies). P4/P6/P7 start immediately (disjoint); P5 starts immediately too (store-lane-independent files) but merges after P2; P4 merges after P3. P8 last on the integrated branch. Every store commit = code + all copies + amended tests in one commit; every lane runs its own gate before merge.

## Risk register

| # | Risk | Mitigation |
|---|---|---|
| R1 | Missed copy among ~33 across three serial re-lands → red vendored gate | same-commit re-land + vendored gate + `sync --check` before every store commit |
| R2 | Containment degrades to silent DB-only reads (ADR-0024 D5c violation) | refuse-on-access uniform; red-first raise assertions; task-family test green unamended |
| R3 | ⚑ answers late → P2 blocked | P1, P3–P7 start now; P2 is the only owner-gated package |
| R4 | Worktree sessions under nearest-wins resolve to the worktree project (correct), but stale-id copies of the main repo could diverge ids | ids mint per directory at scaffold/refresh; worktrees get their own mint; changelog consumer note |
| R5 | Strip-list omission leaks the hold/arm env, or inert holds stall the E2E 15 s | six-constraint checklist per AC (P3) + P8 re-run + leak witness test |
| R6 | Copilot guard breaks quoted balance or artifact E2E | balance pins stay unamended as tripwires; `bash -c` E2E in the P7 gate |
| R7 | Resolver rewrite breaks send-message sender resolution | send CLI tests rewritten in P2 with the same fail-open contract |

## Red-witness log (filled during implementation)

One line per new/amended test: red against pre-change code → green after. R1a is the anchor (red against shipped `MAX(id)` today). Mutation witnesses carried: containment-guard revert ⇒ tier-1 sweep + both amended fail-closed tests red; strip one strip-list entry ⇒ child parks; R3d kills the naive walk; strip the guard from one generated row ⇒ :209/:411 amendments red.
