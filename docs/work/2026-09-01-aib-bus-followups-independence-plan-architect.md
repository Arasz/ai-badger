# Plan — bus follow-ups & resolver independence (architect lane)

**Basis:** research consolidation + research-a/b/c (2026-09-01), owner rulings fixed. Effort high.
**Python gates below** use the repo commands (config.json `commands`); when running locally from
the main checkout, the `.venv` invariant applies (`.venv/bin/python3`).

## Decision resolutions (open decisions this plan touches)

| Decision | Resolution | Rationale |
|---|---|---|
| File shape [OWNER] | Dedicated `.ai-badger/project-id` file | config.json is rewritten wholesale (scaffold.py:740-742) with `additionalProperties:false`; a field means schema+merge+hash churn, a dedicated file has zero churn and survives config deletion |
| Id format [OWNER] | uuid4, minted in `scaffold.py run()` before the config write | repoAlias-derived ids collide across clones; uuid4 needs no derivation semantics |
| Id absent [OWNER] | Return None (fail open to 1:1/env-only) | id-less repos are a permanent fleet state; hooks already fail open (D8 precedent) |
| Walk policy | Nearest `.ai-badger` wins; any ancestor `.ai-badger` above it → raise `ProjectIdAmbiguous(candidates)` | ruling 2 says nested ambiguity refuses; callers already catch it and fail open to None |
| Raccoon disposal | Delete outright (`raccoon_registry_surface`, `RACCOON_BANK_ENV`, `AI_BADGER_RACCOON_DB`) same release | no caller survives D2; a shim keeps a dead code path and three bank fixtures alive for nothing |
| Containment read/write semantics | Refuse-on-access, uniformly, all non-store kinds | keeps test_badger_store_task_family.py:411-422 green unamended; satisfies D5c "surface on access"; one semantic instead of six |
| Detector placement | Open-time detection records per-family unavailable state; accessors consult it | one stat sweep at open; gives the doctor its report data for free |
| Doctor home | `doctor` subcommand in `badger_store.py main()` (`--user` default, `--project PATH`); den-refresh runs `doctor --status` as a pre-flight and reports | it is the only surface shipped to user machines (rides the copies); repair: re-import additive kinds (reconciles code with file-schemas.md:45/:265), inspect-only for map/kvdoc/awm; no `vendorin` copier this change |
| Arm env name | `AI_BADGER_TEST_HOLD_ARM`; gate lives in the env branch only; `_TEST_HOLDS` stays ungated | mirrors the gated var; scope matches ruling 3 exactly |
| Rule 7 sc.1 wording | Reword to first-turn timing: "pi delivers on the first agent turn" | ruling 4 amends the pinned scenario; stale Gherkin would contradict shipped behavior |
| Hermes defer timing | Same release (pi and Hermes together) | ruling 4 names both; research-c shows the Hermes seam is cheaper, not riskier |
| Guard reuse | Copy the `guarded()` shape into adjust_hooks.py (with the skipped `systemMessage`) | features/ dirs ship independently; a cross-feature import breaks at consumer scaffold time |

## P1 — Store containment + doctor (M2) · serial store lane, 1st

**Purpose:** `_open` detects per-family resurrection and records per-family unavailable state instead
of aborting store-wide; accessors of a contained family raise the resurrection error (upgrade
pointer); other families behave exactly as today. New `doctor` verb detects and repairs.
**Files:** `engine/badger_store.py` (`_open` :1991-2019, `_check_resurrections` :916-929,
`_raise_on_resurrection` :873-884, `_legacy_rows` :888-912, `_migrate_family` :1334,
`_migrate_file_set` :1564, `_family_entries` :979-987, `sessions_map` :1030-1042, `main()`
:2096-2110, `prune_status_lines` :2060-2094 as the read-only template); 16 `VENDORED_PATHS` copies
+ 12 `.ai-badger` mirrors re-landed same commit; `python3 tooling/sync_plugin_skills.py`.
**Tests:** red-first amends test_badger_store_session_families.py:597-619 and
test_badger_store.py:347-361; parametrized per-kind-group variants (map, kvdoc, awm, jsonl/recent,
tasks/usage/sessions, each file-set kind) asserting neighbours unaffected;
test_badger_store_task_family.py:411-422 passes unamended; test_p4_integration.py:310-345 passes
unamended (renamed `*.migrated.*` must not read as resurrection).
**ACs:** (1) resurrected map family: open succeeds, `kv_get` on it raises with upgrade pointer,
`searches` reads/writes normally; (2) same holds per kind group; (3) `doctor --status` names the
family, stamp, mtime; `doctor --repair` re-imports a jsonl kind idempotently, inspect-only for map
families; (4) vendored report empty.
**Gate:** `python3 -m pytest -q` (full: copies are global) + `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`.
**Deps:** none. Blocks P2, P3.

## P2 — Resolver independence + mint + den-refresh backfill + L1 (D2/L1) · serial store lane, 2nd

**Purpose:** resolver walks up to the nearest `.ai-badger`, reads the minted id; env override wins;
nested ambiguity refuses; id absent → None. Scaffold mints; den-refresh backfills. L1: first
delivery with `project_id=None` lands the cursor at max-over-delivered-legs, not global MAX(id).
**Files:** `engine/badger_store.py` (`resolve_project_id` :1923-1951 rewrite, raccoon surface
deletion :1846-1920, L1 fix :1766-1773); `features/common/skills/welcome-ai-badger/scripts/scaffold.py`
+ `skills/welcome-ai-badger/scripts/scaffold.py` (mint before :740-742);
`skills/den-refresh/scripts/refresh.py` (backfill between check_prerequisites :191-199 and
re_scaffold :213-230); all copies re-land same commit; tests/test_project_registry.py (bank
fixtures → id files), tests/test_send_message_skill.py:382, tests/test_message_bus_manifest.py
(:33, :68, :140-150), tests/test_message_bus_hermes.py:345, :362, tests/test_message_bus_store.py.
**ACs:** (1) red-first: seed broadcast + 1:1 in window, deliver with `project_id=None`, re-deliver
returns the broadcast (today it is silently consumed); pinned overflow test :545-559 stays green;
(2) nearest-id wins, second ancestor `.ai-badger` raises ProjectIdAmbiguous, callers fail open;
absent id → None; `AI_BADGER_PROJECT_ID` wins over the file; (3) scaffold mints and re-scaffold
preserves; (4) den-refresh backfills an id-less repo and the refreshed repo resolves;
(5) `raccoon_registry_surface` and `RACCOON_BANK_ENV` no longer exist (assertion test).
**Gate:** `python3 -m pytest -q` + `python3 -m pytest -q tests/test_badger_store_vendored.py` + `python3 tooling/sync_plugin_skills.py --check`.
**Deps:** P1; the three [OWNER] answers gate its start.

## P3 — Arm-env hold gate (D3) · serial store lane, 3rd

**Purpose:** `_hold_at` honours `AI_BADGER_TEST_HOLD` only when `AI_BADGER_TEST_HOLD_ARM` is also
set; in-process `_TEST_HOLDS` stay ungated.
**Files:** `engine/badger_store.py` `_hold_at` :97-106 (env branch only); all copies re-land same
commit; strip lists gain the arm env: tests/test_message_bus_integration.py:75, :191-198,
tests/test_message_bus_manifest.py:83, :411, tests/test_message_delivery_hook.py:85, :671;
store-level arming test test_message_bus_store.py:852-865 sets both.
**ACs:** (1) red-first: env hold without arm env returns immediately; with arm env parks until
release; (2) the two-child E2E race parks on the vendored copy's `deliver.after_read` and exactly
one child injects; (3) seam-prefix check `spec.startswith(f"{seam}:")` still pinned;
(4) shipped-pair byte-identity pin (test_adjust_hooks_copilot.py:419) green.
**Gate:** `python3 -m pytest -q tests/test_message_bus_integration.py tests/test_message_bus_store.py` then `python3 -m pytest -q`.
**Deps:** P2.

## P4 — pi defer (D4, pi side) · parallel lane X

**Purpose:** drop the sessionStart spawn; `beforeAgentStart` becomes an unconditional live read;
read+inject coincide in the store's one transaction.
**Files:** `features/pi/adjustments/adapter/hook-bridge.ts` (remove `pendingStart` :381, :399-404,
held-consume :406-419), `index.ts` (remove `pi.on("session_start")` wiring :379-384);
tests/js/pi_message_bus_adapter.test.mjs :97, :137, :193, :266, :293; tests/test_pi_adjustments.py
copy test + roundtrip test; Gherkin sc.1 reword + mirror tests/test_message_bus_integration.py:466-471.
**ACs:** (1) red-first: first `beforeAgentStart` with unread mail returns context AND advances the
cursor; a session that never reaches it leaves mail unconsumed, no cursor row; (2) no
`pendingStart`/sessionStart delivery arm remains in the router surface; (3) Rule 7 mutation flags
(test_message_bus_integration.py:576, :579-581) still pass.
**Gate:** `bun test tests/js/pi_message_bus_adapter.test.mjs && bun test features/pi && bunx tsc --noEmit -p features/pi`; python side `python3 -m pytest -q tests/test_pi_adjustments.py tests/test_message_bus_integration.py`.
**Deps:** none on store code; merge after P3 (shares test_message_bus_integration.py, disjoint hunks).

## P5 — Hermes defer (D4, Hermes side) · parallel lane Y

**Purpose:** drop `on_session_start_message_delivery` + `_bus_pending`; first `pre_llm_call`
consume-and-inject; `on_session_end` keeps cursor deletion.
**Files:** `features/common/hooks/ai_badger_hooks.py` (:957, :1001-1006, :1009-1025, :1040,
registration :1152-1157); mirror `.ai-badger/hooks/ai_badger_hooks.py` re-lands same commit;
tests/test_message_bus_hermes.py start-delivery tests amended.
**ACs:** (1) red-first: no session-start delivery registered; first `pre_llm_call` with unread
mail returns the injected context and advances the cursor once; (2) a session dying before its
first `pre_llm_call` consumes nothing (mail survives); `_bus_pending` symbol gone; (3) session_end
still deletes the cursor.
**Gate:** `python3 -m pytest -q tests/test_message_bus_hermes.py` then `python3 -m pytest -q`.
**Deps:** none on store code; merge after P2 (shares test_message_bus_hermes.py with P2's fixture rewrite, disjoint regions).

## P6 — Docs (D5/D6) · parallel lane Z

**Purpose:** changelog risk lines and the trust-boundary statement.
**Files:** docs/changelog/0.156.0-user-db-message-bus.md (P5–P8 wiring bullet :37-38 Copilot
`sessionEnd` residual-risk line; P3 :25-28 machine-local trust boundary);
`features/common/skills/send-message/SKILL.full.md` + `skills/send-message/SKILL.full.md`
("Sender identity is mandatory" :49), regenerate mirrors with
`python3 tooling/sync_plugin_skills.py`. D9/L7 registry_snapshot is moot on disk: dropped.
**ACs:** (1) P3 bullet states identity is asserted not authenticated and names the
`AI_BADGER_PROJECT_ID` mechanism; P5–P8 bullet carries the sessionEnd residual-risk sentence;
(2) SKILL.full.md trust-boundary paragraph present in both copies.
**Gate:** `python3 tooling/sync_plugin_skills.py --check`.
**Deps:** none.

## P7 — Copilot `if -f` guard (D7) · parallel lane W

**Purpose:** every generated Copilot hook row wraps its command in the existence guard.
**Files:** `features/copilot/adjustments/adjust_hooks.py` (shape (a) :125-131 carries the script
path alongside the rewrite; shape (b) :150-156 uses in-scope `rel_path`); copied `guarded()` shape;
tests/test_adjust_hooks_copilot.py pins amended (:58-59, :99-101, :143-145, :171-172, :209,
:253-257, :292-295, :383-385, :411-412); balance pins :210, :384 and artifact E2E :562 stay.
**ACs:** (1) red-first: generated `.github/hooks/ai-badger-hooks.json` rows each wrap the command
in the `if -f` guard; absent script yields the skipped `systemMessage`, not an error; (2) every
generated `bash` string keeps `bash.count('"') % 2 == 0`; (3) artifact E2E runs under `bash -c`
with the shipped file present.
**Gate:** `python3 -m pytest -q tests/test_adjust_hooks_copilot.py`.
**Deps:** none.

## P8 — Integration package (last)

**Purpose:** prove the packages compose; test + release bookkeeping only, no production edits.
**Files:** new tests/test_project_id_lifecycle.py; new tests/test_containment_bus_coexistence.py;
combined scenario in tests/test_message_bus_integration.py; `VERSION` bump;
docs/changelog/{new-version}-{slug}.md entry (the P6 amendments to 0.156.0 stay as ruled).
**ACs:**
1. Lifecycle loop: scaffold a throwaway repo → id minted → resolver finds it; strip the id →
   den-refresh backfills → resolver finds it; second nested `.ai-badger` → refuse; env override wins.
2. Coexistence: user DB with a resurrected marker-state file → bus open/send/receive works while
   the marker family refuses on access and `doctor --status` names it.
3. The E2E process race passes with the arm-env gate through the vendored copy, plus the
   contained-open + bus-still-works combination in one run.
4. Everything green: `python3 -m pytest -q`; `python3 tooling/index_build.py --check`;
   `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`;
   `bun test features/pi && bun test tests/js/pi_message_bus_adapter.test.mjs`;
   `python3 tooling/sync_plugin_skills.py --check`.
5. `VERSION` bumped and the changelog entry exists.
**Deps:** P1–P7 all merged.

## Parallelism, order of operations, budget

**Serial store lane:** P1 → P2 → P3, strictly. All three touch `engine/badger_store.py`, and
constraint 1 forces every store commit to re-land ~33 byte-identical copies; overlap is impossible.
**Parallel lanes** (own disjoint files, start immediately): X = P4, Y = P5, Z = P6, W = P7.
Merge order: P5 after P2, P4 after P3 (both share a test file with the store lane, disjoint
hunks); P6/P7 anytime; P8 last on the integrated branch.
**Green at every commit:** each store commit carries code + all copies + its amended tests in one
commit (c7424c6f precedent); each lane runs its own gate before merge; push early, draft PR.
**Budget:** subagent-sized — P1 (largest: store surgery + doctor + test matrix), P2 (multi-file,
owner-gated), P4 (js lane: TS + five test amendments), P7 (fiddly pin amendments), P5 (single hook
file + tests). In-orchestrator — P3 (one branch + strip lists), P6 (prose + sync check), P8
(cross-package verification, no production edits).

## Risk register

| # | Risk | Mitigation |
|---|---|---|
| R1 | A missed copy among ~33 across three serial re-lands → red vendored gate | copies re-land in the same commit; vendored gate + `sync_plugin_skills.py --check` before each store commit |
| R2 | Containment degrades to silent DB-only reads, violating ADR-0024 D5c | refuse-on-access uniform semantic; red-first raise assertion; task-family test must pass unamended |
| R3 | [OWNER] answers (shape/format/id-absent) arrive late and block P2 | P1, P3–P7 start now; P2 is the only owner-gated package |
| R4 | Nested-`.ai-badger` refusal hits live worktrees (this session's cwd is one) | sessions in nested dirs set `AI_BADGER_PROJECT_ID`; consumer-impact note in the changelog |
| R5 | Strip-list omissions leak the arm env into production-shaped children, or inert holds stall the E2E 15 s | research-c §3's six constraints checked per AC in P3 and re-run in P8 |
| R6 | Copilot guard breaks quoted-path balance or the artifact E2E | balance pins stay unamended as tripwires; E2E under `bash -c` in the P7 gate |
| R7 | Resolver rewrite breaks send-message sender resolution | send CLI tests (test_send_message_skill.py) rewritten in P2 with the same failure-open contract |
