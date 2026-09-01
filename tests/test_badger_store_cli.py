"""The store CLI's `prune --status` verb (P2.3): retention state across both runtime DBs.

One entry point per the vendored-modules convention (argparse subparsers, main(argv), a
__main__ guard). The verb is read-only by contract — a status report must never create,
migrate or write the store it reports on — and must survive both a never-written table
and a stamp its writer never produced.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import badger_store


def _user_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(tmp_path / "user-root" / "debug"))


def _ts(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _open_audit():
    """The audit sink over its own DB file, with USER_FAMILIES' env-aware hook_audit family."""
    return badger_store._open(  # pylint: disable=protected-access
        badger_store.audit_db_path(), "user", badger_store.USER_FAMILIES)


def test_prune_status_reports_rows_oldest_and_last_prune_per_log_table(
        tmp_path, monkeypatch, capsys):
    """Every log table is reported from the DB it lives in — awm_decisions/searches from
    the user DB, hook_audit from the audit sink — with row count, oldest ts and the
    pruned_at stamp rendered; a table with no stamp reports '-', never a guess."""
    _user_env(tmp_path, monkeypatch)
    user = badger_store.open_user()
    try:
        oldest = _ts(90)
        user.log_append("awm_decisions", oldest, {"marker": "old"})
        user.log_append("awm_decisions", _ts(1), {"marker": "fresh"})
        user.log_append("searches", _ts(5), {"q": "x"})
        user.prune_expired("searches", max_age_days=60)
        stamp = datetime.fromtimestamp(user.meta_get("pruned_at.searches"),
                                       timezone.utc).isoformat()
    finally:
        user.close()
    audit = _open_audit()
    try:
        audit.log_append("hook_audit", _ts(3), {"t": _ts(3), "c": "x", "e": "y"})
    finally:
        audit.close()

    assert badger_store.main(["prune", "--status"]) == 0

    out = capsys.readouterr().out
    assert "db=user path=" in out and "db=audit path=" in out
    assert f"awm_decisions rows=2 oldest={oldest} last_prune=-" in out
    assert "searches rows=1 " in out and f"last_prune={stamp}" in out
    assert "hook_audit rows=1 oldest=" in out


def test_prune_status_creates_no_database_when_absent(tmp_path, monkeypatch, capsys):
    """A status verb that provisions the store it reports on is a write in disguise —
    absent DBs are reported as such, zeros all round, nothing created (exit 0)."""
    _user_env(tmp_path, monkeypatch)

    assert badger_store.main(["prune", "--status"]) == 0

    out = capsys.readouterr().out
    assert out.count("status=no-database") == 2
    assert "awm_decisions rows=0 oldest=- last_prune=-" in out
    assert "searches rows=0 oldest=- last_prune=-" in out
    assert "hook_audit rows=0 oldest=- last_prune=-" in out
    assert not badger_store.user_db_path().exists()
    assert not badger_store.audit_db_path().exists()


def test_prune_without_status_flag_is_a_usage_error(capsys):
    """`prune` alone does nothing silently: the only implemented mode is explicit."""
    with pytest.raises(SystemExit) as exc:
        badger_store.main(["prune"])
    assert exc.value.code == 2
    assert "--status" in capsys.readouterr().err


def test_prune_status_survives_an_empty_table_and_a_garbage_stamp(
        tmp_path, monkeypatch, capsys):
    """A table never written reports rows=0/oldest=- and a stamp the store never wrote
    renders as '-', never a crash — the verb reads whatever a DB may contain."""
    _user_env(tmp_path, monkeypatch)
    user = badger_store.open_user()
    try:
        user.meta_set("pruned_at.searches", "not-a-float")
        stamp_value = time.time()
        user.meta_set("pruned_at.awm_decisions", stamp_value)
        user.log_append("awm_decisions", _ts(2), {"marker": "fresh"})
    finally:
        user.close()

    assert badger_store.main(["prune", "--status"]) == 0

    out = capsys.readouterr().out
    assert "searches rows=0 oldest=- last_prune=-" in out
    expected_stamp = datetime.fromtimestamp(stamp_value, timezone.utc).isoformat()
    assert f"last_prune={expected_stamp}" in out


# ---------------------------------------------------------------------------
# `doctor` (M2/P1): per-family containment status and repair
# ---------------------------------------------------------------------------


def _resurrect_commit_reminder(tmp_path, monkeypatch) -> Path:
    """A user store with a resurrected commit_reminder (map) legacy file."""
    _user_env(tmp_path, monkeypatch)
    legacy = tmp_path / "user-root" / "commit-reminder" / "state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"/repo/a": {"count": 1}}), encoding="utf-8")
    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/db", {"count": 2})  # migrate + rename
    finally:
        store.close()
    time.sleep(0.05)
    legacy.write_text(json.dumps({"/repo/a": {"count": 9}, "/repo/new": {"count": 5}}),
                      encoding="utf-8")
    return legacy


def test_doctor_status_reports_each_resurrected_family_without_creating_or_migrating(
        tmp_path, monkeypatch, capsys):
    """doctor --status names every contained family with stamp/mtime/state and the map
    content diff — and never creates or migrates anything it reports on."""
    _user_env(tmp_path, monkeypatch)

    # an absent DB is reported, not created (the prune --status pattern):
    assert badger_store.main(["doctor", "--status"]) == 0
    out = capsys.readouterr().out
    assert "status=no-database" in out
    assert not badger_store.user_db_path().exists()

    legacy = _resurrect_commit_reminder(tmp_path, monkeypatch)
    assert badger_store.main(["doctor", "--status"]) == 0
    out = capsys.readouterr().out
    assert "family=commit_reminder" in out
    assert "state=resurrected" in out
    assert "diff=" in out  # map-family content diff vs the DB rows (reviewer S3)
    assert "/repo/new" in out  # the diff names what the newer file would add
    # read-only: the file keeps its name, the stamp keeps its value, no migration ran
    assert legacy.exists()


def test_doctor_status_flags_nothing_when_no_family_is_resurrected(
        tmp_path, monkeypatch, capsys):
    """A healthy store reports every family state without a resurrected line."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.log_append("awm_decisions", _ts(1), {"decision": "d"})
    finally:
        store.close()

    assert badger_store.main(["doctor", "--status"]) == 0
    out = capsys.readouterr().out
    assert "state=resurrected" not in out
    assert "family=awm_decisions" in out


def test_doctor_repair_reimports_additive_kinds_and_renames(tmp_path, monkeypatch, capsys):
    """repair: a contained recent (additive) family re-imports idempotently and renames
    to *.migrated; a fresh open holds no contained family and the rows are there."""
    _user_env(tmp_path, monkeypatch)
    legacy = tmp_path / "user-root" / "memory-grade" / "searches.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(
        {"recent": [{"correlationId": "c1", "sourceFiles": [], "ts": 1750000000}]}),
        encoding="utf-8")
    store = badger_store.open_user()
    try:
        store.migrate("searches")  # import + rename + stamp
        store.log_append("searches", badger_store.iso_row_ts(1750000001), {"q": "seeded"})
    finally:
        store.close()
    time.sleep(0.05)
    legacy.write_text(json.dumps(
        {"recent": [{"correlationId": "c2", "sourceFiles": [], "ts": 1750000002}]}),
        encoding="utf-8")

    assert badger_store.main(["doctor", "--repair"]) == 0
    out = capsys.readouterr().out
    assert "family=searches" in out and "re-imported" in out
    assert not legacy.exists()
    assert legacy.with_name("searches.migrated.json").exists()

    store = badger_store.open_user()
    try:
        assert store.contained_families() == {}
        assert len(store.log_rows("searches")) == 3
    finally:
        store.close()


def test_doctor_repair_is_inspect_only_for_map_families(tmp_path, monkeypatch, capsys):
    """repair: a contained map family is reported with guidance and left byte-identical —
    the file may be NEWER than the DB; merging it is an owner decision, not a default."""
    legacy = _resurrect_commit_reminder(tmp_path, monkeypatch)

    assert badger_store.main(["doctor", "--repair"]) == 0
    out = capsys.readouterr().out
    assert "family=commit_reminder" in out
    assert "inspect-only" in out
    assert legacy.exists()  # the resurrected file itself is untouched: not renamed, not imported

    store = badger_store.open_user()
    try:
        assert set(store.contained_families()) == {"commit_reminder"}  # still contained
        rows = {key for (key,) in store.conn.execute(
            "SELECT key FROM commit_reminder")}
        assert "/repo/new" not in rows  # the newer file's keys were NOT merged in
    finally:
        store.close()


def test_doctor_project_target_reports_the_project_tracking_root(
        tmp_path, monkeypatch, capsys):
    """--project PATH scans that project's tracking store and its re-rooted FAMILIES
    registry — the marker_state shape the original incident was, without env redirection."""
    monkeypatch.delenv("AI_BADGER_TRACKING_ROOT", raising=False)
    monkeypatch.delenv("AI_BADGER_USER_ROOT", raising=False)
    project = tmp_path / "project"
    (project / ".ai-badger" / "task-tracking").mkdir(parents=True)
    db_path, families = badger_store.doctor_target(project)
    legacy = Path(families["marker_state"].legacy_path())
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"alpha": "legacy-alpha"}), encoding="utf-8")
    store = badger_store._open(  # pylint: disable=protected-access
        db_path, "tracking", families)
    try:
        store.kv_set("marker_state", "gamma", "db-gamma")
    finally:
        store.close()
    time.sleep(0.05)
    legacy.write_text(json.dumps({"alpha": "stale-surface-write"}), encoding="utf-8")

    assert badger_store.main(["doctor", "--status", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "family=marker_state" in out and "state=resurrected" in out
    assert "diff=" in out
