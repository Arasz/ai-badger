# Plan review — code-reviewer lane (adversarial correctness pass)

Target: `2026-09-01-aib-bus-followups-independence-plan.md` + plan-architect/-tests/-harness + research-a/b/c.
Method: two passes — logic/feasibility read, then mechanical source verification of every claim a finding depends on (worktree HEAD). Line pins below were read, not trusted.

## MUST (plan is wrong or incomplete — blocks implementation dispatch)

**M1 — Containment semantics: the join and its test appendix specify different semantics, and the "skip" variant weakens a read path that raises today.**
Decision register: "Refuse-on-access uniformly for all non-store kinds" (plan, Containment row). plan-tests §2: "File-set kinds: open succeeds, legacy reads skip, writes refuse." These contradict. Source: `_legacy_rows`' kv_glob branch calls `_raise_on_family_resurrection` before merging (`engine/badger_store.py:889`) — file-set legacy reads RAISE today; "skip" silently downgrades them to DB-only while a newer legacy file exists, the exact shape research-b §3 flag 2 ruled out for map/kvdoc/awm. Fix: make file-set legacy reads refuse too (matches the register and the untouched-pin precedent), or justify skip + open-state surfacing and reword the register to per-kind-group semantics. (jsonl/recent "reads already DB-only" is factual — `log_rows` :1265-1276 has no legacy merge; only the register's "uniformly" wording overreaches there.)

**M2 — Same-table neighbour trap: the statusline pair, and an AC that reads as per-table skip.**
`_task_families` registers `statusline` and `statusline_delegate` on the SAME table "statusline" (`features/common/skills/task/scripts/tracker_lib.py:425-433`), and `tracking_transaction` migrates whole tables (:461-472). plan-tests §2's tasks row says "`tracking_transaction` skips only the contained table" — implemented literally, containing statusline-state skips the delegate's migration and (via `migrate` → `_migrate_family`) can refuse delegate writes: neighbour damage the plan itself forbids. No named test pins the pair (tier-1 sweep's neighbour observable is only the bus; the tasks tier-2 test uses single-family tables). Fix: state the guard is per-family inside `migrate`/`_migrate_family`/`_legacy_rows` (all already iterate `_families_for_table`), and add a test: contain statusline-state ⇒ delegate `kv_set`/read succeeds.

**M3 — P2 retires `ProjectIdAmbiguous` but two callers reference it; their edits and copy re-lands are unlisted.**
`features/common/hooks/message_delivery_hook.py:82-83` (`except badger_store.ProjectIdAmbiguous: return None`) and `features/common/skills/send-message/scripts/send_message.py:148-151` (`except ... as exc: ... exc.candidates`) — lazy attribute references, so no import-time break, but the except expressions are evaluated whenever anything propagates out of the resolver (e.g. OSError on the new walk): deletion turns them into AttributeError-during-handling landmines, and the send CLI's ambiguity refusal path dies unspecified. P2's Files list has neither file (nor the send-message hook copy that must re-land with it). Fix: add both callers to P2 (drop/replace the except clauses; specify send-CLI behavior for the retired refusal) and account for their vendored copies.

**M4 — P2's test-conversion inventory misses the files that resolve projects through the bank in hook-level tests; the flagship E2E goes red at P2.**
The exactly-once E2E registers a bank (`tests/test_message_bus_integration.py:221` `_register_bank(... {"bus-proj": [repo]})`), seeds `target_project="bus-proj"` (:243), and passes `env[RACCOON_BANK_ENV]` to both children (:196) — under the new resolver the children resolve None and inject nothing (`assert len(injected) == 1` fails). Same for `tests/test_message_delivery_hook.py` (bank fixture :103-116, child pass-through :673, and the subdirectory/unresolved/ambiguous + Rule 4 project-delivery tests :19-26, :247-326) and `tests/js/pi_message_bus_adapter.test.mjs` (`AI_BADGER_RACCOON_DB` redirect :228, `target_project` sends :249). None is in P2's conversion list (plan P2; plan-tests §3 lists registry/send/manifest/hermes only). The local `RACCOON_BANK_ENV` constants are test-defined, so nothing NameErrors — the failure is behavioral and lands mid-serial-lane. Fix: derive the conversion inventory mechanically (grep `RACCOON_BANK_ENV|_make_bank|ingest.scope` across tests/ and tests/js), assign every hit to P2.

**M5 — The hermes `:362` ambiguity test's conversion target contradicts the join's own walk policy.**
Join: nearest-wins, no ancestor refusal, "`ProjectIdAmbiguous` retires" (Decision register; P2 omits R3b). plan-tests §3: ":362 → mechanism becomes nested-`.ai-badger` refusal caught by the wiring (same 1:1 fail-open shape, kept)" — a refusal the join abolished, "caught by the wiring" that M3 deletes. An implementer authoring red-first tests from plan-tests will build behavior P2 removes. Fix: specify :362's fate — delete, or convert to "nested dirs resolve to the nearest; delivery proceeds to that project" (and repoint the Rule 8 mutation flags accordingly in P8).

## SHOULD (fix before or during the package)

**S1 — L1 fix has a seeding-order trap and an unrecorded residual loss.** Minimal fix = cursor `max(id of delivered rows, 0)` (plan-tests §1). A broadcast with id BELOW the max delivered 1:1 id is still consumed forever (second delivery reads `id > cursor`). R1a as written ("seed one broadcast + one 1:1") is only green if the broadcast's id exceeds the 1:1's — seed broadcast-after-1:1 or bracket it with two broadcasts, else the red test stays red after a correct fix. Record the interleaving residual in the changelog (or rule a per-shape cursor, out of scope).

**S2 — 11 `.ai-badger/` mirror copies are outside every gate the plan's R1 relies on.** 33 tracked `badger_store.py` files: 16 gated by `VENDORED_PATHS` (:303-332; only `.ai-badger/skills/worktree-agent-isolation/...` among mirrors), root `skills/` mirrors by `sync_plugin_skills.py --check` (TARGET = skills/, tooling/sync_plugin_skills.py:30; `.ai-badger` deliberately out, comment :49) — leaving `.ai-badger/engine|hooks|skills/*/scripts` (11 files) hand-landed with no check. This repo's own live scaffold is the ungated surface. Fix: add the 10 missing destinations to `VENDORED_PATHS` (absent-file skip keeps consumer repos safe) or an equivalent check, in P1.

**S3 — Doctor for the incident's actual family (map) is report-only with no decision support.** commit-reminder is `legacy_kind="map"`; `--repair` is inspect-only there (plan AC). file-schemas.md :44-46/:264-266 promises fail-closed-with-upgrade-pointer for map families — fine — but research-b's own repair analysis says map salvage needs an owner-visible diff first. Have `doctor --status/--repair` emit a per-key content comparison (DB rows vs legacy file) so the printed remedy ("restore `*.migrated.*` or den-refresh") becomes decidable, not just repeatable.

**S4 — The den-refresh `doctor --status` pre-flight is orphaned.** Decision register claims it; P1 lands the verb in `badger_store.py main()`, P2 edits `refresh.py` only for backfill (:191-199/:213-230). No package owns the refresh.py wiring or a test for it. Assign it (P2) or drop the claim.

**S5 — Fleet-transition regression is named only for worktrees (R4).** Every repo that resolved via the raccoon bank pre-release resolves None post-P2 until den-refresh backfill — send CLI refuses ("missing sender identity"), delivery goes 1:1-only. That is the ruled D2 cost, but the changelog consumer-impact section should say it explicitly; today only the worktree/stale-id case is covered.

## NOTE

- The "~33 copies" claim is accurate: 33 tracked `badger_store.py` files (32 copies + canonical), 16 manifest-gated.
- P1→P2 seam checked and clean: containment never touches `messages`/`cursors` (born-in-SQLite, skipped at `_check_resurrections` :920-921); L1 is cursor arithmetic in `deliver_for_session` (:1766-1773 verified — global `COALESCE(MAX(id),0)` in the `row is None` branch); the P8 coexistence test covers the combined state.
- Verified accurate: `_hold_at` :97-106 with ungated `_TEST_HOLDS`; `_open` gate at :2015; `prune --status` ro pattern :2060-2094; hermes `_bus_pending` :956-958, `pre_llm_call` return channel :635-639, register() :1152-1157; hooks-manifest hermes session-start arm :39 (drift-notice arm :16 stays); `test_pi_hook_arm_coverage_contract.py` three-key/:237 and three-subscription/:262 pins; task-family pin :411-422 requires read-refusal (drives M1's resolution); send CLI None → refusal is pre-existing behavior, preserved.
- Arm-env name: join's `AI_BADGER_TEST_HOLD_ARMED` supersedes the architect appendix's `…_ARM` — the join already notes this; no action.

## VERDICT

DISPATCH-READY-WITH-CHANGES — the architecture, ordering, gates and red-first spine are sound and the evidence base checks out, but dispatch of P1/P2 must wait for:

1. M1 — one containment semantic per kind group, kv_glob reads refuse (or a justified, register-amended skip).
2. M2 — per-family guard stated (not per-table skip) + a statusline-pair neighbour test.
3. M3 — message_delivery_hook.py and send_message.py caller edits added to P2 with their copy re-lands.
4. M4 — mechanically derived bank→id-file conversion inventory covering test_message_bus_integration.py, test_message_delivery_hook.py, and the JS adapter tests, assigned to P2.
5. M5 — :362's conversion target specified consistently with nearest-wins (delete or convert).
