"""P9 integration package (plan 2026-09-01-aib-user-db-message-bus, §3 P9 — SERIAL, LAST).

The union tests the plan-review B4 clustering named: the send → deliver → render
roundtrip across two harness shapes with the schema seam, the exactly-once race
re-proven across the PROCESS boundary, harness parity asserted from the REAL
manifest, the Copilot sessionEnd close arm, and the Phase-4 spec sweep.

Test map (review §B4/B5 — each test names its failure mode and the mutation that
must kill it):

 1. Roundtrip (t1, plan item 1 + F4) — a break anywhere in the chain send-script
    → store → hook render → additionalContext (identity lost, content mangled,
    order flipped, sender echo). Mutation: render drops the sender field, or the
    delivery query loses sender exclusion — the sender's own hook injects mail.
 2. Process race (t3, plan item 3, F5) — exactly-once fails when the two sides
    are separate OS processes (the in-process barrier cannot reach across fork).
    Mutation: hoist the unread read before BEGIN IMMEDIATE — both children read
    the message before either commits and both inject it.
 3. Parity (t4, plan item 4, Rule 7 sc.3) — a manifest arm whose event/method
    spelling its harness surface does not know wires silently nothing.
    Mutation: drop 'sessionEnd' from the copilot event_map, 'on_session_end'
    from PLUGIN_YAML, or a target from the pi bridge map — each fails here.
 4. Copilot close arm (t7, plan item 7, @deferred Rule 6 sc.3) — the Copilot leg
    of cursor cleanup silently lost (P8 falsified the "no sessionEnd event"
    hypothesis: the event exists and must be wired). Mutation: delete the
    copilot arm from message-delivery-session-end or unmap its spelling.
 5. Spec sweep (t8, plan item 8, review B5) — a pass-condition scenario with no
    owning test. The parser derives the scenario list from the .feature, so
    adding an unmapped scenario fails; a stale owner entry (renamed scenario,
    deleted test) fails too — the checklist cannot rot silently.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import badger_lib
import badger_store
import pytest
from conftest import ROOT

HOOK_PATH = "features/common/hooks/message_delivery_hook.py"
SEND_PATH = "features/common/skills/send-message/scripts/send_message.py"
MANIFEST_PATH = "features/common/hooks/hooks-manifest.json"
HOOKS_JSON_PATH = "features/common/hooks/hooks.json"
COPILOT_ADJUSTER_PATH = "features/copilot/adjustments/adjust_hooks.py"
HERMES_ADJUSTER_PATH = "features/hermes/adjustments/adjust_hooks.py"
PI_BRIDGE_PATH = "features/pi/adjustments/adapter/hook-bridge.ts"
SCHEMA_PATH = "schemas/message.schema.json"
FEATURE_PATH = ".ai-badger/task-tracking/specs/aib-user-db-message-bus.feature"

PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"
USER_ROOT_ENV = "AI_BADGER_USER_ROOT"
HOLD_ENV = "AI_BADGER_TEST_HOLD"
HOLD_ARMED_ENV = "AI_BADGER_TEST_HOLD_ARMED"
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"


# ---------------------------------------------------------------------------
# fixtures + helpers — env-redirected roots only; the real stores are never touched
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_bus_env(monkeypatch):
    """A developer shell must not poison the hook's inputs."""
    for var in (PROJECT_ID_ENV, HOLD_ENV, HOLD_ARMED_ENV, PROJECT_DIR_ENV):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def user_root(tmp_path, monkeypatch) -> Path:
    """The bus lives in a redirected user DB (ai-badger.db under the root)."""
    root = tmp_path / "user-root"
    monkeypatch.setenv(USER_ROOT_ENV, str(root))
    return root


@pytest.fixture
def hook(load_script):
    return load_script(HOOK_PATH)


@pytest.fixture
def send_script(load_script):
    return load_script(SEND_PATH)


def _make_project(repo_dir: Path, project_id: str = "bus-proj") -> Path:
    """Scaffold the minimum bus identity into *repo_dir*: .ai-badger/project-id (ADR-0025).
    The delivery walk reads it from the payload cwd — no registry, no env redirect."""
    aib = repo_dir / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "project-id").write_text(f"{project_id}\n", encoding="utf-8")
    return repo_dir


def _fire(hook, monkeypatch, capsys, payload) -> dict:
    """Feed one payload through guarded_main — the entry every host actually runs."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = hook.guarded_main()
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def _documents_of(response: dict) -> list[dict]:
    context = response.get("hookSpecificOutput", {}).get("additionalContext", "")
    return [json.loads(line) for line in context.splitlines() if line]


# ---------------------------------------------------------------------------
# t1 — the two-harness conversation (plan item 1; Rules 1, 2, 7, 8)
# ---------------------------------------------------------------------------


def test_send_script_then_hook_roundtrip_delivers_two_harnesses_schema_clean(
        hook, send_script, user_root, tmp_path, monkeypatch, capsys, root):
    """Failure mode: any broken link in send-script → store → hook → rendered
    additionalContext — identity lost, content mangled, order flipped, or the
    sender echoing. Mutation: render drops the sender field, or the delivery
    query loses sender exclusion — the sender's own hook injects."""
    repo = tmp_path / "repo"
    _make_project(repo)

    # The P3 skill script (real vendored copy) sends two messages — Rule 1 at the
    # user-facing surface: explicit identity, project broadcast, rc 0.
    sent_contents = ["found it, see src/bus.py", "second thought, see src/bus.py:2"]
    for content in sent_contents:
        rc = send_script.main(["--content", content, "--sender-session", "S1",
                               "--sender-project", "bus-proj", "--project-id", "bus-proj"])
        assert rc == 0, content
        capsys.readouterr()  # drain the script's 'sent <id>' line before firing hooks

    # The sender's own hook (Claude shape) injects nothing — Rule 2 roundtripped
    # through the real script surface, not just the store query.
    own = _fire(hook, monkeypatch, capsys,
                {"hook_event_name": "SessionStart", "session_id": "S1", "cwd": str(repo)})
    assert own == {}, own

    # Receiver A: Claude shape, resolving a SUBDIRECTORY of the registered root —
    # the resolver (not the harness) matched (Rule 8's directory split, E2E).
    claude_response = _fire(hook, monkeypatch, capsys,
                            {"hook_event_name": "SessionStart", "session_id": "S2",
                             "cwd": str(repo / "sub")})
    # Receiver B: the exact ClaudeDeliveryPayload pi's bridge stamps (P6 mapping —
    # three keys, no tool fields), delivered through the same script.
    pi_response = _fire(hook, monkeypatch, capsys,
                        {"hook_event_name": "SessionStart", "session_id": "S3",
                         "cwd": str(repo)})

    schema = badger_lib.load_json(root / SCHEMA_PATH)
    expected = ["found it, see src/bus.py", "second thought, see src/bus.py:2"]
    for response in (claude_response, pi_response):
        # Secondary observable: the response carries the event stamp, not just mail.
        assert response["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        docs = _documents_of(response)
        assert [d["content"] for d in docs] == expected, response
        assert docs == sorted(docs, key=lambda d: d["timestamp"]), "chronological order"
        for doc in docs:
            assert badger_lib.validate(doc, schema) == [], doc
            assert doc["sender"]["sessionId"] == "S1"
            assert doc["sender"]["projectId"] == "bus-proj"

    # Both deliveries landed cursor rows — state advanced, not a replayable read.
    with contextlib.closing(badger_store.open_user()) as store:
        sessions = {r[0] for r in store.conn.execute("SELECT session_id FROM cursors")}
        assert {"S2", "S3"} <= sessions, sessions


# ---------------------------------------------------------------------------
# t3 — the exactly-once race across the process boundary (plan item 3, F5)
# ---------------------------------------------------------------------------


def _child_env(user_root_path: Path, release: Path) -> dict:
    """The P4 subprocess shape: only the redirect vars survive the parent shell."""
    env = {k: v for k, v in os.environ.items()
           if k not in (PROJECT_ID_ENV, HOLD_ENV, HOLD_ARMED_ENV, PROJECT_DIR_ENV)}
    env[USER_ROOT_ENV] = str(user_root_path)
    env[HOLD_ENV] = f"deliver.after_read:{release}"
    env[HOLD_ARMED_ENV] = "1"  # D3/L2: the pair is required for a real park
    return env


def _wait_for_parked_transaction(db_path: Path, deadline_seconds: float = 15.0) -> None:
    """Block until a delivery child holds the user DB's write transaction — the
    F5 hold's observable. The parked child sits inside BEGIN IMMEDIATE, so the
    parent's own BEGIN IMMEDIATE with a tiny busy timeout fails with 'database
    is locked'. Without this proof the release could fire before the collision,
    and the test would pass green-trivially (review §D's warned shape)."""
    conn = sqlite3.connect(str(db_path), timeout=0.05, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 50")
    deadline = time.monotonic() + deadline_seconds
    try:
        while time.monotonic() < deadline:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("ROLLBACK")
                time.sleep(0.01)
            except sqlite3.OperationalError:
                return  # a delivery child is parked mid-write-transaction
        pytest.fail("no delivery child ever parked mid-transaction — the race never collided")
    finally:
        conn.close()


def test_two_hook_processes_race_one_unread_message_exactly_once(
        user_root, tmp_path, monkeypatch):
    """Failure mode: exactly-once breaks when the two hooks are separate OS
    processes (P1-t6's in-process barrier cannot reach across fork). Mutation:
    hoist the unread read before BEGIN IMMEDIATE — both children then read the
    message before either commits, and both inject it."""
    repo = tmp_path / "repo"
    bank = _make_project(repo)
    with contextlib.closing(badger_store.open_user()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="race me", target_project="bus-proj")

    release = tmp_path / "release-hold"
    env = _child_env(user_root, release)
    payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "S2",
                          "cwd": str(repo)}).encode()
    children = []
    try:
        for _ in range(2):
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / HOOK_PATH)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env)
            proc.stdin.write(payload)
            proc.stdin.close()  # EOF: the hook reads stdin to the end before delivering
            children.append(proc)
        _wait_for_parked_transaction(user_root / "ai-badger.db")
        release.touch()
        # communicate() would flush the already-closed stdin; the responses are
        # small enough that direct pipe reads after the release cannot deadlock.
        outs = [(proc.stdout.read(), proc.stderr.read()) for proc in children]
        for proc in children:
            proc.wait(timeout=30)
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.kill()

    responses = []
    for proc, (out, err) in zip(children, outs):
        assert proc.returncode == 0, err.decode()[-400:]
        assert err == b"", err.decode()[-200:]
        responses.append(json.loads(out.decode()))
    # Exactly one child injected the message; the other finished empty — the
    # store's one write transaction serialized real processes.
    injected = [r for r in responses if _documents_of(r)]
    assert len(injected) == 1, responses
    assert [d["content"] for d in _documents_of(injected[0])] == ["race me"]

    # Both hooks finish at the same cursor position (Rule 3 sc.1's second clause).
    with contextlib.closing(badger_store.open_user()) as store:
        cursor = store.conn.execute(
            "SELECT cursor_id FROM cursors WHERE session_id = 'S2'").fetchone()
        last_id = store.conn.execute("SELECT MAX(id) FROM messages").fetchone()[0]
        assert cursor is not None and cursor[0] == last_id


# ---------------------------------------------------------------------------
# t4 — harness parity from the REAL manifest (plan item 4, Rule 7)
# ---------------------------------------------------------------------------


def _copilot_event_map_keys() -> set:
    """The copilot adjuster's event_map keys — the spellings it can translate."""
    src = (ROOT / COPILOT_ADJUSTER_PATH).read_text()
    block = re.search(r"event_map\s*=\s*\{(.*?)\}", src, re.DOTALL)
    assert block, "the copilot adjuster's event_map disappeared"
    return set(re.findall(r'"([A-Za-z]+)":', block.group(1)))


def _delivery_rows() -> list[dict]:
    manifest = json.loads((ROOT / MANIFEST_PATH).read_text())
    rows = [row for row in manifest["hooks"] if row["name"].startswith("message-delivery-")]
    assert len(rows) == 3, sorted(row["name"] for row in rows)
    return rows


def test_every_wired_arm_spelling_has_a_surface_on_its_harness(load_script):
    """Failure mode: a manifest arm whose event/method spelling its harness
    surface does not know — the adjuster or plugin silently wires nothing, the
    harness claims delivery it never performs (Rule 7 sc.3). Mutation: drop
    'sessionEnd' from the copilot event_map, 'on_session_end' from PLUGIN_YAML,
    or a target from the pi bridge map — each fails here."""
    copilot_map = _copilot_event_map_keys()
    hermes_module = load_script(HERMES_ADJUSTER_PATH)
    yaml_block = re.search(r"(?ms)^hooks:\n((?:  - .+\n)+)",
                           hermes_module.PLUGIN_YAML)
    assert yaml_block, "the hermes plugin template lost its hooks block"
    hermes_hooks = set(re.findall(r"  - (\S+)", yaml_block.group(1)))
    hooks_json = json.loads((ROOT / HOOKS_JSON_PATH).read_text())
    claude_events = set(hooks_json["hooks"].keys())
    bridge = (ROOT / PI_BRIDGE_PATH).read_text()
    pi_block = re.search(r"PI_DELIVERY_EVENT_MAP[^{]*\{(.*?)\}", bridge, re.DOTALL)
    assert pi_block, "the pi bridge lost its delivery event map"
    pi_sources = set(re.findall(r'(\w+):\s*"', pi_block.group(1)))
    pi_targets = set(re.findall(r':\s*"([A-Za-z]+)"', pi_block.group(1)))

    wired_agents: set = set()
    claude_arm_events: set = set()
    for row in _delivery_rows():
        for agent, arm in row["agents"].items():
            wired_agents.add(agent)
            if agent == "claude":
                assert arm["event"] in claude_events, (row["name"], arm)
                claude_arm_events.add(arm["event"])
            elif agent == "copilot":
                assert arm["event"] in copilot_map, (row["name"], arm)
            elif agent == "hermes":
                assert arm["method"] in hermes_hooks, (row["name"], arm)
            else:
                pytest.fail(f"unwired harness {agent!r} carries the delivery row "
                            f"{row['name']!r} — wire its surface or exempt it explicitly")

    # pi is wired through the adapter, not the manifest: its bridge must translate
    # exactly the pi delivery seams onto the same Claude spellings the manifest arms
    # carry — a dropped target silently delivers nothing to pi. Since P4 the start
    # seam is GONE (defer: before_agent_start + the per-turn context method, both on
    # the UserPromptSubmit spelling) — only the close seam maps to SessionEnd.
    assert pi_sources == {"before_agent_start", "session_shutdown"}
    assert pi_targets == {"UserPromptSubmit", "SessionEnd"}
    assert pi_targets <= claude_arm_events == {"SessionStart", "UserPromptSubmit",
                                               "SessionEnd"}
    # The unwired-harness safety scenario, asserted negatively (Rule 7 sc.2):
    # nothing outside the wired set carries mail.
    assert wired_agents == {"claude", "copilot", "hermes"}


# ---------------------------------------------------------------------------
# t7 — the @deferred Copilot close leg (plan item 7, Rule 6 sc.3)
# ---------------------------------------------------------------------------


def test_the_session_end_row_carries_the_copilot_session_end_arm(load_script):
    """Failure mode: the Copilot leg of cursor cleanup silently lost — P8's
    falsified hypothesis ('Copilot has no sessionEnd event') means the event
    EXISTS and must be wired, or Copilot cursors leak until the 4-day TTL.
    Mutation: delete the copilot arm from message-delivery-session-end, or
    re-spell its event sessionStart — both fail here."""
    row = next(r for r in _delivery_rows() if r["name"] == "message-delivery-session-end")
    copilot_arm = row["agents"].get("copilot")
    assert copilot_arm, "the @deferred Copilot close leg is open again"
    assert copilot_arm["type"] == "hooks-json"
    assert copilot_arm["entry"] == "hooks.json"
    assert copilot_arm["event"] == "sessionEnd"
    assert copilot_arm["script"] == "message_delivery_hook.py"
    # The arm must actually generate: the adjuster translates the spelling, and
    # the same row's claude leg still joins the SessionEnd precedent.
    assert "sessionEnd" in _copilot_event_map_keys()
    assert row["agents"]["claude"]["event"] == "SessionEnd"


# ---------------------------------------------------------------------------
# t8 — the spec sweep (plan item 8, review B5: 30 non-deferred scenarios)
# ---------------------------------------------------------------------------

#: Every scenario → the test ids (file::test) that own its pass condition
#: (plan §6 mapping + review §B4 cluster). The sweep verifies BOTH directions:
#: a parsed scenario with no owner fails, and a mapped owner that no longer
#: exists in its file fails — the checklist cannot rot silently.
SCENARIO_OWNERS = {
    # Rule 1 — Send requires full sender identity
    "Send with both identities is accepted": [
        "tests/test_message_bus_store.py::test_send_stamps_sender_identity_and_defaults_to_broadcast",
        "tests/test_send_message_skill.py::test_project_broadcast_send_lands_a_project_row",
    ],
    "Send without a projectId is rejected": [
        "tests/test_message_bus_store.py::test_send_without_project_id_is_refused_and_writes_no_row",
        "tests/test_send_message_skill.py::test_missing_sender_project_is_refused_no_row_no_traceback",
    ],
    # Rule 2 — A session never receives its own messages
    "Own broadcast stays invisible": [
        "tests/test_message_bus_store.py::test_deliver_suppresses_the_senders_own_messages",
        "tests/test_message_delivery_hook.py::test_self_suppression_reaches_the_script_surface",
    ],
    "Own project broadcast is still suppressed": [
        "tests/test_message_bus_store.py::test_deliver_suppresses_the_senders_own_messages",
        "tests/test_message_delivery_hook.py::test_self_suppression_reaches_the_script_surface",
    ],
    "Without suppression the sender echoes (mutation)": [
        "tests/test_message_bus_store.py::test_deliver_suppresses_the_senders_own_messages",
    ],
    # Rule 3 — Read and cursor advance share one transaction
    "Concurrent hooks deliver exactly once": [
        "tests/test_message_bus_store.py::test_concurrent_deliveries_inject_exactly_once",
        "tests/test_message_bus_integration.py::test_two_hook_processes_race_one_unread_message_exactly_once",
    ],
    "Hook crash between read and cursor write rolls back": [
        "tests/test_message_bus_store.py::test_hook_crash_between_read_and_commit_rolls_back",
    ],
    "Read moved outside the transaction double-delivers (mutation)": [
        "tests/test_message_bus_store.py::test_concurrent_deliveries_inject_exactly_once",
        "tests/test_message_bus_integration.py::test_two_hook_processes_race_one_unread_message_exactly_once",
    ],
    # Rule 4 — The first delivery gates history to the last 30 minutes
    "Recent messages reach a new session": [
        "tests/test_message_bus_store.py::test_first_delivery_gates_to_the_30_minute_window",
        "tests/test_message_delivery_hook.py::test_session_start_injects_recent_history_and_gates_the_ancient",
        "tests/test_message_bus_hermes.py::test_first_turn_gates_history_older_than_the_window",
    ],
    "A message exactly 30 minutes old is included": [
        "tests/test_message_bus_store.py::test_a_message_exactly_30_minutes_old_is_included",
    ],
    "Old history never reaches a new session": [
        "tests/test_message_bus_store.py::test_first_delivery_gates_to_the_30_minute_window",
        "tests/test_message_delivery_hook.py::test_session_start_injects_recent_history_and_gates_the_ancient",
    ],
    "A live delivery for a session without a cursor applies the gate": [
        "tests/test_message_bus_store.py::test_cursorless_live_read_applies_the_gate_once",
        "tests/test_message_delivery_hook.py::test_cursorless_per_turn_read_applies_the_gate_once",
        "tests/test_message_bus_hermes.py::test_pre_llm_without_a_cursor_applies_the_gate",
    ],
    # Rule 5 — Session-start delivery caps at 16 messages
    "A small inbox delivers whole": [
        "tests/test_message_bus_store.py::test_small_inbox_delivers_whole_in_chronological_order",
        "tests/test_message_bus_integration.py::"
        "test_send_script_then_hook_roundtrip_delivers_two_harnesses_schema_clean",
    ],
    "Exactly 16 holds the boundary": [
        "tests/test_message_bus_store.py::test_sixteen_messages_hold_the_boundary",
        "tests/test_message_delivery_hook.py::test_session_start_caps_at_sixteen_and_never_redelivers_overflow",
    ],
    "100 unread deliver the first 16 and drop the rest": [
        "tests/test_message_bus_store.py::test_overflow_beyond_sixteen_is_dropped_and_never_redelivered",
        "tests/test_message_bus_hermes.py::test_first_turn_caps_at_sixteen_and_the_overflow_never_returns",
    ],
    # Rule 6 — Cursors die on session close or after 4 days
    "Session close removes the cursor row": [
        "tests/test_message_bus_store.py::test_delete_cursor_removes_the_row",
        "tests/test_message_delivery_hook.py::test_session_end_removes_the_cursor",
        "tests/test_message_bus_manifest.py::test_the_wired_close_command_removes_the_cursor",
        "tests/test_message_bus_hermes.py::test_session_end_deletes_the_cursor",
        "tests/test_adjust_hooks_copilot.py::test_copilot_session_end_wires_cursor_cleanup",
        "tests/test_message_bus_integration.py::"
        "test_the_session_end_row_carries_the_copilot_session_end_arm",
    ],
    "A crashed session's cursor expires at 4 days": [
        "tests/test_message_bus_store.py::test_open_user_prunes_cursors_older_than_four_days",
        "tests/test_adjust_hooks_copilot.py::test_ttl_backstop_prunes_through_the_shipped_store_copy",
    ],
    "Close-event identification is verified per harness": [
        "tests/test_message_bus_manifest.py::test_the_copilot_close_event_verdict_is_recorded",
        "tests/test_message_bus_hermes.py::test_plugin_manifest_declares_the_close_event_and_register_wires_it",
        "tests/test_message_bus_integration.py::"
        "test_the_session_end_row_carries_the_copilot_session_end_arm",
    ],
    # Rule 7 — Every harness with hooks gets the delivery hook
    # (renamed from "pi session start delivers": P4 deferred the start seam)
    "pi delivery reaches a session": [
        "tests/js/pi_message_bus_adapter.test.mjs::E2E: a delivery payload delivers "
        "seeded mail through the real script into pi's message shape",
        "tests/test_pi_adjustments.py::test_adjust_hooks_copies_the_message_delivery_script_and_its_store",
        "tests/test_message_bus_integration.py::"
        "test_send_script_then_hook_roundtrip_delivers_two_harnesses_schema_clean",
    ],
    "A hooked harness without the wiring stays safe": [
        "tests/test_message_bus_manifest.py::test_no_unwired_harness_carries_the_delivery_rows",
        "tests/test_message_delivery_hook.py::test_unknown_event_is_a_clean_no_op",
        "tests/test_message_bus_integration.py::"
        "test_every_wired_arm_spelling_has_a_surface_on_its_harness",
    ],
    "A harness that claims delivery must not drop the event": [
        "tests/test_message_bus_manifest.py::test_hooks_json_commands_reconcile_with_the_manifest_rows",
        "tests/test_message_bus_manifest.py::test_claude_scaffold_wires_delivery_onto_all_three_events",
        "tests/test_adjust_hooks_copilot.py::test_wired_copilot_events_are_spellings_the_delivery_script_accepts",
    ],
    # Rule 8 — Project identity comes from the cwd resolver only
    "Same project directory matches": [
        "tests/test_message_delivery_hook.py::test_subdirectory_cwd_resolves_to_the_project_via_the_resolver",
        "tests/test_message_bus_hermes.py::test_project_delivery_resolves_the_process_cwd_through_the_project_id_walk",
    ],
    "Different directories resolving to one project id match": [
        "tests/test_message_delivery_hook.py::test_subdirectory_cwd_resolves_to_the_project_via_the_resolver",
        "tests/test_send_message_skill.py::test_sender_project_resolves_from_the_walked_project_id",
        "tests/test_message_bus_hermes.py::test_project_delivery_resolves_the_process_cwd_through_the_project_id_walk",
    ],
    "A second derivation would miss messages (mutation)": [
        "tests/test_message_delivery_hook.py::test_subdirectory_cwd_resolves_to_the_project_via_the_resolver",
        "tests/test_message_bus_hermes.py::test_project_delivery_resolves_the_process_cwd_through_the_project_id_walk",
    ],
    # Rule 9 — Old stores fail closed against bus tables
    "An old store refuses the new schema": [
        "tests/test_message_bus_store.py::test_stamped2_db_refuses_old_code_naming_den_refresh",
    ],
    "Old store, no bus tables — feature simply absent": [
        "tests/test_message_bus_store.py::test_pre_bus_db_without_bus_tables_opens_unchanged_under_old_code",
    ],
    "Half-reading a bus table is the failure signature (mutation)": [
        "tests/test_message_bus_store.py::test_stamped2_db_refuses_old_code_naming_den_refresh",
    ],
    # Rule 10 — Messages live 4 days
    "Old messages are pruned": [
        "tests/test_message_bus_store.py::test_open_user_prunes_messages_older_than_four_days",
        "tests/test_adjust_hooks_copilot.py::test_ttl_backstop_prunes_through_the_shipped_store_copy",
    ],
    "A message at the 4-day boundary survives until the window closes": [
        "tests/test_message_bus_store.py::"
        "test_a_message_exactly_four_days_old_survives_until_the_window_closes",
    ],
    "Unbounded growth is the failure signature (mutation)": [
        "tests/test_message_bus_store.py::test_open_user_prunes_messages_older_than_four_days",
    ],
    # @deferred Rule — discharged: the four harness close-event verdicts are
    # recorded (P5/P6/P7/P8 legs, consolidated in the plan §7 log)
    "Per-harness close event recorded": [
        "tests/test_message_bus_manifest.py::test_the_copilot_close_event_verdict_is_recorded",
        "tests/test_message_bus_hermes.py::test_plugin_manifest_declares_the_close_event_and_register_wires_it",
        "tests/test_message_bus_integration.py::"
        "test_the_session_end_row_carries_the_copilot_session_end_arm",
    ],
}


def _parse_feature_scenarios() -> list[tuple[str, str, bool]]:
    """Tiny Scenario:/Rule: parser — [(rule, scenario, deferred)]. Fails on a
    duplicate title (owners key by title; a silent merge would hide a rule)."""
    seen: set = set()
    parsed = []
    pending_deferred = False
    rule, deferred = "", False
    for line in (ROOT / FEATURE_PATH).read_text().splitlines():
        stripped = line.strip()
        if stripped == "@deferred":
            pending_deferred = True
        elif stripped.startswith("Rule:"):
            rule, deferred = stripped[len("Rule:"):].strip(), pending_deferred
            pending_deferred = False
        elif stripped.startswith("Scenario:"):
            name = stripped[len("Scenario:"):].strip()
            assert name not in seen, f"duplicate scenario title: {name!r}"
            seen.add(name)
            parsed.append((rule, name, deferred))
    return parsed


#: The sweep's spine: every scenario title of the feature, keyed to its @deferred
#: flag. The spec file is gitignored (it lives in the tracking scaffold, not the
#: tree CI checks out), so the list is inline; where the file EXISTS the parser
#: cross-checks both directions, so the inline list cannot rot unnoticed.
CANONICAL_SCENARIOS = {
    "Send with both identities is accepted": False,
    "Send without a projectId is rejected": False,
    "Own broadcast stays invisible": False,
    "Own project broadcast is still suppressed": False,
    "Without suppression the sender echoes (mutation)": False,
    "Concurrent hooks deliver exactly once": False,
    "Hook crash between read and cursor write rolls back": False,
    "Read moved outside the transaction double-delivers (mutation)": False,
    "Recent messages reach a new session": False,
    "A message exactly 30 minutes old is included": False,
    "Old history never reaches a new session": False,
    "A live delivery for a session without a cursor applies the gate": False,
    "A small inbox delivers whole": False,
    "Exactly 16 holds the boundary": False,
    "100 unread deliver the first 16 and drop the rest": False,
    "Session close removes the cursor row": False,
    "A crashed session's cursor expires at 4 days": False,
    "Close-event identification is verified per harness": False,
    "pi delivery reaches a session": False,
    "A hooked harness without the wiring stays safe": False,
    "A harness that claims delivery must not drop the event": False,
    "Same project directory matches": False,
    "Different directories resolving to one project id match": False,
    "A second derivation would miss messages (mutation)": False,
    "An old store refuses the new schema": False,
    "Old store, no bus tables — feature simply absent": False,
    "Half-reading a bus table is the failure signature (mutation)": False,
    "Old messages are pruned": False,
    "A message at the 4-day boundary survives until the window closes": False,
    "Unbounded growth is the failure signature (mutation)": False,
    "Per-harness close event recorded": True,
}


def test_every_non_deferred_spec_scenario_has_an_owner():
    """Failure mode: a pass-condition scenario with no owning test — coverage
    lost when a rule changes and no test follows (review B5's Phase-4 artefact).
    Mutation: delete any owner entry, add an unmapped scenario to the feature,
    or rename an owning test — the sweep fails on each."""
    non_deferred = [n for n, d in CANONICAL_SCENARIOS.items() if not d]
    deferred = [n for n, d in CANONICAL_SCENARIOS.items() if d]
    assert len(non_deferred) == 30, len(non_deferred)  # the F3 count, pinned
    assert len(deferred) == 1, deferred

    spec = ROOT / FEATURE_PATH
    if spec.exists():
        parsed = _parse_feature_scenarios()
        parsed_map = {name: flag for _, name, flag in parsed}
        if parsed_map != CANONICAL_SCENARIOS:
            inline_only = sorted(set(CANONICAL_SCENARIOS) - set(parsed_map))
            spec_only = sorted(set(parsed_map) - set(CANONICAL_SCENARIOS))
            flag_drift = sorted(name for name in parsed_map
                                if name in CANONICAL_SCENARIOS
                                and parsed_map[name] != CANONICAL_SCENARIOS[name])
            pytest.fail(f"the inline scenario list and the spec file diverge: "
                        f"inline-only={inline_only} spec-only={spec_only} "
                        f"flag-drift={flag_drift}")
    else:  # not in the CI tree — the inline spine still runs the owner sweep
        print(f"note: {FEATURE_PATH} absent; inline scenario list stands alone")

    orphan_owners = set(SCENARIO_OWNERS) - set(CANONICAL_SCENARIOS)
    assert not orphan_owners, \
        f"owners point at scenarios that no longer exist: {sorted(orphan_owners)}"

    for name, is_deferred in CANONICAL_SCENARIOS.items():
        owners = SCENARIO_OWNERS.get(name, [])
        tag = "@deferred " if is_deferred else ""
        assert owners, f"no owning test for {tag}scenario {name!r}"
        for owner in owners:
            rel, member = owner.split("::", 1)
            path = ROOT / rel
            assert path.exists(), f"{name!r}: owner file missing: {rel}"
            text = path.read_text()
            if rel.endswith(".py"):
                assert f"def {member}(" in text, f"{name!r}: owner test missing: {owner}"
            else:
                assert member in text, f"{name!r}: owner test missing: {owner}"

# ---------------------------------------------------------------------------
# B8 — the deployment shape: the full wire response through a real child process
# ---------------------------------------------------------------------------


def test_the_deployed_child_carries_the_bus_summary_on_the_full_response(
        user_root, tmp_path):
    """B8's deployment half: the hook as a host actually runs it — a child process fed
    the Claude-shaped payload, stdout parsed — carries the txn's wake summary on the
    full advisory response (aiBadgerBus alongside hookEventName + additionalContext),
    and the clean-empty follow-up firing stays exactly {} — no envelope, no zero-count
    summary (the TS negative-watermark logic keys on the ABSENT field)."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _make_project(repo_dir)
    with contextlib.closing(badger_store.open_user()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj", content="direct",
                           target_session="S-child")
        store.send_message(sender_session="S1", sender_project="bus-proj", content="everyone")

    env = {k: v for k, v in os.environ.items()
           if k not in (PROJECT_ID_ENV, HOLD_ENV, HOLD_ARMED_ENV, PROJECT_DIR_ENV)}
    env[USER_ROOT_ENV] = os.environ[USER_ROOT_ENV]
    payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "S-child",
                          "cwd": str(repo_dir)}).encode()
    proc = subprocess.run([sys.executable, str(ROOT / HOOK_PATH)], input=payload,
                          capture_output=True, env=env, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr.decode()[-400:]
    response = json.loads(proc.stdout.decode())
    assert set(response["hookSpecificOutput"]) == {"hookEventName", "additionalContext",
                                                   "aiBadgerBus"}
    assert response["hookSpecificOutput"]["aiBadgerBus"] == {"addressed": 1, "broadcast": 1}
    assert [d["content"] for d in _documents_of(response)] == ["direct", "everyone"]

    proc = subprocess.run([sys.executable, str(ROOT / HOOK_PATH)], input=payload,
                          capture_output=True, env=env, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr.decode()[-400:]
    assert json.loads(proc.stdout.decode()) == {}, "clean-empty stays exactly {}"
