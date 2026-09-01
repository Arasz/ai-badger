# Implementation review — aib-pi-message-bus-push-delivery — QA lane (test-quality & red-witness honesty)

**Date:** 2026-09-01 · **Lane:** qa (review-tests, mutation/oracle lens) · **Target:** branch `task/aib-pi-message-bus-push-delivery` (13 commits ahead of main), the changed/added test files, and the red-witness log.
**Mode:** formal review. READ-ONLY except this file; seven production mutations applied-and-reverted in this worktree (each followed by `git checkout --` and a green re-run); no memory writes; no sub-agents.
**Read:** plan rev 2 (C1–C11, P3 test list, merge gate); plan-reviews/2026-09-01-qa.md (the amended A1–A12 gates); 2026-09-01-pi-bus-push-red-witnesses.md (P1 + Gates 1–4); `features/pi/tests/{bus-prefilter,bus-store,adapter-bus,hook-bridge}.test.ts`; `tests/{test_message_bus_store,test_message_delivery_hook,test_message_bus_integration,test_send_message_skill}.py`; production under test: `bus-prefilter.ts`, `bus-store.ts`, `hook-bridge.ts` (parse section), `index.ts` (bus wiring), `engine/badger_store.py` (C9 guard), `features/common/hooks/message_delivery_hook.py` (`guarded_main`, `_redact_payload_text`); `.lefthook/pre-push/verify.sh` + `.github/workflows/*` (gate wiring); `tests/js/pi_message_bus_adapter.test.mjs`.
**Out of scope (named):** production-code security/layering/performance judgement (code-reviewer's artifact); the pbi repo's own branch review (its state is reported only as merge-gate evidence); live probes L1–L6 (P5 artifacts, not test files); the 44-failure root cause; Windows parity; any wall-clock/p95 claim (none asserted anywhere in this review). The ~30 bun gates beyond the five sampled were reviewed by reading, not by mutation — every such claim below is labeled.

**Baseline (Pass 0, run):** full pytest `5175 passed, 17 skipped, 0 fail` (345 s); `bun test features/pi` → `157 pass, 0 fail` (345 expect calls, 88 ms); `node --test tests/js/pi_message_bus_adapter.test.mjs` → `11 pass, 0 fail`.

---

## Verdict: REQUEST-CHANGES

**The tests themselves are good — that is the headline.** The five highest-value gates each die to exactly their named mutants (six mutation runs below, all reverted); every C-ruling C1–C11 has an owning test; no test asserts pre-revision semantics; the wake routing is NOT a bypass (parse → `DeliveryOutcome.bus` → `mailSummary` → `wakeRoute`, both seam halves pinned); the QA-8 DDL pin runs the shipped probe against a store-created real DB instead of re-implementing the query; no fake timers, no sleeps, no wall-clock assertions anywhere in the new suites.

**What blocks is not test quality but proof wiring:** the entire bun suite — 1,430 new test lines carrying the watermark property, the wake matrix and the DDL pin — is wired to **no gate at all** (B-1), and the required red-witness record for P3 does not exist (B-2). The merge gate's own claim "CI: full pytest, bun+tsc both repos" is false in this repo.

**Summary: 2 blocker, 3 should, 5 note. Rows: 10.** Every mutation below was applied in this worktree, run, and reverted (`git status --porcelain` verified after each; final proof at the end).

## Findings table

| id | file:line | rule | severity | the mutation / claim | run? | what it means |
|---|---|---|---|---|---|---|
| B-1 | `.lefthook/pre-push/verify.sh:61,291–299`; `.github/workflows/*` (absence) | `T1-PRF-04`, `T1-CST-04`, `T0-01` | blocker | `$LANES` contains no bun/tsc lane; `lane_js` runs only `tests/js/*.test.mjs` via node; grep for `bun test\|bunx tsc` over all yml/sh/json/toml hits only `features/pi/package.json:6`'s description | read-verified (grep) | 157 bun tests gate nothing: no push, no CI job fails if `bus-prefilter.ts` regresses. The plan's merge-gate line "CI: … bun+tsc both repos" is unimplemented in this repo |
| B-2 | `docs/work/2026-09-01-pi-bus-push-red-witnesses.md` (no P3 section) | `T1-PRF-01`, `T1-PRF-02(b)` | blocker | merge gate: "Every new gate RED-first with pasted output into …red-witnesses.md". Log holds P1 + Gates 1–4 (P2) only; P3's red-first claim exists solely in commit 554c4b21's message | read-verified; partial red evidence supplied by runs M-A…M-F below | the required record for A1–A12 is missing; a commit title is not verification. The five key gates' red outputs now exist (this file) — they must be entered into the log; the remaining ~30 gates have none |
| S-1 | `tests/js/pi_message_bus_adapter.test.mjs:43–65` | `T1-SCO-06`, `T1-SCO-02` | should | the mjs suite loads the same `hook-bridge.ts` (one parser — correct) and is the ONLY parse coverage a gate runs (`js` lane runs on every push), but it still pins "three stdout shapes" and asserts `kind`/`content` properties only; the fourth shape (`aiBadgerBus`) lives solely in the un-gated bun suite | read-verified + node run (11/11) | a regression in `deliveryBusFrom` (bus extraction) is invisible to every gated lane: `kind` stays `"context"` (C10 fallback absorbs it). QA-3's "two samples, one contract" is half-gated. Also the test name is now stale ("three shapes", wire has four) |
| S-2 | pbi `~/RiderProjects/pi-badger-integration` `publish.ts:59–64`, `features/pi/adjustments/adapter/` | plan C5/S4, `T1-PRF-02(b)` | should | pbi branch `task/aib-pi-message-bus-push-delivery-heal`: adapter dir holds only `hook-bridge.ts, index.ts, package.json` — no `bus-prefilter.ts`/`bus-store.ts`; `ADAPTER_FILES` still the original 4 names; no mirrored bus tests | read-verified (read-only listing) | P3's mirror step (copy settled adapter → pbi, append 2 names, mirrored tests) is not done there, so "pbi `bun test` + `--check`" and "publish.ts --check three-way" cannot have run against the settled adapter. Caveat: pbi may track this separately — unverified |
| S-3 | `index.ts:448–450` vs `adapter-bus.test.ts` A10 tests | `T1-SCO-01` (weak pin shape) | should | M-F: `spawnAndSettle` mutated to re-probe post-spawn and advance to the re-read fingerprint — killed, but only incidentally, by the three A10 tests' `probeCalls === 1` assertions | applied+reverted (3 fails → green) | CR-M3's "advance VALUE is the tick-time capture" is pinned by assertion side-effect, not by a test whose subject is the advance value. Relax A10's probe-count asserts and the pin evaporates silently. A discriminating fixture (probe sequence [fp(7,7) tick-time, fp(8,8) post-spawn] ⇒ next tick must still spawn) would pin the stranding property directly |
| N-1 | `features/pi/tests/bus-store.test.ts` (3 hand-copied `CREATE TABLE messages`) | `T0-05` adjacent | note | non-A11 tests hand-copy the store DDL as fixtures | read-verified | acceptable — A11 is the binding pin against the real store-created DB (the QA-8 ask, satisfied) — but the copies are drift bait; A11 is what keeps them honest |
| N-2 | `bus-store.test.ts` A11 loud-skip path | `T1-STR-03` adjacent | note | when no `badger_store.py` sits above the test tree (pbi mirror), the pin passes with a `console.warn` — a reason, but no tracking id | read-verified | documented environment-conditional skip; fine in-repo, becomes load-bearing if the suite is ever mirrored without the store |
| N-3 | `bus-store.test.ts` A11 (`Bun.spawnSync(["python3", …], { env: { …process.env } })`) | `T1-ISO-07` adjacent | note | ambient env inherited (redirect applied on top); ambient `python3` required | read-verified | hermetic enough for a real-store contract pin; on a python3-less runner it errors rather than skips — moot until B-1 wires the suite into CI |
| N-4 | red-witness log, Gate 1 store row (`test_message_bus_store.py:1030`) | `T1-PRF-02` | note | the pasted line number now sits inside the test's docstring; the deselected-count arithmetic (70 total = the pre-amendment file states; 8 selected, 7 failed + `clean_empty` the 1 pass) is internally consistent | unverified (static reasoning) for the line number; mechanism (2-tuple unpack of a bare list) matches the pre-C2 code exactly | the row is honest; the line number predates the final call-site amendments — cite the test name, not the line, when re-pasting |
| N-5 | red-witness log, P1 M4 row | `T1-PRF-02` (positive) | note | documents a mutation that could NOT be restored-as-ruled, names the freezing mechanism (`_DEFAULT_HOME` bound at collection), grep-verifies production is unaffected, and points at the lane report | read-verified | exemplary honesty — this is what a deviation row should look like |

## 1. The five highest-value gates — mutation evidence (all applied + reverted in this worktree)

**M-A — watermark property (A3): drop COUNT equality from the skip gate** (`bus-prefilter.ts`, remove `f.count === clean.count &&`).
```
(fail) A3: global-watermark tick decision > MAX equal but COUNT differs ⇒ spawn (a prune or any other row delta)
41 pass → reverted → green
```
Killed by exactly its owning test; no other test red (correct scoping — the COUNT hardening is CR-N3's and nothing else keys on it).

**M-B — failure-marker advance rule (A9): `advanceAllowed` → `return true`** (`bus-prefilter.ts`).
```
(fail) A9 … > a spawn error or timeout (an error outcome) does not advance
(fail) A9 … > the failure marker does not advance (CR-M1: the cursor may not have moved)
(fail) wiring > A12: a failure-marked timer spawn notifies once per streak …
(fail) wiring > A12: a probe error spawns anyway and latches its notice …
(fail) wiring > A9 at the wiring: the failure marker sends nothing and never advances
(fail) wiring > A9: a clean empty outcome advances too; an error outcome never advances
→ reverted → 0 fail
```
Six reds across both levels, including the CR-M1 retry path (`deliverCalls` 2 after two ticks). The advance rule cannot silently rot.

**M-C — wrap-guard strict-`>` boundary (C9): `>` → `>=`** (`engine/badger_store.py:1923`) — re-runs the log's Gate 2 witness:
```
FAILED tests/test_message_bus_store.py::test_concurrent_deliveries_inject_exactly_once
FAILED tests/test_message_bus_store.py::test_a_caught_up_cursor_is_never_treated_as_wrapped
2 failed, 40 deselected → reverted → 2 passed
```
**Identical to the log's pasted Gate 2 mutation output — that row is verified honest by re-run.**

**M-D — C2b marker wire shape: failure path prints `{}` instead of the marker** (`message_delivery_hook.py:276`, `print(json.dumps(FAILURE_MARKER))` → `print(json.dumps({}))`).
```
FAILED …::test_malformed_stdin_is_a_no_op
FAILED …::test_corrupt_user_db_fails_open
FAILED …::test_registry_explosion_fails_open
FAILED …::test_failure_marker_on_a_forced_store_open_failure
FAILED …::test_guarded_main_still_fails_open_when_the_log_path_throws
5 failed, 2 passed, 28 deselected → reverted
```
Correctly scoped: the two passes are `test_clean_empty_stays_exactly_empty_at_the_wire` (must stay `{}` — it does) and the mail-path B8 pin (untouched by a failure-path mutant). This also independently re-verifies the log's Gate 1 wire row (same tests, same assert `{} == {'hookSpecificOutput': {'aiBadgerBus': {'error': True}}}` shape).

**M-E — wake-routing matrix: broadcast wakes under `addressed` too** (`bus-prefilter.ts`, `mail.broadcast > 0 && policy === "all"` → `mail.broadcast > 0`).
```
(fail) A8 … > idle + broadcast-only under addressed ⇒ consume + inject WITHOUT waking (C3)
(fail) A8 … > streaming + broadcast-only under addressed ⇒ steer without a wake (C4's ruled cell)
(fail) wiring > A8: idle + broadcast-only under the default policy ⇒ steer without a wake (C3)
→ reverted → 0 fail
```
Both QA-4/C4 and C3 rows plus the wiring — the matrix is pinned at both levels.

**M-F — CR-M3 re-read mutant** (S-3 above): `index.ts` `spawnAndSettle` re-probes post-spawn.
```
(fail) wiring > A10/C11: agent_start clears a stuck compaction flag
(fail) wiring > A10: session_compact clears the flag and the tick resumes
(fail) wiring > A10: session_compact_failed ALSO clears the flag (the drift-prone half, QA-6)
→ reverted
```
Killed — but see S-3 for why this kill is incidental.

**Log spot-verification tally (task requirement: 3+ rows):** Gate 2 re-run (M-C, exact match) ✓ actual; Gate 1 wire row (M-D, same tests/asserts) ✓ actual; Gate 3 M2 redaction mutant — `_redact_payload_text` redaction disabled → `FAILED …test_hook_error_log_never_leaks_payload_derived_substrings` → reverted → `1 passed` ✓ actual; Gate 1 store row — mechanism + count arithmetic consistent, line number drifted (N-4) ✓ static.

## 2. Spec-vs-coverage: C1–C11

Every ruling has an owning test: C1 (A3 property + A9 pure/wiring + seam-decorator tests), C2 (B6 store summary ×4, exact-equality oracles; `_read_addressed` columns exercised through every B6 batch), C2b (marker pinned at 4 fail-open entries + wire + TS parse), C3/C4 (A8 both levels, M-E's kill list), C5 (files exist and are pure/injected as ruled — the ADAPTER_FILES half is S-2), C6 (A7 pure + wiring, both env-fallback directions), C7 (A1 no-handle + seam gating under `off`), C8 (B4-i/B4-ii/B5, M2 re-verified), C9 (B7 wrap + strict-`>` companion, M-C), C10 (`mailSummary` fallback + wiring test "legacy mail wakes as addressed"), C11 (A10 including `session_compact_failed` and `agent_start`, TTL expiry pure half). No test asserts pre-revision semantics anywhere: the deleted predicate-mirror fixtures are gone, no broadcast-defer pin remains, `isoCutoffUtc` mirrors absent. The amended A-list gates all exist and pin what the qa review specified — A1's no-handle form, A3's fingerprint matrix incl. exact-equality-never-≤ and staleness-bound-exclusivity, A8's summary fixtures, A10's `_failed` half, A11's store-created DB, A12's latch with reset.

## 3. Tautology / fake-honesty scan

**No bypass in the wake routing.** The chain is: `parseDeliveryStdout` extracts `aiBadgerBus` from the wire string (pinned in bun `hook-bridge.test.ts`: mail+summary, zero-counts, error marker, legacy bytes, malformed-as-absent) → `DeliveryOutcome.bus` is the single shared seam → `mailSummary` (C10 fallback pinned) → `wakeRoute` (matrix pinned) → `pi.sendMessage` call asserted with exact `options` and exact message. The adapter-bus fixtures inject `deliver` returning an already-parsed `DeliveryOutcome` — that is the sanctioned CR-N5iii boundary (bun suites never spawn the real hook), not a bypass: both halves of the seam are independently pinned and the Python side pins the same literal field name (B8, exact full-response equality incl. `aiBadgerBus`). The one gap this scan found is S-1 — the CI-gated copy of the parse suite predates the fourth shape.

**bus-store.test.ts does NOT re-implement the query.** The A11 pin creates the store with the real `badger_store.open_user()` in a redirected temp root (with the honest `os._exit` WAL-sidecar rationale documented in-line), runs the shipped `probeUserDb` against it, asserts the exact fingerprint, and proves the write-negative on the same DB. QA-8's ask is satisfied — in the un-gated suite (B-1 is what keeps it from mattering).

Zero-assertion / NotThrow-only / tautological bodies: none found in any of the eight files. Negative assertions are paired with positives throughout (e.g. A12 asserts the latch fires once AND that a success resets it; the ENOENT test asserts the skip AND that the discarded fingerprint forces a spawn on the file's return). The `decideTick` totality test asserts `not.toThrow` — as a secondary property over a matrix, with the primary assertions carried by its 14 siblings; not a vacuous pass.

## 4. Coverage gaps the implementation revealed

- **S-1** (the fourth parse shape is un-gated) — the only genuine gap found.
- **S-3** (CR-M3's advance-value half pinned incidentally) — the property is not stranded, but its guardian is a different test's assertion style.
- Nothing in the final implementation lacks a test the plan promised: timer arm/disarm/rebind, generation invalidation, in-flight skip, seam decoration, 30 s vs 5 s budgets, notice latch, compaction flags, ENOENT, staleness bound — each has an owning test (read-verified; not individually mutation-probed). The regression pins named by the merge gate (`PI_DELIVERY_EVENT_MAP` without `session_start`, arm-coverage contract, advisory-only build_response pin) are all green in the full run.

## 5. Flakiness

Clean. The bun suites inject `setInterval`/`clearInterval` and the probe/deliver I/O — no fake timers, no real-clock coordination, nothing to leak across tests (`afterEach` deletes the three env vars and the tmp dir). `Date.now()` is read by the wiring but never asserted. The A10 compaction tests rely on wall-clock recency of a just-set flag against a 10-minute TTL — 10 orders of magnitude of headroom, not a flake channel. No `sleep`/`setTimeout` in any new test (the three `time.sleep` hits in the Python files are the pre-existing race-test machinery, untouched). A11's subprocess fixture is env-redirected and tmp-rooted (ambient-env caveats noted in N-3). The Python suites ride the pre-existing `frozen_clock` discipline; no wall-clock assertion exists in any new test.

## What the fix needs (for whoever picks this up)

1. **B-1:** add a bun lane to `verify.sh` (`bun test features/pi` + `bunx tsc --noEmit -p features/pi`) and one CI job — the plan's merge gate already promises both.
2. **B-2:** add the P3 section to the red-witness log; M-A…M-F above are paste-ready red witnesses for the five key gates, or re-run them for fresh output.
3. **S-1:** one fourth-shape case in the mjs parse test (it loads the same bridge; three lines), and retitle "three stdout shapes".
4. **S-2:** run P3's mirror step on the pbi side (or record that it is deferred and by whom).
5. **S-3:** optional one-test hardening of the CR-M3 pin (probe-sequence fixture asserting the next tick still spawns).

---

## Report-back

**Verdict: REQUEST-CHANGES.**

**BLOCKERs (2):**
1. **B-1** — the 157-test bun suite gates nothing: no bun/tsc lane in `verify.sh $LANES`, `lane_js` runs only `tests/js/*.mjs`, no CI job invokes bun; the merge gate's "CI: … bun+tsc both repos" is unimplemented in this repo.
2. **B-2** — the required red-witness log has no P3 section; P3's red-first claim rests on a commit message; the five key gates' red evidence exists only in this review's mutation runs.

**Final `git status --porcelain` (clean-revert proof):**
```
?? docs/work/2026-09-01-pi-bus-push-impl-review-architect.md
```
Empty except review files — the architect lane's parallel output (not mine); **zero mutations remain**: all seven (`bus-prefilter.ts` ×3, `index.ts` ×1, `engine/badger_store.py` ×1, `message_delivery_hook.py` ×2) were `git checkout --`-reverted and re-verified green immediately after each run.
