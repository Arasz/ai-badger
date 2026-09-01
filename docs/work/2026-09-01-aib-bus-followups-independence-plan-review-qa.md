# Plan review — QA lane — aib-bus-followups-independence

Lane: qa (MoE plan review), 2026-09-01. Target: plan-tests.md (TDD spine), checked against the
authoritative join + architect/harness appendices, verified against source at worktree HEAD c7424c6f.
Out of scope, named up front: production layering/security/perf (code-reviewer's artifact), doc
prose quality, the ⚑ rulings themselves. Evidence probes actually run this session:

- R1a probe (run): seeded 1:1 + broadcast; `deliver_for_session("S2", None)` returned only the 1:1
  and landed cursor at the broadcast row id; a second `deliver_for_session("S2", "P")` returned `[]`.
  R1a is red against shipped code for exactly the claimed reason (badger_store.py:1770).
- Derivation probe (run): `badger_store._task_families` → **AttributeError**; `FAMILIES` = 1 family
  (marker_state); `USER_FAMILIES` = 15; `tracker_lib._task_families()` = 5; store-kind (unresurrectable)
  = messages, cursors. The plan's tier-1 citation is not derivable as written.
- Static source confirmations: `_open` aborts store-wide on resurrection (:2002-2017), `_hold_at` has
  no gate today (:96-101), hook catches `ProjectIdAmbiguous` (message_delivery_hook.py:81-82),
  conftest.py scrubs no HOLD env (no global tripwire exists).

## Findings

| id | file:line | rule | severity | the mutation | run? | what it means |
|---|---|---|---|---|---|---|
| QA-1 | plan P2 / plan-tests §3 | T0-02 | blocker | land P2 as listed ⇒ 2 test files break | unverified (static reasoning) | P2's conversion list misses 2 bank-fixture files |
| QA-2 | plan-tests §3 R3b/:362; architect:14 | T0-03 | blocker | author R3b's refusal test ⇒ unimplementable under the ruling | unverified (static reasoning) | plan contradicts its own ⚑ walk policy |
| QA-3 | plan-tests §2 tier-1 | T0-02 | blocker | run the cited derivation ⇒ AttributeError, 6/21 families | applied+reverted (probe) | tier-1 sweep guarantee not derivable from cited sources |
| QA-4 | plan red-witness log / §7.1 | T0-01 | major | fill the log as specified ⇒ false red claims | unverified (static reasoning) | several planned rows are green-before by construction |
| QA-5 | D3 six constraints | T0-06 | major | new test file spawns child, no strip ⇒ env poisoning possible | unverified (static reasoning) | no global tripwire; strips are per-file only |
| QA-6 | plan-tests §3 R3c | T0-07 | major | naive resolver: corrupt/blank id, file-not-dir all slip | unverified (static reasoning) | three walk negative cases unspecified |
| QA-7 | plan-tests §5 pi :266 | T0-03 | major | re-timed E2E drops refire leg ⇒ exactly-once unpinned | unverified (static reasoning) | amendment doesn't name the non-redelivery assertion |
| QA-8 | plan P2 / hook :81-82 | T0-05 | major | retire symbol, keep catch ⇒ AttributeError masks real errors | unverified (static reasoning) | hook's dead except-clause not in P2's edit list |
| QA-9 | plan-tests §2 tier-1 | T0-05 | minor | resurrect tracking family, watch open_user ⇒ weak witness | unverified (static reasoning) | neighbour observable not DB-scoped |
| QA-10 | plan-tests §5 hermes :390 pin | T0-05 | minor | delete `_bus_pending`, pin stays green | unverified (static reasoning) | "drops the stash" clause becomes vacuous |
| QA-11 | tests/js e2eEnv :228 | T0-05 | minor | P2 lands, var goes inert-but-set | unverified (static reasoning) | stale raccoon redirect in pi E2E env |
| QA-12 | D7 E2E claim | T0-01 | — | n/a — verification, positive result | applied+reverted (source-verified) | guard cannot break the E2E's JSON parse |

## MUST (resolve before dispatch)

**QA-1 — P2's bank-fixture conversion list is incomplete (blocker).** The registry retirement kills
the bank read, and two files in P2's blind spot resolve project ids through it:
`tests/test_message_bus_integration.py` (own `_register_bank` :97, used :139 and :230 — the
exactly-once race E2E seeds a `bus-proj` broadcast against `cwd=str(repo)`, a tmp dir with **no**
`.ai-badger`; post-D2 it resolves None ⇒ broadcast never delivered ⇒ race assertions fail) and
`tests/test_message_delivery_hook.py` (own `_register_bank` :102, **11 call sites** :250-:665 —
every project-mail hook delivery). Both use local string
constants so nothing fails at import; the suite goes functionally red the moment P2 lands, in files
P3 also edits (disjoint hunks claim holds, but P2 must convert first). Fix: add both files to P2's
conversion list, `_register_bank` → `_make_project(dir, id)` writing `.ai-badger/project-id`; same
fail-open contracts. Evidence: plan P2 names only registry/send/manifest/hermes.

**QA-2 — R3b is dead weight and the appendices contradict the ruling (blocker).** The join's ⚑
walk policy is nearest-wins, "no ancestor refusal… `ProjectIdAmbiguous` retires with the registry".
Yet plan-tests §3 still authors R3b (ancestor-conflict refusal, "flagged owner-level" — already
ruled) and converts hermes :362 to a "nested-`.ai-badger` refusal caught by the wiring" — a
mechanism that cannot exist under nearest-wins. The architect appendix (:14, :49, :147) still
carries the superseded ancestor-refusal policy wholesale. Fix: delete R3b; re-specify :362's
mechanism as the wiring-level nearest-wins nested case (cwd inside inner ⇒ inner's mail delivered,
outer's mail not — same 1:1 shape kept) or fold it into R3a; correct the architect appendix rows so
no lane implements refusal. Post-retirement the only pinned refusal is send-message identity —
state that deliberately in the plan so "no resolver refusal" reads as decided, not missed.

**QA-3 — tier-1 derivation citation is wrong and under-covers (blocker, run).** plan-tests §2
derives the sweep from `badger_store.FAMILIES` + `_task_families`. Run: `FAMILIES` = marker_state
only; `_task_families` lives in `skills/task/scripts/tracker_lib.py:406` (a **callable** over
redirectable globals, three vendored copies — import the canonical copy); `USER_FAMILIES` (15
families) is not cited at all; and messages/cursors (`legacy_path is None`) cannot be resurrected
and must be skipped, mirroring `_check_resurrections`:922. As cited the derive-or-delete invariant
covers 6 of ~21 families while claiming all. Fix: derive at collection time from `FAMILIES` +
`USER_FAMILIES` + `tracker_lib._task_families()`, skip store-kind entries, and skip the same way
`_check_resurrections` does so a future registry addition cannot dodge the sweep.

**QA-4 — the red-witness log cannot be filled honestly as specified (major).** The standing rule
demands red-before for every new/amended test, but these planned rows are green-before by
construction: R1c (guard — probe shows the global cursor landing is today's behavior with
project_id set), amended store :852 (setting an extra env var is a no-op pre-gate), every strip-list
delenv edit (deleting a not-yet-existing var), amended pi :97 (passes today through the :137
fall-through branch — behaviorally identical in the unit fixture until `sessionStart` is removed
from the interface), :193 drains-nothing (trivially true today), Hermes :345/:362 mechanism-only.
Genuinely red today, right reason (verified): R1a/R1b (probe), containment tier-1/tier-2 (open
aborts store-wide today, `_open`:2002-2017), leak witness (no gate in `_hold_at`:96-101), pi
never-turned (start child spawns + writes cursor today), hermes never-reaches-pre_llm (start
delivery consumes today). Fix: split the log into two row classes — red-first tests (red-before
recorded) and contract pins/guards (green-before, each naming the mutation that would turn it red:
R1c ← over-tightened fix; :852/strip edits ← §7.3's mutation; :97/:193 amendments ← restoring the
deleted branch). Enforcement: each lane's merge gate requires a log row per diff test; P8 verifies
every planned row exists before the full sweep; the join reviewer spot-re-runs one red claim.

## SHOULD

**QA-5 — no global tripwire for hold/arm env.** Strips are per-file tuples in exactly 3 files;
conftest.py scrubs none of them; the copilot artifact E2E (`test_adjust_hooks_copilot.py:560-567`)
and any future file inherit `os.environ` wholesale, so a developer-shell export parks children
anywhere the local fixture is absent (pre-existing for HOLD, widened to two vars by D3). Fix: one
conftest autouse `delenv` of HOLD_ENV + the arm env; per-file strips stay as defense-in-depth; add
it as a seventh constraint in plan-tests §4.

**QA-6 — three walk negative cases are unspecified.** (a) Corrupt/unreadable id file:
`read_text` raising UnicodeDecodeError/OSError today propagates into the hook — the raccoon reader's
own precedent is fail-open ("absent, unreadable or half-readable yields what it yielded",
badger_store.py:1897-1903); (b) empty/whitespace id file: `" "` passes `send_message`'s falsy check
(:1712-1715) and would poison rows — the env override's contract says "Blank reads as unset"
(:1843-1846); the file analog must normalize to None; (c) `.ai-badger` existing as a FILE not a
directory (a `Path.exists()`-based walk mutation). Fix: extend R3c into three named cases, each red
against a naive implementation. R3d (sibling) + R3a (nearest) otherwise cover the walk well.

**QA-7 — name the pi refire leg.** The E2E's exactly-once proof at the pi seam is :284-285 (second
firing ⇒ empty) and close-cleanup :288-290. The :266 amendment preserves "cursor-advance and
close-event legs" but never names the refire; a re-timed E2E that drops it loses the only
non-redelivery pin at that seam (the unit :97 can't carry it — scripted fakes). Fix: one clause —
re-fire the `beforeAgentStart` payload, assert empty.

**QA-8 — P2 must edit the hook's except-clause.** `message_delivery_hook.py:81-82` catches
`badger_store.ProjectIdAmbiguous`; post-retirement the attribute is gone and any unrelated
exception inside resolve raises AttributeError from the handler, masking the real error. That means
a hook edit + its vendored re-lands (and the shipped-pair pin :419) belong in P2, which currently
lists no hook file. The "raccoon surface symbols gone" assertion test should name
`ProjectIdAmbiguous`, `RACCOON_BANK_ENV` and `raccoon_registry_surface` explicitly.

## NOTE

- **QA-9** — tier-1's neighbour observable ("open_user() succeeds, messages roundtrip") only
  witnesses user-db families; a resurrected tracking-db family poisons a different file. Track
  families need `open_tracking()` + a tracking neighbour (the untouched task_family:411-422 pin
  partially covers). Scope the observable per family's `db` field.
- **QA-10** — the Hermes close pin (:390) also claims "drops the stash"; once `_bus_pending` dies
  that clause is vacuous. Amend its name/docstring in P5 or it pins a system that no longer exists.
- **QA-11** — `tests/js` e2eEnv sets `AI_BADGER_RACCOON_DB` (:228) with raccoon comments (:8, :217);
  inert post-P2 but stale. One-line sweep in P4's file or P2's note.
- **QA-12 (clean)** — D7's "E2E still passes" holds: the guard text lives inside a JSON string
  value the generator round-trips via json.dump, and `bash -c` with the shipped file present takes
  the same branch ⇒ identical stdout ⇒ :557/:573 parse. Balance pins :210/:384 are the right
  tripwires. Also clean: tier-2 kind groups cover every `legacy_kind` (map; kvdoc+awm; jsonl+recent;
  tasks/usage/sessions; the 5 file-set kinds) with a neighbour observable each — no kind group
  missed; the R1b fold into R1a is sound; the leak-witness mechanism is sound (red today via the
  ungated env branch, and §7.3 doubles it as the strip-list mutation witness).

## VERDICT

DISPATCH-READY-WITH-CHANGES

Must-fix before dispatch:
1. **QA-1** — add `tests/test_message_bus_integration.py` and `tests/test_message_delivery_hook.py`
   (with their `_register_bank` line ranges) to P2's conversion list.
2. **QA-2** — delete R3b; re-specify the hermes :362 mechanism under nearest-wins; correct the
   architect appendix's superseded walk-policy rows.
3. **QA-3** — re-cite the tier-1 derivation: `FAMILIES` + `USER_FAMILIES` + `tracker_lib._task_families()`,
   skipping `legacy_path is None` store-kind families.
4. **QA-4** — split the red-witness log into red-first vs green-before pin/guard rows with named
   mutations, and name who verifies each row at lane-merge time.
