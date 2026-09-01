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
                                                   test_floor_hostile_legacy_lines_survive_their_first_prune,
                                                   test_floor_hostile_ts_is_normalised_at_import_not_at_sweep_time,
                                                   test_hook_state_imports_state_doc_as_one_kv_row
  4. Resumability + rename convention (D10/D6) .. test_multi_file_family_import_is_resumable_after_crash,
                                                   test_directory_family_rename_is_per_file
  5. Dual-read window (D5a/D5c) ................. test_dirty_sweeps_kv_read_merges_legacy_files_pre_migration,
                                                   test_resurrected_legacy_file_fails_closed
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import badger_store

_SESSION = "01a04e01-18b7-7f42-88c6-19e68738589d"
_SESSION2 = "01a04e10-7099-767a-8cbc-b2d419f8c166"
_PROJ_HASH = "ba748e8f973fc5f04f2b4ca5b9dbf308"


def _user_env(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "user-root"
    root.mkdir(parents=True, exist_ok=True)  # the legacy dirs live directly beneath it
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
    # The bus families (P1, D2) are born in SQLite: no legacy source, so no path to redirect.
    paths = {name: families[name].legacy_path() for name in families
             if families[name].legacy_path is not None}
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


def _parseable_ts_py310(ts) -> bool:
    """badger_store._parseable_ts as the 3.10 floor evaluates it: that interpreter's
    datetime.fromisoformat rejects the "Z" suffix and fractional seconds past 6 digits
    (both parse from 3.11). Every test seeding a floor-hostile ts goes through this, so
    the sweep's decision is pinned to the declared floor, not to the dev interpreter.
    """
    if not isinstance(ts, str) or not ts:
        return False
    if ts.endswith("Z"):
        return False
    _, dot, tail = ts.partition(".")
    if dot:
        digits = re.match(r"\d+", tail)
        if digits and len(digits.group()) > 6:
            return False
    try:
        datetime.fromisoformat(ts)
    except ValueError:
        return False
    return True


def test_floor_hostile_legacy_lines_survive_their_first_prune(tmp_path, monkeypatch):
    """Join-review finding: _import_jsonl stored a legacy line's ts verbatim while the
    prune's sweep parses with datetime.fromisoformat — which on the declared floor (3.10,
    CI's only version) rejects a "Z" suffix and 9-digit fractional seconds. Demonstrated
    end to end: import, then the next prune sweeps the seconds-old rows and counts them
    as ordinary expiries. The import must normalise through iso_row_ts (D36) like the
    recent kind, so every imported row is sweep-parseable on the floor it ships to."""
    root = _user_env(tmp_path, monkeypatch)
    (root / "debug").mkdir(parents=True)
    z_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    nano_ts = (datetime.now(timezone.utc).isoformat().replace("+00:00", "")
               + "123+00:00")  # 9 fractional digits
    z_line = json.dumps({"t": z_ts, "c": "grounded_feedback_hook", "e": "skip",
                         "v": "0.155.0"})
    nano_line = json.dumps({"t": nano_ts, "c": "prompt_markers", "e": "expand",
                            "v": "0.155.0"})
    control_line = json.dumps({"t": datetime.now(timezone.utc).isoformat(),
                               "c": "commit_reminder", "e": "nudge", "v": "0.155.0"})
    (root / "debug" / "audit.jsonl").write_text(
        f"{z_line}\n{nano_line}\n{control_line}\n", encoding="utf-8")
    monkeypatch.setattr(badger_store, "_parseable_ts", _parseable_ts_py310)

    store = _open_user()
    try:
        store.migrate("hook_audit")
        pruned = store.prune_expired("hook_audit", max_age_days=60)

        assert pruned == 0, "seconds-old imported rows must not count as expiries"
        payloads = [row[0] for row in store.conn.execute(
            "SELECT payload FROM hook_audit ORDER BY id")]
        assert payloads == [z_line, nano_line, control_line], (
            "every imported line survives, payload verbatim — only the row ts is "
            "normalised")
    finally:
        store.close()


def test_floor_hostile_ts_is_normalised_at_import_not_at_sweep_time(tmp_path, monkeypatch):
    """The row ts column itself carries the normalisation: a "Z"-suffixed legacy line is
    imported with a floor-parseable row ts (the iso_row_ts contract), while the payload
    keeps the line verbatim. Asserting the column (a secondary observable) keeps the fix
    honest even where the sweep's decision is not exercised."""
    root = _user_env(tmp_path, monkeypatch)
    (root / "debug").mkdir(parents=True)
    z_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (root / "debug" / "audit.jsonl").write_text(
        json.dumps({"t": z_ts, "c": "grounded_feedback_hook", "e": "skip",
                    "v": "0.155.0"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(badger_store, "_parseable_ts", _parseable_ts_py310)

    store = _open_user()
    try:
        store.migrate("hook_audit")

        row_ts, payload = store.conn.execute(
            "SELECT ts, payload FROM hook_audit").fetchone()
        assert _parseable_ts_py310(row_ts), (
            f"imported row ts {row_ts!r} must parse on the 3.10 floor")
        assert not row_ts.endswith("Z")
        assert json.loads(payload)["t"] == z_ts  # the payload stays verbatim
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
        # Crash window: one straggler file's rename never happened. The store's pinned
        # convention renames <name>.denials -> <name>.migrated.denials; the simulation
        # undoes exactly that rename for one straggler.
        straggler = d / f"{_SESSION}.migrated.denials"
        os.replace(straggler, d / f"{_SESSION}.denials")
        store.migrate("memory_first")  # the next import resumes
        count = store.conn.execute("SELECT count(*) FROM memory_first").fetchone()[0]
        assert count == 2, f"resumed import duplicated rows: {count} != 2"
        originals = [p.name for p in d.iterdir()
                     if p.name != ".write.lock" and ".migrated" not in p.name]
        assert originals == [], f"resurrectable originals left behind: {originals}"
        assert (d / f"{_SESSION}.migrated.denials").exists(), \
            "the straggler was not re-renamed after resuming"
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


def test_resurrected_legacy_file_is_contained_per_family(tmp_path, monkeypatch):
    """M2 containment: after a family's migration, a legacy file reappearing with a newer
    mtime is contained PER FAMILY — the store opens, the family is recorded unavailable
    and refuses access, and its neighbours are untouched — never silent divergence."""
    root = _user_env(tmp_path, monkeypatch)
    d = _seed_memory_first(root)
    store = _open_user()
    try:
        store.migrate("memory_first")
    finally:
        store.close()
    time.sleep(0.01)
    (d / _SESSION).write_bytes(b"")  # resurrection: a stale surface re-creates the marker
    reopened = _open_user()
    try:
        contained = reopened.contained_families()
        assert set(contained) == {"memory_first"}, (
            "open must succeed with the resurrected family contained, and only it")
        assert _SESSION in str(contained["memory_first"])
    finally:
        reopened.close()
    # A later re-open records the same containment — the gate is at open time, per family:
    fresh = badger_store._open(  # pylint: disable=protected-access
        badger_store.user_db_path(), "user", badger_store.USER_FAMILIES)
    try:
        assert set(fresh.contained_families()) == {"memory_first"}
    finally:
        fresh.close()
    # The contained family refuses on access, with the upgrade pointer (migrate itself
    # skips it — the refusal lives on the accessors, M2):
    fresh2 = _open_user()
    try:
        with pytest.raises(sqlite3.OperationalError, match="doctor"):
            fresh2.kv_get("memory_first", _SESSION)
        fresh2.migrate("memory_first")  # skipped: never imports the resurrected file
        assert (d / _SESSION).exists()
    finally:
        fresh2.close()


# --- M2 per-family containment: refuse-on-access per kind group ---------------------


def _seed_commit_reminder_map(root: Path, state: dict) -> Path:
    path = root / "commit-reminder" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_contained_map_family_surfaces_on_read_and_refuses_write(tmp_path, monkeypatch):
    """map kind: a contained family's kv reads raise the resurrection error, its writes
    refuse, and a neighbour family (dirty_sweeps) reads and writes exactly as today."""
    root = _user_env(tmp_path, monkeypatch)
    legacy = _seed_commit_reminder_map(root, {"/repo/a": {"count": 1}})
    store = _open_user()
    try:
        store.kv_set("commit_reminder", "/repo/db", {"count": 2})  # migrate + rename
    finally:
        store.close()
    time.sleep(0.05)
    legacy.write_text(json.dumps({"/repo/a": {"count": 9}}))  # resurrection

    store = _open_user()
    try:
        assert set(store.contained_families()) == {"commit_reminder"}
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_get("commit_reminder", "/repo/db")  # even a DB-hit read refuses
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_all("commit_reminder")
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_set("commit_reminder", "/repo/next", {"count": 3})
        # neighbour observable: the file-set neighbour behaves exactly as today
        (root / "dirty-sweep-abc123def4567890.json").write_text(
            json.dumps({"dirty": True}), encoding="utf-8")
        assert store.kv_all("dirty_sweeps") == {"abc123def4567890": {"dirty": True}}
        store.kv_set("dirty_sweeps", "feedbeeffeedbeef", {"dirty": False})
        assert store.kv_get("dirty_sweeps", "feedbeeffeedbeef") == {"dirty": False}
    finally:
        store.close()


def test_contained_kvdoc_family_surfaces_on_its_row_only(tmp_path, monkeypatch):
    """kvdoc kind: containment is per FAMILY — the contained pending document refuses on
    its row key only, and the map sibling sharing the commit_reminder table keeps working."""
    root = _user_env(tmp_path, monkeypatch)
    legacy = root / "commit-reminder" / "pending.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"session": "abc", "note": "pending"}), encoding="utf-8")
    store = _open_user()
    try:
        store.kv_set("commit_reminder", "/repo/db", {"count": 2})  # migrates BOTH families
    finally:
        store.close()
    assert not legacy.exists()
    time.sleep(0.05)
    legacy.write_text(json.dumps({"session": "abc", "note": "rewritten"}), encoding="utf-8")

    store = _open_user()
    try:
        assert set(store.contained_families()) == {"commit_reminder_pending"}
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_get("commit_reminder", "pending")
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_set("commit_reminder", "pending", {"session": "x"})
        # neighbour observable: the map sibling on the SAME table reads and writes normally
        assert store.kv_get("commit_reminder", "/repo/db") == {"count": 2}
        store.kv_set("commit_reminder", "/repo/next", {"count": 3})
        assert store.kv_get("commit_reminder", "/repo/next") == {"count": 3}
    finally:
        store.close()


def test_contained_awm_family_surfaces_on_read_and_refuses_write(tmp_path, monkeypatch):
    """awm kind: a contained awm_state (merged through the _awm_projects path) refuses
    reads and writes; a neighbour append-only family still appends (D5c, M2)."""
    monkeypatch.setattr(badger_store, "_DEFAULT_HOME", tmp_path)
    root = _user_env(tmp_path, monkeypatch)
    legacy = tmp_path / ".claude" / "awm" / "state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(
        {"projects": {"/repo/main": {"project": "/repo/main", "enabled": True}}}),
        encoding="utf-8")
    store = _open_user()
    try:
        store.kv_set("awm_state", "/repo/db", {"project": "/repo/db"})
    finally:
        store.close()
    time.sleep(0.05)
    legacy.write_text(json.dumps(
        {"projects": {"/repo/main": {"project": "/repo/main", "enabled": False}}}),
        encoding="utf-8")

    store = _open_user()
    try:
        assert set(store.contained_families()) == {"awm_state"}
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_get("awm_state", "/repo/db")
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_all("awm_state")
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_set("awm_state", "/repo/next", {"project": "/repo/next"})
        # neighbour observable: a healthy append-only family appends and reads back
        store.log_append("awm_decisions", badger_store.iso_row_ts(time.time()),
                         {"decision": "d1"})
        assert len(store.log_rows("awm_decisions")) == 1
    finally:
        store.close()


def test_contained_append_only_family_reads_db_and_refuses_appends(tmp_path, monkeypatch):
    """jsonl/recent kinds: reads are already DB-only so they keep serving DB rows; the
    first append refuses (never imports the resurrected file, never diverges, D5c/M1)."""
    root = _user_env(tmp_path, monkeypatch)
    legacy = root / "memory-grade" / "searches.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(
        {"recent": [{"correlationId": "c1", "sourceFiles": [], "ts": 1750000000}]}),
        encoding="utf-8")
    store = _open_user()
    try:
        store.migrate("searches")  # import + rename + stamp
        store.log_append("searches", badger_store.iso_row_ts(1750000001), {"q": "seeded"})
    finally:
        store.close()
    time.sleep(0.05)
    legacy.write_text(json.dumps(
        {"recent": [{"correlationId": "c2", "sourceFiles": [], "ts": 1750000002}]}),
        encoding="utf-8")

    store = _open_user()
    try:
        assert set(store.contained_families()) == {"searches"}
        # reads stay DB-only — there is no legacy merge on this path to refuse:
        rows = store.log_rows("searches")
        assert len(rows) == 2 and "seeded" in rows[1][1]
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.log_append("searches", badger_store.iso_row_ts(1750000003), {"q": "x"})
        # the refused append imported nothing and renamed nothing:
        assert legacy.exists()
        assert len(store.log_rows("searches")) == 2
        # neighbour observable: another append-only family appends exactly as today
        store.log_append("awm_decisions", badger_store.iso_row_ts(time.time()),
                         {"decision": "ok"})
        assert len(store.log_rows("awm_decisions")) == 1
    finally:
        store.close()


# --- M2 tier-1 sweep: every registry family, neighbour-canaried ---------------------


def _load_sweep_tracker_lib():
    """A fresh tracker_lib for the sweep's registry derivation (loaded once at collection)."""
    import importlib.util
    path = (Path(__file__).resolve().parents[1]
            / "features/common/skills/task/scripts/tracker_lib.py")
    spec = importlib.util.spec_from_file_location("sweep_tracker_lib", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sweep_tracker_lib"] = module
    spec.loader.exec_module(module)
    return module


_SWEEP_TRACKER = _load_sweep_tracker_lib()


def _sweep_families() -> dict:
    """Every registry family with a legacy source, derived from all three registries.

    badger_store.FAMILIES + tracker_lib._task_families() + badger_store.USER_FAMILIES,
    skipping legacy_path-None store families (messages/cursors): a family added to any
    registry without containment semantics fails this sweep (derive-or-delete).
    """
    combined: dict = {}
    for name, family in badger_store.FAMILIES.items():
        combined[name] = family
    for name, family in _SWEEP_TRACKER._task_families().items():  # pylint: disable=protected-access
        combined[name] = badger_store.Family(
            table=family.table, db=family.db, legacy_path=family.legacy_path,
            legacy_kind=family.legacy_kind, row_key=family.row_key)
    for name, family in badger_store.USER_FAMILIES.items():
        combined[name] = family
    return {name: family for name, family in combined.items()
            if family.legacy_path is not None}


_SWEEP_PARAMS = [(name, family.db) for name, family in _sweep_families().items()]


@pytest.mark.parametrize("family_name,db_kind", _SWEEP_PARAMS)
def test_resurrected_family_leaves_its_neighbours_usable(family_name, db_kind,
                                                         tmp_path, monkeypatch):
    """Tier-1 sweep: ANY resurrected registry family is contained while its store opens
    and the bus (born in SQLite, nothing to resurrect) keeps delivering — per-family
    blast radius for the whole registry, not just the kind groups tier 2 names."""
    monkeypatch.setattr(badger_store, "_DEFAULT_HOME", tmp_path)
    root = _user_env(tmp_path, monkeypatch)
    tracking = tmp_path / "task-tracking"
    tracking.mkdir(parents=True)
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(tracking))
    monkeypatch.setattr(_SWEEP_TRACKER, "DATA_DIR", tracking)

    family = _sweep_families()[family_name]
    if family_name in _SWEEP_TRACKER._task_families():  # pylint: disable=protected-access
        open_kwargs = {"families": dict(_SWEEP_TRACKER._task_families())}  # pylint: disable=protected-access
    else:
        open_kwargs = {}  # FAMILIES default (tracking) or USER_FAMILIES default (user)

    def open_store():
        if db_kind == "tracking":
            return badger_store.open_tracking(**open_kwargs)
        return badger_store.open_user(**open_kwargs)

    _seed_sweep_legacy(family)
    store = open_store()
    try:
        store.migrate(family.table)  # stamp set while the file exists
    finally:
        store.close()
    time.sleep(0.05)
    _seed_sweep_legacy(family)  # resurrection: the file is back, newer than the stamp

    reopened = open_store()
    try:
        assert reopened.contained_families(), f"{family_name} must be recorded contained"
        assert family_name in reopened.contained_families()
    finally:
        reopened.close()

    # the canary neighbour: open_user + a messages roundtrip + a prune run, every time
    user = badger_store.open_user()
    try:
        user.send_message(sender_session="sweep-sender", sender_project="sweep-proj",
                          content="ping", target_session="sweep-receiver")
        delivered = user.deliver_for_session("sweep-receiver", "sweep-proj")
        assert len(delivered) == 1 and delivered[0]["content"] == "ping"
        user.delete_cursor("sweep-receiver")
    finally:
        user.close()
    assert isinstance(badger_store.prune_status_lines(), list)


def _seed_sweep_legacy(family) -> Path:
    """Seed one family's legacy source with the minimal document its kind imports."""
    path = family.legacy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if family.legacy_kind in badger_store.FILE_SET_KINDS:
        if family.legacy_kind == "kv_glob":
            path.write_text(json.dumps({"dirty": True}), encoding="utf-8")
            return path
        if family.legacy_kind == "stem_denials":
            path = path / "01a04e01.ba748e8f973fc5f04f2b4ca5b9dbf308.denials"
        else:
            path = path / "01a04e01-18b7-7f42-88c6-19e68738589d"  # marker / nudge / lane
        path.parent.mkdir(parents=True, exist_ok=True)  # the legacy DIRECTORY itself
        path.write_text("1750000000.0 toolu_01" if family.legacy_kind == "lanes"
                        else ("1" if family.legacy_kind == "stem_denials" else ""),
                        encoding="utf-8")
        return path
    docs = {
        "map": {"/repo/a": {"count": 1}},
        "kvdoc": {"session": "abc", "note": "pending"},
        "awm": {"projects": {"/repo/main": {"project": "/repo/main"}}},
        "jsonl": [{"t": "2026-08-31T00:00:00+00:00", "c": "x", "e": "y"}],
        "recent": {"recent": [{"correlationId": "c1", "sourceFiles": [],
                               "ts": 1750000000}]},
        "tasks": {"tasks": [{"taskId": "T01", "sessionId": "sid-1",
                             "state": "IN_PROGRESS", "resumeAttempts": []}]},
        "usage": {"tasks": [{"taskId": "T01", "sessionId": "sid-1",
                             "trackingSource": "claude", "subagents": []}]},
        "sessions": {"sessions": {"sid-1": {"cwd": "/repo", "pid": 1}}},
    }
    doc = docs[family.legacy_kind]
    text = "\n".join(json.dumps(line) for line in doc) \
        if family.legacy_kind == "jsonl" else json.dumps(doc)
    path.write_text(text, encoding="utf-8")
    return path
