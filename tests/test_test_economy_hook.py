"""Tests for skills/test-economy/scripts/suite_economy_hook.py (PostToolUse hook).

Covers the early-exit gates (non-shell tool, no command, not a test run), the counting
end-to-end through stdin/stdout (silent under the budget, nudge on the run past it,
escalation past the bar), the malformed-input and internal-error paths, both
`tool_name`/`toolName` payload key spellings, and that the emitted JSON is advisory-only:
`additionalContext` only, never `decision`/`permissionDecision`/`continue` on any code path.
"""
from __future__ import annotations

import io
import json
import threading

import pytest


HOOK_PATH = "features/common/skills/test-economy/scripts/suite_economy_hook.py"


@pytest.fixture(autouse=True)
def _no_project_dir_env(monkeypatch):
    """conftest points CLAUDE_PROJECT_DIR at a scratch project (#222 isolation); these
    tests key their stub store by the payload's cwd, so the env override must go — except
    in the test that proves the env wins."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


def _load(load_script):
    return load_script(HOOK_PATH)


def _run_main(module, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def _payload(tool_name="Bash", cwd="/repo", command="pytest", session="sess-1"):
    return {"tool_name": tool_name, "cwd": cwd, "session_id": session,
            "tool_input": {"command": command}}


def _stub_entry_store(module, monkeypatch):
    """Replace persisted-entry I/O with an in-memory dict, keyed like the real functions.

    `update_entry` is the one the hook itself calls; it is faked here atop the same
    `get_entry`/`set_entry`/`advance_session` so a test that only cares about the ratchet's
    outward behaviour need not know the storage call is now a single atomic round trip.
    """
    store: dict = {}

    def fake_get_entry(root):
        return json.loads(json.dumps(store.get(root, {"sessions": {}})))

    def fake_set_entry(root, entry):
        store[root] = json.loads(json.dumps(entry))

    def fake_update_entry(root, session, is_full, now="", max_full=None, escalate_at=None):
        fires, escalated, updated = module.suite_economy.advance_session(
            fake_get_entry(root), session, is_full, now=now,
            max_full=max_full, escalate_at=escalate_at)
        fake_set_entry(root, updated)
        return fires, escalated, updated

    monkeypatch.setattr(module.suite_economy, "get_entry", fake_get_entry)
    monkeypatch.setattr(module.suite_economy, "set_entry", fake_set_entry)
    monkeypatch.setattr(module.suite_economy, "update_entry", fake_update_entry)
    return store


def _captured(module, monkeypatch, capsys, payload, gates=None):
    """Run the hook once; return (rc, decoded stdout payload or None). Gates stubbed out."""
    monkeypatch.setattr(module.suite_economy, "detect_local_gates", lambda root: gates or [])
    rc = _run_main(module, monkeypatch, payload)
    out = capsys.readouterr().out.strip()
    return rc, (json.loads(out) if out else None)


def _run_n(module, monkeypatch, capsys, n, **payload_kwargs):
    """Run the hook n times with the same payload shape; return the last (rc, out)."""
    result = (None, None)
    for _ in range(n):
        result = _captured(module, monkeypatch, capsys, _payload(**payload_kwargs))
    return result


def test_silent_while_full_runs_stay_under_the_budget(load_script, monkeypatch, capsys):
    module = _load(load_script)
    store = _stub_entry_store(module, monkeypatch)
    rc, out = _run_n(module, monkeypatch, capsys, 2)
    assert rc == 0 and out is None
    assert store["/repo"]["sessions"]["sess-1"]["full"] == 2


def test_third_full_run_fires_the_nudge(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    rc, out = _run_n(module, monkeypatch, capsys, 3)
    assert rc == 0 and out is not None
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "full-suite run #3" in context
    assert "pytest" in context


def test_advisory_only_never_blocks(load_script, monkeypatch, capsys):
    """The 0.33.0 rule: no decision/permissionDecision/continue on any code path."""
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    rc, out = _run_n(module, monkeypatch, capsys, 3)
    assert rc == 0
    assert "decision" not in out
    assert "permissionDecision" not in out
    assert "continue" not in out
    assert set(out["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}


def test_escalation_past_the_bar(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    rc, out = _run_n(module, monkeypatch, capsys, 6)
    assert out is not None
    assert "STOP" in out["hookSpecificOutput"]["additionalContext"]


def test_filtered_runs_stay_silent(load_script, monkeypatch, capsys):
    module = _load(load_script)
    store = _stub_entry_store(module, monkeypatch)
    result = (None, None)
    for _ in range(10):
        result = _captured(module, monkeypatch, capsys,
                           _payload(command="pytest tests/test_x.py"))
    rc, out = result
    assert out is None
    assert store["/repo"]["sessions"]["sess-1"]["filtered"] == 10


def test_counts_are_per_session(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    for _ in range(3):
        rc, out = _captured(module, monkeypatch, capsys, _payload(session="s"))
    rc, out = _captured(module, monkeypatch, capsys, _payload(session="fresh"))
    assert out is None, "a fresh session starts with its own budget"


def test_missing_session_id_shares_the_default_bucket(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    payload = _payload()
    payload.pop("session_id")
    for _ in range(3):
        rc, out = _captured(module, monkeypatch, capsys, dict(payload))
    assert out is not None


def test_gate_wiring_reaches_the_message(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    for _ in range(3):
        rc, out = _captured(module, monkeypatch, capsys, _payload(), gates=["lefthook"])
    assert "lefthook" in out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("payload,reason", [
    ({"tool_name": "Edit", "cwd": "/repo", "tool_input": {"file_path": "/repo/a.py"}}, "not_shell"),
    ({"tool_name": "Bash", "cwd": "/repo", "tool_input": {}}, "no_command"),
    ({"tool_name": "Bash", "cwd": "/repo", "tool_input": {"command": "git status"}},
     "not_a_test_run"),
    ({"tool_name": "Bash", "tool_input": {"command": "pytest"}}, "no_root"),
])
def test_early_exits_are_silent(load_script, monkeypatch, capsys, payload, reason):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    rc, out = _captured(module, monkeypatch, capsys, payload)
    assert rc == 0 and out is None, reason


def test_tool_name_camel_case_key_is_recognized(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    payload = {"toolName": "Bash", "cwd": "/repo", "tool_input": {"command": "pytest"},
               "session_id": "s"}
    for _ in range(3):
        rc, out = _captured(module, monkeypatch, capsys, dict(payload))
    assert out is not None


def test_claude_project_dir_wins_over_payload_cwd(load_script, monkeypatch, capsys):
    module = _load(load_script)
    store = _stub_entry_store(module, monkeypatch)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/env-root")
    for _ in range(3):
        rc, out = _captured(module, monkeypatch, capsys, _payload(cwd="/payload-root"))
    assert "/env-root" in store

def test_malformed_stdin_is_silent(load_script, monkeypatch, capsys):
    module = _load(load_script)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    rc = module.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_non_dict_payload_is_silent(load_script, monkeypatch, capsys):
    module = _load(load_script)
    monkeypatch.setattr("sys.stdin", io.StringIO("[1,2,3]"))
    rc = module.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


# --------------------------------------------------- hookEventName echo (R11)


def test_hook_event_name_defaults_to_post_tool_use(load_script, monkeypatch, capsys):
    """No `hook_event_name` in the payload (Claude's real PostToolUse input never carries
    one back out): the echo still defaults to PostToolUse."""
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    result = (None, None)
    for _ in range(3):
        result = _captured(module, monkeypatch, capsys, _payload())
    rc, out = result
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_hook_echoes_the_incoming_hook_event_name(load_script, monkeypatch, capsys):
    module = _load(load_script)
    _stub_entry_store(module, monkeypatch)
    payload = _payload()
    payload["hook_event_name"] = "PostToolUseFailure"
    result = (None, None)
    for _ in range(3):
        result = _captured(module, monkeypatch, capsys, dict(payload))
    rc, out = result
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"


# --------------------------------------------------- PostToolUseFailure arm (D13 = A)


def test_post_tool_use_failure_payload_of_a_failing_run_is_counted(load_script, monkeypatch,
                                                                     capsys):
    """Claude's PostToolUse never sees a failed Bash call; a failing full-suite run must
    still count toward the budget via the PostToolUseFailure arm (hooks-manifest.json:
    test-run-economy-failure)."""
    module = _load(load_script)
    store = _stub_entry_store(module, monkeypatch)
    result = (None, None)
    for _ in range(3):
        payload = _payload()
        payload["hook_event_name"] = "PostToolUseFailure"
        result = _captured(module, monkeypatch, capsys, payload)
    rc, out = result
    assert out is not None, "a failing pytest run must still count"
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"
    assert store["/repo"]["sessions"]["sess-1"]["full"] == 3


# --------------------------------------------------- lost update (L4-8, R24)


class TestConcurrentInvocationsDoNotLoseAnUpdate:
    """Two separate get_entry/set_entry calls race two invocations across the read-write
    gap. The fix routes the per-session update through the store's own atomic `kv_update`
    (suite_economy.update_entry), so a concurrent call blocks on the write lock instead of
    computing from the same stale entry."""

    def test_two_concurrent_full_runs_on_the_same_project_both_survive(
            self, tmp_path, load_script, monkeypatch):
        module = _load(load_script)
        monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
        root = str(tmp_path / "repo")

        real_advance_session = module.suite_economy.advance_session
        first_entered = threading.Event()
        release_first = threading.Event()
        calls = {"n": 0}

        def once_blocking_advance_session(entry, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                first_entered.set()
                assert release_first.wait(timeout=5), "the first update was never released"
            return real_advance_session(entry, *args, **kwargs)

        monkeypatch.setattr(module.suite_economy, "advance_session",
                            once_blocking_advance_session)

        def run_first():
            module.suite_economy.update_entry(root, "s1", True, now="t1")

        def run_second():
            module.suite_economy.update_entry(root, "s2", True, now="t2")

        first = threading.Thread(target=run_first)
        first.start()
        assert first_entered.wait(timeout=5), "the first update never reached advance_session()"

        second_done = threading.Event()
        second = threading.Thread(target=lambda: (run_second(), second_done.set()))
        second.start()
        assert not second_done.wait(timeout=0.3), (
            "the second update must block behind the first's still-open transaction, "
            "not race ahead of it")

        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)

        entry = module.suite_economy.get_entry(root)
        totals = {s: row["full"] for s, row in entry["sessions"].items()}
        assert totals == {"s1": 1, "s2": 1}, "both concurrent increments must survive"


def test_internal_error_never_breaks_the_session(load_script, monkeypatch, capsys, tmp_path):
    """A hook never breaks the session, but never fails invisibly either: guarded_main
    swallows the exception and leaves one content-free line in the error log."""
    module = _load(load_script)
    errors = tmp_path / "hook-errors.log"
    monkeypatch.setattr(module, "HOOK_ERRORS_FILE", errors)

    def explode():
        raise RuntimeError("broken test economy")

    monkeypatch.setattr(module, "main", explode)
    rc = module.guarded_main()

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert "test_economy_hook" in errors.read_text(encoding="utf-8")
