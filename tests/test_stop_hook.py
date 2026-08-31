# pylint: disable=redefined-outer-name  # module-local fixture reuse
"""Tests for skills/task/scripts/stop_hook.py.

Covers: no session_id / invalid stdin JSON are no-ops; STARTED -> IN_PROGRESS promotion with a
token checkpoint; the two independent end-of-task nag branches (state.json never updated,
CLAUDE.md over its size budget) each firing on their own and setting their one-shot reminder
flag; the clean/no-nag path when everything is fine; already-sent reminder flags not re-firing;
and `stop_hook_active` suppressing the FINISHED-task enforcement entirely.

Since #141 wired this script through hooks-manifest.json it also covers: the transcript scan
being skipped when no tracked task owns the session and shared when several do; payload fields
read by fallback rather than indexed; `SessionEnd` checkpointing without ever blocking; an
all-zero checkpoint refusing to overwrite a populated one; and the per-session block budget.

No subprocess is involved in this script, so nothing needs mocking there — isolation is purely
about redirecting tracker_lib's module-level path constants (shared across the whole test
session) into tmp_path, and feeding the hook's stdin payload directly.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json
import sys

import pytest
from conftest import _test_write


@pytest.fixture
def stop_hook(tmp_path, load_script, monkeypatch):
    module = load_script("features/common/skills/task/scripts/stop_hook.py")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(module.lib, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module.lib, "DATA_DIR", data_dir)
    monkeypatch.setattr(module.lib, "EXECUTED_TASKS", data_dir / "executed-tasks.json")
    monkeypatch.setattr(module.lib, "TOKEN_USAGE", data_dir / "token-usage.json")
    monkeypatch.setattr(module.lib, "LOCK_FILE", data_dir / ".write.lock")
    monkeypatch.setattr(module.lib, "STATE_JSON", tmp_path / ".ai-badger" / "state.json")
    monkeypatch.setattr(module.lib, "CLAUDE_MD", tmp_path / "CLAUDE.md")
    # Snapshot so nothing here leaks the shared tracker_lib module's budget globals to other
    # test files (see test_claude_md_compact.py's fixture docstring for why this matters).
    monkeypatch.setattr(module.lib, "CLAUDE_MD_MAX_CHARS", module.lib.CLAUDE_MD_MAX_CHARS)
    monkeypatch.setattr(module.lib, "CLAUDE_MD_MAX_LINES", module.lib.CLAUDE_MD_MAX_LINES)
    return module


def _run_hook(module, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def _write_state(module, tasks=None, usage=None):
    module.lib.save_json(module.lib.EXECUTED_TASKS, {"tasks": tasks or []})
    module.lib.save_json(module.lib.TOKEN_USAGE, {"tasks": usage or []})


def test_no_session_id_returns_zero_without_touching_tasks(stop_hook, monkeypatch, capsys):
    rc = _run_hook(stop_hook, monkeypatch, {"transcript_path": "/tmp/x.jsonl"})

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert not stop_hook.lib.EXECUTED_TASKS.exists()


def test_invalid_stdin_json_returns_zero(stop_hook, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))

    assert stop_hook.main() == 0


def test_started_task_promotes_to_in_progress_with_checkpoint(stop_hook, monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _test_write(transcript, "", encoding="utf-8")
    _write_state(
        stop_hook,
        tasks=[{
            "taskId": "T01", "sessionId": "sid-1", "state": "STARTED",
            "startedAt": stop_hook.lib.now_iso(),
        }],
        usage=[{"taskId": "T01", "checkpoints": {}}],
    )

    rc = _run_hook(stop_hook, monkeypatch, {
        "session_id": "sid-1", "transcript_path": str(transcript),
    })

    assert rc == 0
    tasks = stop_hook.lib.load_tasks()
    assert tasks["tasks"][0]["state"] == "IN_PROGRESS"
    usage = stop_hook.lib.load_usage()
    assert "latest" in usage["tasks"][0]["checkpoints"]


def test_finished_task_without_state_json_update_blocks_once(stop_hook, monkeypatch, tmp_path, capsys):
    _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(),
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["decision"] == "block"
    assert "state.json was not updated" in payload["reason"]
    assert "CLAUDE.md" not in payload["reason"]
    entry = stop_hook.lib.load_tasks()["tasks"][0]
    assert entry["stateJsonReminderSent"] is True


def test_finished_task_claude_md_over_budget_blocks_with_compaction_reason(
    stop_hook, monkeypatch, tmp_path, capsys
):
    _test_write(tmp_path / "CLAUDE.md", "x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(), "stateJsonUpdated": True,
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["decision"] == "block"
    assert "over the size budget" in payload["reason"]
    assert "CLAUDE.md" in payload["reason"]
    assert "state.json was not updated" not in payload["reason"]
    entry = stop_hook.lib.load_tasks()["tasks"][0]
    assert entry["compactionReminderSent"] is True


def test_finished_task_reports_every_over_budget_agent_file(
    stop_hook, monkeypatch, tmp_path, capsys
):
    """HERMES.md was 24-26 lines over budget with nothing checking it (F-36)."""
    _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
    _test_write(tmp_path / "HERMES.md", "x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(), "stateJsonUpdated": True,
    }])

    _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "block"
    assert "HERMES.md" in payload["reason"]
    assert "CLAUDE.md" not in payload["reason"]


def test_finished_task_clean_state_produces_no_nag(stop_hook, monkeypatch, tmp_path, capsys):
    _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(), "stateJsonUpdated": True,
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_reminders_already_sent_do_not_nag_again(stop_hook, monkeypatch, tmp_path, capsys):
    _test_write(tmp_path / "CLAUDE.md", "x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(),
        "stateJsonReminderSent": True, "compactionReminderSent": True,
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_stop_hook_active_flag_suppresses_finished_task_enforcement(
    stop_hook, monkeypatch, tmp_path, capsys
):
    _test_write(tmp_path / "CLAUDE.md", "x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(),
    }])

    rc = _run_hook(stop_hook, monkeypatch, {
        "session_id": "sid-1", "transcript_path": "", "stop_hook_active": True,
    })

    assert rc == 0
    assert capsys.readouterr().out == ""
    entry = stop_hook.lib.load_tasks()["tasks"][0]
    assert "stateJsonReminderSent" not in entry


class FakeDebugLog:
    """Captures log_event calls and resolves a project the way debug_log really does."""

    def __init__(self):
        self.calls = []

    def log_event(self, component, event, **fields):
        self.calls.append((component, event, fields))

    def resolve_project_root(self, payload=None):
        return (payload or {}).get("cwd")


def test_debug_logging_records_checkpoint_event(stop_hook, monkeypatch):
    """Debug log fires a checkpoint event when stop completes normally."""
    fake = FakeDebugLog()
    _write_state(
        stop_hook,
        tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                "startedAt": stop_hook.lib.now_iso()}],
        usage=[{"taskId": "T01", "checkpoints": {}}],
    )

    monkeypatch.setattr(stop_hook, "debug_log", fake)
    _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    events = {e: (c, f) for c, e, f in fake.calls}
    assert "checkpoint" in events
    assert events["checkpoint"][0] == "stop_hook"


def test_debug_logging_is_noop_when_unavailable(stop_hook, monkeypatch):
    """Hook runs normally when debug_log is None."""
    monkeypatch.setattr(stop_hook, "debug_log", None)
    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})
    assert rc == 0


def test_the_checkpoint_record_names_the_project(stop_hook, monkeypatch):
    """An unattributed record pools into every project's analysis; see call-behaviorist."""
    fake = FakeDebugLog()
    monkeypatch.setattr(stop_hook, "debug_log", fake)
    _write_state(
        stop_hook,
        tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                "startedAt": stop_hook.lib.now_iso()}],
        usage=[{"taskId": "T01", "checkpoints": {}}],
    )

    _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "cwd": "/repo"})

    assert [(e, f.get("project")) for _, e, f in fake.calls] == [("checkpoint", "/repo")]


def test_the_skip_record_names_the_project_too(stop_hook, monkeypatch):
    """The early exit is the commonest record of all; unattributed it is worse than useless."""
    fake = FakeDebugLog()
    monkeypatch.setattr(stop_hook, "debug_log", fake)

    _run_hook(stop_hook, monkeypatch, {"cwd": "/repo"})

    assert [(e, f.get("project")) for _, e, f in fake.calls] == [("skip", "/repo")]


def _count_transcript_reads(stop_hook, monkeypatch):
    """Replace parse_transcript_usage with a counter; returns the mutable count list."""
    calls = []
    real = stop_hook.lib.parse_transcript_usage

    def counting(transcript_path):
        calls.append(transcript_path)
        return real(transcript_path)

    monkeypatch.setattr(stop_hook.lib, "parse_transcript_usage", counting)
    return calls


class TestTranscriptIsNotScannedGratuitously:
    """`parse_transcript_usage` reads the whole JSONL; this is now a per-turn hook (#141)."""

    def test_no_tracked_task_for_this_session_reads_no_transcript(
        self, stop_hook, monkeypatch, tmp_path
    ):
        transcript = tmp_path / "t.jsonl"
        _test_write(transcript, "", encoding="utf-8")
        reads = _count_transcript_reads(stop_hook, monkeypatch)
        _write_state(stop_hook, tasks=[{
            "taskId": "T01", "sessionId": "other-session", "state": "IN_PROGRESS",
            "startedAt": stop_hook.lib.now_iso(),
        }])

        rc = _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(transcript),
        })

        assert rc == 0
        assert reads == []

    def test_two_tasks_in_one_session_share_a_single_scan(
        self, stop_hook, monkeypatch, tmp_path
    ):
        # Store-legal same-session pair (D14: one ACTIVE task per session); the scan sharing
        # across two *eligible* entries is pinned directly on checkpoint_tasks below.
        transcript = tmp_path / "t.jsonl"
        _test_write(transcript, "", encoding="utf-8")
        reads = _count_transcript_reads(stop_hook, monkeypatch)
        _write_state(
            stop_hook,
            tasks=[
                {"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                 "startedAt": stop_hook.lib.now_iso()},
                {"taskId": "T02", "sessionId": "sid-1", "state": "FINISHED",
                 "startedAt": stop_hook.lib.now_iso()},
            ],
            usage=[{"taskId": "T01", "checkpoints": {}}, {"taskId": "T02", "checkpoints": {}}],
        )

        _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(transcript),
        })

        assert reads == [str(transcript)]

    def test_checkpoint_tasks_parses_once_across_eligible_entries(
        self, stop_hook, monkeypatch, tmp_path
    ):
        """Two unfinished entries in one call cost one transcript scan, not one per entry.

        Reached through the read-only dual-read window, where a pre-migration legacy file can
        still put two ACTIVE entries on one session beside the store's rows.
        """
        transcript = tmp_path / "t.jsonl"
        _test_write(transcript, "", encoding="utf-8")
        reads = _count_transcript_reads(stop_hook, monkeypatch)
        entries = [
            {"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS"},
            {"taskId": "T02", "sessionId": "sid-1", "state": "STARTED"},
        ]
        usage = {"tasks": [
            {"taskId": "T01", "checkpoints": {}}, {"taskId": "T02", "checkpoints": {}}
        ]}

        assert stop_hook.checkpoint_tasks(entries, usage, str(transcript)) is True
        assert reads == [str(transcript)]

    def test_the_skipped_scan_is_recorded_as_a_skip_not_a_checkpoint(
        self, stop_hook, monkeypatch
    ):
        """A `checkpoint` record for a session that checkpointed nothing is a lie the
        behaviorist's health verdict is computed from."""
        fake = FakeDebugLog()
        monkeypatch.setattr(stop_hook, "debug_log", fake)
        _write_state(stop_hook)

        _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "cwd": "/repo"})

        assert [e for _, e, _ in fake.calls] == ["skip"]


class TestPayloadFieldNamesAreNeverIndexed:
    """Hosts and releases disagree on payload spellings; a KeyError-shaped read turns this
    hook into a silent no-op, which is exactly how it stayed unwired for eight versions."""

    def test_camel_case_payload_still_checkpoints(self, stop_hook, monkeypatch, tmp_path):
        transcript = tmp_path / "t.jsonl"
        _test_write(transcript, "", encoding="utf-8")
        _write_state(
            stop_hook,
            tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "STARTED",
                    "startedAt": stop_hook.lib.now_iso()}],
            usage=[{"taskId": "T01", "checkpoints": {}}],
        )

        rc = _run_hook(stop_hook, monkeypatch, {
            "sessionId": "sid-1", "transcriptPath": str(transcript),
        })

        assert rc == 0
        assert stop_hook.lib.load_tasks()["tasks"][0]["state"] == "IN_PROGRESS"
        assert "latest" in stop_hook.lib.load_usage()["tasks"][0]["checkpoints"]

    def test_camel_case_stop_hook_active_still_suppresses_enforcement(
        self, stop_hook, monkeypatch, tmp_path, capsys
    ):
        _test_write(tmp_path / "CLAUDE.md", "x" * 20000, encoding="utf-8")
        _write_state(stop_hook, tasks=[{
            "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
            "startedAt": stop_hook.lib.now_iso(),
        }])

        _run_hook(stop_hook, monkeypatch, {
            "sessionId": "sid-1", "stopHookActive": True,
        })

        assert capsys.readouterr().out == ""
        assert "stateJsonReminderSent" not in stop_hook.lib.load_tasks()["tasks"][0]

    def test_an_unknown_event_spelling_is_treated_as_a_turn_stop(
        self, stop_hook, monkeypatch, tmp_path, capsys
    ):
        """Only `SessionEnd` disables the block channel; anything unrecognised keeps it,
        because losing enforcement silently is the worse failure."""
        _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
        _write_state(stop_hook, tasks=[{
            "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
            "startedAt": stop_hook.lib.now_iso(),
        }])

        _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "hook_event_name": "SomethingNobodyDocumented",
        })

        assert json.loads(capsys.readouterr().out)["decision"] == "block"


class TestSessionEndIsCheckpointOnly:
    """`SessionEnd` reaches the model on no channel at all — no decision control, JSON output
    ignored. It exists here for the final flush `Stop` never sees, and must never pretend to
    enforce."""

    def test_session_end_checkpoints_and_promotes(self, stop_hook, monkeypatch, tmp_path):
        transcript = tmp_path / "t.jsonl"
        _test_write(transcript, "", encoding="utf-8")
        _write_state(
            stop_hook,
            tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "STARTED",
                    "startedAt": stop_hook.lib.now_iso()}],
            usage=[{"taskId": "T01", "checkpoints": {}}],
        )

        rc = _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(transcript),
            "hook_event_name": "SessionEnd",
        })

        assert rc == 0
        assert stop_hook.lib.load_tasks()["tasks"][0]["state"] == "IN_PROGRESS"
        assert "latest" in stop_hook.lib.load_usage()["tasks"][0]["checkpoints"]

    def test_session_end_never_prints_a_block_and_spends_no_one_shot_flag(
        self, stop_hook, monkeypatch, tmp_path, capsys
    ):
        _test_write(tmp_path / "CLAUDE.md", "x" * 20000, encoding="utf-8")
        _write_state(stop_hook, tasks=[{
            "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
            "startedAt": stop_hook.lib.now_iso(),
        }])

        rc = _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "hook_event_name": "SessionEnd",
        })

        assert rc == 0
        assert capsys.readouterr().out == ""
        entry = stop_hook.lib.load_tasks()["tasks"][0]
        assert "stateJsonReminderSent" not in entry
        assert "compactionReminderSent" not in entry


class TestAZeroCheckpointNeverOverwritesAGoodOne:
    """A missing or unreadable transcript yields all zeros; landing that destroys the last
    real measurement. The degenerate `contextTokens: 0, assistantMessages: 3` records in the
    downstream projects are what this guard is for (#141)."""

    GOOD = {
        "timestamp": "2026-07-20T01:26:44Z",
        "contextTokens": 276168,
        "assistantMessages": 896,
        "cumulative": {"inputTokens": 1764, "outputTokens": 814836,
                       "cacheReadTokens": 208585370, "cacheCreationTokens": 2780237},
    }

    def test_a_missing_transcript_leaves_a_populated_checkpoint_alone(
        self, stop_hook, monkeypatch, tmp_path
    ):
        _write_state(
            stop_hook,
            tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                    "startedAt": stop_hook.lib.now_iso()}],
            usage=[{"taskId": "T01", "checkpoints": {"latest": dict(self.GOOD)}}],
        )

        _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(tmp_path / "gone.jsonl"),
        })

        assert stop_hook.lib.load_usage()["tasks"][0]["checkpoints"]["latest"] == self.GOOD

    def test_the_exact_degenerate_shape_seen_downstream_is_refused(
        self, stop_hook, monkeypatch, tmp_path
    ):
        """`contextTokens: 0, assistantMessages: 3`, all-zero cumulative — a message count
        with no tokens behind it measures nothing, so it must not count as data."""
        transcript = tmp_path / "t.jsonl"
        empty_usage = {"input_tokens": 0, "output_tokens": 0,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        _test_write(transcript, "\n".join(
            json.dumps({"type": "assistant", "message": {"usage": empty_usage}})
            for _ in range(3)
        ) + "\n", encoding="utf-8")
        _write_state(
            stop_hook,
            tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                    "startedAt": stop_hook.lib.now_iso()}],
            usage=[{"taskId": "T01", "checkpoints": {"latest": dict(self.GOOD)}}],
        )

        _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(transcript),
        })

        assert stop_hook.lib.load_usage()["tasks"][0]["checkpoints"]["latest"] == self.GOOD

    def test_a_zero_checkpoint_is_still_written_when_there_is_none_yet(
        self, stop_hook, monkeypatch, tmp_path
    ):
        """Refusing the overwrite must not become refusing to record at all."""
        _write_state(
            stop_hook,
            tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                    "startedAt": stop_hook.lib.now_iso()}],
            usage=[{"taskId": "T01", "checkpoints": {}}],
        )

        _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(tmp_path / "gone.jsonl"),
        })

        assert stop_hook.lib.load_usage()["tasks"][0]["checkpoints"]["latest"]["contextTokens"] == 0

    def test_a_real_checkpoint_still_replaces_an_older_real_one(
        self, stop_hook, monkeypatch, tmp_path
    ):
        transcript = tmp_path / "t.jsonl"
        _test_write(transcript, json.dumps({
            "type": "assistant",
            "message": {"usage": {"input_tokens": 10, "output_tokens": 20,
                                  "cache_read_input_tokens": 30,
                                  "cache_creation_input_tokens": 40}},
        }) + "\n", encoding="utf-8")
        _write_state(
            stop_hook,
            tasks=[{"taskId": "T01", "sessionId": "sid-1", "state": "IN_PROGRESS",
                    "startedAt": stop_hook.lib.now_iso()}],
            usage=[{"taskId": "T01", "checkpoints": {"latest": dict(self.GOOD)}}],
        )

        _run_hook(stop_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": str(transcript),
        })

        latest = stop_hook.lib.load_usage()["tasks"][0]["checkpoints"]["latest"]
        assert latest["contextTokens"] == 80
        assert latest["assistantMessages"] == 1


class TestTheBlockBudgetIsFinite:
    """Claude Code stops honouring a Stop hook's block after eight in one session. A ninth
    costs a turn and changes nothing, so the hook counts its own and stops asking."""

    @staticmethod
    def _finished_task(stop_hook, task_id):
        return {"taskId": task_id, "sessionId": "sid-1", "state": "FINISHED",
                "startedAt": stop_hook.lib.now_iso()}

    def test_a_block_increments_the_sessions_counter(self, stop_hook, monkeypatch, tmp_path):
        _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
        _write_state(stop_hook, tasks=[self._finished_task(stop_hook, "T01")])

        _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1"})

        tasks = stop_hook.lib.load_tasks()
        assert tasks[stop_hook.BLOCK_COUNTS_KEY]["sid-1"] == 1

    def test_no_block_is_emitted_once_the_budget_is_spent(
        self, stop_hook, monkeypatch, tmp_path, capsys
    ):
        _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
        _write_state(stop_hook, tasks=[self._finished_task(stop_hook, "T01")])
        tasks = stop_hook.lib.load_tasks()
        tasks[stop_hook.BLOCK_COUNTS_KEY] = {"sid-1": stop_hook.MAX_BLOCKS_PER_SESSION}
        stop_hook.lib.save_json(stop_hook.lib.EXECUTED_TASKS, tasks)

        rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1"})

        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_an_unspent_one_shot_flag_survives_a_refused_block(
        self, stop_hook, monkeypatch, tmp_path
    ):
        """The reminder is worth sending later; burning its one shot on a block the platform
        will ignore throws the message away."""
        _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
        _write_state(stop_hook, tasks=[self._finished_task(stop_hook, "T01")])
        tasks = stop_hook.lib.load_tasks()
        tasks[stop_hook.BLOCK_COUNTS_KEY] = {"sid-1": stop_hook.MAX_BLOCKS_PER_SESSION}
        stop_hook.lib.save_json(stop_hook.lib.EXECUTED_TASKS, tasks)

        _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1"})

        assert "stateJsonReminderSent" not in stop_hook.lib.load_tasks()["tasks"][0]

    def test_another_sessions_spent_budget_does_not_gag_this_one(
        self, stop_hook, monkeypatch, tmp_path, capsys
    ):
        _test_write(tmp_path / "CLAUDE.md", "short\n", encoding="utf-8")
        _write_state(stop_hook, tasks=[self._finished_task(stop_hook, "T01")])
        tasks = stop_hook.lib.load_tasks()
        tasks[stop_hook.BLOCK_COUNTS_KEY] = {"other": stop_hook.MAX_BLOCKS_PER_SESSION}
        stop_hook.lib.save_json(stop_hook.lib.EXECUTED_TASKS, tasks)

        _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1"})

        assert json.loads(capsys.readouterr().out)["decision"] == "block"
