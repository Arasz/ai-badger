# Research lane B — per-family containment on store open + doctor/repair path

Date: 2026-09-01 · Lane: B (read-only evidence record) · Owner ruling D1/M2, option c.
All paths relative to the `aib-bus-followups-independence` worktree at HEAD c7424c6f.

## 1. The open path and every raise site

`_open` (engine/badger_store.py:1991-2019): `_ensure_root` → `_precreate_db_file` → connect →
WAL/pragmas → `_create_schema` → `_ensure_schema_version` (:432; newer-version D27 raise
:462-466; upgrade hooks :467-477) → **`store._check_resurrections()`** at :2015. Any exception
closes the conn and re-raises (:2016-2018).

`_check_resurrections` (:916-929) iterates **every** family of this DB kind; a family with a
legacy file present raises via `_raise_on_resurrection` (:929; def :873-884) or, for
FILE_SET_KINDS (:733), `_raise_on_family_resurrection` (:923-924; def :952-963). Both raise
`sqlite3.OperationalError` with repair guidance (:877-881). Condition: `stamp is not None and
path.stat().st_mtime > stamp` (:876) — no stamp → no raise. Every call site:

| Site | Reached from (public surface) |
|---|---|
| `_check_resurrections` :924/:929 ← `_open` :2015 | `open_user` :2028, `open_tracking` :2021; tracker_lib `_open_store` (tracker_lib.py:453-457) |
| `_legacy_rows` :888 (kv_glob), :898 (map/kvdoc/awm) | reads `kv_get` :820, `kv_all` :834 |
| `_migrate_family` :1334 | writes `kv_set` :1207, `kv_delete` :1224, `kv_update` :1246, `log_append` :1300 via `migrate` :1314 |
| `_migrate_file_set` :1564 | same writes, file-set kinds |
| `_family_entries` :984 | `tasks_all` :995, `usage_all` :1015 |
| `sessions_map` inline :1042 | `sessions_map` :1030 |

Observed incident shape: commit_reminder (`legacy_kind="map"`, :557-561) resurrected → the
:2015 open gate raised → `open_user` dead for **all** user families, including the
born-in-SQLite, unresurrectable `messages`/`cursors` (:633-635, skipped at :920-921).

## 2. Containment semantics per legacy_kind

Family dataclass :484-513; `FAMILIES` :519, `USER_FAMILIES` :542; task families:
`_task_families` (tracker_lib.py:406-434).
- **store** (messages, cursors): no legacy path — nothing to contain (:633-635). Unaffected.
- **map** (marker_state :521-527; commit_reminder :557-561): reads `kv_get`/`kv_all` merge
  legacy through `_legacy_rows` :896-912 → contained: **skip the family's legacy merge, serve
  DB rows only** (condition surfaced, see §3 flag 2 — never silent). Writes `kv_set`/
  `kv_delete`/`kv_update` via `migrate` → `_migrate_family` :1334 → contained: **refuse the
  family's write** with the resurrection error (upgrade pointer, :877-881), scoped to its table.
- **kvdoc** (commit_reminder_pending :563-569, pending_feedback :570-576, hook_state :628-632,
  statusline ×2 tracker_lib.py:426-433) and **awm** (awm_state :543-549, merged via
  `_awm_projects` :910-911): one row under `row_key` merged at :908-909 — same read/write
  containment as map.
- **jsonl** (awm_decisions :550-556, hook_audit :622-627) and **recent** (searches :577-583):
  reads `log_rows` :1266 / `log_rows_since` :1280 are already DB-only; writes `log_append`
  :1297 → `migrate` raise → contained: reads unchanged; writes to that table refused.- **tasks/usage/sessions** (tracker_lib.py:415-425): reads `tasks_all` :995 / `usage_all`
  :1015 merge legacy via `_family_entries` :979-987 (raise :984); `sessions_map` :1030 raises
  at :1042. Writes `task_upsert` :1055 / `usage_upsert` :1082 / `session_upsert` :1104 do not
  migrate themselves — `tracking_transaction` migrates every `_TASK_FAMILY_TABLES` table
  (tracker_lib.py:461-472, tables at :403). Contained: `_family_entries` returns `[]`,
  `sessions_map` skips the family, the transaction's `migrate` skips the contained table,
  upserts proceed against DB rows only. In every case the other families' methods behave
  exactly as today — a per-family guard, not a global mode flag.
- **file-set kinds** (markers :586-591, nudges :592-597, lanes :598-603, kv_glob :604-610,
  stem_denials :611-616; gate call sites :923-924, :1564; kv_glob legacy reads :887-895):
  contained: open **detects but does not abort** for that family; kv_glob reads skip legacy files;
  writes via `_migrate_file_set` refused for that family.

## 3. The fail-closed contract (D5c/D27) — what containment must not weaken

- ADR-0024 decision 6 (docs/adr/0024-sqlite-runtime-store.md:57-60): "Readers merge the legacy
  file and the database per key with last-write-wins… On open, a legacy file whose mtime
  postdates the recorded migration stamp triggers re-import (append-only stores) or fail-closed
  with an upgrade pointer (map stores). **Silent divergence is never an option.**" Residual:
  stale-surface map writes "are not seen by current code until that surface refreshes".
- Open question 3, resolved (:110): stamp semantics — "mtime postdates stamp → re-import or
  fail closed, per kind"; per-key recency is DB-row presence.
- file-schemas.md:42-46 (same dual-read/resurrection text) and :264-266: "a legacy file that
  reappears after migration is treated as resurrection — re-imported (append-only families) or
  failed closed with an upgrade pointer (map families), per ADR-0024. An old `*.migrated.*`
  file left in place is inert."
- D8 keeps hooks fail-open at the caller layer (docs/adr/0024:70-72); tracker_lib:453-455:
  "raises… — callers decide fail-open (hooks) or fail-loud (CLI)".

**MUST-find flags:**
1. The written contract is per-family ("per kind", "map families") but **no text scopes the
   failure to the family**; the store-wide open gate is an implementation choice. Containment
   keeping (a) the per-family signal + upgrade pointer and (b) never treating a resurrected
   map/kvdoc/awm file's newer content as fresh does not violate the quoted text. The code is
   **stricter than written** for append-only kinds: `_migrate_family` :1334 raises before
   importing for every non-file-set kind, while the contract says re-import
   (file-schemas.md:45, :265) — a doctor that re-imports additive kinds is closer to the letter.
2. Containment must not turn a resurrected map/kvdoc/awm family into silent DB-only reads plus
   allowed writes: with a stamp present and a newer file, DB rows may be stale relative to the
   file — serving them without surfacing the condition is the divergence D5c prevents. Any
   read-side containment needs the condition surfaced (error on access, status surface, or
   explicit unavailable-state), not just skipped.

## 4. Tests pinning store-wide fail-closed today

- tests/test_badger_store_session_families.py:597-619
  `test_resurrected_legacy_file_fails_closed`: (a) `_open_user()` raises on a resurrected
  memory-first marker (:609-612, "open_user() must fail closed on a resurrected legacy file");
  (b) fresh `badger_store._open(..., USER_FAMILIES)` also raises (:616-619). **Both change**:
  open must succeed; variant asserts memory_first contained (per §2) while another family
  (e.g. searches) still opens, reads and writes normally.
- tests/test_badger_store.py:347-361 `test_resurrected_legacy_map_file_fails_closed`:
  `badger_store.open_tracking()` raises on resurrected marker-state.json (:359-361). Same
  change; tracking-side variant asserts marker_state contained, tasks/statusline unaffected.
- tests/test_badger_store_task_family.py:411-422
  `test_accessor_load_tasks_surfaces_resurrection_fail_closed`: `tracker_lib.load_tasks()`
  raises (via `_family_entries` :984). Already **per-family blast radius** — survives
  containment iff family-scoped reads still raise (§3 flag 2); if reads become DB-only, this
  test changes instead.
- tests/test_p4_integration.py pins the non-resurrection side only: the runbook drill
  (:310-345; restored `*.migrated.*` "reads as pre-migration legacy, not as a resurrection",
  :339) must keep passing — a repair must not make a restored file read as resurrected (a
  rename preserves mtime). Variants to add: one per kind group (map, kvdoc, awm, jsonl/recent,
  tasks/usage/sessions, each file-set kind) asserting neighbours stay usable.

## 5. The copies mechanism (byte-identical re-landing)

- Manifest lives **inside the canonical module**: `VENDORED_PATHS` (engine/badger_store.py:
  303-332, 16 repo-relative destinations, all landed here); check function
  `vendored_copies_report` (:334-357) byte-compares each landed copy against the **running**
  module (`Path(__file__).resolve()`, :338). `engine/framework_copies.py` is cache-tree
  ownership/prune, not copy sync (framework_copies.py:1-5). Gate:
  tests/test_badger_store_vendored.py:25-27 — report must be `[]`. No automated copier exists
  for the manifest (comment :300-302: vendorin "lands with the P0.5 re-scaffold and P2.2's
  mirror sync" — still pending). Precedent: commit c7424c6f re-landed every copy **by hand in
  the same commit** ("all vendored badger_store.py copies re-landed same-commit (F1)").
- After changing engine/badger_store.py an editor must: (1) byte-copy the canonical file over
  every landed `VENDORED_PATHS` destination (16, under features/ and skills/); (2) regenerate
  the skills/ mirrors with `python3 tooling/sync_plugin_skills.py` (copytrees whole skill dirs
  incl. scripts/, :5-12, :118); (3) re-land the 12 scaffolded `.ai-badger/` mirrors
  (.ai-badger/engine, .ai-badger/hooks, .ai-badger/skills/*/scripts) or via den-refresh
  re-scaffold; (4) run tests/test_badger_store_vendored.py + the store tests. ~33 copies exist.

## 6. Doctor verb — where it fits and what repair could do

- `badger_store.main()` (engine/badger_store.py:2096-2110): one verb today, `prune --status`.
  Its read-only pattern (`prune_status_lines` :2060-2094: `mode=ro`, never creates/migrates,
  absent DB reported) is the template for a `doctor --status` detection verb; shipping there
  lands it in all vendored copies automatically (§5).
- `skills/den-refresh/scripts/refresh.py` (main :304-352; drift :200-206): already detects
  drift, backs up `.ai-badger/`, re-scaffolds (SKILL.md: "Reports what changed, backs up
  .ai-badger/, and re-scaffolds"). Repair-at-update-time fits here — but den-refresh targets a
  **project's** `.ai-badger/`, while the incident surface is the **machine** user root
  (`_user_root` :529-532) — a user-DB doctor must resolve the user root, not the project root.
- `tooling/*.py` argparse verbs (validate.py:513, index_build.py:180) are repo-dev tools, not
  shipped to scaffolded projects — wrong home for a user-machine repair verb (HYPOTHESIS: from
  repo layout; tooling/ is absent from features/ packaging). The error messages already
  promise remedies: "restore the *.migrated.json name or den-refresh the stale surface"
  (:879-881) and "run den-refresh to upgrade ai-badger" (:464-465) — a doctor is where those
  promises become executable.

Repair options (content may be **newer** than the DB — that is why D5c fails closed):
- **Guidance-only / inspect**: read-only per-family report (stamp, file mtime, DB row counts,
  content diff vs DB) plus printed instructions — safest, weakest.
- **Salvage + re-import**: additive kinds (jsonl, recent, file-sets) import idempotently on
  natural keys / exact content keys (:1516-1520, :1543-1549, OR IGNORE :1376-1382) — re-import
  then rename to `*.migrated` loses nothing. For map/kvdoc/awm, OR IGNORE does **not** update
  keys the DB already holds, so newer legacy values would be silently dropped — salvage needs
  an explicit merge/LWW rule or owner-visible diff first.
- **Restamp/quarantine**: rename to `*.migrated` (or `.resurrected-<ts>` sidecar) without
  importing — declares the file inert (file-schemas.md:266) but **discards** newer legacy
  content; safe only after an inspect step confirms content matches the DB.

## Open design decisions for the plan

- Read-side containment semantics per kind: refuse with the resurrection error on the family's
  accessors (keeps test_badger_store_task_family.py:411-422 green) vs DB-only reads with the
  condition surfaced elsewhere — §3 flag 2 rules out silent DB-only.
- Whether `_check_resurrections` stays at open as a **detector** (record per-family unavailable
  state, expose via a status surface) or moves entirely to per-accessor time.
- What "unavailable" means for **writes** to a contained family: hard refuse (upgrade pointer)
  vs queue-vs-drop — map/kvdoc/awm writes currently raise before any DB mutation (:1334);
  decide what a hook caller's fail-open (D8) does with a refused write.
- Which kinds the doctor may auto-repair (re-import for additive kinds) vs inspect-only
  (map/kvdoc/awm), and whether re-import for append-only kinds reconciles the code (:1334
  raises) with the written contract (file-schemas.md:45, :265 says re-import).
- Where the doctor verb lives: `badger_store.py main()` subcommand (ships via §5 to every
  copy) vs den-refresh script vs both (detect in store, repair in den-refresh); and whether it
  targets the machine user root, the project tracking root, or both. Whether the vendored
  re-landing (§5) gets an automated copier (`vendorin`) as part of this change.
- Test-variant matrix scope: one containment test per kind group (§4) vs one parametrized
  family sweep; and which secondary observables pin "neighbours unaffected" (bus open/read/
  write, prune runs, message send/receive).
