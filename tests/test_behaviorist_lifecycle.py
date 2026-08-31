"""`behaviorist on` — how long logging stays on, including indefinitely.

A capped window suits a one-off investigation. Standing instrumentation — the drift a
project only shows over weeks — needs logging that does not switch itself off mid-question.
The 5000-record cap in debug_log bounds the disk either way.
"""
from __future__ import annotations

import json
from datetime import timedelta


def _load(load_script, tmp_path, monkeypatch):
    beh = load_script("features/common/skills/call-behaviorist/scripts/behaviorist.py")
    root = tmp_path / "debug"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(beh.dl, "DEBUG_DIR", root)
    monkeypatch.setattr(beh.dl, "STATE_FILE", root / "state.json")
    monkeypatch.setattr(beh.dl, "AUDIT_FILE", root / "audit.jsonl")
    return beh


def _state(beh):
    """State through the logger's own accessor: the store row since P2.2, legacy file otherwise."""
    return beh.dl._state()  # pylint: disable=protected-access


class TestBoundedDurationsStillWork:
    """The existing grammar is unchanged — a duration still expires, and is still capped."""

    def test_hours_minutes_and_bare_number(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        assert beh.parse_duration("4h") == 4 * 3600
        assert beh.parse_duration("90m") == 90 * 60
        assert beh.parse_duration("1h30m") == 3600 + 30 * 60
        assert beh.parse_duration("2") == 2 * 3600

    def test_a_bounded_duration_is_capped_and_records_an_expiry(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        assert beh.parse_duration("48h") == beh.MAX_DURATION_SECONDS

        assert beh.cmd_on("4h", project_scoped=False) == 0
        assert _state(beh)["expires_at"] is not None


class TestPermanentLogging:
    """`forever` keeps logging on until it is switched off by hand."""

    def test_forever_parses_to_no_expiry(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        assert beh.parse_duration("forever") is None
        assert beh.parse_duration("never") is None
        assert beh.parse_duration("FOREVER") is None

    def test_forever_records_no_expiry(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)

        assert beh.cmd_on("forever", project_scoped=False) == 0

        state = _state(beh)
        assert state["enabled"] is True
        assert state["expires_at"] is None

    def test_logging_stays_on_long_past_the_old_24h_cap(
            self, load_script, tmp_path, monkeypatch):
        """The guard that mattered: a null expiry must never read as expired."""
        beh = _load(load_script, tmp_path, monkeypatch)
        beh.cmd_on("forever", project_scoped=False)

        far_future = beh.dl.now() + timedelta(days=400)
        monkeypatch.setattr(beh.dl, "now", lambda: far_future)

        assert beh.dl.enabled_for("/any/project") is True

    def test_a_bounded_window_still_expires(self, load_script, tmp_path, monkeypatch):
        """Companion to the test above — proves the expiry check still fires at all."""
        beh = _load(load_script, tmp_path, monkeypatch)
        beh.cmd_on("4h", project_scoped=False)

        far_future = beh.dl.now() + timedelta(days=400)
        monkeypatch.setattr(beh.dl, "now", lambda: far_future)

        assert beh.dl.enabled_for("/any/project") is False

    def test_status_names_the_absent_expiry(self, load_script, tmp_path, monkeypatch, capsys):
        beh = _load(load_script, tmp_path, monkeypatch)
        beh.cmd_on("forever", project_scoped=False)
        capsys.readouterr()

        beh.cmd_status()

        assert "never" in capsys.readouterr().out.lower()
