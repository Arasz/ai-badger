"""Hermes wiring for the user-DB message bus (P7, aib-user-db-message-bus).

The plugin surface is ai_badger_hooks.py plus the PLUGIN_YAML template in
features/hermes/adjustments/adjust_hooks.py: on_session_start delivers the gated,
capped history and stashes it (a session-start hook has no return channel into the
model), pre_llm_call surfaces the stash plus the live per-turn read, and
on_session_end deletes the session's cursor — the Hermes leg of the @deferred
close-event rule. Hermes payloads carry no cwd and no project identity, so cwd is the
process cwd at callback time and projectId comes only from the store resolver
(AI_BADGER_PROJECT_ID explicit-wins; otherwise the raccoon registry bank).

Every test runs against env-redirected roots — AI_BADGER_USER_ROOT moves the user DB,
AI_BADGER_RACCOON_DB names a synthetic bank — and the real ~/.ai-badger/ DBs are never
touched. The store under test is the copy the plugin actually loads: the vendored
badger_store.py beside ai_badger_hooks.py.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

SESSION = "sess-r"
OTHER = "sess-other"


# ---------------------------------------------------------------------------
# fixtures and helpers — env-redirected roots, the vendored store, hermes shapes
# ---------------------------------------------------------------------------


@pytest.fixture
def hooks(load_script):
    """A fresh plugin module per test: module-level stash state never leaks between tests."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def bus_env(tmp_path, monkeypatch):
    """Env-redirected roots and clean identity envs; tests opt into overrides per test."""
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    monkeypatch.delenv("AI_BADGER_PROJECT_ID", raising=False)
    monkeypatch.delenv("AI_BADGER_RACCOON_DB", raising=False)


@pytest.fixture
def bus(hooks, bus_env):
    """The badger_store module the plugin really loads — the vendored copy beside it."""
    return hooks._load_message_bus_store()


def _seed(bus, content, *, target_session=None, target_project=None,
          sender=OTHER, project="proj-other"):
    """Store one message as another session would have sent it; returns its row id."""
    store = bus.open_user()
    try:
        return store.send_message(sender_session=sender, sender_project=project,
                                  content=content, target_session=target_session,
                                  target_project=target_project)
    finally:
        store.close()


def _backdate(bus, message_id, *, days):
    """Rewrite one message's ts into the past — the gate tests' clock, no sleeps."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(bus.user_db_path())
    try:
        conn.execute("UPDATE messages SET ts = ? WHERE id = ?", (ts, message_id))
        conn.commit()
    finally:
        conn.close()


def _cursor_row(bus, session_id):
    """The session's cursor row, or None — read straight off the redirected DB."""
    conn = sqlite3.connect(bus.user_db_path())
    try:
        return conn.execute("SELECT cursor_id FROM cursors WHERE session_id = ?",
                            (session_id,)).fetchone()
    finally:
        conn.close()


def _start(hooks, session_id=SESSION):
    """Fire on_session_start the way Hermes does: kwargs only, no cwd in the payload."""
    return hooks.on_session_start_message_delivery(session_id=session_id, platform="cli")


def _turn(hooks, session_id=SESSION, prompt="what next?"):
    """Fire pre_llm_call the way Hermes does: the prompt is user_message, no cwd."""
    return hooks.pre_llm_inject_context(session_id=session_id, user_message=prompt,
                                        platform="cli")


def _close(hooks, session_id=SESSION):
    """Fire on_session_end the way Hermes does: session_id and nothing else."""
    return hooks.on_session_end_message_delivery(session_id=session_id)


def _context(result) -> str:
    return (result or {}).get("context", "")


def _make_project(directory, project_id: str):
    """Scaffold the minimum bus identity: <dir>/.ai-badger/project-id (ADR-0025)."""
    aib = directory / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "project-id").write_text(f"{project_id}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# the wiring itself — manifest rows and register() routing
# ---------------------------------------------------------------------------


def test_plugin_manifest_declares_the_close_event_and_register_wires_it(
        tmp_path, load_script, root):
    """The installed plugin.yaml must declare on_session_end in hooks AND provides_hooks.

    A manifest row without a registered callback never fires; a callback without the
    manifest row is invisible to Hermes' loader — the two lists must move together or
    the close-event cleanup silently does not exist on installed plugins.
    """
    import yaml

    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    target, home = tmp_path / "proj", tmp_path / "home"
    home.mkdir()
    context = {
        "framework_root": root,
        "config": {"agents": ["hermes"]},
        "feature_dir": root / "features" / "hermes" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
    }
    with patch("pathlib.Path.home", return_value=home):
        adjust_hooks.adjust(context)

    manifest = yaml.safe_load(
        (home / ".hermes" / "plugins" / "ai-badger" / "plugin.yaml").read_text("utf-8"))
    assert "on_session_end" in manifest["hooks"]
    assert "on_session_end" in manifest["provides_hooks"]


def test_register_wires_the_delivery_callbacks_onto_their_events(hooks):
    """Each delivery arm registers under the event Hermes actually fires — a callback
    nothing registers is the feature-shipped-but-plugin-inert defect the shipping-list
    test exists for, and the close arm is the one this wiring adds."""
    registered = []

    class _Ctx:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    hooks.register(_Ctx())

    starts = [cb for name, cb in registered if name == "on_session_start"]
    turns = [cb for name, cb in registered if name == "pre_llm_call"]
    ends = [cb for name, cb in registered if name == "on_session_end"]
    assert hooks.on_session_start_message_delivery in starts
    assert hooks.pre_llm_inject_context in turns
    assert hooks.on_session_end_message_delivery in ends


# ---------------------------------------------------------------------------
# session start — the gated, capped history delivery
# ---------------------------------------------------------------------------


def test_session_start_delivers_history_into_the_first_turn_exactly_once(
        hooks, bus, tmp_path, monkeypatch):
    """Start delivery reaches the FIRST turn's context and never a second one.

    The session-start hook has no return channel, so the stash is the only route to the
    model; a stash that survived its pop would re-inject the same history every turn.
    The cursor row is the secondary observable: start really delivered, not just stashed.
    """
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)
    _seed(bus, "standup moved to 3", target_session=SESSION)

    assert _start(hooks) is None
    assert _cursor_row(bus, SESSION) is not None

    first = _turn(hooks)
    assert "standup moved to 3" in _context(first)
    assert "standup moved to 3" not in _context(_turn(hooks))


def test_start_delivery_gates_history_older_than_the_window(
        hooks, bus, tmp_path, monkeypatch):
    """A two-day-old message must not reach a new session through the wiring — the gate
    lives in the store, but a callback that bypassed the start semantics would flood a
    fresh session with the whole backlog anyway."""
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)
    old_id = _seed(bus, "old news", target_session=SESSION)
    _backdate(bus, old_id, days=2)
    _seed(bus, "fresh news", target_session=SESSION)

    _start(hooks)
    context = _context(_turn(hooks))

    assert "fresh news" in context
    assert "old news" not in context


def test_start_delivery_caps_at_sixteen_and_the_overflow_never_returns(
        hooks, bus, tmp_path, monkeypatch):
    """Sixteen oldest in the window, the rest dropped, and a message sent after start
    still arrives — the cursor must land past the gated window, or the dropped tail
    floods the very next turn."""
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)
    for i in range(1, 21):
        _seed(bus, f"backlog-{i:02d}", target_session=SESSION)

    _start(hooks)
    first_lines = [line for line in _context(_turn(hooks)).splitlines()
                   if line.startswith("- backlog-")]
    assert len(first_lines) == 16
    assert first_lines[0].startswith("- backlog-01")
    assert first_lines[-1].startswith("- backlog-16")

    _seed(bus, "sent-after-start", target_session=SESSION)
    second = _context(_turn(hooks))
    assert "sent-after-start" in second
    assert "backlog-17" not in second


# ---------------------------------------------------------------------------
# pre_llm_call — the live per-turn delivery
# ---------------------------------------------------------------------------


def test_pre_llm_delivers_messages_that_arrive_after_start(
        hooks, bus, tmp_path, monkeypatch):
    """The per-turn leg: a message sent between turns reaches the next turn — start-only
    wiring would leave mid-session coordination permanently unseen."""
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)

    _start(hooks)
    assert "early word" not in _context(_turn(hooks))

    _seed(bus, "early word", target_session=SESSION)
    assert "early word" in _context(_turn(hooks))


def test_pre_llm_without_a_cursor_applies_the_gate(hooks, bus, tmp_path, monkeypatch):
    """A session whose start event never fired must not read the whole backlog on its
    first per-turn read — the D5 gate exists for exactly this harness skew."""
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)
    old_id = _seed(bus, "ancient backlog", target_session=SESSION)
    _backdate(bus, old_id, days=2)
    _seed(bus, "fresh direct", target_session=SESSION)
    assert _cursor_row(bus, SESSION) is None

    context = _context(_turn(hooks))

    assert "fresh direct" in context
    assert "ancient backlog" not in context
    assert _cursor_row(bus, SESSION) is not None


# ---------------------------------------------------------------------------
# identity — session id, cwd and the project resolver
# ---------------------------------------------------------------------------


def test_delivery_callbacks_without_a_session_id_do_nothing(
        hooks, bus, tmp_path, monkeypatch):
    """Hermes always sends session_id, but a shape drift that dropped it must degrade to
    a no-op, not a ValueError from the store escaping into the host loop."""
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)
    _seed(bus, "addressed mail", target_session=SESSION)

    assert _start(hooks, session_id="") is None
    assert hooks._bus_pending == {}
    assert "addressed mail" not in _context(_turn(hooks, session_id=""))
    assert _close(hooks, session_id="") is None


def test_project_delivery_uses_the_explicit_project_override(
        hooks, bus, tmp_path, monkeypatch):
    """AI_BADGER_PROJECT_ID is the resolver's explicit-wins rule — the project leg must
    ride it even where no registry knows the cwd, and must not leak other projects'
    mail or other sessions' 1:1 traffic."""
    anywhere = tmp_path / "anywhere"
    anywhere.mkdir()
    monkeypatch.chdir(anywhere)
    monkeypatch.setenv("AI_BADGER_PROJECT_ID", "proj-x")
    _seed(bus, "for proj-x", target_project="proj-x")
    _seed(bus, "for proj-y", target_project="proj-y")
    _seed(bus, "machine broadcast")
    _seed(bus, "not for me", target_session=OTHER)

    _start(hooks)
    context = _context(_turn(hooks))

    assert "for proj-x" in context
    assert "machine broadcast" in context
    assert "for proj-y" not in context
    assert "not for me" not in context


def test_project_delivery_resolves_the_process_cwd_through_the_project_id_walk(
        hooks, bus, tmp_path, monkeypatch):
    """Payloads carry no cwd, so the callback probes the process cwd and the store
    resolver decides — a second derivation (path hash, harness-side id) would select a
    different project and silently miss resolver-addressed messages."""
    project = tmp_path / "bus-repo"
    project.mkdir()
    _make_project(project, "proj-bus")
    monkeypatch.chdir(project)
    _seed(bus, "cross-directory ping", target_project="proj-bus",
          sender="sess-far", project="proj-bus")

    _start(hooks)
    assert "cross-directory ping" in _context(_turn(hooks))


def test_unresolved_project_delivers_one_to_one_only(hooks, bus, tmp_path, monkeypatch):
    """An unresolvable project must fail open to the 1:1 leg — refusing everything would
    drop direct mail, and guessing a project would read someone else's (D7)."""
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    _seed(bus, "direct ping", target_session=SESSION)
    _seed(bus, "project mail", target_project="proj-x")

    _start(hooks)
    context = _context(_turn(hooks))

    assert "direct ping" in context
    assert "project mail" not in context


def test_nested_projects_resolve_nearest_and_deliver_inner_only(hooks, bus, tmp_path, monkeypatch):
    """Nested .ai-badger dirs resolve nearest-wins (ADR-0025) — a session in the inner
    project receives the inner project's mail, never the outer's, plus its 1:1 leg."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    _make_project(outer, "proj-outer")
    _make_project(inner, "proj-inner")
    monkeypatch.chdir(inner)
    _seed(bus, "direct ping", target_session=SESSION)
    _seed(bus, "outer mail", target_project="proj-outer")
    _seed(bus, "inner mail", target_project="proj-inner")

    _start(hooks)
    context = _context(_turn(hooks))

    assert "direct ping" in context
    assert "outer mail" not in context
    assert "inner mail" in context


# ---------------------------------------------------------------------------
# session end — the close event (the @deferred rule's Hermes leg)
# ---------------------------------------------------------------------------


def test_session_end_deletes_the_cursor_and_drops_the_stash(
        hooks, bus, tmp_path, monkeypatch):
    """The close event is the cursor's primary death (the 4-day TTL is the backstop).

    This is the executable verification record for the Hermes leg of the @deferred
    close-event rule: on_session_end is registered (see the wiring tests) and invoking
    it removes the session's cursor row and any never-surfaced start stash.
    """
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)
    _seed(bus, "standup moved to 3", target_session=SESSION)
    _start(hooks)
    assert _cursor_row(bus, SESSION) is not None
    assert SESSION in hooks._bus_pending

    assert _close(hooks) is None

    assert _cursor_row(bus, SESSION) is None
    assert SESSION not in hooks._bus_pending


def test_session_end_without_a_cursor_is_a_clean_no_op(hooks, bus, tmp_path, monkeypatch):
    """Closing a session that never delivered — a misfired start, a crashed recovery —
    must not break shutdown: delete_cursor's absent-row path returns False and the
    callback returns None."""
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)

    assert _close(hooks) is None
    assert _cursor_row(bus, SESSION) is None


# ---------------------------------------------------------------------------
# fail-open — a broken bus never breaks a session (D31)
# ---------------------------------------------------------------------------


def test_a_store_error_never_escapes_any_delivery_callback(
        hooks, bus, tmp_path, monkeypatch):
    """D31/D7: a broken store must cost the session nothing — every callback returns
    cleanly, no stash appears, and the turn's OTHER injections still flow."""
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(bus, "open_user", _boom)
    project = tmp_path / "proj-a"
    project.mkdir()
    monkeypatch.chdir(project)

    assert _start(hooks) is None
    assert hooks._bus_pending == {}

    turn = _turn(hooks)
    assert turn is not None, "a dead bus must not take the rest of the hook down with it"
    assert "/usage" in turn.get("context", "")

    assert _close(hooks) is None
