"""P4 cross-package integration drills (plan aib-sqlite-storage-migration-phased-rollout).

The per-lane suites already pin: family-level lazy migration + rename, dual-read windows,
resurrection fail-closed, resumable multi-file import, the retention throttle, the WAL race,
and the CLI/hook contracts. This file covers what they deliberately do not: the SEAMS between
packages — both runtime DBs in one session lifecycle, the D31 recovery runbook against real
corruption, process-level first-write migration (D23), and the scaffolded consumer's
delivered shape running end to end.

Design table (failure mode -> test -> mutation that proves it real):

  1. Cross-DB misrouting or a shared transaction spanning both stores
       test_session_lifecycle_through_both_stores_keeps_each_invariant_independent
       (alias one DB onto the other -> the no-cross-talk asserts go red)
  2. One broken store taking the other store down mid-lifecycle
       test_a_broken_store_does_not_disturb_the_sibling_store
       (couple the connections -> the sibling's writes die with the corrupt DB -> red)
  3. Re-import after DB loss duplicating rows (OR IGNORE dropped on the recovery path)
       test_recovery_runbook_deleted_db_and_restored_names_reimport_without_duplicates
       (plain INSERT in the map import branch -> red)
  4. The runbook holding for the user DB but not the project DB's families
       test_recovery_runbook_on_the_project_side_marker_state
       (rename convention or stamp keying broken per family -> red)
  5. An empty-shell DB silently diverging instead of healing from restored legacy
       test_recovery_runbook_zero_byte_db_shell_heals_when_legacy_names_restored
       (treat an unstamped DB as already-migrated -> rows never return -> red)
  6. A corrupt DB failing with an unreadable error or a crash loop instead of one
     actionable message, and the runbook failing to restore from it
       test_recovery_runbook_garbage_db_fails_open_with_readable_error_then_restores
       (swallow the DatabaseError and keep the corrupt file -> silent no-op writes -> red)
  7. Two processes' first writes double-importing or double-renaming (D23)
       test_two_processes_racing_the_first_write_import_once_and_rename_once
       (drop the legacy flock or the under-lock re-check -> duplicates -> red)
  8. The scaffold shipping a stale or edited store copy (D16 delivery)
       test_scaffolded_consumer_carries_badger_store_copies_verbatim
       (drift a features/ vendored copy -> the delivered copy differs -> red)
  9. The delivered shape missing the managed gitignore block (DB files get committed)
       test_scaffolded_consumer_gitignore_block_ignores_the_tracking_db_and_sidecars
       (remove scaffold.py's gitignore merge -> red)
  10. The delivered copy being broken at runtime — a verb that cannot run
       test_hook_verb_runs_in_the_scaffolded_copy_and_lands_the_tracking_db
       (break the copy step -> the verb exits non-zero -> red)

Fixture realism: every legacy seed carries at least two keys, the awm drill carries two
projects, and every migration happens with the legacy mtime strictly older than the stamp —
a degenerate one-row/one-key fixture can go red for the wrong reason and stay green when
the parameter under test stops working.
"""
from __future__ import annotations

import json
import os
import subprocess
import sqlite3
import sys
import time
from pathlib import Path

import pytest

import badger_store
from conftest import ROOT

_TASK_SESSION = "01a04e1c-p4in-tegr-ation-se55ion0001"
_PROJECT_A = "/repo/away-mode-project"
_PROJECT_B = "/repo/other-project"


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _both_roots(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """A project root and a user root at distinct paths; both env roots set."""
    project = tmp_path / "consumer-repo" / ".ai-badger" / "task-tracking"
    user = tmp_path / "user-home" / ".ai-badger"
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(project))
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(user))
    return project, user


def _task_families() -> dict:
    """The tracking store's task-family registry, mirroring tracker_lib's shape."""
    def rel(name):
        return lambda: badger_store.tracking_db_path().parent / name

    return {
        "tasks": badger_store.Family(
            table="tasks", db="tracking", legacy_path=rel("executed-tasks.json"),
            legacy_kind="tasks"),
        "token_usage": badger_store.Family(
            table="token_usage", db="tracking", legacy_path=rel("token-usage.json"),
            legacy_kind="usage"),
        "sessions": badger_store.Family(
            table="sessions", db="tracking", legacy_path=rel("current-session.json"),
            legacy_kind="sessions"),
    }


def _awm_families(claude_home: Path) -> dict:
    """The user store's away-mode families with the legacy paths under a scratch home.

    The real registry pins the awm legacy files to the snapshot home (they are not
    .ai-badger artifacts); the drill needs them hermetic, so it re-anchors the same
    kinds under the scratch home without changing their shapes.
    """
    def rel(name):
        return lambda: claude_home / ".claude" / "awm" / name

    return {
        "awm_state": badger_store.Family(
            table="awm_state", db="user", legacy_path=rel("state.json"),
            legacy_kind="awm"),
        "awm_decisions": badger_store.Family(
            table="awm_decisions", db="user", legacy_path=rel("decisions.jsonl"),
            legacy_kind="jsonl"),
    }


def _seed_commit_reminder(user_root: Path, state: dict) -> Path:
    """The commit-reminder legacy KV document: one top-level dict keyed by project root."""
    legacy = user_root / "commit-reminder" / "state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return legacy


def _delete_db(db_path: Path) -> None:
    """The runbook's delete step: the database and its WAL sidecars."""
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 1. Cross-DB consistency drill — one session lifecycle through BOTH stores
# ---------------------------------------------------------------------------


def test_session_lifecycle_through_both_stores_keeps_each_invariant_independent(
        tmp_path, monkeypatch):
    """One simulated session writes through the project store (tracking.db) AND the user
    store (ai-badger.db); each store holds its own invariants independently and nothing
    crosses the seam: every row lands in the DB its writer owns, and the same session id
    appears on both sides without either store borrowing the other's storage.
    """
    project_root, user_root = _both_roots(tmp_path, monkeypatch)
    claude_home = tmp_path / "claude-home"
    started = "2026-08-31T10:00:00+00:00"

    # task_upsert is a whole-row write (every column comes from the entry), so the
    # scenario evolves ONE entry dict in place — the same shape tracker_lib's verbs use.
    entry = {
        "taskId": "T-P4-1", "sessionId": _TASK_SESSION, "state": "IN_PROGRESS",
        "title": "P4 integration drill", "branch": "feat/p4-drill",
        "cwd": str(tmp_path / "consumer-repo"), "startedAt": started,
        "trackingSource": "claude", "resumeAttempts": [],
    }

    tracking = badger_store.open_tracking(families=_task_families())
    user = badger_store.open_user(families=_awm_families(claude_home))
    try:
        assert tracking.db_path != user.db_path, "the drill needs two distinct databases"

        # 1) the task starts on the project side, inside one write transaction
        tracking.conn.execute("BEGIN IMMEDIATE")
        tracking.task_upsert(dict(entry))
        tracking.session_upsert(_TASK_SESSION, {
            "transcriptPath": str(tmp_path / "consumer-repo" / "t.jsonl"),
            "cwd": str(tmp_path / "consumer-repo"), "pid": 4242, "recordedAt": started,
        })
        tracking.conn.commit()

        # 2) away mode arms for the project on the user side; another project's earlier
        #    entry is already there (per-project independence needs a second key)
        user.kv_set("awm_state", _PROJECT_B, {"enabled": True, "since": started})
        user.kv_set("awm_state", _PROJECT_A, {"enabled": True, "since": started})
        user.log_append("awm_decisions", started,
                        {"session": _TASK_SESSION, "project": _PROJECT_A, "action": "armed"})

        # 3) the session progresses: reminder flag + usage on the project side
        entry["stateJsonReminderSent"] = True
        tracking.conn.execute("BEGIN IMMEDIATE")
        tracking.task_upsert(dict(entry))
        tracking.conn.commit()
        tracking.conn.execute("BEGIN IMMEDIATE")
        tracking.usage_upsert({
            "taskId": "T-P4-1", "sessionId": _TASK_SESSION, "trackingSource": "claude",
            "usage": {"grandTotal": 12345, "cacheEfficiency": 0.9}, "subagents": [],
            "checkpoints": {}, "grade": None,
        })
        tracking.conn.commit()

        # 4) away mode disarms on the user side; the decision history appends on
        user.kv_set("awm_state", _PROJECT_A, {"enabled": False, "since": started})
        user.log_append("awm_decisions", "2026-08-31T11:00:00+00:00",
                        {"session": _TASK_SESSION, "project": _PROJECT_A, "action": "disarmed"})

        # 5) the task finishes on the project side
        entry["state"] = "FINISHED"
        entry["finishedAt"] = "2026-08-31T12:00:00+00:00"
        tracking.conn.execute("BEGIN IMMEDIATE")
        tracking.task_upsert(dict(entry))
        tracking.conn.commit()
    finally:
        tracking.close()
        user.close()

    assert project_root.joinpath("tracking.db").is_file()
    assert user_root.joinpath("ai-badger.db").is_file()

    # Fresh handles: each store's invariants verified independently of the writers.
    tracking = badger_store.open_tracking(families=_task_families())
    user = badger_store.open_user(families=_awm_families(claude_home))
    try:
        # project-side invariants
        rows = tracking.conn.execute(
            "SELECT task_id, session_id, state, finished_at, state_json_reminder_sent "
            "FROM tasks").fetchall()
        assert rows == [("T-P4-1", _TASK_SESSION, "FINISHED", "2026-08-31T12:00:00+00:00", 1)]
        usage = tracking.conn.execute(
            "SELECT usage FROM token_usage WHERE task_id = 'T-P4-1'").fetchone()
        assert json.loads(usage[0])["grandTotal"] == 12345
        assert tracking.conn.execute(
            "SELECT cwd FROM sessions WHERE session_id = ?", (_TASK_SESSION,)
        ).fetchone()[0].endswith("consumer-repo")

        # user-side invariants
        assert user.kv_get("awm_state", _PROJECT_A) == {"enabled": False, "since": started}
        assert user.kv_get("awm_state", _PROJECT_B) == {"enabled": True, "since": started}, (
            "one project's disarm must never touch a sibling project's entry")
        decisions = list(user.conn.execute(
            "SELECT ts, payload FROM awm_decisions ORDER BY id"))
        assert [json.loads(p)["action"] for _, p in decisions] == ["armed", "disarmed"]

        # the seam: the same session lived in both DBs, each recording its own side —
        # and no row crossed over into the other DB's tables (both files share one DDL,
        # so a misrouted write would still be visible where it does not belong).
        assert tracking.conn.execute("SELECT count(*) FROM awm_state").fetchone()[0] == 0
        assert tracking.conn.execute("SELECT count(*) FROM awm_decisions").fetchone()[0] == 0
        assert user.conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert user.conn.execute("SELECT count(*) FROM token_usage").fetchone()[0] == 0
    finally:
        tracking.close()
        user.close()


def test_a_broken_store_does_not_disturb_the_sibling_store(tmp_path, monkeypatch):
    """The seam is between two independent databases: corrupting tracking.db must leave the
    user store fully working, and vice versa — one drill per direction, both in this test.
    """
    project_root, user_root = _both_roots(tmp_path, monkeypatch)

    tracking = badger_store.open_tracking(families=_task_families())
    user = badger_store.open_user(families={})
    try:
        user.kv_set("commit_reminder", _PROJECT_A, {"count": 1})
        tracking.conn.execute("BEGIN IMMEDIATE")
        tracking.task_upsert({"taskId": "T-1", "sessionId": _TASK_SESSION,
                              "state": "IN_PROGRESS", "resumeAttempts": []})
        tracking.conn.commit()
    finally:
        tracking.close()
        user.close()

    tracking_path = project_root / "tracking.db"
    user_path = user_root / "ai-badger.db"
    tracking_path.write_bytes(b"not a database at all" * 32)

    with pytest.raises(sqlite3.DatabaseError):
        badger_store.open_tracking(families=_task_families())

    user = badger_store.open_user(families={})
    try:
        assert user.kv_get("commit_reminder", _PROJECT_A) == {"count": 1}
        user.kv_set("commit_reminder", _PROJECT_B, {"count": 2})
        assert user.kv_get("commit_reminder", _PROJECT_B) == {"count": 2}
    finally:
        user.close()

    # the reverse direction: a broken user store leaves the project store working —
    # on a fresh tracking root, since the first direction's tracking DB stays corrupt
    # (repairing it is the runbook drill's job, not this test's)
    project_root_2 = tmp_path / "second-repo" / ".ai-badger" / "task-tracking"
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(project_root_2))
    tracking = badger_store.open_tracking(families=_task_families())
    tracking.conn.execute("BEGIN IMMEDIATE")
    tracking.task_upsert({"taskId": "T-1", "sessionId": _TASK_SESSION,
                          "state": "IN_PROGRESS", "resumeAttempts": []})
    tracking.conn.commit()
    tracking.close()

    user_path.write_bytes(b"\x00garbage" * 64)
    with pytest.raises(sqlite3.DatabaseError):
        badger_store.open_user(families={})

    tracking = badger_store.open_tracking(families=_task_families())
    try:
        assert tracking.tasks_all()[0]["taskId"] == "T-1"
        tracking.conn.execute("BEGIN IMMEDIATE")
        # a second ACTIVE row needs its own session — one active task per session (D14)
        tracking.task_upsert({"taskId": "T-2", "sessionId": "01a04e2c-s4bl-ings-ess5ion0002",
                              "state": "IN_PROGRESS", "resumeAttempts": []})
        tracking.conn.commit()
        assert {t["taskId"] for t in tracking.tasks_all()} == {"T-1", "T-2"}
    finally:
        tracking.close()


# ---------------------------------------------------------------------------
# 2. Recovery-runbook drill (D31): delete DB -> restore *.migrated.* -> lazy re-import
# ---------------------------------------------------------------------------


def test_recovery_runbook_deleted_db_and_restored_names_reimport_without_duplicates(
        tmp_path, monkeypatch):
    """The documented runbook (ADR-0024 decision 8): delete the database, restore the
    *.migrated.* names, and the lazy import redoes the work — rows return exactly once.
    """
    _, user_root = _both_roots(tmp_path, monkeypatch)
    legacy = _seed_commit_reminder(
        user_root, {"/repo/legacy-a": {"count": 3}, "/repo/legacy-b": {"count": 7}})

    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/written", {"count": 9})  # write-migrates
    finally:
        store.close()
    migrated = legacy.with_name("state.migrated.json")
    assert migrated.is_file() and not legacy.exists()
    db_path = badger_store.user_db_path()

    # the disaster: the database is gone — and with it every DB-only row. The runbook
    # restores exactly what the legacy files carry; "/repo/written" never lived in one,
    # so its loss is the documented cost of the disaster, not a recovery defect.
    _delete_db(db_path)

    # the runbook: restore the *.migrated.* name (a rename preserves the mtime, so the
    # restored file reads as pre-migration legacy, not as a resurrection)
    os.replace(migrated, legacy)

    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/after-crash", {"count": 1})  # lazy re-import
        rows = [row[0] for row in store.conn.execute(
            "SELECT key FROM commit_reminder ORDER BY key")]
        assert rows == ["/repo/after-crash", "/repo/legacy-a", "/repo/legacy-b"], (
            "the re-import must restore every legacy row exactly once")
        assert migrated.is_file(), "the re-import re-quarantines the legacy file"
        assert not legacy.exists()
    finally:
        store.close()


def test_recovery_runbook_on_the_project_side_marker_state(tmp_path, monkeypatch):
    """The runbook is not user-DB-only: the project store recovers the same way —
    tracking.db deleted, marker-state restored, the default FAMILIES registry re-imports.
    """
    project_root, _ = _both_roots(tmp_path, monkeypatch)
    legacy_dir = project_root.parent / "prompt-markers"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy = legacy_dir / "marker-state.json"
    legacy.write_text(json.dumps({"s1": {"armed": True}, "s2": {"armed": False}}) + "\n",
                      encoding="utf-8")

    store = badger_store.open_tracking()
    try:
        store.kv_set("marker_state", "s3", {"armed": True})  # write-migrates
    finally:
        store.close()
    migrated = legacy_dir / "marker-state.migrated.json"
    assert migrated.is_file() and not legacy.exists()

    _delete_db(badger_store.tracking_db_path())
    os.replace(migrated, legacy)

    store = badger_store.open_tracking()
    try:
        store.kv_set("marker_state", "s4", {"armed": True})
        # "s3" was DB-only: it died with the deleted database, like every DB-only row.
        state = store.kv_all("marker_state")
        assert state == {"s1": {"armed": True}, "s2": {"armed": False},
                         "s4": {"armed": True}}
        assert store.conn.execute(
            "SELECT count(*) FROM marker_state").fetchone()[0] == 3, "no duplicate rows"
        assert migrated.is_file() and not legacy.exists()
    finally:
        store.close()


def test_recovery_runbook_zero_byte_db_shell_heals_when_legacy_names_restored(tmp_path,
                                                                              monkeypatch):
    """The truncated-to-zero variant: SQLite treats an empty file as a valid blank
    database, so the open succeeds with every row gone — and the runbook's restore step
    alone heals it (no stamp survives, so the restored legacy re-imports) instead of the
    shell silently diverging from the legacy truth.
    """
    _, user_root = _both_roots(tmp_path, monkeypatch)
    legacy = _seed_commit_reminder(user_root, {"/repo/legacy-a": {"count": 3}})
    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/kept", {"count": 5})
    finally:
        store.close()
    migrated = legacy.with_name("state.migrated.json")
    assert migrated.is_file()

    # truncate, then run the restore step of the runbook (the DB file itself survives
    # as an empty shell — and an empty shell holds nothing, so "/repo/kept" is gone
    # with it; only the restored legacy can return)
    badger_store.user_db_path().write_bytes(b"")
    os.replace(migrated, legacy)

    store = badger_store.open_user()
    try:
        assert store.conn.execute("SELECT count(*) FROM commit_reminder").fetchone()[0] == 0, (
            "the shell starts empty — the test premise, not the outcome")
        store.kv_set("commit_reminder", "/repo/after", {"count": 0})  # lazy re-import
        rows = [row[0] for row in store.conn.execute(
            "SELECT key FROM commit_reminder ORDER BY key")]
        assert rows == ["/repo/after", "/repo/legacy-a"]
    finally:
        store.close()


def test_recovery_runbook_garbage_db_fails_open_with_readable_error_then_restores(
        tmp_path, monkeypatch):
    """A garbage-corrupted database must fail with ONE readable error naming the file —
    not a crash loop, not silence — and the runbook must restore a working store from it.
    """
    _, user_root = _both_roots(tmp_path, monkeypatch)
    legacy = _seed_commit_reminder(user_root, {"/repo/legacy-a": {"count": 3}})
    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/kept", {"count": 5})
    finally:
        store.close()
    migrated = legacy.with_name("state.migrated.json")
    db_path = badger_store.user_db_path()

    db_path.write_bytes(b"\xff\x00\xde\xadbeef-not-sqlite" * 64)
    with pytest.raises(sqlite3.DatabaseError) as excinfo:
        badger_store.open_user()
    assert "file is not a database" in str(excinfo.value), (
        f"the corruption must surface as SQLite's readable error, got: {excinfo.value}")

    # the runbook: delete the corrupt database, restore the migrated names
    _delete_db(db_path)
    os.replace(migrated, legacy)

    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/after", {"count": 0})
        # "/repo/kept" was DB-only: the corrupt database took it; the runbook restores
        # the rows the legacy files carry, and nothing else.
        rows = [row[0] for row in store.conn.execute(
            "SELECT key FROM commit_reminder ORDER BY key")]
        assert rows == ["/repo/after", "/repo/legacy-a"]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 3. Concurrent first-write migration — two PROCESSES, one legacy file (D23)
# ---------------------------------------------------------------------------

# Runs in its own interpreter: opens the store first, then waits at a two-slot barrier
# immediately before the first write, so both processes reach the lazy import inside its
# window. Everything it needs arrives via argv/env — it must never import the suite.
_RACE_WORKER = """
import json, os, sys, time
from pathlib import Path

root, tag, ready_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
sys.path.insert(0, str(Path(root) / "engine"))
import badger_store  # noqa: E402  (path set two lines up)

store = badger_store.open_user()
(ready_dir / f"{tag}.ready").write_text("ok", encoding="utf-8")
deadline = time.time() + 15
while not all((ready_dir / f"{peer}.ready").is_file() for peer in ("p1", "p2")):
    if time.time() > deadline:
        raise SystemExit(f"barrier timeout, ready files: {sorted(p.name for p in ready_dir.iterdir())}")
    time.sleep(0.0005)  # tight: the barrier must sit INSIDE the import's race window

store.kv_set("commit_reminder", f"/repo/{tag}", {"pid": os.getpid()})
seen = store.kv_get("commit_reminder", f"/repo/{tag}")
store.close()
print(json.dumps({"tag": tag, "wrote": seen is not None}))
"""


def test_two_processes_racing_the_first_write_import_once_and_rename_once(
        tmp_path, monkeypatch):
    """TRUE concurrency (D23): two interpreter processes open the same legacy-file store
    and write simultaneously — exactly one import (no duplicate rows), exactly one rename,
    and both processes' writes land. The thread-based approximation cannot see the
    process-level races this pins (the flock across PIDs, the WAL conversion race).
    """
    _, user_root = _both_roots(tmp_path, monkeypatch)
    # Hundreds of per-project keys: the import itself takes tens of milliseconds, so the
    # race window the processes must collide in is wide enough to be forced, not hoped for.
    legacy_state = {f"/repo/legacy-{i:03d}": {"count": i} for i in range(400)}
    legacy = _seed_commit_reminder(user_root, legacy_state)
    time.sleep(0.05)  # legacy mtime must strictly predate the migration stamp

    ready_dir = tmp_path / "barrier"
    ready_dir.mkdir()
    worker = tmp_path / "race_worker.py"
    worker.write_text(_RACE_WORKER, encoding="utf-8")

    env = dict(os.environ)
    env["AI_BADGER_USER_ROOT"] = str(user_root)
    env["PYTHONPATH"] = str(ROOT / "engine")
    procs = [subprocess.Popen(
        [sys.executable, str(worker), str(ROOT), tag, str(ready_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        for tag in ("p1", "p2")]
    outs = [proc.communicate(timeout=90) for proc in procs]
    for tag, (out, err), proc in zip(("p1", "p2"), outs, procs):
        assert proc.returncode == 0, f"process {tag} failed:\n{out}\n{err}"
        assert json.loads(out.strip())["wrote"] is True, f"{tag} could not read back its write"

    store = badger_store.open_user()
    try:
        rows = [row[0] for row in store.conn.execute(
            "SELECT key FROM commit_reminder ORDER BY key")]
        assert rows == sorted(legacy_state) + ["/repo/p1", "/repo/p2"], (
            "exactly one import + both writes expected, got "
            f"{len(rows)} rows (expected {len(legacy_state) + 2})")
        counts = store.conn.execute(
            "SELECT count(*) FROM commit_reminder").fetchone()[0]
        assert counts == len(legacy_state) + 2, "no duplicate rows may survive the race"
    finally:
        store.close()

    assert not legacy.exists(), "the legacy file must have been renamed exactly once"
    assert legacy.with_name("state.migrated.json").is_file()
    stray = sorted(p.name for p in legacy.parent.iterdir()
                   if p.name not in ("state.migrated.json", ".write.lock"))
    assert stray == [], f"the race left stray artifacts behind: {stray}"


# ---------------------------------------------------------------------------
# 4. Scaffold E2E for the store — the delivered consumer shape
# ---------------------------------------------------------------------------


def _scaffold_config() -> dict:
    """The consumer config the deployment-shape tests scaffold with."""
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "project": {"name": "p4-drill", "summary": "s", "domain": "d"},
        "stacks": ["python"], "agents": ["claude", "hermes"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {}, "personaRouting": [], "skillScope": "default", "docs": {},
    }


@pytest.fixture(scope="module")
def scaffolded(tmp_path_factory) -> dict:
    """One real scaffold run over a fresh consumer, under a HOME of its own.

    Built the way the deployment-shape tests build theirs: a subprocess running the real
    scaffold.py entry point, env with no AI_BADGER escape hatch and no inherited project
    dir, --no-install because the drill needs no user-global installs.
    """
    base = tmp_path_factory.mktemp("p4-scaffold")
    home = base / "home"
    home.mkdir()
    consumer = base / "consumer"
    consumer.mkdir()
    config = base / "config.json"
    config.write_text(json.dumps(_scaffold_config()), encoding="utf-8")

    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("AI_BADGER", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "features/common/skills/welcome-ai-badger/scripts/scaffold.py"),
         "--config", str(config), "--target", str(consumer), "--root", str(ROOT),
         "--no-install"],
        capture_output=True, text=True, cwd=str(consumer), env=env, check=False)
    assert proc.returncode == 0, f"scaffold run failed:\n{proc.stdout}\n{proc.stderr}"
    return {"home": home, "consumer": consumer}


def test_scaffolded_consumer_carries_badger_store_copies_verbatim(scaffolded):
    """The delivered shape includes badger_store.py copies and every one of them is
    byte-identical to the canonical engine module — the D16 manifest, proven at the far
    end of the scaffold pipeline rather than inside this repo.
    """
    aib = scaffolded["consumer"] / ".ai-badger"
    canonical = ROOT / "engine" / "badger_store.py"
    copies = sorted(aib.rglob("badger_store.py"))
    landed = {str(p.relative_to(aib)) for p in copies}
    assert "engine/badger_store.py" in landed, f"engine copy missing: {landed}"
    assert "hooks/badger_store.py" in landed, f"hooks copy missing: {landed}"
    assert "skills/task/scripts/badger_store.py" in landed, (
        f"task-skill copy missing: {landed}")
    assert len(copies) >= 6, f"expected the store vendored across the consumers, got {landed}"
    expected = canonical.read_bytes()
    skewed = [str(p.relative_to(aib)) for p in copies if p.read_bytes() != expected]
    assert skewed == [], f"scaffold delivered skewed store copies: {skewed}"


def test_scaffolded_consumer_gitignore_block_ignores_the_tracking_db_and_sidecars(
        scaffolded):
    """The delivered .gitignore carries the managed block with the tracking database and
    its WAL/SHM sidecars — a scaffold without it gets .db files committed.
    """
    text = (scaffolded["consumer"] / ".gitignore").read_text(encoding="utf-8")
    lines = text.splitlines()
    begin = next(i for i, l in enumerate(lines) if l.startswith("# BEGIN ai-badger"))
    end = next(i for i, l in enumerate(lines) if l.startswith("# END ai-badger"))
    block = lines[begin + 1:end]
    for entry in (".ai-badger/task-tracking/tracking.db",
                  ".ai-badger/task-tracking/*.db-wal",
                  ".ai-badger/task-tracking/*.db-shm"):
        assert entry in block, f"{entry} missing from the delivered managed block: {block}"
    assert text.count("# BEGIN ai-badger managed block") == 1, "block delivered twice"


def test_hook_verb_runs_in_the_scaffolded_copy_and_lands_the_tracking_db(scaffolded):
    """The delivered copy runs: a task-tracker verb executed in the scaffolded consumer
    resolves the consumer's own tracking root through the delivered badger_store, reports
    through the CLI contract, and lands tracking.db where the gitignore block expects it.
    """
    consumer = scaffolded["consumer"]
    env = dict(os.environ)
    env["HOME"] = str(scaffolded["home"])
    env.pop("AI_BADGER_TRACKING_ROOT", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    tracker = consumer / ".ai-badger" / "skills" / "task" / "scripts" / "task_tracker.py"

    proc = subprocess.run([sys.executable, str(tracker), "status"], capture_output=True,
                          text=True, cwd=str(consumer), env=env, check=False)
    assert proc.returncode == 0, f"status verb failed in the scaffolded copy:\n{proc.stderr}"
    assert "No tracked tasks." in proc.stdout, proc.stdout

    db = consumer / ".ai-badger" / "task-tracking" / "tracking.db"
    assert db.is_file(), "the verb must land tracking.db inside the consumer's .ai-badger"

    # the store's own CLI verb through the same delivered copy: read-only retention status
    store_cli = consumer / ".ai-badger" / "skills" / "task" / "scripts" / "badger_store.py"
    proc = subprocess.run([sys.executable, str(store_cli), "prune", "--status"],
                          capture_output=True, text=True, cwd=str(consumer), env=env,
                          check=False)
    assert proc.returncode == 0, f"prune --status failed in the scaffolded copy:\n{proc.stderr}"
    assert "db=user" in proc.stdout and "hook_audit" in proc.stdout, proc.stdout
