# S4 implementation report — Jev advisory (parser fail-closed, vendoring equivalence, fail-safe directions)

> Recovered verbatim from the `d-13` delegation receipt (the lane's JSONL transcript was tee-elided
> at ~25 MB; the receipt carries the full report). Committed `3c7c2d89` on `lane/S4-jev`, merged in
> the wave-2 join.

**S4 complete — committed `3c7c2d89` on `lane/S4-jev` (5 files, 1778 insertions), not pushed. Sub-agents: 0.**

## AC-by-AC evidence

### AC(1) Parser fail-closed matrix green, 2 RED witnesses
`tests/test_jev_choice_parser.py` — 107 rows. RED before the module existed (2 named rows, verbatim):

```
ERROR tests/test_jev_choice_parser.py::test_valid_choice_answer_parses - FileNotFoundError:
  .../features/common/skills/task-decomposition/scripts/jev_choice.py
ERROR tests/test_jev_choice_parser.py::test_missing_winner_probability_degrades_to_winner_only
2 errors in 0.50s
```
Full-file RED on first run: `109 errors in 0.98s`. Green in the gate below. Covers: valid; NaN confidence→0; missing/non-finite winner→`{winner:1}`+0; impossible winner→`unknown-choice`; clamping; `"2"`/`true`→0; malformed body; `error-envelope`; detail ≤120 with no body/prompt leakage; garbage of every kind never raises.

### AC(2) Vendoring equivalence + second-line red proof
`normalized equal: True | raw lines differing: 1` (source sha `c30e023f…`, vendored `bda7234e…`). Mutation witness, verbatim:
```
MUTATED second line: LOOPBACK 127.0.0.1 -> 127.0.0.2
=== RED run (mutated second line) ===
FAILED tests/test_jev_client_vendored.py::test_vendored_copy_is_byte_identical_except_the_one_sanctioned_line
FAILED tests/test_jev_client_vendored.py::test_the_sanctioned_line_is_the_jev_name_and_the_rule_is_kept
FAILED tests/test_jev_client_vendored.py::test_comparator_flags_a_second_changed_line
3 failed in 0.91s
=== REVERTED ===
3 passed in 0.77s
```

### AC(3) Flags-off zero network with poisoned stub
- `test_flags_off_never_touches_the_transport` — poison raises `BaseException` so the module's `except Exception` cannot swallow it; matrix `{}`/`"0"`/`"true"`/capability-without-master all no-op.
- `test_flags_off_opens_no_connection_even_with_a_loopback_test_endpoint` — real capture server: `requests == []`, `connections == 0`.
- Positive control `test_loopback_stub_is_a_real_seam_when_enabled` — same server, flags on: exactly 1 POST to `/api/alpha/decisions`, `Authorization: Bearer sk-test-…`, body byte-equal to the pinned tier wire. RED witness: the pre-implementation choice-file run failed these on `AttributeError: … has no attribute 'tier_enabled'` (69 failed / 2 passed).

### AC(4) Prompt-literal fixture pin
`test_tier_and_wave_constants_match_the_r4_fixtures`, `test_tier_payload_is_the_r4_wire_literal`, `test_wave_payload_is_the_r4_wire_literal`. Fixtures hand-copied with provenance comment (`r4-jev-decisions.md` §3–4, read 2026-09-28; never parsed at runtime); names `<id>_tier`/`<id_i>_<id_j>`, exact instruction lines and criteria from the brief.

### AC(5) Fail-safe directions with red witnesses
`medium`/`low`/conf<0.6/NaN → no proposal; declared `level`/`model` → no override; `serialize`, `share-wave` conf<0.7, NaN, transport failure → `serialize`; end-to-end `tier_proposals` failure → `{}`, `wave_hints` failure → every pair `serialize`. RED witness = same 69-failure run (`propose_tier`/`pair_decision`/`TierProposal` missing).

### AC(6) Caps/chunking/truncation determinism
`PAIR_CAP=10`, `STATE_CHAR_CAP=32000`, `INSTRUCTION_CHAR_CAP=1000`, `ATTEMPTS=2`, `ATTEMPT_SECONDS=8.0` pinned. 23 ready members → 3 calls with `[10,10,3]` members and `[45,45,3]` questions, no duplicate questions; truncation ladder full → instructions 1000 → `{id,goal}` with steps never dropped; two builds byte-identical.

### Gate (exact brief command)
```
$ .venv/bin/python3 -m pytest tests/test_jev_choice_parser.py tests/test_jev_client_vendored.py tests/test_jev_choice.py -q
182 passed in 0.77s
```
Per file: parser 107, vendored 3, choice 72. Pre-commit run also passed `version-sync, index-build, changelog-index, plugin-skills-sync, docs-guard, deps-guard, shipped-paths-guard, scaffold-freshness-guard, rules-index-regen, pylint`. Working tree clean.

## Rejected alternatives

- **Tolerant vs strict body JSON** — strict (pi's `JSON.parse`): `NaN` literal on the wire → `malformed`; the NaN-confidence row is exercised on a constructed answer, where pi's clamp branch lives. Fail-closed at the wire, faithful at the object level.
- **Non-object `answers` → malformed** (my first test) — rejected; pi degrades to `{}` and rejects each question as `mis-keyed`. Test corrected to the port.
- **`endpoint_url` without a key** — returns `None` (fail-closed) even though bare `api_base` would name production; test base always wins, non-loopback/non-`sk-test-` → `None`.
- **Full cross-chunk pair coverage** — rejected a clique-cover/pair-chunking algorithm; block chunking (≤`PAIR_CAP` members/call) leaves cross-block pairs unasked and they default to `serialize`, the only direction the advisory is allowed to move. S5's deterministic deferral stays the source of truth.
- **Vendoring `memory_context.py` for `Budget`** — rejected per DR9; ~20 stdlib lines ported, reason recorded in a module comment.
- **`AI_BADGER_JEV_TIMEOUT_MS` default 2500 ms (pi)** — rejected: the brief pins `ATTEMPT_SECONDS=8.0` and 2 attempts; default is 8 s/attempt, env overrides admitted.
- **One merged tier+wave call** — deferred: S4 builders are exact to the R4 single-step wire payload, per-step failure isolation; the merged call is a later cost optimization noted in R4.
- **Renaming the `mod` fixture pattern** — kept, with a module-level `# pylint: disable=redefined-outer-name`, the stance pyproject already records; the pre-commit hook uses `--rcfile=/dev/null`, and the real production shadow (`model` param vs `model(env)`) was renamed to `model_id` rather than silenced.

## Files changed
`features/common/skills/task-decomposition/scripts/{openrouter_client.py,jev_choice.py}`, `tests/{test_jev_choice_parser.py,test_jev_client_vendored.py,test_jev_choice.py}`. Nothing outside them.

## Deviations

- Added pi's `error-envelope` body reject (mapped to `server` kind) beyond the brief's listed vocabulary.
- `wave_hints` returns every pair, unasked ones as `serialize`; flags-off still returns `{}`.
- Extra NaN-safe negated gate comparisons and mapping guards; status/kind classifier rows added.
