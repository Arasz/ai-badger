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
    """Replace persisted-entry I/O with an in-memory dict, keyed like the real functions."""
    store: dict = {}

    def fake_get_entry(root):
        return json.loads(json.dumps(store.get(root, {"sessions": {}})))

    def fake_set_entry(root, entry):
        store[root] = json.loads(json.dumps(entry))

    monkeypatch.setattr(module.suite_economy, "get_entry", fake_get_entry)
    monkeypatch.setattr(module.suite_economy, "set_entry", fake_set_entry)
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
