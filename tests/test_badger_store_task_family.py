"""Task-family migration and dual-read windows over badger_store (P0.3 scope f, D18/D22).

The P0.2 tests pin the map-kind machinery against marker_state; this file pins the same
contract for the task family's real shapes — row lists (executed-tasks.json, token-usage.json),
the session map (current-session.json), and the two statusline KV documents — plus the
P0.6a carries: the post-import count check (finding 3), no INSERT OR REPLACE on tasks
(MUST-2), and doc-level stopBlocks surviving migration.

Window semantics under test, per family:
  - legacy-only read fallback (empty DB + legacy file: reads serve legacy entries);
  - write-migrates-rename (first write imports rows, renames the file, D6);
  - both-non-empty precedence (crash state: the DB row wins per key, D22);
  - resurrection fail-closed (legacy file recreated after the stamp: open raises, D5c).
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

import badger_store

TASK_ENTRY = {
    "taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
    "title": "Fix widgets", "branch": "feat/widgets", "cwd": "/repo",
    "transcriptPath": "/repo/t.jsonl", "resumeCommand": "claude --resume sid-1",
    "startedAt": "2026-08-31T00:00:00+00:00", "trackingSource": "claude",
    "resumeAttempts": [],
}
USAGE_ENTRY = {
    "taskId": "T01", "sessionId": "sid-1", "trackingSource": "claude",
    "checkpoints": {"start": {"contextTokens": 10}}, "subagents": [], "grade": None,
}


def _seed(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture(name="family_root")
def _family_root(tmp_path, monkeypatch):
    """A task-tracking root with the five task-family legacy paths registered."""
    tracking = tmp_path / "task-tracking"
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(tracking))

    def rel(name):
        return lambda: tracking / name

    families = {
        "tasks": badger_store.Family(
            table="tasks", db="tracking", legacy_path=rel("executed-tasks.json"),
            legacy_kind="tasks"),
        "token_usage": badger_store.Family(
            table="token_usage", db="tracking", legacy_path=rel("token-usage.json"),
            legacy_kind="usage"),
        "sessions": badger_store.Family(
            table="sessions", db="tracking", legacy_path=rel("current-session.json"),
            legacy_kind="sessions"),
        "statusline": badger_store.Family(
            table="statusline", db="tracking", legacy_path=rel("statusline-state.json"),
            legacy_kind="kvdoc", row_key="state"),
        "statusline_delegate": badger_store.Family(
            table="statusline", db="tracking", legacy_path=rel("statusline-delegate.json"),
            legacy_kind="kvdoc", row_key="delegate"),
    }
    return tracking, families


def _open(families) -> badger_store.Store:
    return badger_store.open_tracking(families=families)


# ---------------------------------------------------------------------------
# tasks family
# ---------------------------------------------------------------------------


def test_tasks_legacy_only_read_fallback(family_root):
    """Empty DB + legacy file: reads serve the legacy entries — never an empty fallback (D5a)."""
    tracking, families = family_root
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})

    store = _open(families)
    try:
        assert store.tasks_all() == [dict(TASK_ENTRY)]
    finally:
        store.close()


def test_tasks_first_write_imports_then_renames(family_root):
    """First write: legacy entries import as rows, then the file renames to *.migrated.json (D6)."""
    tracking, families = family_root
    legacy = _seed(tracking / "executed-tasks.json",
                   {"tasks": [dict(TASK_ENTRY)], "stopBlocks": {"sid-1": 2}})
    time.sleep(0.05)  # legacy mtime must strictly predate the migration stamp

    store = _open(families)
    try:
        store.migrate("tasks")
        store.conn.execute("BEGIN IMMEDIATE")
        store.task_upsert({**TASK_ENTRY, "state": "FINISHED", "finishedAt":
                           "2026-08-31T01:00:00+00:00"})
        store.conn.commit()

        rows = store.conn.execute(
            "SELECT task_id, session_id, state, title, branch, tracking_source, "
            "state_json_reminder_sent, resume_attempts FROM tasks ORDER BY rowid"
        ).fetchall()
        assert rows == [("T01", "sid-1", "FINISHED", "Fix widgets", "feat/widgets",
                         "claude", 0, "[]")]
        assert store.meta_get("stopBlocks") == {"sid-1": 2}  # doc-level residue carried over
        assert not legacy.exists()
        migrated = tracking / "executed-tasks.migrated.json"
        assert json.loads(migrated.read_text())["tasks"][0]["taskId"] == TASK_ENTRY["taskId"]
    finally:
        store.close()


def test_tasks_both_non_empty_db_row_wins(family_root):
    """Crash state (stamp committed, file un-renamed) plus a diverging DB row: DB wins (D22)."""
    tracking, families = family_root
    legacy = _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)

    store = _open(families)
    store.migrate("tasks")
    store.close()
    legacy.with_name("executed-tasks.migrated.json").rename(legacy)  # recreate the crash state

    reopened = _open(families)
    try:
        reopened.conn.execute("BEGIN IMMEDIATE")
        reopened.task_upsert({**TASK_ENTRY, "state": "FINISHED"})
        reopened.conn.commit()
        assert reopened.tasks_all() == [{**TASK_ENTRY, "state": "FINISHED"}]
    finally:
        reopened.close()


def test_tasks_resurrected_legacy_file_is_contained_per_family(family_root):
    """The legacy file recreated after its migration: contained per family (M2) — the
    store opens, the tasks family refuses on access, its stamp stays untouched."""
    tracking, families = family_root
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)

    store = _open(families)
    store.migrate("tasks")
    store.close()
    time.sleep(0.05)
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})  # stale surface

    store = _open(families)
    try:
        assert set(store.contained_families()) == {"tasks"}
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.tasks_all()
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.task_upsert({**TASK_ENTRY, "state": "FINISHED"})
        # the transaction skips the contained table and never blesses the file:
        store.migrate("tasks")
        assert (tracking / "executed-tasks.json").exists()
    finally:
        store.close()


def test_tasks_import_count_check_refuses_silent_drops(family_root):
    """A legacy entry violating NOT NULL (no sessionId) must fail the import loudly, not
    vanish through INSERT OR IGNORE (P0.6a finding 3) — no stamp, no rename, no rows."""
    tracking, families = family_root
    legacy = _seed(tracking / "executed-tasks.json",
                   {"tasks": [{"taskId": "T-broken"}, dict(TASK_ENTRY)]})

    store = _open(families)
    try:
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            store.migrate("tasks")
        assert "T-broken" in str(excinfo.value)
        assert legacy.exists(), "a failed import must not rename the file"
        assert store.conn.execute(
            "SELECT COUNT(*) FROM meta WHERE key LIKE 'migrated_at%'").fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    finally:
        store.close()


def test_task_upsert_is_update_not_replace(family_root):
    """Re-upserting one task must leave the session's other rows untouched (P0.6a MUST-2):
    INSERT OR REPLACE would delete the other row sharing the partial-index predicate."""
    _, families = family_root
    store = _open(families)
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        store.task_upsert(dict(TASK_ENTRY))
        store.task_upsert({**TASK_ENTRY, "taskId": "T02", "state": "FINISHED",
                           "finishedAt": "2026-08-31T01:00:00+00:00"})
        store.conn.commit()

        store.conn.execute("BEGIN IMMEDIATE")
        store.task_upsert({**TASK_ENTRY, "title": "Retitled"})  # existing row: UPDATE path
        store.conn.commit()

        rows = store.conn.execute(
            "SELECT task_id, title, state FROM tasks ORDER BY rowid").fetchall()
        assert rows == [("T01", "Retitled", "IN_PROGRESS"), ("T02", "Fix widgets", "FINISHED")]
    finally:
        store.close()


def test_task_upsert_round_trips_every_ruled_column(family_root):
    """Flags round-trip as booleans only when sent, NULLs stay absent, lists stay lists."""
    _, families = family_root
    flagged = {**TASK_ENTRY, "taskId": "T02", "state": "FINISHED",
               "finishedAt": "2026-08-31T01:00:00+00:00",
               "stateJsonUpdated": True, "stateJsonReminderSent": True,
               "compactionReminderSent": True,
               "resumeAttempts": [{"at": "2026-08-31T02:00:00+00:00", "dryRun": False}]}
    store = _open(families)
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        store.task_upsert(dict(TASK_ENTRY))
        store.task_upsert(flagged)
        store.conn.commit()

        entries = {entry["taskId"]: entry for entry in store.tasks_all()}
        assert "stateJsonReminderSent" not in entries["T01"], "unsent flags must stay absent"
        assert entries["T02"]["stateJsonReminderSent"] is True
        assert entries["T02"]["resumeAttempts"] == flagged["resumeAttempts"]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# token_usage family
# ---------------------------------------------------------------------------


def test_usage_import_and_round_trip(family_root):
    """token-usage.json imports keyed on taskId; JSON payloads and grade round-trip."""
    tracking, families = family_root
    _seed(tracking / "token-usage.json", {"tasks": [{
        **USAGE_ENTRY, "grade": 4, "gradedAt": "2026-08-31T03:00:00+00:00",
        "usage": {"inputTokens": 100},
    }]})

    store = _open(families)
    try:
        store.migrate("token_usage")
        assert store.usage_all() == [{
            **USAGE_ENTRY, "grade": 4, "gradedAt": "2026-08-31T03:00:00+00:00",
            "usage": {"inputTokens": 100},
        }]
        assert not (tracking / "token-usage.json").exists()
    finally:
        store.close()


def test_usage_import_skips_entries_without_a_task_id(family_root):
    """An entry without taskId is unreachable by find_entry: skipped at import, not fabricated
    into a row (P0.6a finding 4) — and unlike a NOT NULL violation it is not a count-check
    failure, because it was never expected to land."""
    tracking, families = family_root
    _seed(tracking / "token-usage.json",
          {"tasks": [{"subagents": []}, dict(USAGE_ENTRY)]})

    store = _open(families)
    try:
        store.migrate("token_usage")
        assert [entry["taskId"] for entry in store.usage_all()] == [USAGE_ENTRY["taskId"]]
        assert not (tracking / "token-usage.json").exists()
    finally:
        store.close()


# ---------------------------------------------------------------------------
# sessions family
# ---------------------------------------------------------------------------


def test_sessions_import_and_legacy_fallback(family_root):
    """current-session.json imports keyed on the session id; reads merge legacy-only rows."""
    tracking, families = family_root
    _seed(tracking / "current-session.json", {"sessions": {
        "sid-1": {"transcriptPath": "/repo/t.jsonl", "cwd": "/repo", "pid": 424242,
                  "recordedAt": "2026-08-31T00:00:00+00:00"},
    }})

    store = _open(families)
    try:
        # Pre-migration: the legacy file is the only source, and it is served verbatim.
        assert store.sessions_map() == {
            "sid-1": {"transcriptPath": "/repo/t.jsonl", "cwd": "/repo", "pid": 424242,
                      "recordedAt": "2026-08-31T00:00:00+00:00"},
        }
        store.migrate("sessions")  # rows now exist; writes hit the DB, not the file
        store.conn.execute("BEGIN IMMEDIATE")
        store.session_upsert("sid-2", {"cwd": "/repo", "pid": 1})
        store.session_delete("sid-1")
        store.conn.commit()
        assert set(store.sessions_map()) == {"sid-2"}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# statusline kvdoc families (two legacy files, one KV table)
# ---------------------------------------------------------------------------


def test_statusline_two_files_one_table(family_root):
    """statusline-state.json and statusline-delegate.json land as distinct KV rows."""
    tracking, families = family_root
    _seed(tracking / "statusline-state.json", {"capturedAt": "2026-08-31T00:00:00+00:00",
                                               "sessionId": "sid-1"})
    _seed(tracking / "statusline-delegate.json", {"command": "my-renderer.sh"})

    store = _open(families)
    try:
        store.migrate("statusline")
        assert store.kv_get("statusline", "state")["sessionId"] == "sid-1"
        assert store.kv_get("statusline", "delegate") == {"command": "my-renderer.sh"}
        assert not (tracking / "statusline-state.json").exists()
        assert not (tracking / "statusline-delegate.json").exists()
    finally:
        store.close()


def test_statusline_resurrection_is_contained_per_family(family_root):
    """The delegate record recreated after its stamp: contained PER FAMILY (M2) — the
    store opens, the delegate family refuses on access, and the state sibling on the
    shared statusline table keeps working."""
    tracking, families = family_root
    legacy = _seed(tracking / "statusline-delegate.json", {"command": "a.sh"})
    time.sleep(0.05)

    store = _open(families)
    store.migrate("statusline")
    store.close()
    time.sleep(0.05)
    _seed(tracking / "statusline-delegate.json", {"command": "b.sh"})

    store = _open(families)
    try:
        assert set(store.contained_families()) == {"statusline_delegate"}
        assert legacy.exists()  # contained, never touched
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_get("statusline", "delegate")
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_set("statusline", "delegate", {"command": "c.sh"})
    finally:
        store.close()


def test_contained_statusline_sibling_keeps_its_delegate_neighbour(family_root):
    """Two families share table 'statusline' (tracker_lib's state + delegate pair):
    containment is per FAMILY — the contained state family refuses on its row while
    the delegate sibling still reads and writes its own row (review M2)."""
    tracking, families = family_root
    _seed(tracking / "statusline-state.json", {"sessionId": "sid-1"})
    _seed(tracking / "statusline-delegate.json", {"command": "a.sh"})
    time.sleep(0.05)

    store = _open(families)
    store.migrate("statusline")
    store.kv_set("statusline", "delegate", {"command": "db.sh"})  # both rows in the DB
    store.close()
    time.sleep(0.05)
    _seed(tracking / "statusline-state.json", {"sessionId": "sid-9"})  # state resurrects

    store = _open(families)
    try:
        assert set(store.contained_families()) == {"statusline"}
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.kv_get("statusline", "state")
        # the delegate neighbour: reads and writes its own row exactly as today
        assert store.kv_get("statusline", "delegate") == {"command": "db.sh"}
        store.kv_set("statusline", "delegate", {"command": "new.sh"})
        assert store.kv_get("statusline", "delegate") == {"command": "new.sh"}
    finally:
        store.close()


def test_contained_task_family_refuses_reads_but_allows_neighbour_upserts(tracker_lib):
    """tasks/usage/sessions kinds: the contained family's reads raise, its writes refuse,
    and a tracking_transaction skips ONLY the contained table — a neighbour family's
    upsert through the real transaction still lands (M2, plan tier-2 tasks row)."""
    tracking = tracker_lib.DATA_DIR
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)
    with tracker_lib.tracking_transaction() as store:
        tracker_lib.save_tasks(store, {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})  # resurrection

    with tracker_lib.tracking_transaction() as store:
        # the transaction entered: the migrate loop skipped the contained tasks table
        assert set(store.contained_families()) == {"tasks"}
        assert (tracking / "executed-tasks.json").exists()  # skipped, not imported
        # refuse-on-read for the contained family (the task_family:411 pin, still up):
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.tasks_all()
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            tracker_lib.load_tasks(store)
        # refuse-on-write for the contained table:
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store.task_upsert({**TASK_ENTRY, "state": "FINISHED"})
        # the neighbour family's upsert through the same transaction succeeds:
        store.usage_upsert({**USAGE_ENTRY, "grade": 2})

    doc = tracker_lib.load_usage()  # neighbour read-back through the accessor pair
    assert doc["tasks"][0]["grade"] == 2
    assert (tracking / "executed-tasks.json").exists()


# ---------------------------------------------------------------------------
# task family at the tracker_lib accessor level (P0.3f)
#
# P0.3c proved these windows through the CLI verbs; the accessor pair
# lib.load_tasks/lib.save_tasks is the surface every non-CLI consumer (hooks,
# statusline) reads through, so the same D5a/D6/D22/D5c contract is pinned
# there directly. tracker_lib resolves every legacy path through module
# globals at call time (D9), so redirecting DATA_DIR re-roots the whole family.
# ---------------------------------------------------------------------------

TRACKER_LIB_RELPATH = "features/common/skills/task/scripts/tracker_lib.py"


@pytest.fixture(name="tracker_lib")
def _tracker_lib(load_script, tmp_path):
    """A fresh tracker_lib with its task-tracking paths redirected into tmp_path."""
    lib = load_script(TRACKER_LIB_RELPATH)
    data_dir = tmp_path / ".ai-badger" / "task-tracking"
    lib.PROJECT_ROOT = tmp_path
    lib.DATA_DIR = data_dir
    lib.EXECUTED_TASKS = data_dir / "executed-tasks.json"
    lib.TOKEN_USAGE = data_dir / "token-usage.json"
    lib.CURRENT_SESSION = data_dir / "current-session.json"
    lib.LOCK_FILE = data_dir / ".write.lock"
    return lib


def test_accessor_load_tasks_serves_legacy_only_without_renaming(tracker_lib):
    """Empty DB + legacy file: the accessor serves legacy rows and never renames (D5a/D6)."""
    tracking = tracker_lib.DATA_DIR
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})

    doc = tracker_lib.load_tasks()

    assert doc["tasks"] == [dict(TASK_ENTRY)]
    assert (tracking / "executed-tasks.json").exists()  # read-only: migration is a write's job


def test_accessor_save_tasks_imports_then_renames(tracker_lib):
    """First write through the accessor: legacy imports, file renames, reads serve the DB (D6)."""
    tracking = tracker_lib.DATA_DIR
    legacy = _seed(tracking / "executed-tasks.json",
                   {"tasks": [dict(TASK_ENTRY)], "stopBlocks": {"sid-1": 2}})
    time.sleep(0.05)  # legacy mtime must strictly predate the migration stamp

    with tracker_lib.tracking_transaction() as store:
        tracker_lib.save_tasks(store, {"tasks": [{**TASK_ENTRY, "state": "FINISHED"}]})

    assert not legacy.exists()
    migrated = tracking / "executed-tasks.migrated.json"
    assert json.loads(migrated.read_text())["tasks"][0]["taskId"] == TASK_ENTRY["taskId"]
    doc = tracker_lib.load_tasks()
    assert doc["tasks"] == [{**TASK_ENTRY, "state": "FINISHED"}]
    assert doc["stopBlocks"] == {"sid-1": 2}  # doc-level budget carried across the migration


def test_accessor_load_tasks_db_row_wins_when_both_sources_non_empty(tracker_lib):
    """Crash state (stamp committed, rename undone) plus a diverging DB row: DB wins (D22)."""
    tracking = tracker_lib.DATA_DIR
    legacy = _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)
    with tracker_lib.tracking_transaction() as store:  # first write: import + rename
        tracker_lib.save_tasks(store, {"tasks": [dict(TASK_ENTRY)]})
    legacy.with_name("executed-tasks.migrated.json").rename(legacy)  # recreate the crash state
    with tracker_lib.tracking_transaction() as store:  # a newer row lands behind the stale file
        tracker_lib.save_tasks(store, {"tasks": [{**TASK_ENTRY, "state": "FINISHED"}]})

    doc = tracker_lib.load_tasks()

    assert doc["tasks"] == [{**TASK_ENTRY, "state": "FINISHED"}]  # per-key LWW, DB row wins


def test_accessor_load_tasks_surfaces_resurrection_fail_closed(tracker_lib):
    """A stale surface rewriting the legacy file post-migration: the accessor raises (D5c)."""
    tracking = tracker_lib.DATA_DIR
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)
    with tracker_lib.tracking_transaction() as store:
        tracker_lib.save_tasks(store, {"tasks": [dict(TASK_ENTRY)]})
    time.sleep(0.05)
    _seed(tracking / "executed-tasks.json", {"tasks": [dict(TASK_ENTRY)]})  # resurrection

    with pytest.raises(sqlite3.OperationalError):
        tracker_lib.load_tasks()  # surfaced, never swallowed by the accessor
