"""The tracking-state guard names who wrote, instead of blaming whoever is nearest.

`_real_tracking_state_is_untouched` snapshots `.ai-badger/task-tracking/` before and after the
whole session and fails if anything changed. That is the right invariant and the wrong evidence:
a `*/30` resume cron or a `poll_limit.py` daemon left over from an earlier session writes into
that directory too, and the fixture attributes it to the suite.

It failed a pre-push lane four times on 2026-08-01, on runs where the suite was clean — twice
confirmed by re-running immediately and getting a green suite with no error. The cost is not the
lost minutes. It is that a real leak and a passing cron tick produce the same message, so the
learned response becomes "re-run until green", which is exactly how #222's leak survived.

So the suite marks its own writes, the way #232 marked its own spawns: `save_json` records a
breadcrumb when `AI_BADGER_REAL_WRITE_LOG` is set and the destination is inside the real
checkout. An external daemon inherits no such variable, so its writes are unmarked — and
unmarked changes are reported without failing, while a marked one names the test and fails.
"""
from __future__ import annotations

import json
import os

import pytest


def _tracker(load_script):
    return load_script("features/common/skills/task/scripts/tracker_lib.py")


class TestTheMarkerIsInertByDefault:
    """Production must not pay for a diagnostic the suite asked for."""

    def test_nothing_is_written_when_the_variable_is_unset(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        monkeypatch.delenv("AI_BADGER_REAL_WRITE_LOG", raising=False)
        log = tmp_path / "writes.jsonl"

        tracker.save_json(tmp_path / "somewhere.json", {"a": 1})

        assert not log.exists()

    def test_the_save_still_happens_when_the_variable_is_set(
        self, tmp_path, load_script, monkeypatch
    ):
        """The marker observes; it must never prevent."""
        tracker = _tracker(load_script)
        monkeypatch.setenv("AI_BADGER_REAL_WRITE_LOG", str(tmp_path / "writes.jsonl"))
        target = tmp_path / "payload.json"

        tracker.save_json(target, {"a": 1})

        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


class TestOnlyWritesInsideTheRealCheckoutAreMarked:
    """Every test writes tracking state — into a scratch project or a tmpdir, which is fine.

    Marking those drowns the signal, and the first draft did exactly that: it compared against
    CLAUDE_PROJECT_DIR, which tests monkeypatch freely, so a full run flagged four legitimate
    writes into pytest tmpdirs. The invariant is about the real checkout and nothing else.
    """

    def test_a_write_outside_the_real_checkout_is_not_marked(
        self, tmp_path, load_script, monkeypatch
    ):
        tracker = _tracker(load_script)
        real = tmp_path / "real-checkout"
        real.mkdir()
        log = tmp_path / "writes.jsonl"
        monkeypatch.setenv("AI_BADGER_REAL_WRITE_LOG", str(log))
        monkeypatch.setenv("AI_BADGER_REAL_ROOT", str(real))

        tracker.save_json(tmp_path / "scratch-elsewhere.json", {"a": 1})

        assert not log.exists()

    def test_a_write_inside_the_real_checkout_is_marked(
        self, tmp_path, load_script, monkeypatch
    ):
        tracker = _tracker(load_script)
        real = tmp_path / "real-checkout"
        real.mkdir()
        log = tmp_path / "writes.jsonl"
        monkeypatch.setenv("AI_BADGER_REAL_WRITE_LOG", str(log))
        monkeypatch.setenv("AI_BADGER_REAL_ROOT", str(real))

        tracker.save_json(real / "escaped.json", {"a": 1})

        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
        assert record["path"].endswith("escaped.json")
        assert record["pid"] == os.getpid()

    def test_the_marker_names_the_test_that_wrote(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        real = tmp_path / "real-checkout"
        real.mkdir()
        log = tmp_path / "writes.jsonl"
        monkeypatch.setenv("AI_BADGER_REAL_WRITE_LOG", str(log))
        monkeypatch.setenv("AI_BADGER_REAL_ROOT", str(real))

        tracker.save_json(real / "escaped.json", {"a": 1})

        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
        assert "test_the_marker_names_the_test_that_wrote" in record["test"]


class TestABrokenMarkerNeverBreaksTheSave:
    """Same rule as #232's breadcrumb: a diagnostic does not get to fail what it observes."""

    def test_an_unwritable_marker_path_does_not_raise(self, tmp_path, load_script, monkeypatch):
        tracker = _tracker(load_script)
        monkeypatch.setenv(
            "AI_BADGER_REAL_WRITE_LOG", str(tmp_path / "nope" / "deeper" / "writes.jsonl")
        )
        monkeypatch.setenv("AI_BADGER_REAL_ROOT", str(tmp_path))
        target = tmp_path / "payload.json"

        tracker.save_json(target, {"a": 1})

        assert target.is_file()

    def test_an_unset_project_dir_does_not_raise(self, tmp_path, load_script, monkeypatch):
        """Outside the suite CLAUDE_PROJECT_DIR may be absent; that must not matter."""
        tracker = _tracker(load_script)
        monkeypatch.setenv("AI_BADGER_REAL_WRITE_LOG", str(tmp_path / "writes.jsonl"))
        monkeypatch.delenv("AI_BADGER_REAL_ROOT", raising=False)
        target = tmp_path / "payload.json"

        tracker.save_json(target, {"a": 1})

        assert target.is_file()


class TestTheFixtureSeparatesTheTwo:
    """The whole point: a marked change fails, an unmarked one is reported and does not."""

    def test_a_marked_change_is_attributed_to_its_test(self, tmp_path):
        import conftest

        log = tmp_path / "writes.jsonl"
        log.write_text(
            json.dumps({"path": "/repo/.ai-badger/task-tracking/executed-tasks.json",
                        "pid": 1, "test": "tests/test_leaky.py::test_it (call)"}) + "\n",
            encoding="utf-8",
        )

        assert conftest.suite_attributed_writes(log) == [
            "tests/test_leaky.py::test_it (call) -> "
            "/repo/.ai-badger/task-tracking/executed-tasks.json"
        ]

    def test_an_absent_log_attributes_nothing(self, tmp_path):
        import conftest

        assert conftest.suite_attributed_writes(tmp_path / "never-written.jsonl") == []

    def test_a_torn_line_does_not_stop_the_report(self, tmp_path):
        """Written by several processes; teardown must report rather than crash."""
        import conftest

        log = tmp_path / "writes.jsonl"
        log.write_text(
            '{"path": "/a", "pid": 1, "test": "t_one"}\n'
            '{"path": "/b", "pid": 2, "test": "t_tw\n'
            '{"path": "/c", "pid": 3, "test": "t_three"}\n',
            encoding="utf-8",
        )

        offenders = conftest.suite_attributed_writes(log)

        assert any("t_one" in o for o in offenders)
        assert any("t_three" in o for o in offenders)


class TestTheSuiteArmsIt:
    def test_the_run_has_the_variable_set(self):
        assert os.environ.get("AI_BADGER_REAL_WRITE_LOG"), (
            "conftest must point AI_BADGER_REAL_WRITE_LOG at a scratch file for the session"
        )

    def test_both_sides_spell_the_variable_the_same(self, load_script):
        import conftest

        assert _tracker(load_script).REAL_WRITE_LOG_ENV == conftest.REAL_WRITE_LOG_ENV


class TestTheOtherWritePathIsMarkedToo:
    """save_json is not the only way a suite process touches real tracking state.

    `locked_store` opens LOCK_FILE for writing, and `.write.lock` was one of the three files
    changing on the runs this fixture blamed the suite for. Marking only save_json would leave
    a leak through the lock path reported as a note instead of a failure.
    """

    def test_taking_the_lock_inside_the_real_checkout_is_marked(
        self, tmp_path, load_script, monkeypatch
    ):
        tracker = _tracker(load_script)
        log = tmp_path / "writes.jsonl"
        monkeypatch.setenv("AI_BADGER_REAL_WRITE_LOG", str(log))
        monkeypatch.setenv("AI_BADGER_REAL_ROOT", str(tmp_path))
        monkeypatch.setattr(tracker, "LOCK_FILE", tmp_path / "real" / ".write.lock")
        monkeypatch.setattr(tracker, "DATA_DIR", tmp_path / "real")

        with tracker.locked_store():
            pass

        assert ".write.lock" in log.read_text(encoding="utf-8")
