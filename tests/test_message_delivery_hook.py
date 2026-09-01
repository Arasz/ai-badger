# pylint: disable=redefined-outer-name  # pytest fixtures reuse param names by design
"""Tests for features/common/hooks/message_delivery_hook.py (P4, aib-user-db-message-bus).

The shared delivery hook: one script, the Claude-shaped hook contract (``{hook_event_name,
session_id, cwd}`` on stdin, ``hookSpecificOutput.additionalContext`` JSON on stdout),
consumed by Claude (UserPromptSubmit/SessionStart/SessionEnd), Copilot
(userPromptSubmitted/sessionStart), and pi via the adapter's child-process bridge.

Test map (plan aib-user-db-message-bus §3 P4 · spec rules in parentheses):
  A. Render/response contract (F4, P9-t1) ...... test_render_is_one_schema_conformant_document_per_line,
                                                  test_render_preserves_order_content_and_timestamp_verbatim,
                                                  test_response_is_additionalcontext_only_advisory
  B. SessionStart history (Rules 4+5) .......... test_session_start_injects_recent_history_and_gates_the_ancient,
                                                  test_session_start_caps_at_sixteen_and_never_redelivers_overflow,
                                                  test_session_start_on_a_session_with_a_cursor_is_a_live_read
  C. Per-turn live (Rule 4 scenario 4, D5) ..... test_per_turn_delivery_is_live_after_the_first_read,
                                                  test_cursorless_per_turn_read_applies_the_gate_once
  D. Addressing + suppression (Rules 2+8) ...... test_self_suppression_reaches_the_script_surface,
                                                  test_subdirectory_cwd_resolves_to_the_project_via_the_resolver
  E. SessionEnd (Rule 6) ....................... test_session_end_removes_the_cursor,
                                                  test_session_end_for_unknown_session_is_harmless
  F. Fail-open (D31/D7) ........................ test_malformed_stdin_is_a_no_op,
                                                  test_corrupt_user_db_fails_open,
                                                  test_registry_explosion_fails_open,
                                                  test_unresolved_project_still_delivers_one_to_one,
                                                  test_ambiguous_project_still_delivers_one_to_one,
                                                  test_missing_session_id_is_a_clean_no_op,
                                                  test_unknown_event_is_a_clean_no_op
  G. Chain-drop guard (Rule 7 sc.3, half 1) .... test_every_termination_path_emits_parseable_json_and_exits_zero
  H. No-drop read→response (plan t6) ........... test_the_store_document_list_is_what_stdout_carries
  I. Multi-harness reuse + deployment shape .... test_copilot_event_spellings_deliver,
                                                  test_standalone_invocation_via_subprocess

Deterministic mechanisms: all fixtures are env-redirected (AI_BADGER_USER_ROOT moves the
user DB; identity is a planted .ai-badger/project-id per ADR-0025 — the real ~/.ai-badger/
store is never touched), timestamps come from real send_message stamps
(no sleeps, no clock freezing needed at this layer: the gate boundaries are store-pinned
in tests/test_message_bus_store.py, these tests pin the event→behaviour mapping).

Mutation docstrings name the change each test must kill (§D discipline); the run table
lives in the lane report.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import badger_store
from conftest import ROOT

HOOK_PATH = "features/common/hooks/message_delivery_hook.py"

PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"
USER_ROOT_ENV = "AI_BADGER_USER_ROOT"
HOLD_ENV = "AI_BADGER_TEST_HOLD"
HOLD_ARMED_ENV = "AI_BADGER_TEST_HOLD_ARMED"
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"

#: A delivered document exactly as the store returns it — schema-valid per F4.
SENTINEL_DOC = {
    "sender": {"sessionId": "S1", "projectId": "P"},
    "content": "sentinel message",
    "timestamp": "2026-09-01T12:00:00+00:00",
}


# ---------------------------------------------------------------------------
# fixtures — env-redirected roots only; the real stores are never touched
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_bus_env(monkeypatch):
    """A developer shell must not poison the hook's inputs: the explicit project
    override, a live test hold (and its arm), and conftest's own
    CLAUDE_PROJECT_DIR all stay out of these tests unless a test sets them."""
    for var in (PROJECT_ID_ENV, HOLD_ENV, HOLD_ARMED_ENV, PROJECT_DIR_ENV):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def user_root(tmp_path, monkeypatch) -> Path:
    """The bus lives in a redirected user DB."""
    root = tmp_path / "user-root"
    monkeypatch.setenv(USER_ROOT_ENV, str(root))
    return root


@pytest.fixture
def hook(load_script):
    return load_script(HOOK_PATH)


def _make_project(repo_dir: Path, project_id: str = "bus-proj") -> Path:
    """Scaffold the minimum bus identity into *repo_dir*: .ai-badger/project-id (ADR-0025).
    The delivery command's cwd walk finds it — no registry, no env redirect."""
    aib = repo_dir / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "project-id").write_text(f"{project_id}\n", encoding="utf-8")
    return repo_dir


def _fire(hook, monkeypatch, capsys, payload, *, raw: str = None) -> tuple[int, dict]:
    """Feed one payload (or raw stdin text) through guarded_main; return (rc, stdout-JSON).

    guarded_main is the entry every host actually runs — the fail-open net is part of
    the behaviour under test, so the happy paths go through it too.
    """
    monkeypatch.setattr("sys.stdin", io.StringIO(
        raw if raw is not None else json.dumps(payload)))
    rc = hook.guarded_main()
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _store():
    return badger_store.open_user()


def _cursor_row(session_id: str):
    with contextlib.closing(_store()) as store:
        return store.conn.execute(
            "SELECT cursor_id FROM cursors WHERE session_id = ?", (session_id,)).fetchone()


def _message_rows():
    with contextlib.closing(_store()) as store:
        return store.conn.execute(
            "SELECT id, content FROM messages ORDER BY id").fetchall()


def _seed_ancient(store, content: str, *, project: str = "P") -> None:
    """A message 2 days old — send_message stamps now, so ancient fixtures insert directly
    (the boundary arithmetic itself is store-pinned; here 2 days is just 'gated off')."""
    store.conn.execute(
        "INSERT INTO messages(ts, sender_session, sender_project, target_session, "
        "target_project, content) VALUES (?, ?, ?, NULL, ?, ?)",
        ("2026-08-30T12:00:00+00:00", "OLDSENDER", project, project, content))
    store.conn.commit()


def _context_of(response: dict) -> str:
    """The additionalContext string, asserting the response carries it."""
    inner = response.get("hookSpecificOutput")
    assert isinstance(inner, dict), f"no hookSpecificOutput in {response}"
    context = inner.get("additionalContext")
    assert isinstance(context, str) and context, f"no additionalContext in {response}"
    return context


def _documents_of(context: str) -> list[dict]:
    """Parse the render contract: one JSON document per line, chronological order."""
    return [json.loads(line) for line in context.splitlines()]


# ---------------------------------------------------------------------------
# A. render/response contract (F4 — the helper is what P9-t1 will assert through)
# ---------------------------------------------------------------------------


def test_render_is_one_schema_conformant_document_per_line(hook, root):
    """P9-t1's seam: render_messages emits ONE schema-conformant message document per
    line — jsonschema validates each line clean against schemas/message.schema.json.
    Mutation killer: a prose render ('From S: content') or a dropped field fails the
    parse or the validation."""
    import badger_lib

    schema = badger_lib.load_json(root / "schemas" / "message.schema.json")
    docs = [
        {**SENTINEL_DOC, "content": "first"},
        {**SENTINEL_DOC, "sender": {"sessionId": "S2", "projectId": "Q"},
         "content": "second", "timestamp": "2026-09-01T12:30:00+00:00"},
    ]
    rendered = hook.render_messages(docs)
    lines = rendered.splitlines()
    assert len(lines) == len(docs), "one line per document, nothing else on the wire"
    for line, doc in zip(lines, docs):
        assert json.loads(line) == doc, "each line parses to the exact document"
        assert badger_lib.validate(json.loads(line), schema) == [], \
            f"rendered payload violates the message schema: {line}"


def test_render_preserves_order_content_and_timestamp_verbatim(hook):
    """The store's document list survives rendering byte-for-byte: chronological order,
    content never re-encoded, the store's ts carried as timestamp (secondary observables).
    Mutation killer: reversing order or re-encoding content."""
    docs = [{**SENTINEL_DOC, "content": f"m{i} → ✓", "timestamp": f"2026-09-01T12:0{i}:00+00:00"}
            for i in range(3)]
    rendered = hook.render_messages(docs)
    assert [_documents_of(rendered)[i]["content"] for i in range(3)] == ["m0 → ✓", "m1 → ✓", "m2 → ✓"]
    assert _documents_of(rendered)[0]["timestamp"] == "2026-09-01T12:00:00+00:00"
    assert hook.render_messages([]) == "", "an empty list renders to nothing"


def test_response_is_additionalcontext_only_advisory(hook):
    """The response shape is exactly the context-enrichment precedent's: hookSpecificOutput
    carrying hookEventName + additionalContext — and NOTHING advisory-unsafe: no
    decision/permissionDecision/continue key anywhere (a delivery hook coercing the host
    is the failure this blanket assertion kills). Empty context → {} (inject nothing)."""
    response = hook.build_response("UserPromptSubmit", hook.render_messages([SENTINEL_DOC]))
    assert set(response) == {"hookSpecificOutput"}
    assert set(response["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    assert response["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    def all_keys(obj):
        keys = set()
        if isinstance(obj, dict):
            keys.update(obj.keys())
            for value in obj.values():
                keys.update(all_keys(value))
        elif isinstance(obj, list):
            for item in obj:
                keys.update(all_keys(item))
        return keys

    unsafe = {"decision", "permissionDecision", "continue", "suppressOutput"}
    assert not all_keys(response) & unsafe

    assert hook.build_response("UserPromptSubmit", "") == {}, \
        "no messages → no injection, not an empty additionalContext block"


# ---------------------------------------------------------------------------
# B. SessionStart — history mode (Rules 4+5 at the hook surface)
# ---------------------------------------------------------------------------


def test_session_start_injects_recent_history_and_gates_the_ancient(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Rule 4 through the script: a SessionStart in a registered project injects the
    recent (minutes-old) project messages chronologically and never the 2-day-old ones —
    the store's gate reached through the harness surface."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        _seed_ancient(store, "ancient")
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="first", target_project="bus-proj")
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="second", target_project="bus-proj")

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "SessionStart", "session_id": "NEW",
                          "cwd": str(tmp_path / "repo")})

    assert rc == 0
    docs = _documents_of(_context_of(response))
    assert [d["content"] for d in docs] == ["first", "second"]
    assert response["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert all(d["sender"]["projectId"] == "bus-proj" for d in docs)


def test_session_start_caps_at_sixteen_and_never_redelivers_overflow(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Rule 5 through the script: 20 unread inject the 16 oldest, the cursor lands PAST
    the gated window, and the overflow is never revisited by the next firing."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        for i in range(20):
            store.send_message(sender_session="S1", sender_project="bus-proj",
                               content=f"m{i}", target_project="bus-proj")

    _, response = _fire(hook, monkeypatch, capsys,
                        {"hook_event_name": "SessionStart", "session_id": "S",
                         "cwd": str(tmp_path / "repo")})
    docs = _documents_of(_context_of(response))
    assert [d["content"] for d in docs] == [f"m{i}" for i in range(16)], "cap holds, oldest first"

    _, second = _fire(hook, monkeypatch, capsys,
                      {"hook_event_name": "SessionStart", "session_id": "S",
                       "cwd": str(tmp_path / "repo")})
    assert second == {}, "the cursor past the window means the 84-tail never re-injects"


def test_session_start_on_a_session_with_a_cursor_is_a_live_read(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """A re-started session whose cursor survived (crashed close) does NOT re-gate old
    history — exactly-once beats start-injection: only messages past the cursor inject."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="seen at first start", target_project="bus-proj")
    _fire(hook, monkeypatch, capsys,
          {"hook_event_name": "SessionStart", "session_id": "S", "cwd": str(tmp_path / "repo")})
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="sent while running", target_project="bus-proj")

    _, response = _fire(hook, monkeypatch, capsys,
                        {"hook_event_name": "SessionStart", "session_id": "S",
                         "cwd": str(tmp_path / "repo")})
    assert [d["content"] for d in _documents_of(_context_of(response))] == ["sent while running"]


# ---------------------------------------------------------------------------
# C. UserPromptSubmit — live mode (Rule 4 scenario 4 / D5 at the surface)
# ---------------------------------------------------------------------------


def test_per_turn_delivery_is_live_after_the_first_read(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Per-turn delivery: the first firing consumes and lands a cursor; a message sent
    afterwards injects on the NEXT prompt and only it (no backlog, no re-injection)."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="before first turn", target_project="bus-proj")
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "S",
               "cwd": str(tmp_path / "repo")}
    _, first = _fire(hook, monkeypatch, capsys, payload)
    assert [d["content"] for d in _documents_of(_context_of(first))] == ["before first turn"]

    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="mid-session", target_project="bus-proj")
    _, second = _fire(hook, monkeypatch, capsys, payload)
    assert [d["content"] for d in _documents_of(_context_of(second))] == ["mid-session"]

    _, third = _fire(hook, monkeypatch, capsys, payload)
    assert third == {}, "a live read with nothing new injects nothing"


def test_cursorless_per_turn_read_applies_the_gate_once(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Rule 4 scenario 4 (D5) through the script: a session whose start event never fired
    gets the 30-minute gate applied on its first PER-TURN delivery — the 2-day backlog is
    skipped, the cursor lands past the gated window, later turns still get new mail.
    Mutation killer: the D5 gate dropped → 'ancient' injects here."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        _seed_ancient(store, "ancient")
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="fresh", target_project="bus-proj")

    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "S",
               "cwd": str(tmp_path / "repo")}
    _, first = _fire(hook, monkeypatch, capsys, payload)
    assert [d["content"] for d in _documents_of(_context_of(first))] == ["fresh"]

    _, second = _fire(hook, monkeypatch, capsys, payload)
    assert second == {}, "the gated-off backlog never surfaces on the next turn either"


# ---------------------------------------------------------------------------
# D. addressing + suppression (Rules 2+8 at the hook surface)
# ---------------------------------------------------------------------------


def test_self_suppression_reaches_the_script_surface(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Rule 2 end-to-end: the sender's own broadcast and project message inject NOTHING
    back to the sender's session through the script — while another session receives
    both. Mutation killer: the store's sender-exclusion dropped → the sender echoes."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S", sender_project="bus-proj",
                           content="own broadcast")
        store.send_message(sender_session="S", sender_project="bus-proj",
                           content="own project", target_project="bus-proj")

    _, own = _fire(hook, monkeypatch, capsys,
                   {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                    "cwd": str(tmp_path / "repo")})
    assert own == {}, "the sender must not see its own messages"

    _, other = _fire(hook, monkeypatch, capsys,
                     {"hook_event_name": "UserPromptSubmit", "session_id": "T",
                      "cwd": str(tmp_path / "repo")})
    assert [d["content"] for d in _documents_of(_context_of(other))] == \
        ["own broadcast", "own project"]


def test_subdirectory_cwd_resolves_to_the_project_via_the_resolver(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Rule 8 / M1+M2 at the hook level: the script must derive project identity through
    the cwd RESOLVER — a session running in a SUBDIRECTORY of the registered project
    receives the project's mail. The naive-path-hash mutation (identity derived by
    exact-match or hashing the cwd string) misses the message, which is exactly what
    this test is built to catch."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo" / "docs" / "deep"))
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="cross-directory", target_project="bus-proj")

    _, response = _fire(hook, monkeypatch, capsys,
                        {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                         "cwd": str(tmp_path / "repo" / "docs" / "deep")})
    assert [d["content"] for d in _documents_of(_context_of(response))] == ["cross-directory"]


# ---------------------------------------------------------------------------
# E. SessionEnd — cursor lifecycle (Rule 6 at the surface)
# ---------------------------------------------------------------------------


def test_session_end_removes_the_cursor(hook, user_root, tmp_path, monkeypatch, capsys):
    """Rule 6 scenario 1 through the script: the close event deletes the session's
    cursor row — exit 0, parseable no-op JSON. Mutation killer: SessionEnd misrouted to
    a delivery (or delete never called) → the row survives."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="x", target_project="bus-proj")
    _fire(hook, monkeypatch, capsys,
          {"hook_event_name": "UserPromptSubmit", "session_id": "S",
           "cwd": str(tmp_path / "repo")})
    assert _cursor_row("S") is not None, "precondition: the live session holds a cursor"

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "SessionEnd", "session_id": "S"})

    assert rc == 0
    assert response == {}
    assert _cursor_row("S") is None, "the close event must remove the cursor row"


def test_session_end_for_unknown_session_is_harmless(hook, monkeypatch, capsys):
    """A close for a session that never delivered (or already closed) is a no-op: exit 0,
    parseable JSON — never an error surface."""
    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "SessionEnd", "session_id": "GHOST"})
    assert rc == 0
    assert response == {}


# ---------------------------------------------------------------------------
# F. fail-open (D31/D7) — a broken bus must NEVER break a session
# ---------------------------------------------------------------------------


def test_malformed_stdin_is_a_no_op(hook, monkeypatch, capsys):
    """Garbage on stdin (not JSON) → exit 0, parseable JSON in the C2b failure-marker
    shape (the parse failure is a guarded_main catch), no injection.
    Mutation killer: the parse unguarded → exception escapes, exit non-zero."""
    rc, response = _fire(hook, monkeypatch, capsys, None, raw="this is { not json")
    assert rc == 0
    assert response == FAILURE_MARKER


def test_corrupt_user_db_fails_open(hook, tmp_path, monkeypatch, capsys):
    """An unreadable/corrupt user DB (every bus operation doomed) → exit 0, parseable
    JSON — the C2b failure marker, wire-distinguishable from a clean empty read so a
    poller's watermark never advances over undelivered mail (CR-M1). The host session
    must still not notice the bus exists. Mutation killer: the fail-open net removed →
    sqlite3.DatabaseError propagates, exit non-zero."""
    root = tmp_path / "corrupt-root"
    root.mkdir()
    (root / "ai-badger.db").write_bytes(b"this is not a sqlite database")
    monkeypatch.setenv(USER_ROOT_ENV, str(root))

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "SessionStart", "session_id": "S", "cwd": "/x"})
    assert rc == 0
    assert response == FAILURE_MARKER


def test_registry_explosion_fails_open(hook, user_root, monkeypatch, capsys):
    """A registry read that BLOWS UP (not a designed refusal — a genuine error) → exit 0,
    parseable JSON in the C2b failure-marker shape, nothing injected. The designed
    refusals below deliver 1:1; an exception here must not even do that."""
    def explode(cwd, registry=None):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(badger_store, "resolve_project_id", explode)

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                          "cwd": "/somewhere"})
    assert rc == 0
    assert response == FAILURE_MARKER


def test_unresolved_project_still_delivers_one_to_one(
        hook, user_root, monkeypatch, capsys):
    """D7's designed fail-open: no resolvable project → the session's 1:1 mail still
    arrives; project and broadcast legs are skipped, never a crash. Mutation killer:
    the script refusing entirely on resolution failure → the 1:1 is lost."""
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="P", content="direct",
                           target_session="S")
        store.send_message(sender_session="S1", sender_project="P", content="for P",
                           target_project="P")

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                          "cwd": "/nowhere/registered"})
    assert rc == 0
    assert [d["content"] for d in _documents_of(_context_of(response))] == ["direct"]


def test_nested_projects_resolve_nearest_and_deliver_inner(
        hook, user_root, tmp_path, monkeypatch, capsys):
    """Nested .ai-badger dirs resolve nearest-wins (ADR-0025): a payload whose cwd sits
    in the inner project receives the inner project's mail and its 1:1 leg, never the
    outer's — the walk stops at the first .ai-badger it finds."""
    _make_project(tmp_path / "repo", "outer")
    _make_project(tmp_path / "repo" / "sub", "inner")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo" / "sub"))
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="P", content="direct",
                           target_session="S")
        store.send_message(sender_session="S1", sender_project="P", content="for inner",
                           target_project="inner")
        store.send_message(sender_session="S1", sender_project="P", content="for outer",
                           target_project="outer")

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                          "cwd": str(tmp_path / "repo" / "sub")})
    assert rc == 0
    assert [d["content"] for d in _documents_of(_context_of(response))] == ["direct", "for inner"]


def test_missing_session_id_is_a_clean_no_op(hook, user_root, monkeypatch, capsys):
    """A payload without a usable session id cannot be delivered — the script must no-op
    BEFORE touching the store (the store would raise; the net would swallow it, but the
    clean path is: no store call at all). Covers all three degenerate forms: the key
    absent, blank/whitespace, and a non-string. Mutation killer: session_id passed
    through unvalidated → the whitespace/int forms reach the store (spy fires)."""
    calls = []

    def spy(*args, **kwargs):
        calls.append(1)
        raise AssertionError("open_user must not run without a session id")

    monkeypatch.setattr(badger_store, "open_user", spy)

    for payload in ({"hook_event_name": "UserPromptSubmit", "cwd": "/x"},
                    {"hook_event_name": "UserPromptSubmit", "session_id": "   ", "cwd": "/x"},
                    {"hook_event_name": "UserPromptSubmit", "session_id": 123, "cwd": "/x"}):
        rc, response = _fire(hook, monkeypatch, capsys, payload)
        assert rc == 0
        assert response == {}
    assert calls == [], "a session-less payload must never reach the store"


def test_unknown_event_is_a_clean_no_op(hook, user_root, monkeypatch, capsys):
    """An event the script does not serve (PreToolUse, PostToolUse, …) is a no-op: no
    delivery, no cursor delete, no crash — the hook never guesses an unknown contract."""
    calls = []

    def spy(*args, **kwargs):
        calls.append(1)
        raise AssertionError("open_user must not run for an unknown event")

    monkeypatch.setattr(badger_store, "open_user", spy)

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "PreToolUse", "session_id": "S", "cwd": "/x"})
    assert rc == 0
    assert response == {}
    assert calls == []


# ---------------------------------------------------------------------------
# G. chain-drop guard (Rule 7 scenario 3, script half) — every path terminates well
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", [
    "empty-inbox", "malformed-stdin", "unknown-event", "missing-session",
    "session-end", "corrupt-db",
], ids=str)
def test_every_termination_path_emits_parseable_json_and_exits_zero(
        hook, user_root, tmp_path, monkeypatch, capsys, scenario):
    """A hook WIRED into a harness chain must never be the one that drops the event:
    EVERY firing — empty inbox, garbage stdin, unknown event, missing session, close,
    corrupt store — terminates exit 0 with parseable JSON on stdout (a host chaining
    hooks can always read a response). Mutation killer: any path returning without
    printing."""
    if scenario == "corrupt-db":
        root = tmp_path / "corrupt-root"
        root.mkdir()
        (root / "ai-badger.db").write_bytes(b"not a database")
        monkeypatch.setenv(USER_ROOT_ENV, str(root))
        payload, raw = {"hook_event_name": "SessionStart", "session_id": "S", "cwd": "/x"}, None
    elif scenario == "malformed-stdin":
        raw = "{broken"
        payload = None
    elif scenario == "unknown-event":
        payload, raw = {"hook_event_name": "PostToolUse", "session_id": "S"}, None
    elif scenario == "missing-session":
        payload, raw = {"hook_event_name": "UserPromptSubmit", "cwd": "/x"}, None
    elif scenario == "session-end":
        payload, raw = {"hook_event_name": "SessionEnd", "session_id": "S"}, None
    else:  # empty-inbox
        payload, raw = {"hook_event_name": "SessionStart", "session_id": "S", "cwd": "/x"}, None

    if raw is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    rc = hook.guarded_main()
    out = capsys.readouterr().out
    assert rc == 0, f"{scenario} must exit 0"
    assert out.strip(), f"{scenario} must print a response"
    json.loads(out)  # parseable — a raise here fails the test


# ---------------------------------------------------------------------------
# H. no-drop between read and response (plan t6)
# ---------------------------------------------------------------------------


def test_the_store_document_list_is_what_stdout_carries(
        hook, user_root, monkeypatch, capsys):
    """The messages the store's deliver_for_session returns are EXACTLY what stdout
    carries — no re-filtering, no re-shaping between the transaction and the wire.
    Mutation killer: the script dropping or rewriting documents after the read."""
    monkeypatch.setattr(
        badger_store.Store, "deliver_for_session",
        lambda self, session_id, project_id=None:
            ([SENTINEL_DOC, {**SENTINEL_DOC, "content": "two"}],
             {"addressed": 2, "broadcast": 0}))

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                          "cwd": "/x"})
    assert rc == 0
    assert _documents_of(_context_of(response)) == [SENTINEL_DOC, {**SENTINEL_DOC, "content": "two"}]


# ---------------------------------------------------------------------------
# I. multi-harness reuse + the deployment shape
# ---------------------------------------------------------------------------


def test_copilot_event_spellings_deliver(hook, user_root, tmp_path, monkeypatch, capsys):
    """The same script serves Copilot's event spellings (sessionStart / userPromptSubmitted)
    — the multi-harness reuse contract: one delivery surface, per-harness event names."""
    _make_project(tmp_path / "repo")
    monkeypatch.setenv(PROJECT_DIR_ENV, str(tmp_path / "repo"))
    session = "COP"
    for i, event in enumerate(("sessionStart", "userPromptSubmitted")):
        with contextlib.closing(_store()) as store:
            store.send_message(sender_session="S1", sender_project="bus-proj",
                               content=f"for copilot {i}", target_project="bus-proj")
        _, response = _fire(hook, monkeypatch, capsys,
                            {"hook_event_name": event, "session_id": session,
                             "cwd": str(tmp_path / "repo")})
        assert [d["content"] for d in _documents_of(_context_of(response))] == \
            [f"for copilot {i}"], event


def test_standalone_invocation_via_subprocess(hook, user_root, tmp_path, monkeypatch, capsys):
    """The deployment shape: a host spawns the script as a child process, feeds the
    Claude-shaped payload on stdin, reads the JSON response — with the VENDORED
    badger_store beside the script (script-dir import), not the engine copy."""
    _make_project(tmp_path / "repo")
    with contextlib.closing(_store()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="from a child process", target_project="bus-proj")

    env = {k: v for k, v in os.environ.items()
           if k not in (PROJECT_ID_ENV, HOLD_ENV, PROJECT_DIR_ENV)}
    env[USER_ROOT_ENV] = os.environ[USER_ROOT_ENV]
    proc = subprocess.run(
        [sys.executable, str(ROOT / HOOK_PATH)],
        input=json.dumps({"hook_event_name": "SessionStart", "session_id": "S",
                          "cwd": str(tmp_path / "repo")}).encode(),
        capture_output=True, env=env, timeout=60, check=False)

    assert proc.returncode == 0, proc.stderr.decode()[-400:]
    response = json.loads(proc.stdout.decode())
    assert [d["content"] for d in _documents_of(_context_of(response))] == \
        ["from a child process"]


# ---------------------------------------------------------------------------
# J. delivery summary + failure marker (P2 C2/C2b — the wake-classification wire)
# ---------------------------------------------------------------------------


#: C2b (CR-M1): the fail-open net's wire shape — distinguishable from a clean empty
#: read, additive inside hookSpecificOutput, never a host-acted key (CR-N6).
FAILURE_MARKER = {"hookSpecificOutput": {"aiBadgerBus": {"error": True}}}


def test_clean_empty_stays_exactly_empty_at_the_wire(hook, user_root, monkeypatch, capsys):
    """C2b's clean-empty boundary: an empty inbox prints {} — EXACTLY, no aiBadgerBus
    key with zero counts, no envelope (the TS negative-watermark logic keys on the
    ABSENT field, QA-10 case 3). Green by construction until someone 'enriches' the
    empty path — that mutation is exactly what this pin kills."""
    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "UserPromptSubmit", "session_id": "S",
                          "cwd": "/x"})
    assert rc == 0
    assert response == {}


def test_failure_marker_on_a_forced_store_open_failure(hook, tmp_path, monkeypatch, capsys):
    """C2b (CR-M1): a failure inside guarded_main is wire-distinguishable from a clean
    empty read — the response is {"hookSpecificOutput": {"aiBadgerBus": {"error": true}}}
    (exit 0, fail-open unchanged, log line unchanged shape + the C8 message). A corrupt
    user DB forces the store-open failure; the poller's watermark-advance rule keys on
    this marker — a failure-marked {} must never read as a clean empty inbox (M1's
    silent-stall shape).
    Mutation killer: printing {} on the failure path."""
    root = tmp_path / "corrupt-root"
    root.mkdir()
    (root / "ai-badger.db").write_bytes(b"this is not a sqlite database")
    monkeypatch.setenv(USER_ROOT_ENV, str(root))

    rc, response = _fire(hook, monkeypatch, capsys,
                         {"hook_event_name": "SessionStart", "session_id": "S", "cwd": "/x"})
    assert rc == 0
    assert response == FAILURE_MARKER
