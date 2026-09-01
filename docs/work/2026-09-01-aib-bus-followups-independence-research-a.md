# Research A — ai-badger-independent project resolution (evidence record)

Lane A, 2026-09-01, read-only worktree `aib-bus-followups-independence`. Owner ruling: the bus's
cwd→project_id resolver must stop reading the ai-raccoon bank; where there is `.ai-badger/` there
is a project; id minted at scaffold time, den-refresh backfills; env override wins; nested
ambiguity still refuses; L1 cursor lands at max-over-delivered-legs.

## 1. Current resolver surface and every caller

All in `engine/badger_store.py` (canonical; byte-identical vendored copies exist — see below):

- `PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"` — explicit override, set-and-non-blank wins before
  any registry read (engine/badger_store.py:1839-1843, 1928-1931).
- `RACCOON_BANK_ENV = "AI_BADGER_RACCOON_DB"`, default `~/.ai-raccoon/memory.db`,
  `_SCOPE_KEY_PREFIX = "ingest.scope."` (engine/badger_store.py:1846-1852).
- `ProjectIdAmbiguous` — refusal outcome, carries sorted `candidates` (engine/badger_store.py:1854-1859).
- `_real_path` — realpath+abspath containment identity (engine/badger_store.py:1861-1866).
- `_path_contains` — equal-or-ancestor prefix containment (engine/badger_store.py:1868-1873).
- `raccoon_registry_surface()` — read-only sqlite connect to the bank; `settings`
  `ingest.scope.<id>` keys + `watches` rows; `global` scope skipped; absent/unreadable bank
  yields `{}` (engine/badger_store.py:1881-1920).
- `resolve_project_id(cwd, registry=None)` — override → probe → surface → sorted matches →
  0 = None, >1 = raise, 1 = id (engine/badger_store.py:1923-1951).

Callers (repo-wide; the store is vendored per `VENDORED_PATHS`,
features/common/skills/welcome-ai-badger/scripts/badger_store.py:303-340, byte-equality enforced
by `vendored_copies_report`, same file :345-359; `engine/badger_store.py` and
`features/common/hooks/badger_store.py` verified identical via `cmp`):

- Claude-shaped delivery hook: `features/common/hooks/message_delivery_hook.py:81` (resolve inside
  `_resolve_project`, ambiguity → None → 1:1 only, :76-83), delivery at :104-113.
- Hermes plugin delivery: `features/common/hooks/ai_badger_hooks.py:978` (+ :984 `deliver_for_session`).
- Send CLI: `features/common/skills/send-message/scripts/send_message.py:95` (sender resolution)
  and :148-151 (ambiguous → refusal, exit 1). `deliver_for_session` call sites: hook :109,
  hermes :984.
- No MCP tool calls `resolve_project_id` (grep over features/: only hooks + send-message hits).
- The send-message skill ships its own hook copy:
  `features/common/skills/send-message/scripts/message_delivery_hook.py:81` (wired copy per
  tests/test_message_bus_manifest.py:34-36).

Tests pinning raccoon-bank behavior:

- `tests/test_project_registry.py` — the resolver's red-test suite: synthetic bank via
  `AI_BADGER_RACCOON_DB` (:14, :48), `_make_bank` writes `ingest.scope.<id>` keys (:75-91);
  tests 11-13 pin the default reader (`test_raccoon_reader_reads_scope_arrays_and_watch_rows`
  :234, `..._skips_the_global_scope_and_bad_rows` :252, `test_unreadable_bank_reads_as_empty...`
  :271); test 8 pins env-override-wins via a throwing registry fake (:182).
- `tests/test_send_message_skill.py` — send CLI resolves sender from the bank
  (`test_sender_project_resolves_from_the_raccoon_registry` :382; bank writer :108-139).
- `tests/test_message_bus_manifest.py` — hook-level wiring tests redirect
  `AI_BADGER_RACCOON_DB` at a synthetic bank (:33, :68) and register scope keys
  (`_register_bank` :140-150).
- `tests/test_message_bus_hermes.py:345,362` — unresolved/ambiguous project → 1:1 only.

All three test files would need their bank fixtures replaced by in-repo `.ai-badger` id files;
the ambiguity and containment tests survive conceptually but change mechanism.

## 2. Scaffold write points, validation, re-scaffold idempotency

- The scaffolder is `features/common/skills/welcome-ai-badger/scripts/scaffold.py` (mirror at
  `skills/welcome-ai-badger/scripts/scaffold.py`); CLI validates config first
  (`bl.validate_file(config_path, root/'schemas'/'config.schema.json')`, scaffold.py:810-813).
- config.json is **rewritten every run**: `written_config = dict(self.config)` +
  `frameworkVersion`, then `bl.dump_json(self.aib / "config.json", written_config)`
  (scaffold.py:740-742). The existing `.ai-badger/config.json` is NOT read back — a minted id
  inside config.json would be lost on re-scaffold unless the run merges it in first.
- Seed-once (preserved) files: state.json, agent-instructions/model.json,
  markers-context.json (scaffold.py:420-427, :791-794). `--reset-seed-files` discards.
- config.schema.json: top-level `required` frameworkVersion/project/stacks/agents and
  `"additionalProperties": false` (schemas/config.schema.json:9-16) — an unknown id field fails
  validation today. Adding it = schema edit + config-hash churn (`configHash` in manifest,
  scaffold.py:762) + scaffold merge logic + refresh validation.
- Re-scaffold (den-refresh) path re-reads config and re-scaffolds; refresh validates config
  against the same schema (refresh.py:336-350) and re_scaffold passes the loaded dict into the
  Scaffolder (refresh.py:213-230). Note refresh.py:449: "config.json is project-owned and a
  refresh does not rewrite it (#172)" — content-stable because the same input round-trips.
- Validation engine: `tooling/validate.py` (`SCHEMA_INSTANCES`, :484-505; config stack-gap check
  :540-545) — validates the framework catalog, not target repos. `tooling/index_build.py --check`
  is the build gate over the catalog (repo CLAUDE.md build command). Neither would see a minted
  id in a *target* repo; only schema validity of config.json is checked at scaffold/refresh time.

## 3. den-refresh backfill

- Flow: `skills/den-refresh/SKILL.md` — script does mechanical work; prerequisites are
  `.ai-badger/config.json` + `manifest.json` (SKILL.md "Prerequisites"; code
  `check_prerequisites`, refresh.py:191-199). It backs up `.ai-badger/` → `.ai-badger.bckp/`
  (refresh.py:180-186), runs drift, and re-scaffolds with the existing config (refresh.py:213-230)
  from the framework at `$AI_BADGER`.
- Backfit point: after `check_prerequisites` passes and before `re_scaffold` — mint the id into
  config.json (or the dedicated file) and let the re-scaffold persist it. Refresh already loads
  and re-validates config (refresh.py:336-344), so a mint step there lands in both file shapes.
- Fleet mid-backfill: repos refreshed after the release have ids; not-yet-refreshed repos have
  `.ai-badger/` with no id. The resolver must define behavior for "id absent" (see §4) until the
  fleet converges. HYPOTHESIS: drift notices alone will not force refresh; some repos stay
  id-less indefinitely, so the None/refuse behavior is a permanent state, not a migration window.

## 4. Redesign evidence: file shape + walk policy

Candidates vs criteria:

- (a) Schema/validation churn — config.json field: schema edit + additionalProperties:false
  update + manifest configHash churn + scaffold must merge (it rewrites config wholesale,
  scaffold.py:740-742). Dedicated `.ai-badger/project-id` file: zero schema churn; not part of
  any manifest/drift surface (drift compares manifest entries,
  refresh.py:207-212), so nothing validates or guards it — no gate, no hash.
- (b) Resolver read cost — today: one sqlite open + two queries per resolution
  (engine/badger_store.py:1897-1918). Either file shape is one read at the located `.ai-badger`;
  an upward walk adds one stat per ancestor directory until a hit (or FS root).
- (c) Pre-scaffold / deleted-config — dedicated file: survives config.json deletion or
  hand-edit churn; config.json field: dies with the file. Both are inert before scaffold
  (no `.ai-badger` ⇒ no project ⇒ None).
- Walk policy inputs: the probe today is `$CLAUDE_PROJECT_DIR` else payload cwd
  (features/common/hooks/message_delivery_hook.py:66-73); `_real_path` canonicalizes
  (engine/badger_store.py:1861-1866). A linear upward walk on one path has a single ancestor
  chain, so "nearest .ai-badger wins" is deterministic; this worktree itself is the live case
  (worktree root has `.ai-badger/`, and the parent main repo's `.ai-badger/` sits above it in
  the walk). Multiple-match ambiguity as implemented today (several registry ids containing the
  cwd, engine/badger_store.py:1945-1950) has no direct analog once ids are per-directory —
  whether some refusal must survive (e.g., marker file vs directory, or parent-root conflict)
  is open; `ProjectIdAmbiguous` callers all already catch it and fail open to None
  (message_delivery_hook.py:82-83, send_message.py:148-151, ai_badger_hooks.py:978-981).

## 5. L1 leg-scoped cursor

- Read legs: `_read_addressed` builds the three D3 shapes — 1:1 always; project + broadcast
  branches only when `project_id` truthy (engine/badger_store.py:1794-1817, :1802-1806).
- First-delivery branch (`row is None`): gated read (`since_ts=cutoff`, `_GATE_WINDOW` 30 min,
  engine/badger_store.py:40), cap `_START_CAP = 16` (:45), then
  `next_cursor = SELECT COALESCE(MAX(id), 0) FROM messages` — **MAX over ALL messages**,
  (engine/badger_store.py:1766-1773). With `project_id=None` only 1:1 rows are delivered, but the
  cursor still lands past project/broadcast rows inside the window ⇒ consumed, never revisited.
  The comment cites R5 "overflow never revisited" — written for the all-legs case (D6/D7).
- Live branch is fine: `id > cursor`, cursor = last returned row (engine/badger_store.py:1774-1778).
- Pinned tests: `test_deliver_without_project_id_delivers_one_to_one_only` checks the delivered
  list only — **no cursor assertion in the None case** (tests/test_message_bus_store.py:422-436).
  The MAX(id) landing is pinned only with all legs running
  (`test_overflow_beyond_sixteen_is_dropped_and_never_redelivered` asserts `cursor_id >= newest`
  with project_id "P", tests/test_message_bus_store.py:545-559; also
  `test_cursorless_live_read_applies_the_gate_once` :492-510). So the L1 fix has no red test
  today; the TDD gate needs one that seeds a broadcast + a 1:1, delivers with project_id=None,
  then re-delivers and expects the broadcast to surface.
- Minimal shape: in the `row is None` branch only, when `project_id` is None compute
  `next_cursor = max(id of rows[:_START_CAP], default 0)` (max-over-delivered-legs) instead of
  global MAX(id); keep global MAX(id) when all legs ran, so the R5 overflow guarantee and the
  two pinned tests above stay intact. HYPOTHESIS: when `project_id` is set but zero rows
  matched, global MAX(id) remains correct because all legs were exercised.

## Open design decisions for the plan

- File shape: minted id inside `.ai-badger/config.json` (schema `additionalProperties:false`
  must open a property; scaffold must merge on re-write) vs dedicated `.ai-badger/project-id`
  file (no schema churn, but outside manifest/drift/hash coverage).
- Id format and minting source (uuid4? repoAlias-derived? `sourceControl.repoAlias` already
  exists in the schema, schemas/config.schema.json:82) and where minting lives in
  scaffold.py `run()` (must precede the config write, scaffold.py:740-742).
- Resolver behavior when `.ai-badger/` exists but carries no id (legacy repo, mid-backfill
  fleet): return None (env-only delivery) vs refuse with candidates.
- Walk policy: nearest-`.ai-badger`-wins vs refuse when an ancestor `.ai-badger` is also
  present; whether `ProjectIdAmbiguous` survives, is repurposed, or is replaced by a
  no-marker error.
- Whether the raccoon surface (`raccoon_registry_surface`, `RACCOON_BANK_ENV`,
  `AI_BADGER_RACCOON_DB`) is deleted outright or kept behind a deprecation shim for one
  release; same for the three test files' bank fixtures.
- L1 scope: fix only the `project_id=None` first-delivery branch (minimal) vs make
  max-over-delivered-legs the landing rule for every first delivery (changes the pinned
  overflow guarantee, tests/test_message_bus_store.py:556-559).
- Vendored-copy rollout: engine/badger_store.py is byte-equality canonical for 17 copies
  (VENDORED_PATHS) — whether the refactor edits features/common/hooks/badger_store.py in
  lockstep or re-runs the mirror sync.
- den-refresh backfill placement and report shape (new report key vs note), and whether
  refresh refuses or warns when minting is skipped.