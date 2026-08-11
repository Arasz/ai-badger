"""The commit hook commands rather than suggests, and escalates when nobody acts.

Three behaviours, all in `commit_reminder.py` so they are testable without a hook payload:
the message is imperative and names the Conventional Commits form; repeated fires with no
commit in between are counted; and once that count crosses a bar the work is flagged at risk,
which is what `ensure-work-is-committed` reads to tell a parent a subagent is stuck.
"""
from __future__ import annotations

import json
from conftest import _test_write


SCRIPT = "features/common/skills/commit-reminder/scripts/commit_reminder.py"


class TestTheMessageCommands:
    """A reminder nobody acts on is a reminder; this has to read as an instruction."""

    def test_the_message_is_imperative_not_a_suggestion(self, load_script):
        cr = load_script(SCRIPT)

        message = cr.build_message(count=7, reason="spread across 3 directories", fires=1)

        assert "Commit now" in message
        assert "consider" not in message.lower(), "a suggestion is what this replaces"

    def test_the_message_names_the_conventional_commits_form(self, load_script):
        """The convention is useless if the agent has to go and look it up."""
        cr = load_script(SCRIPT)

        message = cr.build_message(count=7, reason="", fires=1)

        assert "<type>[optional scope]: <description>" in message
        assert cr.CONVENTION_URL in message

    def test_the_message_still_carries_the_count_and_the_impact_reason(self, load_script):
        cr = load_script(SCRIPT)

        message = cr.build_message(count=7, reason="spread across 3 directories", fires=1)

        assert "7 uncommitted file(s)" in message
        assert "spread across 3 directories" in message

    def test_an_escalated_message_says_the_work_can_be_lost(self, load_script):
        """The parent acts on this, so it must state the consequence, not just repeat itself."""
        cr = load_script(SCRIPT)

        message = cr.build_message(count=9, reason="", fires=3, at_risk=True)

        assert "at risk" in message.lower()
        assert "3" in message, "the escalation must say how many times it has asked"


class TestFiresAreCountedUntilSomethingIsCommitted:
    """The count is the evidence an agent is stuck, so a commit has to clear it."""

    def test_a_first_crossing_fires_and_starts_the_count(self, load_script):
        cr = load_script(SCRIPT)

        fires, at_risk, entry = cr.advance({"marker": 0, "fires": 0}, count=6, threshold=5)

        assert fires is True
        assert at_risk is False
        assert entry["fires"] == 1

    def test_each_further_crossing_increments_the_count(self, load_script):
        cr = load_script(SCRIPT)
        entry = {"marker": 0, "fires": 0}

        for expected in (1, 2, 3):
            _, _, entry = cr.advance(entry, count=5 + expected, threshold=5)
            assert entry["fires"] == expected

    def test_a_commit_clears_the_count(self, load_script):
        """A dropped file count is the only evidence of a commit this hook has."""
        cr = load_script(SCRIPT)
        entry = {"marker": 8, "fires": 2}

        _, _, entry = cr.advance(entry, count=0, threshold=5)

        assert entry["fires"] == 0, "committing must clear the stuck-agent evidence"

    def test_silence_between_crossings_does_not_inflate_the_count(self, load_script):
        """The debounce already suppresses the fire; it must not count as one either."""
        cr = load_script(SCRIPT)
        fires, _, entry = cr.advance({"marker": 6, "fires": 1}, count=6, threshold=5)

        assert fires is False
        assert entry["fires"] == 1


class TestWorkIsFlaggedAtRisk:
    """What a parent reads to decide whether to take over, commit, or kill a subagent."""

    def test_three_unanswered_commands_flag_the_work_at_risk(self, load_script):
        cr = load_script(SCRIPT)
        entry = {"marker": 0, "fires": 0}

        flags = []
        for i in range(1, 4):
            _, at_risk, entry = cr.advance(entry, count=5 + i, threshold=5)
            flags.append(at_risk)

        assert flags == [False, False, True], "the bar is three unanswered commands"

    def test_the_entry_records_who_was_asked_and_since_when(self, load_script):
        """A parent needs to know which agent, not just that something is stuck."""
        cr = load_script(SCRIPT)

        _, _, entry = cr.advance({"marker": 0, "fires": 0}, count=6, threshold=5,
                                 now="2026-07-31T12:00:00Z", session="sess-1")

        assert entry["since"] == "2026-07-31T12:00:00Z"
        assert entry["session"] == "sess-1"

    def test_the_bar_is_configurable(self, load_script):
        cr = load_script(SCRIPT)

        _, at_risk, _ = cr.advance({"marker": 0, "fires": 0}, count=6, threshold=5,
                                   escalate_after=1)

        assert at_risk is True


class TestOldStateStillLoads:
    """The state file predates this change and is on every machine that ran the old hook."""

    def test_a_bare_integer_marker_is_read_as_an_entry(self, load_script, tmp_path, monkeypatch):
        cr = load_script(SCRIPT)
        state = tmp_path / "state.json"
        _test_write(state, json.dumps({str(tmp_path): 4}), encoding="utf-8")
        monkeypatch.setattr(cr, "STATE_FILE", state)

        entry = cr.get_entry(str(tmp_path))

        assert entry["marker"] == 4
        assert entry["fires"] == 0

    def test_an_entry_round_trips_through_the_state_file(self, load_script, tmp_path,
                                                         monkeypatch):
        cr = load_script(SCRIPT)
        monkeypatch.setattr(cr, "STATE_FILE", tmp_path / "state.json")

        cr.set_entry(str(tmp_path), {"marker": 6, "fires": 2, "since": "t", "session": "s"})

        assert cr.get_entry(str(tmp_path))["fires"] == 2


class TestSinceIsWhenItStarted:
    """A parent reads this as how long the work has been at risk."""

    def test_since_records_the_first_unanswered_command_not_the_latest(self, load_script):
        cr = load_script(SCRIPT)
        entry = {"marker": 0, "fires": 0}

        _, _, entry = cr.advance(entry, count=6, threshold=5, now="T0-first")
        _, _, entry = cr.advance(entry, count=7, threshold=5, now="T1")
        _, _, entry = cr.advance(entry, count=8, threshold=5, now="T2-latest")

        assert entry["since"] == "T0-first", "refreshing it understates the risk it reports"

    def test_a_commit_then_a_new_crossing_starts_a_fresh_clock(self, load_script):
        cr = load_script(SCRIPT)
        entry = {"marker": 0, "fires": 0}
        _, _, entry = cr.advance(entry, count=6, threshold=5, now="T0")
        _, _, entry = cr.advance(entry, count=0, threshold=5, now="T1")  # committed

        _, _, entry = cr.advance(entry, count=6, threshold=5, now="T2-new")

        assert entry["since"] == "T2-new"


class TestTheStateFileSurvivesConcurrency:
    """Parallel agents in separate worktrees share one file."""

    def test_a_write_is_atomic_so_a_reader_never_sees_a_torn_file(self, load_script, tmp_path,
                                                                 monkeypatch):
        cr = load_script(SCRIPT)
        state = tmp_path / "state.json"
        monkeypatch.setattr(cr, "STATE_FILE", state)
        seen = []

        real_replace = cr.os.replace

        def spy(src, dst):
            seen.append(cr.load_state())  # what a concurrent reader would get mid-write
            real_replace(src, dst)

        monkeypatch.setattr(cr.os, "replace", spy)
        cr.set_entry(str(tmp_path), {"marker": 6, "fires": 2})
        cr.set_entry(str(tmp_path), {"marker": 7, "fires": 3})

        assert seen[1] != {}, "a reader mid-write must still see the previous complete state"
        assert seen[1][str(tmp_path.resolve())]["fires"] == 2
