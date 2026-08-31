"""Red tests for the session-store families + D10 migration spec (P2.0) — the contract
P2.1a/b implement.

Extends the USER DB with the seven session-store families (plan rev 2, store inventory):

    memory_first         (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                          denials INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)
                         — ~/.ai-badger/memory-first/<uuid> is an EMPTY file whose presence
                           means "consulted" (verified on this machine: all 573 markers are
                           0 bytes); <uuid>.denials sidecars hold a bare integer count.
                           Both facts about a session land in ONE row: consulted in payload,
                           the denial count in the denials counter column.
    semantica_nudge      (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                          updated_at TEXT NOT NULL)
                         — ~/.ai-badger/semantica-nudge/<uuid> entries are EMPTY files (711
                           on this machine; the plan's "711 dirs" is wrong — they are flat
                           files, no subdirectories exist). Presence = nudge shown; payload
                           pins {"shown": true}.
    dispatch_lanes       (lane_id TEXT PRIMARY KEY, entries TEXT NOT NULL,
                          updated_at TEXT NOT NULL)
                         — ~/.ai-badger/dispatch-lanes/<uuid> files are NOT JSON: lines of
                           "<epoch-float> <tool_use_id>". The whole lane's lines become the
                           entries JSON column (whole-document payload invariant).
    dirty_sweeps         (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)
                         — ~/.ai-badger/dirty-sweep-<hash>.json; the natural key is the
                           legacy hash verbatim (sha1 of the MAIN checkout root, 16 hex
                           chars, D4): all worktrees of a repo share one record, and the key
                           is NOT re-derived from the opening repo.
    blast_radius_denials (key TEXT PRIMARY KEY, denials INTEGER NOT NULL,
                          updated_at TEXT NOT NULL)
                         — ~/.ai-badger/blast-radius-guard/<session>.<project-hash>.denials
                           hold a bare integer; the natural key is the filename stem, which
                           encodes session AND project (a session counts per project).
    hook_audit           (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
                          payload TEXT NOT NULL) + idx_hook_audit_ts
                         — ~/.ai-badger/debug/audit.jsonl lines carry their timestamp in the
                           "t" field (NOT "ts"): the import uses it verbatim, the whole line
                           is the payload, and the ts-index DDL convention applies (D17c).
    hook_state           (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)
                         — ~/.ai-badger/debug/state.json is one document (D26): it imports
                           as a single kvdoc row under key "debug".

D10 per-family migration spec, pinned as behavior (mechanism stays implementer freedom):

  - Natural key per family: session id / lane id / legacy hash / filename stem / (ts, payload).
  - Idempotent import: INSERT OR IGNORE on the natural key — a re-import adds nothing.
  - Multi-file families (directory- or pattern-backed) import RESUMABLY: a crash between
    COMMIT and the rename leaves rows imported and legacy files present; the next import
    completes without duplicates (D6).
  - RENAME CONVENTION (pinned): per-FILE rename, "<name>.migrated[.<suffix>]" in place —
    marker <uuid> becomes <uuid>.migrated, a <uuid>.denials sidecar becomes
    <uuid>.migrated.denials, dirty-sweep-<h>.json becomes dirty-sweep-<h>.migrated.json.
    The legacy DIRECTORY itself is never renamed or removed (a stale surface may keep
    writing new files there, D5); after a family's import no original filename remains,
    so nothing can resurrect.
  - Dual-read window: until a family migrates, KV reads merge legacy rows (DB wins on key
    collision, D5a) — including the new file-name-keyed dirty_sweeps shape; after
    migration a resurrected legacy file fails closed on open and on migrate (D5c).

hook_audit is an append-log: no KV dual-read (the P1.2b jsonl precedent — its legacy lines
are preserved by the lazy import itself).

Test map:
  1. DDL ........................................ test_open_user_creates_session_family_tables,
                                                   test_hook_audit_ts_index_exists_in_sqlite_master,
                                                   test_hook_state_kv_round_trips,
                                                   test_memory_first_table_carries_denials_counter
  2. Family registration ........................ test_session_families_registered_in_user_families,
                                                   test_session_family_legacy_paths_follow_user_root_env
  3. D10 import specs ........................... test_memory_first_import_marks_consulted_and_counts_denials,
                                                   test_memory_first_import_is_idempotent_on_session_id,
                                                   test_semantica_nudge_import_keys_sessions_and_is_idempotent,
                                                   test_dispatch_lanes_import_keeps_entry_lines,
                                                   test_dirty_sweeps_natural_key_is_the_legacy_hash,
                                                   test_blast_radius_denials_key_is_the_filename_stem,
                                                   test_hook_audit_import_uses_line_ts_and_dedups,
                                                   test_hook_state_imports_state_doc_as_one_kv_row
  4. Resumability + rename convention (D10/D6) .. test_multi_file_family_import_is_resumable_after_crash,
                                                   test_directory_family_rename_is_per_file
  5. Dual-read window (D5a/D5c) ................. test_dirty_sweeps_kv_read_merges_legacy_files_pre_migration,
                                                   test_resurrected_legacy_file_fails_closed
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import badger_store

_SESSION = "01a04e01-18b7-7f42-88c6-19e68738589d"
_SESSION2 = "01a04e10-7099-767a-8cbc-b2d419f8c166"
_PROJ_HASH = "ba748e8f973fc5f04f2b4ca5b9dbf308"


def _user_env(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "user-root"
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(root))
    return root


def _open_user():
    return badger_store.open_user()


# ---------------------------------------------------------------------------
# 1. DDL
# ---------------------------------------------------------------------------


def test_open_user_creates_session_family_tables(tmp_path, monkeypatch):
    """open_user() creates the seven session-store tables with their pinned columns."""
    _user_env(tmp_path, monkeypatch)
    store = _open_user()
    try:
        have = {
            row[0]
            for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in ("memory_first", "semantica_nudge", "dispatch_lanes", "dirty_sweeps",
                      "blast_radius_denials", "hook_audit", "hook_state"):
            assert table in have, f"session family table {table} missing from the user DB"
        columns = {
            table: [row[1] for row in store.conn.execute(f"PRAGMA table_info({table})")]
            for table in ("memory_first", "semantica_nudge", "dispatch_lanes",
                          "dirty_sweeps", "blast_radius_denials", "hook_audit", "hook_state")
        }
        assert columns["memory_first"] == [
            "session_id", "payload", "denials", "updated_at"]
        assert columns["semantica_nudge"] == ["session_id", "payload", "updated_at"]
        assert columns["dispatch_lanes"] == ["lane_id", "entries", "updated_at"]
        assert columns["dirty_sweeps"] == ["key", "value", "updated_at"]
        assert columns["blast_radius_denials"] == ["key", "denials", "updated_at"]
        assert columns["hook_audit"] == ["id", "ts", "payload"]
        assert columns["hook_state"] == ["key", "value", "updated_at"]
    finally:
        store.close()


def test_hook_audit_ts_index_exists_in_sqlite_master(tmp_path, monkeypatch):
    """The ts-index DDL convention covers hook_audit: idx_hook_audit_ts ON hook_audit(ts)."""
    _user_env(tmp_path, monkeypatch)
    store = _open_user()
    try:
        row = store.conn.execute(
            "SELECT tbl_name, sql FROM sqlite_master "
            "WHERE type='index' AND name='idx_hook_audit_ts'"
        ).fetchone()
        assert row is not None, "idx_hook_audit_ts missing from sqlite_master (D17c)"
        assert row[0] == "hook_audit"
        assert "ts" in row[1]
    finally:
        store.close()


def test_hook_state_kv_round_trips(tmp_path, monkeypatch):
    """hook_state is a KV table: set/get/delete through the store's KV seam."""
    _user_env(tmp_path, monkeypatch)
    store = _open_user()
    try:
        store.kv_set("hook_state", "debug", {"enabled": True, "scope": "user"})
        assert store.kv_get("hook_state", "debug") == {"enabled": True, "scope": "user"}
        assert store.kv_get("hook_state", "missing", "d") == "d"
        store.kv_delete("hook_state", "debug")
        assert store.kv_get("hook_state", "debug") is None
    finally:
        store.close()


def test_memory_first_table_carries_denials_counter(tmp_path, monkeypatch):
    """The denials counter is a real defaulted column — a session's denial count is
    filtered data (gate MAX_DENIALS), so it is a column, not buried in payload."""
    _user_env(tmp_path, monkeypatch)
    store = _open_user()
    try:
        store.conn.execute(
            "INSERT INTO memory_first(session_id, payload, updated_at) VALUES (?, ?, ?)",
            (_SESSION, json.dumps({"consulted": True}), badger_store._now()),
        )
        row = store.conn.execute(
            "SELECT denials FROM memory_first WHERE session_id = ?", (_SESSION,)
        ).fetchone()
        assert row == (0,), "denials must default to 0"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. Family registration
# ---------------------------------------------------------------------------


def test_session_families_registered_in_user_families():
    """USER_FAMILIES carries the seven session-store families, all user-DB, correct tables."""
    families = badger_store.USER_FAMILIES
    expected = {
        "memory_first": "memory_first",
        "semantica_nudge": "semantica_nudge",
        "dispatch_lanes": "dispatch_lanes",
        "dirty_sweeps": "dirty_sweeps",
        "blast_radius_denials": "blast_radius_denials",
        "hook_audit": "hook_audit",
        "hook_state": "hook_state",
    }
    for name, table in expected.items():
        family = families.get(name)
        assert family is not None, f"session family {name} not registered in USER_FAMILIES"
        assert family.table == table
        assert family.db == "user"


def test_session_family_legacy_paths_follow_user_root_env(tmp_path, monkeypatch):
    """Every session-family legacy path resolves under AI_BADGER_USER_ROOT at call time:
    memory-first/, semantica-nudge/, dispatch-lanes/, blast-radius-guard/ directories, the
    dirty-sweep pattern's parent (the user root itself), debug/audit.jsonl, debug/state.json."""
    root = _user_env(tmp_path, monkeypatch)
    families = badger_store.USER_FAMILIES
    paths = {name: families[name].legacy_path() for name in families}
    assert paths["memory_first"] == root / "memory-first"
    assert paths["semantica_nudge"] == root / "semantica-nudge"
    assert paths["dispatch_lanes"] == root / "dispatch-lanes"
    assert paths["dirty_sweeps"].parent == root
    assert paths["blast_radius_denials"] == root / "blast-radius-guard"
    assert paths["hook_audit"] == root / "debug" / "audit.jsonl"
    assert paths["hook_state"] == root / "debug" / "state.json"


# ---------------------------------------------------------------------------
# 3. D10 import specs (legacy fixtures mirror the real shapes inspected 2026-08-31)
# ---------------------------------------------------------------------------


def _seed_memory_first(root: Path) -> Path:
    """Real shape: <uuid> empty presence markers + <uuid>.denials integer sidecars."""
    d = root / "memory-first"
    d.mkdir(parents=True)
    (d / _SESSION).write_bytes(b"")  # presence marker, 0 bytes like every real sample
    (d / f"{_SESSION}.denials").write_text("3", encoding="utf-8")
    (d / f"{_SESSION2}.denials").write_text("5", encoding="utf-8")  # denials-only session
    return d


def test_memory_first_import_marks_consulted_and_counts_denials(tmp_path, monkeypatch):
    """One row per session: consulted in payload, denial count in the denials column —
    including a denials-only session that never had a marker file."""
    root = _user_env(tmp_path, monkeypatch)
    _seed_memory_first(root)
    store = _open_user()
    try:
        store.migrate("memory_first")
        rows = {
            row[0]: (row[1], row[2])
            for row in store.conn.execute(
                "SELECT session_id, payload, denials FROM memory_first")
        }
        assert rows[_SESSION][1] == 3
        assert json.loads(rows[_SESSION][0]).get("consulted") is True
        assert rows[_SESSION2][1] == 5
    finally:
        store.close()


def test_memory_first_import_is_idempotent_on_session_id(tmp_path, monkeypatch):
    """Re-importing the same legacy files adds nothing (D10: INSERT OR IGNORE on the
    natural key). Simulated crash-after-COMMIT-before-rename: rows present, files back
    under their original names — the second import must not duplicate."""
    root = _user_env(tmp_path, monkeypatch)
    d = _seed_memory_first(root)
    store = _open_user()
    try:
        store.migrate("memory_first")
        before = store.conn.execute(
            "SELECT count(*) FROM memory_first").fetchone()[0]
        for migrated in list(d.glob("*.migrated*")):
            original = migrated.name.replace(".migrated", "")
            os.replace(migrated, d / original)  # the crash window: rename undone
        store.migrate("memory_first")
        after = store.conn.execute("SELECT count(*) FROM memory_first").fetchone()[0]
        assert before == 2, "first import should have landed 2 session rows"
        assert after == before, "re-import duplicated rows (natural key not enforced)"
    finally:
        store.close()


def test_semantica_nudge_import_keys_sessions_and_is_idempotent(tmp_path, monkeypatch):
    """711 empty <uuid> files in the real dir: each becomes one session row, payload
    {"shown": true}; a re-import adds nothing."""
    root = _user_env(tmp_path, monkeypatch)
    d = root / "semantica-nudge"
    d.mkdir(parents=True)
    for uuid in (_SESSION, _SESSION2):
        (d / uuid).write_bytes(b"")
    store = _open_user()
    try:
        store.migrate("semantica_nudge")
        store.migrate("semantica_nudge")  # idempotency: second import is a no-op
        rows = {
            row[0]: json.loads(row[1])
            for row in store.conn.execute(
                "SELECT session_id, payload FROM semantica_nudge")
        }
        assert set(rows) == {_SESSION, _SESSION2}
        assert rows[_SESSION] == {"shown": True}
    finally:
        store.close()


def test_dispatch_lanes_import_keeps_entry_lines(tmp_path, monkeypatch):
    """A lane file is NOT JSON: lines of '<epoch-float> <tool_use_id>' (real sample
    dispatch-lanes/5aae500b...). The lane imports as ONE row keyed on the lane id, its
    lines preserved as the entries JSON column."""
    root = _user_env(tmp_path, monkeypatch)
    d = root / "dispatch-lanes"
    d.mkdir(parents=True)
    (d / "5aae500b-13fe-4392-b18d-c0a6c7bb50ea").write_text(
        "1787911664.227173 toolu_01KSekMtzFGmXVZg4yKfKe6y\n"
        "1787912636.8198888 toolu_0193JYBQZmEW8hzTqeCDCgir\n", encoding="utf-8")
    store = _open_user()
    try:
        store.migrate("dispatch_lanes")
        rows = {
            row[0]: row[1]
            for row in store.conn.execute("SELECT lane_id, entries FROM dispatch_lanes")
        }
        assert set(rows) == {"5aae500b-13fe-4392-b18d-c0a6c7bb50ea"}
        entries = json.loads(rows["5aae500b-13fe-4392-b18d-c0a6c7bb50ea"])
        assert len(entries) == 2
        assert entries[0]["ts"] == "1787911664.227173"
        assert entries[0]["tool_use_id"] == "toolu_01KSekMtzFGmXVZg4yKfKe6y"
        store.migrate("dispatch_lanes")  # idempotent on the lane id
        assert store.conn.execute(
            "SELECT count(*) FROM dispatch_lanes").fetchone()[0] == 1
    finally:
        store.close()


def test_dirty_sweeps_natural_key_is_the_legacy_hash(tmp_path, monkeypatch):
    """D4: the natural key is the legacy filename hash verbatim — sha1 of the MAIN
    checkout root, 16 hex chars. Two hashes (two repos) give two rows; the same hash
    re-imports into one row; worktrees share the record by construction (same hash)."""
    root = _user_env(tmp_path, monkeypatch)
    doc = {"dirty": True, "checked_at": "2026-08-31T17:39:24+00:00"}
    (root / "dirty-sweep-abc123def4567890.json").write_text(
        json.dumps(doc), encoding="utf-8")
    (root / "dirty-sweep-ffff00001111aaaa.json").write_text(
        json.dumps({"dirty": False}), encoding="utf-8")
    store = _open_user()
    try:
        store.migrate("dirty_sweeps")
        store.migrate("dirty_sweeps")  # idempotency
        rows = {
            row[0]: json.loads(row[1])
            for row in store.conn.execute("SELECT key, value FROM dirty_sweeps")
        }
        assert set(rows) == {"abc123def4567890", "ffff00001111aaaa"}
        assert rows["abc123def4567890"] == doc
    finally:
        store.close()


def test_blast_radius_denials_key_is_the_filename_stem(tmp_path, monkeypatch):
    """Real shape blast-radius-guard/<session>.<project-hash>.denials (integer content):
    the key is the filename stem (session AND project — a session counts per project),
    the count lands in the denials column."""
    root = _user_env(tmp_path, monkeypatch)
    d = root / "blast-radius-guard"
    d.mkdir(parents=True)
    name = f"{_SESSION}.{_PROJ_HASH}.denials"
    (d / name).write_text("1", encoding="utf-8")
    store = _open_user()
    try:
        store.migrate("blast_radius_denials")
        row = store.conn.execute(
            "SELECT key, denials FROM blast_radius_denials").fetchone()
        assert row == (f"{_SESSION}.{_PROJ_HASH}", 1)
        store.migrate("blast_radius_denials")  # idempotent on the stem key
        assert store.conn.execute(
            "SELECT count(*) FROM blast_radius_denials").fetchone()[0] == 1
    finally:
        store.close()


def test_hook_audit_import_uses_line_ts_and_dedups(tmp_path, monkeypatch):
    """Real audit.jsonl lines carry their timestamp in the "t" field (NOT "ts"): the
    import takes ts from "t" verbatim, stores the line verbatim as payload, dedups on
    (ts, payload), and a torn line quarantines (skipped; file still renamed)."""
    root = _user_env(tmp_path, monkeypatch)
    (root / "debug").mkdir(parents=True)
    good1 = ('{"t": "2026-08-31T17:39:24+00:00", "c": "grounded_feedback_hook", '
             '"e": "skip", "v": "0.150.0"}')
    good2 = ('{"t": "2026-08-31T17:40:00+00:00", "c": "prompt_markers", '
             '"e": "expand", "v": "0.150.0"}')
    (root / "debug" / "audit.jsonl").write_text(
        f"{good1}\n{good2}\n{{torn json\n", encoding="utf-8")
    store = _open_user()
    try:
        store.migrate("hook_audit")
        rows = list(store.conn.execute(
            "SELECT ts, payload FROM hook_audit ORDER BY ts"))
        assert [r[0] for r in rows] == [
            "2026-08-31T17:39:24+00:00", "2026-08-31T17:40:00+00:00"]
        assert rows[0][1] == good1
        assert len(rows) == 2, "torn line must not import"
        store.migrate("hook_audit")  # idempotent on (ts, payload)
        assert store.conn.execute("SELECT count(*) FROM hook_audit").fetchone()[0] == 2
    finally:
        store.close()


def test_hook_state_imports_state_doc_as_one_kv_row(tmp_path, monkeypatch):
    """debug/state.json is one document (D26): it imports as a single hook_state row under
    key "debug" — the kvdoc pattern pending-feedback.json already uses."""
    root = _user_env(tmp_path, monkeypatch)
    (root / "debug").mkdir(parents=True)
    doc = {"enabled": True, "scope": "user", "project": None,
           "enabled_at": "2026-08-14T13:08:37+00:00", "expires_at": None}
    (root / "debug" / "state.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    store = _open_user()
    try:
        store.migrate("hook_state")
        assert store.kv_get("hook_state", "debug") == doc
        store.migrate("hook_state")  # idempotent on the row key
        assert store.conn.execute(
            "SELECT count(*) FROM hook_state").fetchone()[0] == 1
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4. Resumability + per-file rename convention (D10/D6)
# ---------------------------------------------------------------------------


def test_multi_file_family_import_is_resumable_after_crash(tmp_path, monkeypatch):
    """D10: a multi-file family's import is resumable. Simulated crash mid-import —
    some files fully migrated (rows + rename), one restored to its original name —
    then the next import completes: no duplicates, the straggler re-renamed, and no
    original filename left in the legacy directory (nothing resurrectable)."""
    root = _user_env(tmp_path, monkeypatch)
    d = _seed_memory_first(root)
    (d / _SESSION2).write_bytes(b"")  # a third artifact: marker for session2 too
    store = _open_user()
    try:
        store.migrate("memory_first")
        # Crash window: one straggler file's rename never happened.
        straggler = d / f"{_SESSION}.denials.migrated.denials"
        os.replace(straggler, d / f"{_SESSION}.denials")
        store.migrate("memory_first")  # the next import resumes
        count = store.conn.execute("SELECT count(*) FROM memory_first").fetchone()[0]
        assert count == 2, f"resumed import duplicated rows: {count} != 2"
        originals = [p.name for p in d.iterdir()
                     if p.name != ".write.lock" and ".migrated" not in p.name]
        assert originals == [], f"resurrectable originals left behind: {originals}"
        assert straggler.exists(), "the straggler was not re-renamed after resuming"
    finally:
        store.close()


def test_directory_family_rename_is_per_file(tmp_path, monkeypatch):
    """RENAME CONVENTION (pinned): the store renames per FILE — "<name>.migrated[.<ext>]"
    in place — and never renames or removes the legacy DIRECTORY (a stale surface may
    still create files there, D5). Empty marker <uuid> becomes <uuid>.migrated; a
    <uuid>.denials sidecar becomes <uuid>.migrated.denials."""
    root = _user_env(tmp_path, monkeypatch)
    d = _seed_memory_first(root)
    store = _open_user()
    try:
        store.migrate("memory_first")
        assert d.is_dir(), "the legacy directory must survive migration"
        names = sorted(p.name for p in d.iterdir() if p.name != ".write.lock")
        assert names == sorted([
            f"{_SESSION}.migrated", f"{_SESSION}.migrated.denials",
            f"{_SESSION2}.migrated.denials"]), names
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 5. Dual-read window (D5a/D5c)
# ---------------------------------------------------------------------------


def test_dirty_sweeps_kv_read_merges_legacy_files_pre_migration(tmp_path, monkeypatch):
    """D5a during the window: before a family migrates, its legacy rows are readable —
    DB rows win on key collision. dirty_sweeps is file-name-keyed: the hash is the key,
    the file's document the value."""
    root = _user_env(tmp_path, monkeypatch)
    (root / "dirty-sweep-abc123def4567890.json").write_text(
        json.dumps({"dirty": True}), encoding="utf-8")
    store = _open_user()
    try:
        merged = store.kv_all("dirty_sweeps")
        assert merged.get("abc123def4567890") == {"dirty": True}, (
            "legacy dirty-sweep file must be readable during the window (D5a)")
    finally:
        store.close()


def test_resurrected_legacy_file_fails_closed(tmp_path, monkeypatch):
    """D5c: after a family's migration, a legacy file reappearing with a newer mtime
    fails closed — on open and on migrate — never silent divergence."""
    root = _user_env(tmp_path, monkeypatch)
    d = _seed_memory_first(root)
    store = _open_user()
    try:
        store.migrate("memory_first")
    finally:
        store.close()
    time.sleep(0.01)
    (d / _SESSION).write_bytes(b"")  # resurrection: a stale surface re-creates the marker
    try:
        _open_user()
        raise AssertionError("open_user() must fail closed on a resurrected legacy file")
    except sqlite3.OperationalError:
        pass
    # A later re-open must also refuse — the gate is at open time, not once per process:
    try:
        fresh = badger_store._open(
            badger_store.user_db_path(), "user", badger_store.USER_FAMILIES)
        raise AssertionError("re-open must fail closed on resurrection")
    except sqlite3.OperationalError:
        pass
