"""The read side of the commit hook's state: which agents are about to lose work.

A PostToolUse hook can only add context to the agent that triggered it — it has no channel to
that agent's parent. So the hook records, and this reports: a parent runs it to find out which
subagent has been told to commit repeatedly and has not, while there is still time to take over,
commit, or kill it.
"""
from __future__ import annotations

import json


SCRIPT = "features/common/skills/commit-reminder/scripts/ensure_committed.py"


def _state(tmp_path, payload) -> "Path":
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(load_script, monkeypatch, state_file, argv=None, uncommitted=("a.py",)):
    """Run the reporter against a state file.

    `uncommitted` stands in for `git status` at the recorded roots, which are fixture paths
    with no repository behind them. It defaults to "still dirty" so a test says what it means:
    the report also drops any project whose work has since been committed.
    """
    module = load_script(SCRIPT)
    monkeypatch.setattr(module.commit_reminder, "STATE_FILE", state_file)
    monkeypatch.setattr(module.commit_reminder, "uncommitted_files",
                        lambda root: list(uncommitted))
    return module, module.main(argv or [])


class TestNothingAtRisk:
    def test_a_clean_state_reports_nothing_at_risk(self, load_script, monkeypatch, tmp_path,
                                                   capsys):
        _, rc = _run(load_script, monkeypatch, _state(tmp_path, {}))

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []

    def test_an_agent_below_the_bar_is_not_reported(self, load_script, monkeypatch, tmp_path,
                                                   capsys):
        """Two unanswered commands is a slow agent; three is one that is not going to commit."""
        state = _state(tmp_path, {"/repo": {"marker": 6, "fires": 2}})

        _, rc = _run(load_script, monkeypatch, state)

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []


class TestAtRiskIsReported:
    def test_an_agent_at_the_bar_is_reported_with_what_a_parent_needs(
            self, load_script, monkeypatch, tmp_path, capsys):
        state = _state(tmp_path, {"/repo/wt-a": {
            "marker": 9, "fires": 3, "since": "2026-07-31T12:00:00Z", "session": "sess-7"}})

        _, rc = _run(load_script, monkeypatch, state)

        assert rc == 0
        at_risk = json.loads(capsys.readouterr().out)["atRisk"]
        assert len(at_risk) == 1
        entry = at_risk[0]
        assert entry["project"] == "/repo/wt-a"
        assert entry["unanswered"] == 3
        assert entry["session"] == "sess-7"
        assert entry["since"] == "2026-07-31T12:00:00Z"

    def test_the_old_marker_only_state_is_never_at_risk(self, load_script, monkeypatch,
                                                        tmp_path, capsys):
        """Machines that ran the previous hook have bare integers on disk; they carry no count."""
        state = _state(tmp_path, {"/repo": 9})

        _, rc = _run(load_script, monkeypatch, state)

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []

    def test_every_at_risk_project_is_reported_not_just_the_first(
            self, load_script, monkeypatch, tmp_path, capsys):
        """Parallel subagents are the case this exists for, so one is never the whole answer."""
        state = _state(tmp_path, {
            "/repo/wt-a": {"marker": 9, "fires": 3},
            "/repo/wt-b": {"marker": 7, "fires": 5},
            "/repo/wt-c": {"marker": 6, "fires": 1},
        })

        _, rc = _run(load_script, monkeypatch, state)

        projects = [e["project"] for e in json.loads(capsys.readouterr().out)["atRisk"]]
        assert sorted(projects) == ["/repo/wt-a", "/repo/wt-b"]


class TestItNeverBlocks:
    def test_it_exits_zero_even_when_work_is_at_risk(self, load_script, monkeypatch, tmp_path,
                                                     capsys):
        """Reporting is not gating: a non-zero exit would fail whatever ran it."""
        state = _state(tmp_path, {"/repo": {"marker": 9, "fires": 4}})

        _, rc = _run(load_script, monkeypatch, state)
        capsys.readouterr()

        assert rc == 0

    def test_an_unreadable_state_file_reports_nothing_rather_than_raising(
            self, load_script, monkeypatch, tmp_path, capsys):
        _, rc = _run(load_script, monkeypatch, tmp_path / "does-not-exist.json")

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []


class TestItSurvivesMalformedState:
    """A parent runs this to find out if it is losing work; crashing is the worse failure."""

    def test_a_non_utf8_state_file_reports_nothing_rather_than_exiting_non_zero(
            self, load_script, monkeypatch, tmp_path, capsys):
        state = tmp_path / "state.json"
        state.write_bytes(b"\xff\xfe not utf-8 at all")

        _, rc = _run(load_script, monkeypatch, state)

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []

    def test_a_non_integer_fires_value_is_skipped_rather_than_raising(
            self, load_script, monkeypatch, tmp_path, capsys):
        state = _state(tmp_path, {"/repo": {"marker": 9, "fires": "3"}})

        _, rc = _run(load_script, monkeypatch, state)

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []


class TestFinishedWorkStopsBeingAtRisk:
    """The entry only clears on a later hook run, so a done worktree would stay at risk."""

    def test_a_project_with_nothing_uncommitted_is_not_reported(
            self, load_script, monkeypatch, tmp_path, capsys):
        state = _state(tmp_path, {"/repo": {"marker": 9, "fires": 4}})

        _, rc = _run(load_script, monkeypatch, state, uncommitted=())

        assert rc == 0
        assert json.loads(capsys.readouterr().out)["atRisk"] == []

    def test_a_project_that_still_has_uncommitted_work_is_reported(
            self, load_script, monkeypatch, tmp_path, capsys):
        state = _state(tmp_path, {"/repo": {"marker": 9, "fires": 4}})

        _, rc = _run(load_script, monkeypatch, state, uncommitted=("a.py",))

        assert rc == 0
        assert [e["project"] for e in json.loads(capsys.readouterr().out)["atRisk"]] == ["/repo"]
