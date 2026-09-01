"""Tests for the send-message skill CLI (P3, aib-user-db-message-bus).

The skill is a CLI, so every behaviour test runs
``features/common/skills/send-message/scripts/send_message.py`` as a subprocess — the
surface an agent's shell call actually hits — against user/tracking/debug roots
redirected into the test's tmp tree (the conftest isolation pattern: the real
``~/.ai-badger`` DBs are never opened, let alone written, and the raccoon registry
never reaches past ``AI_BADGER_RACCOON_DB``).

Test map (plan aib-user-db-message-bus §3 P3 · spec rules in parentheses):
  1. Targeting + identity (Rule 1, D3) ......... test_one_to_one_send_lands_a_row_with_full_sender_identity_and_null_project,
                                                 test_project_broadcast_send_lands_a_project_row,
                                                 test_machine_broadcast_send_lands_a_row_with_no_target,
                                                 test_session_target_wins_over_project_target
  2. Refusals through the CLI (Rule 1, D7) ..... test_missing_sender_session_is_refused_no_row_no_traceback,
                                                 test_missing_sender_project_is_refused_no_row_no_traceback,
                                                 test_ambiguous_project_is_refused_with_candidates
  3. Content + timestamp (schema contract) ..... test_content_is_stored_verbatim,
                                                 test_timestamp_is_utc_iso8601_per_the_message_schema
  4. Sender-session derivation legs (D8) ....... test_session_env_var_wins_over_sessions_store_matches,
                                                 test_sender_session_resolves_from_pid_ancestry,
                                                 test_sender_session_resolves_from_unique_cwd
  5. Sender-project resolution (R8, A3) ........ test_explicit_project_env_override_resolves_without_a_registry,
                                                 test_sender_project_resolves_from_the_raccoon_registry
  6. The doc says what the CLI does ............ test_the_skill_doc_documents_identity_requirement_and_session_precedence
  7. Vendored copy (D16) ....................... test_the_vendored_copy_is_byte_identical_to_the_canonical

Failure modes each test pins: a refusal that exits 0 or tracebacks (D7), a row written
by a refused send (R1), a mangled content payload, a local-time or non-ISO timestamp, a
derivation leg that lost its precedence to a weaker match, and a vendored copy that
drifted from the canonical store module.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import badger_store
from conftest import ROOT

SCRIPT = ROOT / "features/common/skills/send-message/scripts/send_message.py"
SKILL_DOC = ROOT / "features/common/skills/send-message/SKILL.md"

#: The CLI's refusal prefix — every expected failure (D7) speaks in this voice, never
#: a traceback, and exits non-zero.
REFUSAL = "send refused:"


# ---------------------------------------------------------------------------
# helpers — env redirect, fixtures, subprocess runner, DB readers
# ---------------------------------------------------------------------------


def _base_env(tmp_path: Path) -> dict:
    """A hermetic environment for the subprocess: every store root inside *tmp_path*.

    Identity signals a developer shell may legitimately carry are popped so a test
    only sees a leg when it planted that leg itself.
    """
    env = dict(os.environ)
    env[badger_store.USER_ROOT_ENV] = str(tmp_path / "user-root")
    env[badger_store.TRACKING_ROOT_ENV] = str(tmp_path / "tracking-root")
    env[badger_store.DEBUG_DIR_ENV] = str(tmp_path / "debug-dir")
    for signal in (badger_store.PROJECT_ID_ENV, "CLAUDE_CODE_SESSION_ID"):
        env.pop(signal, None)
    return env


def _send(tmp_path: Path, *args: str, cwd: Path = None) -> subprocess.CompletedProcess:
    """Run the send CLI the way an agent's shell would, hermetically."""
    env = _base_env(tmp_path)
    if cwd is None:
        cwd = tmp_path
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, env=env, cwd=str(cwd), timeout=60,
    )


def _seed_sessions(tmp_path: Path, sessions: dict) -> None:
    """Write current-session rows into the redirected tracking store.

    Uses the store's own session_upsert so the seeds share the production row shape —
    a hand-written row would happily drift from what the derivation actually reads.
    """
    import contextlib

    with contextlib.ExitStack() as stack:
        monkey = stack.enter_context(pytest.MonkeyPatch.context())
        monkey.setenv(badger_store.TRACKING_ROOT_ENV, str(tmp_path / "tracking-root"))
        store = badger_store.open_tracking()
        try:
            for session_id, info in sessions.items():
                store.session_upsert(session_id, info)
        finally:
            store.close()


def _make_project(directory: Path, project_id: str) -> Path:
    """Scaffold the minimum bus identity: <dir>/.ai-badger/project-id (ADR-0025)."""
    aib = directory / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "project-id").write_text(f"{project_id}\n", encoding="utf-8")
    return directory


def _message_rows(tmp_path: Path) -> list[tuple]:
    """Every messages row in the redirected user DB, oldest first; [] when absent."""
    db = tmp_path / "user-root" / "ai-badger.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT id, ts, sender_session, sender_project, target_session, "
            "target_project, content FROM messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _bank_env(tmp_path: Path, bank: Path) -> dict:
    """_base_env with the raccoon bank pointed at *bank* — for env-dict callers."""
    env = _base_env(tmp_path)
    env[badger_store.RACCOON_BANK_ENV] = str(bank)
    return env


def _send_with_env(tmp_path: Path, env: dict, *args: str,
                   cwd: Path = None) -> subprocess.CompletedProcess:
    """A send with a caller-built environment (the env-leg and override tests)."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, env=env,
        cwd=str(cwd or tmp_path), timeout=60,
    )


def _explicit_identity_args() -> list[str]:
    """Identity both halves resolved explicitly — targeting tests stay on one axis."""
    return ["--sender-session", "sess-sender", "--sender-project", "proj-sender"]


# ---------------------------------------------------------------------------
# 1. targeting + identity (Rule 1, D3)
# ---------------------------------------------------------------------------


def test_one_to_one_send_lands_a_row_with_full_sender_identity_and_null_project(tmp_path):
    """A 1:1 send stores sender {sessionId, projectId} and — the A2 secondary
    observable — target_project NULL: write-normalisation, not dual-target rows."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    proc = _send(tmp_path, "--content", "found it, see src/bus.py",
                 "--session-id", "sess-target", *_explicit_identity_args(), cwd=workdir)

    assert proc.returncode == 0, proc.stderr
    assert "sent" in proc.stdout  # the send path ran to completion, not a silent no-op
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    (_id, _ts, sender_session, sender_project, target_session, target_project,
     _content) = rows[0]
    assert (sender_session, sender_project) == ("sess-sender", "proj-sender")
    assert target_session == "sess-target"
    assert target_project is None


def test_project_broadcast_send_lands_a_project_row(tmp_path):
    """--project-id alone is a project broadcast: no target_session, project stored."""
    proc = _send(tmp_path, "--content", "standup in five",
                 "--project-id", "proj-target", *_explicit_identity_args())

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    (_id, _ts, _s, _p, target_session, target_project, _c) = rows[0]
    assert target_session is None
    assert target_project == "proj-target"


def test_machine_broadcast_send_lands_a_row_with_no_target(tmp_path):
    """Neither target flag is a machine broadcast: both target columns NULL."""
    proc = _send(tmp_path, "--content", "heads up: deploy window now",
                 *_explicit_identity_args())

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    (_id, _ts, _s, _p, target_session, target_project, _c) = rows[0]
    assert target_session is None and target_project is None


def test_session_target_wins_over_project_target(tmp_path):
    """Both target flags → 1:1 wins (D3): the row is 1:1 with the project half dropped,
    so no read predicate can ever see a dual-target row."""
    proc = _send(tmp_path, "--content", "both flags",
                 "--session-id", "sess-target", "--project-id", "proj-target",
                 *_explicit_identity_args())

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    (_id, _ts, _s, _p, target_session, target_project, _c) = rows[0]
    assert target_session == "sess-target"
    assert target_project is None


# ---------------------------------------------------------------------------
# 2. refusals through the CLI (Rule 1 scenario 2; D7's clean-refusal voice)
# ---------------------------------------------------------------------------


def test_missing_sender_session_is_refused_no_row_no_traceback(tmp_path):
    """No session half, no derivation → refused non-zero with the missing-identity
    voice, and — the part that matters — no row survives the refusal."""
    workdir = tmp_path / "work"  # no sessions seeded: ancestry and cwd match nothing
    workdir.mkdir()
    proc = _send(tmp_path, "--content", "nobody sent this",
                 "--sender-project", "proj-sender", cwd=workdir)

    assert proc.returncode != 0
    assert REFUSAL in proc.stderr and "sessionId" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert _message_rows(tmp_path) == []


def test_missing_sender_project_is_refused_no_row_no_traceback(tmp_path):
    """No project half — empty registry, no override, no arg → refused non-zero,
    clean voice, nothing written (Rule 1 scenario 2's second half)."""
    proc = _send(tmp_path, "--content", "no project here",
                 "--sender-session", "sess-sender")

    assert proc.returncode != 0
    assert REFUSAL in proc.stderr and "projectId" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert _message_rows(tmp_path) == []


def test_ambiguous_project_is_refused_with_candidates(tmp_path):
    """An .ai-badger directory without a project-id (pre-backfill legacy repo) refuses
    the send: the resolver returns None, the CLI's missing-identity refusal fires —
    non-zero exit, no row (ADR-0025: id-absent is fail-open at delivery, refused at
    send — identity is mandatory)."""
    workdir = tmp_path / "shared"
    (workdir / ".ai-badger").mkdir(parents=True)
    proc = _send(tmp_path, "--content", "which project?",
                 "--sender-session", "sess-sender", cwd=workdir)

    assert proc.returncode != 0
    assert REFUSAL in proc.stderr
    assert "projectId" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert _message_rows(tmp_path) == []


# ---------------------------------------------------------------------------
# 3. content + timestamp (the schemas/message.schema.json contract at the send surface)
# ---------------------------------------------------------------------------


def test_content_is_stored_verbatim(tmp_path):
    """The stored content is the argv string byte for byte — newlines, unicode,
    quoting and shell-significant characters survive untouched."""
    payload = "line1\nline2 — ünïcode 'single' \"double\" $dollar `tick` ; rm -rf /"
    proc = _send(tmp_path, "--content", payload, *_explicit_identity_args())

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][6] == payload


def test_timestamp_is_utc_iso8601_per_the_message_schema(tmp_path):
    """The row ts parses as ISO-8601 with a zero UTC offset (the schema's
    date-time contract) and is stamped at send time, not by some other clock."""
    before = datetime.now(timezone.utc) - timedelta(minutes=1)
    proc = _send(tmp_path, "--content", "tick", *_explicit_identity_args())
    after = datetime.now(timezone.utc) + timedelta(minutes=1)

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    ts = datetime.fromisoformat(rows[0][1])
    assert ts.utcoffset() == timedelta(0)
    assert before <= ts <= after


# ---------------------------------------------------------------------------
# 4. sender-session derivation legs (D8, the claude_session_source pattern)
# ---------------------------------------------------------------------------


def test_session_env_var_wins_over_sessions_store_matches(tmp_path, monkeypatch):
    """The pattern's precedence under full contention: env, ancestry and cwd matches
    all present → the env leg wins (a weaker leg stealing the identity is the bug)."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    _seed_sessions(tmp_path, {
        "sess-by-ancestry": {"pid": os.getpid(), "cwd": str(tmp_path / "elsewhere")},
        "sess-by-cwd": {"pid": 999999, "cwd": str(workdir)},
    })
    env = _base_env(tmp_path)
    env["CLAUDE_CODE_SESSION_ID"] = "sess-from-env"
    proc = _send_with_env(tmp_path, env, "--content", "who am I",
                          "--sender-project", "proj-sender", cwd=workdir)

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][2] == "sess-from-env"


def test_sender_session_resolves_from_pid_ancestry(tmp_path):
    """No env, no arg: a seeded session whose pid is this process's ancestor is the
    sender — the ancestry leg, with a non-matching sibling row left in the store."""
    _seed_sessions(tmp_path, {
        "sess-ancestor": {"pid": os.getpid(), "cwd": str(tmp_path / "its-cwd")},
        "sess-other": {"pid": 999999, "cwd": str(tmp_path / "other-cwd")},
    })
    proc = _send(tmp_path, "--content", "from the ancestry",
                 "--sender-project", "proj-sender")

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][2] == "sess-ancestor"


def test_sender_session_resolves_from_unique_cwd(tmp_path):
    """No env, no arg, no ancestry hit: exactly one session carrying this cwd is the
    sender — the unique-cwd leg; two matches would have to refuse, not pick."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    _seed_sessions(tmp_path, {
        "sess-here": {"pid": 999999, "cwd": str(workdir)},
        "sess-there": {"pid": 999998, "cwd": str(tmp_path / "not-this-cwd")},
    })
    proc = _send(tmp_path, "--content", "from the cwd",
                 "--sender-project", "proj-sender", cwd=workdir)

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][2] == "sess-here"


# ---------------------------------------------------------------------------
# 5. sender-project resolution (Rule 8's resolver contract, at the send surface)
# ---------------------------------------------------------------------------


def test_explicit_project_env_override_resolves_without_a_registry(tmp_path):
    """AI_BADGER_PROJECT_ID is the answer before anything is read (A3): the bank
    path names a file that does not exist, and the send still carries the override."""
    env = _base_env(tmp_path)
    env[badger_store.PROJECT_ID_ENV] = "proj-override"
    proc = _send_with_env(tmp_path, env, "--content", "override wins",
                          "--sender-session", "sess-sender")

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3] == "proj-override"


def test_sender_project_resolves_from_the_walked_project_id(tmp_path):
    """No override: the cwd resolver's upward walk supplies the project half —
    the nearest .ai-badger/project-id above the workdir (ADR-0025), not cwd equality."""
    workdir = tmp_path / "work" / "deep"
    workdir.mkdir(parents=True)
    _make_project(tmp_path / "work", "proj-registry")
    proc = _send(tmp_path, "--content", "resolved by the walk",
                 "--sender-session", "sess-sender", cwd=workdir)

    assert proc.returncode == 0, proc.stderr
    rows = _message_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3] == "proj-registry"


# ---------------------------------------------------------------------------
# 6. the doc + the vendored copy
# ---------------------------------------------------------------------------


def test_the_skill_doc_documents_identity_requirement_and_session_precedence():
    """SKILL.md is the agent's only contract for the CLI: both sender flags, the
    both-halves-required rule (R10) and the session-wins precedence must be stated
    where the agent reads — not recoverable from the script alone."""
    text = SKILL_DOC.read_text(encoding="utf-8")
    assert "--sender-session" in text and "--sender-project" in text
    assert "the session wins" in text


def test_the_vendored_copy_is_byte_identical_to_the_canonical():
    """The skill's store copy must be the canonical module verbatim (D16) — this
    file's own pin, independent of the manifest-driven byte-check."""
    vendored = ROOT / "features/common/skills/send-message/scripts/badger_store.py"
    assert vendored.read_bytes() == (ROOT / "engine/badger_store.py").read_bytes()
