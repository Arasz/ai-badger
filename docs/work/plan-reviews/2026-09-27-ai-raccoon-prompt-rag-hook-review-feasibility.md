# Plan review: feasibility and structure (aib-ai-raccoon-prompt-rag-hook)

Lens: package order, parallelism, twin lists and registries, budget, simpler shape, pi byte parity.
Source read at main `4abf5ade` (identical to the plan's base apart from the research record). Grades:
MEASURED (command run), READ (source opened), INFERRED.

**Counts: 4 MUST, 8 SHOULD, 6 NOTE.**

---

## MUST

### M1. P1's new `--all` check turns five `test_every_check_can_fail` controls red, and it breaks two fixture twins the plan does not list
*Plan §4 P1, §7.* Three test helpers each write a miniature hooks manifest whose arms name
`demo_hook.py`, event `SessionStart`, with **no `hooks.json` beside it**:
- `tests/test_every_check_can_fail.py:553-574` (`_hooks_manifest` / `_validate_tree`, written under `features/demo/hooks/`)
- `tests/test_validate.py:17-27`
- `tests/test_skills_lint.py:22-32`

The meta-test asserts that the **unprovoked** fixture exits 0 (`test_every_check_can_fail.py:1057-1066`).
There are five `validate.py --all` provocations built on `_validate_tree` (`:897-913`). Once
`hooks_manifest_unresolved` joins `validate_all`, every one of those controls reports unresolved
arms and exits 1. That is 5 red tests (READ). The copilot arm in these fixtures also uses the Claude
spelling `SessionStart`, and V5 makes an unmapped Copilot event a gap. The hermes arm there is
`hooks-json`, while the plan's rules only define `hooks-json` for Claude and Copilot. The
`test_validate.py` / `test_skills_lint.py` tests that expect rc 1 would keep passing, but for the
wrong reason.

The P1 gate runs `test_every_check_can_fail.py` and would catch this, but P1 plans no fixture change,
and the gate omits `tests/test_validate.py` and `tests/test_skills_lint.py`.

**Fix:** add the three fixture helpers to P1's Files. Each writes a resolving `hooks.json` (and a
Copilot-cased event), or drops the hermes/copilot arms in favour of the exemption shape. Add both
test files to the P1 gate. Resolve `entry` **relative to the manifest's own directory**, not a
hard-coded `features/common/hooks/`, because the glob is `features/*/hooks/hooks-manifest.json`
(`validate.py:372`) and the meta fixture lives at `features/demo/hooks/`.

### M2. "Suite green at every package boundary" is false: regeneration and release are deferred to P6, but tests and gates enforce them on every commit and push
*Plan §4 preamble, P2–P5, §5 "P6 regenerates once".*
- `tests/test_sync_plugin_skills.py:262-270` (`TestRealCatalogParity`) and
  `tests/test_plugin_copy_points_at_the_tailored_one.py:142-143` run `sync_plugin_skills --check`
  against the **real repo**. They go red the moment P2 adds `memory_context.py` under
  `features/common/skills/ai-raccoon-memory/scripts/` without mirroring it into `skills/` (READ).
- The pre-push gate (`.lefthook/pre-push/verify.sh:61,231-247`) runs `release`, `scaffold`,
  `plugin-skills`, `index`, `validate` and `tdd` on every push (READ). Before P6:
  - `release_guard` fails, because `features/`/`tooling/` changed with `VERSION` unbumped (`gates/release_guard.py` logic step 5).
  - `scaffold_freshness_guard` fails after P1, because Copilot prompt-markers `timeoutSec` 5→10 changes `.github/hooks/ai-badger-hooks.json`, and after P2, because the skill copy under `.ai-badger/skills/` is stale.
  - `.pre-commit-config.yaml` runs sync/index/scaffold checks at **commit** time too.

  So nothing can be pushed until P6, which contradicts the "small commits, early draft PR" invariant.

**Fix:** move the release skeleton into the first pushed package: bump `VERSION` 0.178.0, run
`version_sync`, add a changelog stub, and generate its README row. Then make "run
`sync_plugin_skills.py` + self-re-scaffold (`--no-install`) + `index_build.py`" a closing step of
**every** package that touches `features/` (P1–P5), not P6 only. P6 then only refreshes the
changelog text. Update §5's shared-file table: `skills/ai-raccoon-memory/scripts/`, `.ai-badger/**`,
`.claude/settings.json` and `.github/hooks/*` become shared by P1–P6, which serializes those
regeneration commits. See S1.

### M3. The binding Q1 ruling (port env var) never reached the packages or the test rows
*Plan §1 "Constants, no knobs", C7, P4.3 + Files, H13, I2, I7, Q1 row, §10, vs the closing "Orchestrator rulings".*
The ruling replaces the `sitecustomize` shim with `AI_BADGER_MEMORY_CONTEXT_PORT`: an integer from
1 to 65535, with garbage falling back to 7721 and the host fixed at 127.0.0.1. The body still:
- instructs P4.3 to write `tests/raccoon_sitecustomize/sitecustomize.py`;
- has H13 and I2 run under that shim;
- has I7 whitelist "the sitecustomize shim's redirect table";
- says in §1 that tests "never" reach the endpoint through env.

The new env input has no test rows, so its parsing is untested. That parsing is exactly where a
defect ships: `"0"`, `"65536"`, `"-1"`, `" 8080"`, `"8080abc"`, `"1e3"`, `"127.0.0.2:80"` and
`"evil@host"` each need a verdict, and the value must be read at call time.

**Fix:**
- Rewrite C7, P4.3, H13, I2, I7, §1 and §10 to the ruling.
- Add P3 rows: valid port used; each invalid value → 7721; the request host is always `127.0.0.1` whatever the value (the mutation is building the URL by string concatenation from the env value); the value is read at call time.
- Drop P4.3's file.

### M4. I1's pi assertion contradicts W6 and §1.2(3) on real data
*Plan §1.2 point 3, P6 I1, W6.* Hermes's `adjust()` copies every `SHARED_SKILL_MODULES` file into
the **project** `.ai-badger/hooks/` (`features/hermes/adjustments/adjust_hooks.py:211-217`, READ).
That is the same directory pi's `adjust_hooks.py:83-97` copies `ai_badger_hooks.py` into. In I1's
combined scaffold (`claude, copilot, hermes, pi`), `.ai-badger/hooks/memory_context.py` **will
exist**, and W6 asserts that it does. So I1's "nothing under … pi-owned `.ai-badger/hooks/` copies
… names `memory_context`" fails, or gets weakened until it proves nothing. §1.2(3), "the sibling is
absent there", is false in any hermes+pi project.

pi exclusion still holds, because pi never calls `pre_llm_inject_context` and `loadGates` reads only
Pre/PostToolUse (`adapter/hook-bridge.ts:91,96`, `index.ts:68,324,729`, READ). But the tripwire has
to be stated on what pi *executes*, not on which files exist.

**Fix:** restate §1.2(3) as "pi may carry the file but never invokes it". Change I1/I4 to assert:
- no `.pi/` or pi-extension file names `memory_context`;
- the adapter's `before_agent_start` spawns only `DELIVERY_SCRIPT`;
- pi's own copy list lacks it.

Drop the "pi-owned `.ai-badger/hooks/`" clause.

---

## SHOULD

### S1. Parallelism is real for P0∥P1∥P2∥P3a and for P4∥P5 on hand-edited files, but not once M2 is applied
READ: the hand-edited file sets are disjoint as §5 states.
- P1: `validate.py`, Copilot `adjust_hooks.py`, `hooks.json`, 1–2 tests (+3 fixture tests, M1).
- P2: `memory_context.py`, core test, ADR, `docs/adr/README.md`.
- P3a: `tests/raccoon_fake.py`.
- P4: hook, `hooks.json`, test.
- P5: `ai_badger_hooks.py`, Hermes `adjust_hooks.py`, `test_hermes_plugin_install.py`, test.

The **generated** outputs are shared by every lane that must stay pushable. These are
`skills/ai-raccoon-memory/scripts/`, `.ai-badger/skills/…`, `.ai-badger/hooks/*` (Hermes copies
`memory_context.py` there in P5), `.claude/settings.json`, `.github/hooks/ai-badger-hooks.json`,
`index.json` and `VERSION`/`plugin.json`. Two parallel worktree lanes that each regenerate will
conflict on those files.

**Fix:** parallel lanes commit hand-edited files only. One integration step per merge regenerates
and commits the outputs. State that explicitly in §5.

The P4 precondition (Q4) is answered: no test requires every `hooks.json` command to be named by a
manifest row. The only reconciler is scoped to message-bus rows
(`tests/test_message_bus_manifest.py:206-217`), and both generators are manifest-driven
(`hook_wiring.py:243-262`, Copilot `adjust_hooks.py:96-123`), so the P4 command is inert. The
plugin loads repo-root `hooks/hooks.json`, not `features/common/hooks/hooks.json` (READ). Remove the
UNVERIFIED precondition.

### S2. pi byte parity: "byte-identical" is not achievable as written. Pin the divergences deliberately
*Plan §1 "byte-identical", R-e, C21/C22/C26/C30/C35.* Verified against `rag-core.ts`, with the JS/Python outputs MEASURED via `node -e` / `python3 -c`:

| # | pi behaviour (`rag-core.ts`) | Naive Python | Measured |
|---|---|---|---|
| a | `oneLine` truncates by **UTF-16 code units** (`flat.slice(0,max)`, `:172-173`), same for the 80-char query echo | code points | JS `"a😀".slice(0,2)` → `"a\ud83d"` (lone surrogate); Python keeps the whole emoji |
| b | Rank `${hit.ranking ?? "?"}` uses JS Number→String (`:260,:266`) | `repr`/`str` | JS `0.00001`→`0.00001`, Python `1e-05`; JS `1e-7`, Python `1e-07`. `_js_number` "for int-valued floats" (R-e) is not enough |
| c | `??` treats only null/undefined as missing: `ranking: 0` → `rank 0`; `path: ""` does **not** fall back to `sourceFile` (`:177`) | `or` falls through on 0 and `""` | JS `"" ?? "x"` → `""` |
| d | `lineStart: null` passes `!== undefined` (`:267-270`) and renders `:null-null` | `is not None` → no suffix | JS: `true` |
| e | `\s`/`trim()` (JS) vs `\s`/`strip()` (Python) differ on U+FEFF, U+0085 and U+001C–001F | — | INFERRED from the language specs |

Point (a) cannot be copied: a Python string holding a lone surrogate raises on UTF-8 encode, which
breaks the Hermes return path. The Claude path is safe only if `json.dumps(ensure_ascii=True)` is
used.

**Fix:** define parity as "byte-identical for BMP text with numeric/absent fields". Truncate by code
points, as a documented divergence. Implement `_js_number` as the JS algorithm: shortest repr, with
exponent only when the exponent is below -6 or at least 21, and the `e-7` / `e+21` spelling. Choose
and pin `0`, `""`, `null` and non-BMP behaviour with C-rows. Produce C22/C36 goldens by **running**
`toMemoryContext` under bun once and committing the output with provenance. A "golden" retyped from
the TS source at `:412-435` is circular. Real rankings are normalized to [0,1] (`shape.out`), so (b)
is rare but cheap to get right.

### S3. The F2 matcher disagrees with the generators it polices
*§1.3, V4.* Both generators select commands with `command.rstrip('"').endswith(script)`
(`hook_wiring.py:201-218` `select_hooks`, Copilot `adjust_hooks.py:120-123`, READ). V4 makes the
validator use basename equality instead. In both mismatch cases below, the validator is green while
the generators do something else:
- A lone `not_memory_context_hook.py` command: the validator reports a gap, but the generator wires the wrong script.
- Both `memory_context_hook.py` and `x_memory_context_hook.py`: the validator resolves, but the generator double-wires.

The existing message-bus reconciler already shows the better shape: it calls the real `select_hooks`
and asserts `len(commands) == 1` (`test_message_bus_manifest.py:214-217`).

**Fix:** add "exactly one command matches under the generators' own `endswith` rule" to the check, and
keep basename equality for that one. Note that the message-bus reconciler becomes a subset twin of F2
(derive-or-delete follow-up).

### S4. `validate.py` loading the Copilot adjuster must load it from the framework, not from `--root`
*P1.1, V5.* `validate.py` imports only `engine/` and `gates/` today (`tooling/validate.py:11-24`,
READ). If it loads `features/copilot/adjustments/adjust_hooks.py` from `--root`, every fake-root
`--all` test breaks, because those trees have no `features/copilot`.

**Fix:** load it from `Path(__file__).parents[1]`. State the tooling→features dependency, or move
`COPILOT_TO_SOURCE_EVENT` into `engine/badger_lib.py`, which both already import. That keeps the
layering and avoids a by-path load.

### S5. Declining `ai-raccoon-memory` leaves the Hermes per-prompt search live
*R-k, W4.* Confirmed, not UNVERIFIED. `SHARED_SKILL_MODULES` is copied unconditionally
(`features/hermes/adjustments/adjust_hooks.py:158-163,211-217`), and `pre_llm_inject_context` has no
exclusion check (grep for `exclude|declin` in `ai_badger_hooks.py` finds nothing, READ). This is a
default-on feature that costs about 1.3 s per prompt and sends prompt text, so a declined skill must
not run it.

**Fix (simple):** the Hermes arm calls `build()` only when `<project>/.ai-badger/skills/ai-raccoon-memory/`
exists, because a declined skill is not scaffolded. Add a W4-Hermes row.

### S6. Name one transport mechanism
*§1 "chunked reads with a deadline check, or a worker thread joined on the deadline".*

**Fix:** choose one: a daemon worker thread joined on `budget`, with the socket timeout also set to
`budget` so an abandoned thread in the long-lived Hermes process ends. That is ~10 lines and makes
T26 straightforward. Leaving the choice to the implementer invites both.

### S7. Missing registry and doc rows
- `docs/dictionary.md` has per-feature rows (`:27` is the memory-first gate row). The new `memory-context` row belongs beside it, not at `:22`/`:94` only (READ).
- `features/common/skills/documentation-drift-audit/references/ai-badger-drift-audit-map.md:44-55` enumerates `hooks.json` commands per event. It is already stale ("8 hooks"; the manifest has 25, MEASURED), so it is either a twin to update or a record to leave. Decide explicitly.
- `features/common/skills/code-review-evidence/references/ai-badger-hook-feature-review.md` is this repo's own checklist for a tri-agent hook feature. The plan should run it at P6 review. It flags the inert-without-sibling pair on **both** Hermes callbacks, and the loader call placed outside `try` (READ).
- The ADR number 0031 is a conflict hotspot like the changelog row. Re-check it at rebase.
- `README.md:204` and `docs/skills.md:106` mirror the SKILL `description`. Update them only if P6.3 changes the description, and state which.

### S8. The self-scaffold must name `--no-install` for acceptance runs
P6.4 re-scaffolds a repo whose agents include `hermes` (`.ai-badger/config.json:21-26`, READ). Without
`--no-install` it rewrites `~/.hermes/plugins/ai-badger/` (memory: "an acceptance check must not
write to what it checks").

**Fix:** use a deliberate install run only for the P6.6 demo, and state that.

---

## NOTE

- **N1. F2 baseline claim verified.** A prototype of the §1.3 rule over the real manifest (25 entries; arms: claude hooks-json 24, claude plugin-hooks-json 1, copilot hooks-json 14, hermes plugin 12) finds exactly 2 gaps, prompt-markers claude and copilot. All 12 Hermes methods resolve under the event-or-callback rule (MEASURED). C3 and the Q-R1 ruling are sound. For this feature the Hermes arm (`pre_llm_call`) resolves trivially, so F2 protects its Claude/Copilot wiring only.
- **N2. V15/V16 dedupe works.** The discovery command and the rewritten explicit command yield the same `skill_script_id` (`prompt-markers/scripts/user_prompt_hook.py`) with no matcher, so `_prune`/`merge_hooks` collapse them (`hook_wiring.py:113-195`, READ). `test_context_enrichment_wiring_end_to_end.py:57` compares a **sorted** list and scaffolds only mcp-index and prompt-markers, so R-d's "order may shift" rewrite is probably unnecessary. Run it before editing it.
- **N3. Row arithmetic is off by small amounts.** Recounted from §6: P4 has 16 rows (plan says 17), P5 has 13 + 2 existing (plan says 14 + 2), and P6 has 17 (plan says 16). That is 132 new rows. It does not matter, but "~133" came from the rows, not from a budget.
- **N4. Budget: moderately over-engineered, about 20% cuttable.** ~132 rows for roughly 400 LOC across two new files, one Hermes arm and one validator function.
  - Cut these, which are redundant with existing enforcement or with each other:
    - S1 + S3 + W14, which enforce F1 three more ways (S2's static `ast` scan covers it). This is the memory note's "one rule through three mechanisms".
    - W12/W13, which duplicate `TestRealCatalogParity`, `index_build --check` and the pre-commit/pre-push lanes.
    - I7, a text grep whose premise the port ruling removed. `_home_off_limits` already guarantees there is no token, so no request can happen.
    - H15, which W2a derives.
    - C0, a purity check by AST that is better held by review.
  - Keep the C-rows: byte parity is the product. Fold them into parametrized tables.
  - That leaves about 105 rows. Everything else pays for itself.
- **N5. Hermes memo scope.** `on_session_start` clears a process-global dict, so in a multi-session gateway one session's start clears the others' entries. The only cost is one re-search. Keep it as is, but say so in the ADR.
- **N6. `badger_store` reuse.** `resolve_project_id` is pure: an env override, then a file walk (`badger_store.py:2105-2119`, READ). The skill's vendored copy is byte-identical to the hooks copy (`cmp`, MEASURED). pi resolves the id the same way (`index.ts:134-150`), so the ids agree. The cost is importing a 2519-line module on every prompt, which is negligible against a 1.3 s search. R-i can close as "no side effects on import" once H6 confirms it.

---

## Is there a simpler shape that meets the rulings?

Yes, and it is a resequencing more than a redesign:

1. **Five packages instead of seven.**
   - P0: the spike.
   - P1: F2 + prompt-markers + the M1 fixtures + the release skeleton (M2).
   - P2: `memory_context.py` complete (pure core + transport + `build`, one file, so P2/P3 were strictly sequential anyway), with `raccoon_fake.py` still writable in parallel.
   - P3: the Claude hook ∥ the Hermes arm, as two hand-edit lanes.
   - P4: integration (manifest row, docs, demo).
2. **Regenerate per package, not once.** Every package ends with sync + self-scaffold `--no-install` + index. That is what keeps the plan's own "green at every boundary" claim true (M2).
3. **One mechanism per rule:**
   - F1: static AST scan.
   - Deadline: thread join.
   - Pi exclusion: one contract test (I4, as restated in M4).
   - Timeout ordering: W2a/W2b only.
4. **About 105 test rows** (N4), with the port-parsing rows from M3 added.
5. **The decline check on Hermes**, one `Path.exists` (S5), instead of relying on the kill switch.

None of this contradicts R1–R6 or the Q rulings.
