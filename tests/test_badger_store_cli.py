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
