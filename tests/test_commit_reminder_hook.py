"""Tests for skills/commit-reminder/scripts/commit_reminder_hook.py (PostToolUse hook).

Covers the early-exit gates (non-edit tool, unresolved project root), the debounce ratchet
end-to-end through stdin/stdout (fires once per threshold-crossing, re-arms after the marker
drops), the malformed-input and internal-error paths, both `tool_name`/`toolName` payload key
spellings, and that the emitted JSON is advisory-only: `additionalContext` only, never
`decision`/`permissionDecision`/`continue` on any code path.
"""
from __future__ import annotations

import io
import json
import sqlite3
import threading


HOOK_PATH = "features/common/skills/commit-reminder/scripts/commit_reminder_hook.py"


def _load(load_script):
    return load_script(HOOK_PATH)


def _run_main(module, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def _payload(tool_name="Edit", cwd="/repo"):
    return {"tool_name": tool_name, "cwd": cwd, "tool_input": {"file_path": "/repo/a.py"}}


def _stub_entry_store(module, monkeypatch):
    """Replace persisted-entry I/O with an in-memory dict, keyed like the real functions.

    `update_entry` is the one the hook itself calls; it is faked here atop the same
    `get_entry`/`set_entry`/`advance` so a test that only cares about the ratchet's outward
    behaviour need not know the storage call is now a single atomic round trip.
    """
    store: dict = {}

    def fake_get_entry(root):
        return dict(store.get(root, {"marker": 0, "fires": 0}))

    def fake_set_entry(root, entry):
        store[root] = dict(entry)

    def fake_update_entry(root, count, threshold=5,
                          escalate_after=module.commit_reminder.ESCALATE_AFTER,
                          now="", session=""):
        fires, at_risk, updated = module.commit_reminder.advance(
            fake_get_entry(root), count, threshold, escalate_after, now=now, session=session)
        fake_set_entry(root, updated)
        return fires, at_risk, updated

    monkeypatch.setattr(module.commit_reminder, "get_entry", fake_get_entry)
    monkeypatch.setattr(module.commit_reminder, "set_entry", fake_set_entry)
    monkeypatch.setattr(module.commit_reminder, "update_entry", fake_update_entry)
    return store


def _stub_uncommitted_files(module, monkeypatch, count):
    files = [f"file{i}.py" for i in range(count)]
    monkeypatch.setattr(module.commit_reminder, "uncommitted_files", lambda root: files)
    return files


def _all_keys(obj):
    """Flatten every dict key anywhere in a parsed JSON object, for a blanket assertion."""
    keys = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for value in obj.values():
            keys.update(_all_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_all_keys(item))
    return keys


def test_non_edit_tool_never_checks_git(load_script, monkeypatch, capsys):
    hook = _load(load_script)

    def explode(root):
        raise AssertionError("uncommitted_files must not be called for a non-edit tool")

    monkeypatch.setattr(hook.commit_reminder, "uncommitted_files", explode)

    rc = _run_main(hook, monkeypatch, _payload(tool_name="Bash"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_below_threshold_is_silent(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 4)

    rc = _run_main(hook, monkeypatch, _payload())

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_crossing_threshold_fires_advisory_only(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 5)

    rc = _run_main(hook, monkeypatch, _payload())

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    message = out["hookSpecificOutput"]["additionalContext"]
    assert "5" in message
    assert isinstance(message, str) and message
    forbidden = {"decision", "permissionDecision", "continue"}
    assert _all_keys(out) & forbidden == set()


def test_same_count_again_is_debounced(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 5)

    _run_main(hook, monkeypatch, _payload())
    capsys.readouterr()
    rc = _run_main(hook, monkeypatch, _payload())

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_ratchet_down_then_up_fires_again(load_script, monkeypatch, capsys):
    """The single most load-bearing case: a commit must re-arm the debounce, not trap it."""
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)

    _stub_uncommitted_files(hook, monkeypatch, 5)
    _run_main(hook, monkeypatch, _payload())
    capsys.readouterr()

    _stub_uncommitted_files(hook, monkeypatch, 1)  # a commit happened
    rc = _run_main(hook, monkeypatch, _payload())
    assert rc == 0
    assert capsys.readouterr().out == ""

    _stub_uncommitted_files(hook, monkeypatch, 6)  # crosses the threshold again
    rc = _run_main(hook, monkeypatch, _payload())
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "6" in out["hookSpecificOutput"]["additionalContext"]


def test_malformed_stdin_not_json_is_silent(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_malformed_stdin_json_array_is_silent(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([1, 2, 3])))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_tool_name_key_is_recognized(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 5)

    rc = _run_main(hook, monkeypatch, {"tool_name": "Edit", "cwd": "/repo"})

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "5" in out["hookSpecificOutput"]["additionalContext"]


def test_tool_name_camel_case_key_is_recognized(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 5)

    rc = _run_main(hook, monkeypatch, {"toolName": "Edit", "cwd": "/repo"})

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "5" in out["hookSpecificOutput"]["additionalContext"]


def test_internal_error_is_recorded_somewhere(tmp_path, load_script, monkeypatch, capsys):
    hook = _load(load_script)
    errors = tmp_path / "hook-errors.log"
    monkeypatch.setattr(hook, "HOOK_ERRORS_FILE", errors)

    def explode():
        raise RuntimeError("broken commit reminder")

    monkeypatch.setattr(hook, "main", explode)

    rc = hook.guarded_main()

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert "commit_reminder_hook" in errors.read_text(encoding="utf-8")


def test_debug_logging_checked_and_fire_events(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 5)

    calls = []

    class FakeDebugLog:
        def log_event(self, component, event, project=None, session=None, **fields):
            calls.append((component, event, fields))

    monkeypatch.setattr(hook, "debug_log", FakeDebugLog())

    _run_main(hook, monkeypatch, _payload())
    capsys.readouterr()

    events = {event: (component, fields) for component, event, fields in calls}
    assert "checked" in events
    assert events["checked"][0] == "commit_reminder_hook"
    assert events["checked"][1]["count"] == 5
    assert events["checked"][1]["threshold"] == 5
    assert "fire" in events
    assert events["fire"][0] == "commit_reminder_hook"
    assert events["fire"][1]["count"] == 5


def test_debug_logging_is_a_true_noop_when_debug_log_unavailable(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 5)
    monkeypatch.setattr(hook, "debug_log", None)

    rc = _run_main(hook, monkeypatch, _payload())

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "5" in out["hookSpecificOutput"]["additionalContext"]


def test_threshold_env_var_override_is_honored(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 2)
    monkeypatch.setenv("AI_BADGER_COMMIT_REMINDER_THRESHOLD", "2")

    rc = _run_main(hook, monkeypatch, _payload())

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "2" in out["hookSpecificOutput"]["additionalContext"]


def test_non_numeric_threshold_env_var_falls_back_to_default(load_script, monkeypatch, capsys):
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)
    _stub_uncommitted_files(hook, monkeypatch, 4)
    monkeypatch.setenv("AI_BADGER_COMMIT_REMINDER_THRESHOLD", "not-a-number")

    rc = _run_main(hook, monkeypatch, _payload())

    assert rc == 0
    assert capsys.readouterr().out == ""  # 4 < default threshold of 5


def test_no_project_root_is_silent(load_script, monkeypatch, capsys):
    hook = _load(load_script)

    def explode(root):
        raise AssertionError("uncommitted_files must not be called when root can't be resolved")

    monkeypatch.setattr(hook.commit_reminder, "uncommitted_files", explode)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    rc = _run_main(hook, monkeypatch, {"tool_name": "Edit"})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_three_unanswered_commands_escalate_through_main(load_script, monkeypatch, capsys):
    """The escalation must be wired into the hook, not just correct in the logic module.

    Without this, mutating the `fires` argument at the call site left the whole suite green.
    """
    hook = _load(load_script)
    _stub_entry_store(hook, monkeypatch)

    messages = []
    for count in (5, 6, 7):
        _stub_uncommitted_files(hook, monkeypatch, count)
        _run_main(hook, monkeypatch, _payload())
        messages.append(json.loads(capsys.readouterr().out)["hookSpecificOutput"]
                        ["additionalContext"])

    assert messages[0].startswith("[ai-badger] Commit now")
    assert messages[1].startswith("[ai-badger] Commit now")
    assert "STOP AND COMMIT" in messages[2]
    assert "after 3 commands" in messages[2], "the count reaching the message must be live"


class TestTheHookStaysFailOpenOnABrokenStore:
    """AC1 gives the report a strict reader; this hook must keep the fail-open default (R26)."""

    def test_guarded_main_exits_zero_with_no_traceback_when_the_store_cannot_open(
            self, tmp_path, load_script, monkeypatch, capsys):
        hook = _load(load_script)
        errors = tmp_path / "hook-errors.log"
        monkeypatch.setattr(hook, "HOOK_ERRORS_FILE", errors)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload())))

        def _boom(*_a, **_k):
            raise sqlite3.OperationalError("disk I/O error")
        monkeypatch.setattr(hook.commit_reminder.badger_store, "open_user", _boom)

        rc = hook.guarded_main()

        assert rc == 0
        assert capsys.readouterr().out == ""


class TestConcurrentInvocationsDoNotLoseAnUpdate:
    """L4-8: separate get_entry/set_entry calls race two invocations across the read-write gap."""

    def test_two_concurrent_updates_on_the_same_project_both_survive(
            self, tmp_path, load_script, monkeypatch):
        """Two edits land close together and each cross a new threshold (5, then 6 files).

        Racing from the same stale entry, both would compute `fires=1` from marker 0 and the
        last write would win: one crossing lost. Serialized, the second sees the first's
        marker (5) and 6 > 5 still counts as a fresh crossing, so both survive.
        """
        hook = _load(load_script)
        monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
        root = str(tmp_path / "repo")

        real_advance = hook.commit_reminder.advance
        first_entered = threading.Event()
        release_first = threading.Event()
        calls = {"n": 0}

        def once_blocking_advance(entry, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                first_entered.set()
                assert release_first.wait(timeout=5), "the first update was never released"
            return real_advance(entry, *args, **kwargs)

        monkeypatch.setattr(hook.commit_reminder, "advance", once_blocking_advance)

        def run_first():
            hook.commit_reminder.update_entry(root, 5, 5, 3, now="T1", session="s1")

        def run_second():
            hook.commit_reminder.update_entry(root, 6, 5, 3, now="T2", session="s2")

        first = threading.Thread(target=run_first)
        first.start()
        assert first_entered.wait(timeout=5), "the first update never reached advance()"

        second_done = threading.Event()
        second = threading.Thread(target=lambda: (run_second(), second_done.set()))
        second.start()
        assert not second_done.wait(timeout=0.3), (
            "the second update must block behind the first's still-open transaction, "
            "not race ahead of it")

        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)

        entry = hook.commit_reminder.get_entry(root)
        assert entry["fires"] == 2, "both concurrent fires must survive, not just one"
