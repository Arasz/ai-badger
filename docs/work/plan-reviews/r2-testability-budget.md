# R2 — testability & budget-arithmetic attack on plan rev 1

Scope: `docs/work/2026-09-28-task-decomposition-plan.md` (rev 1) against `p{1,2,3}` sections, `r{1..4}` lanes, and the repo contracts I read/ran here: `tests/test_every_check_can_fail.py`, `gates/tdd_guard.py`, `tests/test_dependency_honesty.py`, `tests/test_badger_store_vendored.py`, `tests/test_status_report.py`, `tooling/version_sync.py`, `gates/scaffold_freshness_guard.py`, `features/common/skills/welcome-ai-badger/scripts/scaffold.py:17`, `.lefthook/pre-push/verify.sh`, and the local interpreters. Out of scope: DR1–DR3 architecture merits, production security/layering. All findings below are static plan analysis unless marked measured.

## MUST

**F1 — The plan cannot push a green branch between S1 and S13; two lanes go red by construction.**
Plan location: S1 (plan.md:50–53), S9 (plan.md:90–93), S12 (plan.md:105–108), S13 (plan.md:110–113).
Evidence: `tooling/version_sync.py::check` (275) fails on plugin.json, marketplace.json, `model-groups.json frameworkVersion`, root `*.md` "Scaffolded by" lines, and every `.ai-badger/**` `frameworkVersion` stamp — and `_ai_badger_json_mismatches` (181–189) says sync() *never rewrites* those stamps, only a re-scaffold fixes them. S1 bumps VERSION but owns none of these targets (S13 does). `verify.sh::_select_lanes` (448–454) returns `LOCAL_LANES` on **every** push — no path filtering — so `version-sync` is red from S1. `gates/scaffold_freshness_guard.py` fails fast with `Narrowing` when the manifest records fewer skills than config derives (376–386) and otherwise re-scaffold-and-diffs; S9 adds a skill source two waves before S13's re-scaffold, and S10/S11 edit mirrored sources, S12 edits config — so `scaffold` is red from S9.
Concrete edit: S1 runs `tooling/version_sync.py` (write) + one scaffolder run and commits the stamps; the step that first adds/edits a scaffolded source (S9, then S10/S11/S12) re-scaffolds in the same commit; or the plan explicitly authorises named lane skips for waves 0–3 instead of letting implementers discover blocked pushes mid-lane.

**F2 — S13's re-scaffold command cannot deliver the new skill, so S13 AC (4) cannot pass.**
Plan location: S13 `AI_BADGER_MCP_AVAILABILITY=all … --no-install --skills ''` (plan.md:111–113).
Evidence: `scaffold.py:17` — "An explicitly empty `--skills` means 'the set already scaffolded', not 'none': it is recovered" (from the manifest). The manifest cannot contain `task-decomposition` until a re-scaffold adds it, and `--skills ''` recovers the old set. `scaffold_freshness_guard`'s own remediation therefore passes the config-derived list (`rescaffold_argv`, `REMEDIATION_RATIONALE`) precisely because recovery re-delivers the narrowed manifest.
Concrete edit: use the guard's remediation form (`--skills` = the derived expected list), or land the re-scaffold in S9 where the skill source appears; S13 then only re-stamps.

**F3 — S5's waves AC is either false or vacuous; the `waves`↔`serialized_pairs` semantics are undefined.**
Plan location: S5 Do/AC (plan.md:71, 73); DR7 (plan.md:20).
Evidence: DR7 says waves = greedy packing serializing on `files∩`/`resources∩`. If conflict means "defer to a later wave", `ready ⊆ wave[0]` is false for any conflicting ready pair. If conflict means "same wave, listed in `serialized_pairs`", `wave[0] == ready` and the AC proves nothing. The plan never says which; P2-B1 carries both outputs without disambiguating. P1-A4's "generation 0 == ready exactly" predates serialization and cannot be the tie-breaker.
Concrete edit: pin one model — "wave[0] is the ready prefix admitted by the tie-order and conflict rule; every ready member appears in some wave; no wave contains a `files∩`/`resources∩` pair" (deferral), or "waves are DAG-only; conflicts appear only in `serialized_pairs`" (pair) — plus the red witness that flips the conflict predicate.

**F4 — `content_hash`'s normal form is undefined, so the idempotency ACs are untestable or tautological.**
Plan location: DR4 (plan.md:17), DR5 (plan.md:18 → P2-B1 create/replace rows), S7 AC (4) (plan.md:83).
Evidence: `plan_create` promises `created:false` for "identical normalized content", `plan_replace` promises `replaced:false` for "same content_hash … even with stale revision". "Normalized" and the hashed field set (revision? timestamps? statuses? evidence? step order? defaults?) are never specified. A test must either call the code's own normalizer to build its expectation (T0-04) or guess a normal form the server may not use.
Concrete edit: freeze in §2 — `content_hash = SHA-256` over `model_dump_json()` with an explicit exclude-list, plus the stale-revision success row; pin one known-answer vector in S7.

**F5 — S4 tests none of the Jev fail-safe directions.**
Plan location: S4 (plan.md:66–68); DR9 (plan.md:22).
Evidence: "tier upgrade-only ≥0.6, never demotes"; "wave hints can only add serialization (any failure → serialize)"; "wave serialize-default ≥0.7" exist only in Do prose. S4's four ACs cover the parser, vendoring, flags-off, and prompt bytes. A flipped comparison (`choice==low` demotes; failure → share-wave) leaves every AC green.
Concrete edit: add AC (5) with two red witnesses — `medium`/`low` or confidence < 0.6 → no proposal; `serialize`/transport failure → serialized pair, `share-wave` < 0.7 → no serialization.

**F6 — S7's server `--check` becomes a discovered check with no REGISTRY provocation; the meta-test will go red.**
Plan location: S7 AC (6) (plan.md:83); only `tooling/task_plan_schema.py --check` is registered (S2, plan.md:56–58).
Evidence: `tests/test_every_check_can_fail.py::_declares_check_flag` (998) flags any tracked script containing `add_argument("--check"`; `discovered_checks` (1053) includes `features/**/scripts/`; `test_every_check_has_a_provocation` (1117) fails without a provocation or exemption. S13's full suite therefore fails on this alone.
Concrete edit: register `features/common/skills/task-decomposition/scripts/task_graph_server.py --check` with a hermetic provocation (mutated/missing schema → exit 1; clean → 0), or rename the verb and record an EXEMPTIONS reason.

**F7 — S8 AC (3) is unfalsifiable ("entries … or the unmet-prerequisite note").**
Plan location: S8 (plan.md:88).
Evidence: the same fixture passes whichever branch the implementation always takes, so a declaration writer that never writes an entry is green via the note.
Concrete edit: two fixtures with the prerequisite environment controlled — `uv --version` resolvable → entry present in `.mcp.json`/`.github/mcp.json`; unresolvable → the note with its exact expected content/field.

**F8 — Nothing tests the server-rendered plan file; renderer and parser are each tested against their own fixture.**
Plan location: DR10 (plan.md:23), §2 (plan.md:38), S11 (plan.md:100–103), S13 e2e (plan.md:111–113).
Evidence: the renderer (writes `.ai-badger/task-tracking/plans/<date>-<taskId>.md` with banner, `**S<N> …**`, one checkbox per AC) has no AC; S11's red tests hand-write `**P/S**` fixture plans; S13's e2e never reads the file. A missing/broken renderer leaves every gate green while the declared fallback path is dead.
Concrete edit: S13's e2e calls `status_report.plan_checklist()` on the file the server just rendered (path, matched, `[step]` counts), or add a dedicated render/parse round-trip test in S7 or S11.

**F9 — The lanes' interpreter cannot import pydantic as written, and the plan's gate commands bypass the repo's Python resolution.**
Plan location: S2 (plan.md:55–58), S13 (plan.md:113).
Evidence (measured this session): `.venv/bin/python3 -c "import pydantic"` → `ModuleNotFoundError`; `.venv/bin/python3 -m pip` → "No module named pip"; `verify.sh::_resolve_python` prefers the main checkout `.venv`, which is what the `local/venv-python.md` invariant mandates; the plan's gates say bare `pytest`, `python3`, and S2 wires `task_plan_schema.py --check` (which imports pydantic) into `lane_validate`.
Concrete edit: S2 gains the explicit env step (`uv pip install --python <checkout>/.venv/bin/python3 -r engine/requirements.txt`, or `AIB_PYTHON`), and every gate string uses `$PY`/`.venv/bin/python3`; S13's `python3 -m pytest -q` likewise.

## SHOULD

**F10 — DR5–DR12 edges with no AC: skipped-dep readiness + `skipped_deps[]`, `plan-in-progress`, `schema-version-unsupported`.**
Plan location: DR7 (plan.md:20) vs P1-A4 (`ready` requires every dep *complete*); §2 code set (plan.md:36); S5 (71–73), S6 (78), S7 (83), S13 (111–113).
Evidence: an implementer can follow either source and no listed test objects; S13's "plan_replace rejection mid-execution" names no code; no step exercises a row/doc `schema_version > 1`.
Concrete edit: S5 adds "skip a dep → dependent is ready; `skipped_deps[]` populated; a failed-dep descendant is `blocked`"; S7 asserts `plan-in-progress` for an `in_progress`/`complete`/`failed` step and allowance for skipped-only; S6/S7 assert the unsupported-version refusal happens before pydantic and leaves the row untouched.

**F11 — `steps_ready`'s advisory contract contradicts the offline-server ruling; nobody owns P2-B4's fan-out caps.**
Plan location: DR5 (plan.md:18), DR9 (plan.md:22), S4 (65–68), S7 (80–83).
Evidence: P2-B1 gives `steps_ready` an `advisory` input and an in-server Jev proposal block; DR9 moves Jev to skill scripts and declares the server offline; the plan never restates the tool signature or says how proposals reach the caller. `PAIR_CAP=10`, `STATE_CHAR_CAP`, and chunking have no AC in any step.
Concrete edit: freeze `steps_ready`'s inputs/outputs in §2 and say the skill composes advisory after the call (or delete the parameter), and add an AC for the caps if the skill script owns them.

**F12 — S10's "every C2 row dispositioned" is prose-only.**
Plan location: S10 Do/AC (plan.md:95–98).
Evidence: the pin test asserts three forbidden and four required strings in `task/SKILL.md` plus one quick-task sentence. Rows in `multi-agent-communication:40`, both task extensions, `worktree-agent-isolation/{SKILL.md,references/shared-worktree-collisions.md}`, and the delegator note have no assertion — a silently skipped file passes the gate.
Concrete edit: extend `tests/test_task_pipeline_vocabulary.py` with one required new sentence per rewritten C2 row (the row list is already in P3-C2).

**F13 — S5's "RED witnesses on 3 named guards" contradicts the every-new-guard rule and names none.**
Plan location: §3 (plan.md:48) vs S5 AC (plan.md:73).
Evidence: S5 introduces at least `dependencies-incomplete`, `criteria-unmet`, `already_complete`, `invalid-transition`+`allowed_transitions`, the force bypass, `integration_sink`, "check strings never executed", and `files∩`/`resources∩` serialization. "3 named guards" is neither named nor exhaustive, and the negative (no subprocess) AC needs a temporary call to become red.
Concrete edit: list the guards whose witnesses are required, or say "every guard listed in the Do", and give the no-subprocess guard its mutation.

**F14 — Race tests are timing-dependent with no scheduling mechanism.**
Plan location: S3 AC (2) (plan.md:63, "two-process race → one winner"); S6 AC (1) (plan.md:78, "interleaved writers → one conflict").
Evidence: an un-orchestrated two-process race is a flake source (T0-06); no interleave seam or barrier is named.
Concrete edit: schedule the interleave — hold a second connection's `BEGIN IMMEDIATE` while the first writer attempts its CAS, or inject a barrier at the read-modify-write seam — and assert the resulting error rather than the race outcome.

**F15 — S13's local full-suite AC conflicts with the repo's test-economy invariant and makes the join step the longest dispatch.**
Plan location: S13 AC (2) (plan.md:113); §4 (plan.md:119).
Evidence: `pipeline-runs-the-rest`/`test-run-economy` reserve the full suite for CI (the shipped test-economy hook counts full runs); verify.sh's own budget note measures the local lane set at median 85 s / p99 563 s / max 841 s before pytest; CI's pytest job timeout is 20 min. S13 already runs the full suite once locally *and* all gates ×9.
Concrete edit: AC (2) becomes "push the branch; CI `verify.sh pytest` green on the pushed head (report the run)"; local keeps the touched surface; keep one documented full run only if CI is dead.

**F16 — The vendoring AC names an artifact that cannot satisfy it.**
Plan location: S4 (plan.md:66, 68); DR9 (plan.md:22).
Evidence: DR9/S4 say `jev_client.py` is "vendored `openrouter_client.py` + ported `Budget`" and then require "byte-compare minus the one changed line". A file that also gains the ~20-line `Budget` port cannot be one line different. P2-B4 keeps the one-line vendored copy (`TEST_BASE_ENV` rename) and the `Budget` port in separate files.
Concrete edit: name the vendored copy path (`scripts/openrouter_client.py`, exactly one changed line) and keep `Budget` in `jev_choice.py`; or state the exact expected diff count for `jev_client.py`.

**F17 — CLI≡MCP equality is a near-tautological oracle.**
Plan location: S7 AC (5) (plan.md:83).
Evidence: both transports share the same store and domain code, so "payloads equal" compares the code to itself (T0-04); a synchronized payload change passes both sides.
Concrete edit: pin the twelve names and one golden payload literal per tool (from the frozen interface/`tools.json`), keeping cross-transport equality as an extra check.

**F18 — The `uv` smoke has no home: it is in S7's Gate, but `uv` is in no CI workflow and `uv run --script` fetches pydantic on first run.**
Plan location: S7 AC (6)/Gate (plan.md:83); S12's `dependencies.json` change.
Evidence: `.github/workflows/pylint.yml:43–50` installs pip requirements only (no `uv`); a pytest that shells `uv run --script` fails on CI and on a cold/offline machine (network fetch), making the gate non-hermetic.
Concrete edit: either keep the smoke a one-time manually measured artifact (say so and drop it from the Gate), or add `astral-sh/setup-uv` pinned to a commit SHA with a warmed cache in the workflow that runs it.

## NIT

**F19 — The prompt "pin test" can read its oracle from the doc it pins.** S4 AC (4) (plan.md:68): if the test parses `r4-jev-decisions.md` at run time, a doc edit silently updates the expectation. Carry the bytes as literals, as `tests/test_memory_context_jev.py` does for pi goldens.

**F20 — S3 witness precision.** S3 AC (4) (plan.md:63): "removing the CHECK constraint flips exactly the garbage-payload test" must name which module is mutated (the one the test imports) and scope the run to `tests/test_badger_store_plans.py`; otherwise the vendored-byte-equality test flips too and "exactly" is false.

**F21 — Module path not frozen.** S2 owns `task_plan_model.py` (plan.md:56); S5 says "(or `task_graph.py` sibling)" (plan.md:72). §2 freezes field names but not the path; freeze it so S2→S5 serialization and the design-tests references are stable.

**F22 — Test-convention pins absent.** The plan should pin `load_script` (dotted repo-relative names, `tests/test_conftest_load_script.py`) for the script modules and `sys.executable` for the server spawn; tests staying under `tests/` is already correct.

## Still open

1. Whether the executor pushes per step at all — if the whole task lands as one end commit, F1/F2's red windows collapse into the final step, but that contradicts `small-commits-early-draft-pr` and the plan's per-step gate claims.
2. Whether `ready ⊆ wave[0]` was intended under P2's pair-serialization reading (F3) — the plan text admits both.
3. Whether S13's full local suite is meant as CI evidence (F15) — depends on CI liveness at execution time.
4. Whether the `uv` smoke (F18) is a manual MEASURED artifact or a repeatable gate — the plan says both in different lines.

**Verdict: PROCEED AFTER MUSTS** — the defect class the plan is most exposed to is not coverage arithmetic (50 ACs against 13 steps is plausible) but gates that cannot fail (F3–F8) and an execution model whose own lanes are red until the last step (F1–F2, F9).