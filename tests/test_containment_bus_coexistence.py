"""P8 integration — per-family containment and the message bus coexist in one store.

The M2 contract at the seams the other packages lean on: a resurrected legacy file
contains THAT family only — `open_user` still opens, the bus still sends and delivers,
and `doctor_scan` names the contained family without touching the bus tables. The bus
exercises the real delivery path (gate, cursor, leg scoping) while containment is live.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

import badger_store


def _user_env(tmp_path, monkeypatch):
    root = tmp_path / "user-root"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(root))
    monkeypatch.setattr(badger_store, "_DEFAULT_HOME", tmp_path)
    return root


def _seed_marker(root):
    """One memory_first presence marker (the file-set kind with the simplest shape)."""
    path = root / "memory-first" / "01a04e01-18b7-7f42-88c6-19e68738589d"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_contained_family_never_blocks_the_bus(tmp_path, monkeypatch):
    """Resurrect memory_first after its legitimate import: the family is contained,
    while send/deliver — the gate, the leg-scoped first cursor and a later project
    read — run normally, and the doctor scan names exactly the contained family."""
    root = _user_env(tmp_path, monkeypatch)
    legacy = _seed_marker(root)

    store = badger_store.open_user()
    try:
        store.migrate("memory_first")  # the legitimate pre-resurrection import
    finally:
        store.close()
    time.sleep(0.05)
    _seed_marker(root)  # resurrection: a stale surface rewrites the migrated file

    store = badger_store.open_user()
    try:
        assert set(store.contained_families()) == {"memory_first"}

        # The bus is unaffected: 1:1 leg under the D7 fail-open, leg-scoped cursor,
        # then a later session whose project resolves still gets the in-window mail.
        store.send_message(sender_session="S1", sender_project="P",
                           content="direct ping", target_session="S2")
        broadcast_id = store.send_message(sender_session="S1", sender_project="P",
                                          content="project mail", target_project="P")
        assert [d["content"] for d in store.deliver_for_session("S2", None)] == \
            ["direct ping"]
        assert [d["content"] for d in store.deliver_for_session("S3", "P")] == \
            ["project mail"]
        assert broadcast_id > 0

        # The contained family refuses on its migration path; the doctor scan names it.
        with pytest.raises(sqlite3.OperationalError, match="reappeared"):
            store._migrate_file_set(  # pylint: disable=protected-access
                badger_store.USER_FAMILIES["memory_first"])
        findings = badger_store.doctor_scan(store.db_path, badger_store.USER_FAMILIES)
        named = {f["family"] for f in findings if f.get("state") == "resurrected"}
        assert "memory_first" in named
    finally:
        store.close()
