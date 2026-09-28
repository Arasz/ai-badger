# R2 implementation review — test honesty + architecture/docs consistency

> **Recovery note.** The review panel's report (delegation `d-24`, qa, 2026-09-28) was tee-elided
> in transit: every available surface drops the opening ~5.5–7.4k characters, so the panel summary
> and finding 1's full text survive only in distilled form below (marked `[reconstructed]`),
> reconstructed from the reviewer's own verdict sentence and the fix-wave punch item it produced.
> Findings 2 (tail)–8 and the closing sections are verbatim from the receipt. Dispositions were
> verified against the merged tree after the fix wave.

**Verdict (verbatim): MERGEABLE AFTER MUSTS** — one MUST: finding 1 (the changelog advertises an
opt-in Jev advisory that no shipped instruction or code path can invoke; DR9's skill-side
post-processing was never wired). Findings 2–4 are SHOULDs that should land before or with the
release finish; 5–8 are NITs. Everything else sampled — the 12-tool freeze on the real wire, CAS
under scheduled interleave, def-erral waves, dual-read status parsing, replayed mutations,
schema/model dual validation, and the layer-purity constraints — holds and was shown able to go
red.

## Findings

**1. MUST — the advertised Jev advisory has no invocation path** `[reconstructed]`
Per the verdict: "the changelog advertises an opt-in Jev advisory that no shipped instruction or
code path can invoke; DR9's skill-side post-processing was never wired." **Disposition: fix-lane
B1** (Jev `__main__` CLI + skill/reference wiring + contract pins) — the same gap R1-F3/R3-F9
independently identified.

**2. SHOULD — `ac_check` drifts from the terminal rule** *(body partially lost; tail verbatim from
here)* …d not guarded.
`references/mcp-plan-tools.md:20` says: *"record passed or failed with evidence while the step is `in_progress`; completion freezes it."*
Evidence (ad hoc spawn, `sys.executable`, tmp tracking root):
```
step_skip s1 -> ok
ac_check on skipped: {"revision": 2, "changed": true, "step_id": "s1",
  "criterion": {"id": "ac1", "status": "passed", ...}, "criteria": {"passed": 1, "total": 1}}
```
The suite itself normalises this drift: `tests/test_task_graph_mcp_server.py:834` calls `ac_check`
right after `plan_create`, i.e. on a **pending** step. DR7 makes `complete`/`skipped` terminal; a
skipped step can now accumulate passing criteria and bump revisions, which contradicts the
terminal rule in spirit even though P2-B1's ac_check row only names `complete`.
Fix: guard `{"complete", "skipped"}` in `_tool_ac_check`, or fix the reference wording to "any
non-terminal step" and note the P2-B1 deviation. Either way docs and code must agree.
**Disposition: fix wave** — the `_terminal_replays` guard plus "non-terminal" reference wording
(verified in the merged tree: `task_graph_server.py:548`).

**3. SHOULD — four of the lane reports are committed empty placeholders, so S4–S7's TDD red
evidence is not persisted.**
```
$ wc -c docs/work/impl-reports/*.md
0  docs/work/impl-reports/s4-jev.md
0  docs/work/impl-reports/s5-ops.md
0  docs/work/impl-reports/s6-plan-store.md
0  docs/work/impl-reports/s7-transports.md
```
`git log --diff-filter=A` shows they were created as 0-byte placeholders at the wave-0/1/2 joins
and never filled. An empty file reads identically to a complete one — this is the drift the
*derive-or-delete-the-list* invariant exists to prevent.
**Disposition: closed post-merge** — recovered verbatim from the `d-13`…`d-16` receipts
(`595c33e6`), same as R1-F4.

**4. SHOULD — `test_blocked_is_empty_when_no_ancestor_failed_or_skipped` is vacuous for its own
fixture.**
`tests/test_task_graph_ops.py:684-690` runs seed 21 and loops `for entry in graph.blocked(plan):
assert entry.blocked_by ...`. Verified seed 21 yields `blocked: []`, so the loop body never
executes and the assertion-less test passes:
```
seed 21 blocked: []
seed 21 statuses: {s0 pending, s1 in_progress, s2 skipped, s3 in_progress, s4 in_progress, s5 in_progress, s6 complete}
seed 3  blocked: []
```
The name claims a property the body never checks. The precise behaviour is covered by
`test_blocked_lists_failed_or_skipped_ancestors_of_remaining_steps:666`, so the false-confidence
cost is bounded.
Fix: assert the real biconditional over several seeds including one where the loop is non-empty,
or delete the test.
**Disposition: fix-lane A12** — the biconditional over seeds 21/5/7/3 (verified at
`test_task_graph_ops.py:698`).

**5. NIT — the generated-corpus conflict invariant is unreachable.**
`tests/test_task_graph_ops.py:356-359` sweeps 15 generated plans for "no wave packs a conflicting
pair", but `_generated_plan` (`:112-134`) never sets `files`/`resources`, so every pair is
conflict-free by construction. Evidence: M4 (`_conflicts → None`) left this test green while its
three siblings failed. **Disposition: fix-lane A13** — the corpus seeds `files`/`resources` and
asserts `conflicts > 0` (which also exposed and fixed the latent `wave[0] ⊆ ready` overclaim).

**6. NIT — P2-B1 (authoritative per §2) and the actual wire disagree on three input shapes.**
```
step_complete: required=[task_id, step_id, expected_revision]   # B1 lists evidence + criterion_results as required
plan_get:      props=[task_id, include]                         # B1 lists optional `revision`
plan_replace:  required=[..., task_description_ref, steps, loop] # B1 marks these "same optionals as create"
```
The server's defaults are sane and the shipped user docs make no counter-claim. It is drift
between the freeze and the wire, not a behaviour bug.
Fix: record the three deviations in the plan/impl report so the next lane reading B1 as verbatim
does not "fix" the service toward P2-B1's stale table.
**Disposition: fix-lane B10** — the "Wire input deviations (R2)" section in the plan records all
three (verified at `2026-09-28-task-decomposition-plan.md:56-58`).

**7. NIT — dead statement in a guard test.**
`tests/test_task_graph_ops.py:555-560`: the first `step` construction is used only by
`assert step is not None`. It cannot fail and confuses the fixture.
**Disposition: fix-lane A12** (deleted).

**8. NIT — unicode is pinned at model/store but not at the transport.**
An ad-hoc spawn shows `Größe — naïve café 日本語 ✓ 🐍` round-trips through `plan_create`/
`plan_get(include:"full")` byte-exactly, but no committed test would notice an `ensure_ascii`/
encoding regression. Fix: one unicode round-trip case in `test_task_graph_mcp_server.py`.
**Disposition: fix-lane A14** — `test_plan_get_full_round_trips_unicode_bytes` with exactly this
fixture string (verified at `test_task_graph_mcp_server.py:532`).

## Still open (verbatim)

- **Host smoke not reproducible here (per O1 this is an owner-performed acceptance check).** The MCP-shape half is verified mechanically (real pipes, `initialize`/`tools/list`/`tools/call`); launching under Claude Code/pi is out of scope for this lane.
- **Environmental failure, not a branch defect:** the R-D teardown error (`conftest.py:256`) — user DB at schema v3 while pre-0.179 hooks run in this machine's sessions. "This is exactly plan risk R-D's condition (re-occurred after the recorded recovery); the branch's own suites are tmp-pinned and green." **(Root cause later identified and fixed — see ADR-0032.)**
- **Not verified, by design:** live OpenRouter calls (loopback stub only; no key), and `uv run --script` on a cold cache (recorded as owner-performed per R2-F18/R3-F3).
- **Nuance for the next reviewer:** in the pytest process `task_plan_store._load_badger_store()` returns the already-imported canonical `engine/badger_store.py`, so `test_task_plan_store.py`'s store is not the shipped sibling — the shipped copy is covered by the subprocess server tests plus `test_vendored_copies_report_is_empty`. No defect found, but the suite's test map overstates "vendored" coverage.
