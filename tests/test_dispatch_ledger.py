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
    """The ledger with its state redirected into tmp_path — never the real ~/.ai-badger.
    The ledger's state is a `dispatch_lanes` row in the user store, so redirecting the
    store's user root redirects the ledger."""
    module = load_script(MODULE)
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
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


def test_a_broken_ledger_reports_no_siblings(ledger, tmp_path, monkeypatch):
    """Fails open: an unreadable ledger must not become a reason to block dispatch."""
    ledger.record("sess_a", "toolu_1", now=1000.0)
    ledger.record("sess_a", "toolu_2", now=1000.1)
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(blocked / "no" / "store"))

    assert ledger.concurrent("sess_a", "toolu_2", now=1000.1, window=WINDOW) == 0


def test_a_missing_session_id_records_nothing(ledger):
    """No session id means no way to scope the ledger; recording anyway would pool
    unrelated dispatches into one bucket and deny them all."""
    assert ledger.record("", "toolu_1", now=1000.0) is False
    assert ledger.concurrent("", "toolu_1", now=1000.0, window=WINDOW) == 0


def test_concurrent_records_all_survive(ledger, tmp_path):
    """Eight lanes recording at once must yield eight entries.

    Found in review: `record` was read-modify-write, which drops entries under exactly the
    condition the ledger exists for — the docstring's own "siblings land milliseconds apart"
    is the same statement as "these hook processes overlap". Measured 7/8 surviving on one
    run and 8/8 on the next, so the gate was a coin flip rather than a consistent failure.
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: ledger.record("sess_race", f"toolu_{n}", now=1000.0),
                      range(8)))

    assert ledger.concurrent("sess_race", "none", now=1000.0, window=WINDOW) == 8


def test_a_session_id_cannot_escape_the_ledger_dir(ledger):
    """The sanitizer is a security control, so it needs a test that fails without it.

    Found by review mutation: replacing `_safe_session` with `str(session_id)` survived the
    whole suite, and `../../pwned` would then write outside LEDGER_DIR.
    """
    path = ledger.ledger_path("../../pwned")

    # `.resolve()` on both sides: `LEDGER_DIR / "../../pwned"` contains LEDGER_DIR in its
    # unnormalised `.parents`, so the lexical form of this assertion passed for a path that
    # escapes to /tmp/pwned. The first version of this test did exactly that.
    assert ledger.LEDGER_DIR.resolve() in path.resolve().parents, path.resolve()
    assert "/" not in path.name and ".." != path.name, path.name


def test_a_corrupted_row_reports_no_siblings(ledger):
    """Byte→row rewrite of the malformed-line test (P2.1b): a corrupt entries cell must
    fail open, not raise out of concurrent and disable the gate for the whole session."""
    import sqlite3

    ledger.record("sess_a", "toolu_1", now=1000.0)
    store = ledger.badger_store.open_user()
    try:
        store.conn.execute(
            "UPDATE dispatch_lanes SET entries = ? WHERE lane_id = ?",
            ("not-json-at-all", ledger._safe_session("sess_a")))  # noqa: SLF001  # pylint: disable=protected-access
        store.conn.commit()
    finally:
        store.close()

    assert ledger.concurrent("sess_a", "toolu_1", now=1000.0, window=WINDOW) == 0


def test_record_survives_a_corrupted_row(ledger):
    """Byte→row rewrite of the invalid-utf8 test (P2.1b): a corrupt entries cell must not
    wedge the lane — the next record rebuilds it and the count resumes."""
    ledger.record("sess_a", "toolu_1", now=1000.0)
    store = ledger.badger_store.open_user()
    try:
        store.conn.execute(
            "UPDATE dispatch_lanes SET entries = x'fffe' WHERE lane_id = ?",
            (ledger._safe_session("sess_a"),))  # noqa: SLF001  # pylint: disable=protected-access
        store.conn.commit()
    finally:
        store.close()

    assert ledger.concurrent("sess_a", "toolu_1", now=1000.0, window=WINDOW) == 0
    assert ledger.record("sess_a", "toolu_2", now=1000.1) is True
    assert ledger.concurrent("sess_a", "probe", now=1000.1, window=WINDOW) == 1


def test_an_entry_from_the_future_is_not_counted(ledger):
    """A backward clock step (NTP, suspend/resume) left entries that never age out.

    `stamp - ts <= window` admits every negative delta, so the claim that "a window cannot
    wedge" was false across a clock correction.
    """
    ledger.record("sess_a", "toolu_1", now=2000.0)

    assert ledger.concurrent("sess_a", "toolu_2", now=1000.0, window=WINDOW) == 0


def test_a_newline_in_the_tool_use_id_cannot_forge_an_entry(ledger):
    """One record must add exactly one countable lane, whatever the id contains."""
    ledger.record("sess_a", "toolu_a\n1000.0 phantom", now=1000.0)

    assert ledger.concurrent("sess_a", "other", now=1000.0, window=WINDOW) == 1
