# R1 implementation review — correctness (adversarial)

> **Recovery note.** The review panel's report (delegation `d-23`, code-reviewer, 2026-09-28) was
> tee-elided in transit: every available surface (the transcript, the delegation cache) drops the
> opening ~5.7–7.6k characters, so the panel summary and the full text of findings 1–2 survive only
> in distilled form below (marked `[reconstructed]`), reconstructed from the reviewer's own verdict
> sentence and the fix-wave punch items they produced. Findings 3–10 and the closing sections are
> verbatim from the receipt. Dispositions were verified against the merged tree after the fix wave.

**Verdict (verbatim): MERGEABLE AFTER MUSTS** — the graph/CAS/wave/parser core is correct and well
pinned; find 1 is a real crash on the protocol surface with a small byte-stdio fix, and findings
2–5 should land in the same pass.

## Findings

**1. MUST — a crash on the protocol surface: non-UTF8 stdin bytes** `[reconstructed]`
A peer writing invalid UTF-8 on the server's stdin raised an unhandled traceback
(`task_graph_server.py:1294`, reproduced with `\xff\xxfe` input) instead of a JSON-RPC `-32700`.
The verdict's "small byte-stdio fix" names it. **Disposition: fix-lane A1** — `serve()` reads
`sys.stdin.buffer` and decodes per line with `errors="replace"`; invalid bytes answer `-32700` and
the loop survives (pinned by `test_non_utf8_stdin_bytes_get_an_error_and_the_loop_survives`; the
CLI arg path got matching fault-tolerant decode in A2).

**2. `[body lost to elision]`** — surviving tail fragment (verbatim): *"…ode `store-error`) for rows
that were not written by this server."* — a refusal-mapping/foreign-row finding. **Disposition:
folded into fix lane A's punch list** (A3's store gating and the A-lane refusal pins cover the
named surface).

**3. SHOULD — the Jev advisory is unreachable from the skill that is supposed to use it.**
`features/common/skills/task-decomposition/scripts/jev_choice.py:1` versus
`features/common/skills/task-decomposition/SKILL.md` and
`references/{decomposition-method,mcp-plan-tools,plan-vocabulary}.md`.
- Witness: `grep -rn "jev_choice\|AI_BADGER_JEV" features/common/skills/task-decomposition/ --include="md"` → no hits. DR9 makes the advisory skill-side ("the skill post-processes `steps_ready` output with hints"), but no skill instruction names the module, the `AI_BADGER_JEV`/`AI_BADGER_JEV_TIER`/`AI_BADGER_JEV_WAVES` flags, or the apply rule. An agent following the skill can never turn it on; the changelog is the only documentation.
- Fix: add a short opt-in section to `references/decomposition-method.md` and pin it in `test_task_decomposition_contract.py`.
- **Disposition: fix-lane B1** — `__main__` CLI + skill wiring + contract pins (red/green in the B1 evidence).

**4. SHOULD — four of twelve step reports are committed as zero-byte files.**
`docs/work/impl-reports/{s4-jev,s5-ops,s6-plan-store,s7-transports}.md` (all `0` bytes). The plan's per-step gates require pasted RED output for S4–S7; an empty file reads identically to a complete one — the drift the derive-or-delete invariant exists to prevent.
- Fix: write the four reports, or delete the placeholders and record the dispensation; a small gate deriving the expected report list would prevent the same hole next task.
- **Disposition: closed post-merge** — the four reports were recovered verbatim from the `d-13`…`d-16` delegation receipts (their own tee-elision was the cause) and committed on the follow-up branch (`595c33e6`).

**5. SHOULD (operational) — the branch's committed v3 scaffold has poisoned the machine user DB.**
`.ai-badger/hooks/badger_store.py` at HEAD has `SCHEMA_VERSION = 3`; hooks loaded from the worktree upgraded `~/.ai-badger/ai-badger.db`.
- Witness: `user DB stamp: ('3',)`, `plans table: ('plans',)`; `~/.ai-badger/hook-errors.log` 5 549 entries, latest `message_delivery_hook OperationalError at badger_store.py:461: store schema version 3 is newer than this code knows (2)`. This is plan risk R-D realized a second time; the "all gates green" claim is false in this environment.
- Fix before merge: repeat the documented recovery (drop the leaked empty `plans` table, stamp 2) or `den-refresh` every checkout; longer term keep the *user* DB upgrade behind an opt-in.
- **Disposition: fix-lane A3 at the root** (`NON_TRACKING_SCHEMA_VERSION = 2`; target-by-kind DDL; leaked-stamp-3 tolerance pinned) + user-DB recovery at the fix-wave join + **ADR-0032** records the rule.

**6. NIT — `plan_get` silently lost P2-B1's optional `revision` filter.**
`PlanGetInput` has only `include` versus `plan-sections/p2-api-contract.md:31` (`PlanRef` · `include`, `revision`); a caller passing `revision` gets `invalid-arguments` for a documented input. **Disposition: fix-lane A8** — `revision` restored as a CAS guard (`conflict` with `current_revision`/`expected_revision`).

**7. NIT — `allowed_transitions` carries statuses where P2 promised tool names.**
`task_graph.py:190-198` returns `["in_progress","skipped"]`; P2-B1 line 34 says `["step_start"]`, and P2's list is stale after the DR7 skip amendment. **Disposition: fix-lane A9** — `ALLOWED_TOOLS` mapping, tool names on the wire.

**8. NIT — force-bypass and failure records are dropped by the next write to the same slot.**
The plan document is the only store (no event log): a forced `step_start` override survives only until the step advances; a failed step's reason is gone after its retry. Fix: keep the evidence or state in DR6/DR7 that the slot is intentionally lossy and pin it. **Disposition: fix-lane A10** — the lossy-slot ruling is documented in both docstrings and pinned by `test_force_and_failure_records_live_in_one_lossy_slot`.

**9. NIT — `task_plan_store._load_sibling`/`_load_badger_store` accept any cached module under the bare name** (no `__file__` comparison, unlike the other sibling loaders). Latent, not live (all copies byte-identical). **Disposition: fix-lane A11** — `__file__` guards + private sibling load (which also repaired the global-rebinding regression that lane found and fixed itself).

**10. NIT — the wave advisory's wall-clock scales with plan size** (fresh `Budget` per call; 100-step ready set ≈ 160 s worst case). **Disposition: fix-lane B6** — one shared budget per advisory run, worst-case transport calls pinned at 2.

## Still open (verbatim)

- **Hypotheses not run:** a >memory-sized single NDJSON line is unbounded (`for line in source`); a 20 MB line was handled (`id 1` and `id 2` both answered, `EXIT=0`), so this is a theoretical OOM only.
- `plan_replace`'s DR12 phrase "or `plan_replace` with a note" has no `note` parameter anywhere in P2-B1 or the implementation. Reads as loose prose in DR12 rather than a contract, but worth a one-line resolution in the plan. **(Resolved: B10 deleted the phantom clause and pinned the real contract.)**
- `ac_check`'s no-op replay compares the full stored evidence list, so re-recording the same verdict after an intervening flip appends and bumps revision; matched to the tests, but the docstring's "already recorded" could be read more loosely.
- Payload `updated_at` and the row's `updated_at` come from two clock reads (and different ISO shapes); no observable lie — noted for completeness.
- The R-D recovery was already run once on this machine and did not stick (finding 5). **(Root cause later identified — `open_user()` re-upgrading on every hook load — fixed by A3, recorded in ADR-0032.)**
