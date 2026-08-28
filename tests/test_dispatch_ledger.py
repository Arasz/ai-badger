"""Tests for the concurrent-dispatch ledger behind the isolation half of the dispatch gate.

The gate denies an unisolated write dispatch only under parallelism, so it needs to answer
one question: is another agent lane from this session live right now?

Design note — why a time window and not Pre/PostToolUse pairing. Pairing would track an
agent's real lifetime, but it depends on `PostToolUse` firing for `Agent`, which is
unverified; when it does not fire, a stale entry wedges the gate closed for every later
dispatch. A window cannot wedge: entries age out on their own. It works because parallel
dispatch is *expressed* as several `Agent` calls in one assistant message, so siblings land
milliseconds apart — far inside any sane window.

Each test names the failure mode it targets:

- `test_a_lone_dispatch_sees_no_sibling` — the quiet path. If this breaks, the gate fires on
  ordinary single-agent work, which is the failure that gets a gate switched off.
- `test_a_second_dispatch_sees_the_first` — the whole point; a fan-out that reports 0 siblings
  is a gate that never fires.
- `test_an_entry_outside_the_window_is_not_counted` — without this the ledger is a permanent
  record and every dispatch after the first looks parallel forever.
- `test_a_dispatch_does_not_count_itself` — off-by-one that would deny every single dispatch.
- `test_separate_sessions_do_not_see_each_other` — in-session fan-out is the signal; another
  session's lanes are the *other* half of the gate (live sockets) and must not double-count.
- `test_a_broken_ledger_reports_no_siblings` — fails open. A gate that cannot read its own
  state must allow, never block.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import pytest

MODULE = "features/common/skills/task/scripts/dispatch_ledger.py"

WINDOW = 90.0


@pytest.fixture
def ledger(load_script, tmp_path, monkeypatch):
    """The ledger with its state redirected into tmp_path — never the real ~/.ai-badger."""
    module = load_script(MODULE)
    monkeypatch.setattr(module, "LEDGER_DIR", tmp_path / "dispatch-lanes")
    return module


def test_a_lone_dispatch_sees_no_sibling(ledger):
    ledger.record("sess_a", "toolu_1", now=1000.0)

    assert ledger.concurrent("sess_a", "toolu_1", now=1000.0, window=WINDOW) == 0


def test_a_second_dispatch_sees_the_first(ledger):
    ledger.record("sess_a", "toolu_1", now=1000.0)
    ledger.record("sess_a", "toolu_2", now=1000.2)

    assert ledger.concurrent("sess_a", "toolu_2", now=1000.2, window=WINDOW) == 1


def test_an_entry_outside_the_window_is_not_counted(ledger):
    ledger.record("sess_a", "toolu_1", now=1000.0)
    ledger.record("sess_a", "toolu_2", now=1000.0 + WINDOW + 1)

    assert ledger.concurrent("sess_a", "toolu_2", now=1000.0 + WINDOW + 1,
                             window=WINDOW) == 0


def test_a_dispatch_does_not_count_itself(ledger):
    ledger.record("sess_a", "toolu_1", now=1000.0)
    ledger.record("sess_a", "toolu_1", now=1000.1)  # a retry reuses the id

    assert ledger.concurrent("sess_a", "toolu_1", now=1000.1, window=WINDOW) == 0


def test_separate_sessions_do_not_see_each_other(ledger):
    ledger.record("sess_a", "toolu_1", now=1000.0)
    ledger.record("sess_b", "toolu_2", now=1000.1)

    assert ledger.concurrent("sess_b", "toolu_2", now=1000.1, window=WINDOW) == 0


def test_a_broken_ledger_reports_no_siblings(ledger, monkeypatch):
    """Fails open: an unreadable ledger must not become a reason to block dispatch."""
    ledger.record("sess_a", "toolu_1", now=1000.0)
    ledger.record("sess_a", "toolu_2", now=1000.1)
    monkeypatch.setattr(ledger, "LEDGER_DIR", ledger.LEDGER_DIR / "nonexistent" / "deeper")

    assert ledger.concurrent("sess_a", "toolu_2", now=1000.1, window=WINDOW) == 0


def test_a_missing_session_id_records_nothing(ledger):
    """No session id means no way to scope the ledger; recording anyway would pool
    unrelated dispatches into one bucket and deny them all."""
    assert ledger.record("", "toolu_1", now=1000.0) is False
    assert ledger.concurrent("", "toolu_1", now=1000.0, window=WINDOW) == 0
