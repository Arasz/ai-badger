# pylint: disable=redefined-outer-name  # pytest fixtures reuse param names by design
"""Tests for the message-bus delivery WIRING (P5, aib-user-db-message-bus).

P5 wires P4's shared delivery surface (features/common/hooks/message_delivery_hook.py)
into the hook-shaped harnesses via hooks-manifest.json + hooks.json; the script itself is
consumed UNCHANGED — these tests pin the wiring, not the delivery behaviour (that is
tests/test_message_delivery_hook.py) nor the store (tests/test_message_bus_store.py).

Test map (plan aib-user-db-message-bus §3 P5 · spec rules in parentheses):
  A. Manifest rows (Rule 7 sc.1, F2 fold) ...... test_manifest_routes_the_delivery_events_per_agent
  B. hooks.json reconciliation (#147 class) .... test_hooks_json_commands_reconcile_with_the_manifest_rows
  C. Chain-drop guard, wiring half (R7 sc.3) ... test_delivery_rows_are_unconditional_and_plugin_rooted
  D. Claude generated config (R7 sc.1 + R6) .... test_claude_scaffold_wires_delivery_onto_all_three_events
  E. Copilot generated config + verdict (F2) ... test_copilot_scaffold_wires_delivery_and_never_a_close_event,
                                                  test_the_copilot_close_event_verdict_is_recorded
  F. Unwired-harness safety (Rule 7 sc.2) ...... test_no_unwired_harness_carries_the_delivery_rows
  G. The wired command executes (F9 half) ...... test_the_wired_start_command_injects_history,
                                                  test_the_wired_close_command_removes_the_cursor
  H. Copy-skew for the wired copy .............. test_the_skill_copy_is_byte_identical_to_the_canonical_hook

Config-assertion vs execution (F9, plan-review finding): tests A–F and H are static config
assertions — they prove the rows exist, are unconditional, reconcile, and reach the
generated configs; they do NOT prove Claude or Copilot executes a hook at runtime. G
executes the exact command string the config carries (placeholder substituted) against an
env-redirected store, leaving only the host firing the event unproven — that residual is
P5's manual E2E note in the plan's §7 log and P9-t1's cross-package proof.

The one mandated mutation (§D, Rule 7 sc.2): a manifest WITHOUT the delivery rows — realised
as a foreign agent arm added to a delivery row — must red test F; run + kill + revert is
recorded in the lane report.

Deterministic mechanisms: env-redirected roots only (AI_BADGER_USER_ROOT moves the user DB,
AI_BADGER_RACCOON_DB points at a synthetic bank) — the real ~/.ai-badger/ and ~/.ai-raccoon/
stores are never touched; the raccoon-bank fixture is the P2 spike's pinned shape.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import badger_store
from conftest import ROOT

MANIFEST_PATH = "features/common/hooks/hooks-manifest.json"
HOOKS_JSON_PATH = "features/common/hooks/hooks.json"
CANONICAL_HOOK = "features/common/hooks/message_delivery_hook.py"
#: The wired copy hooks.json commands name — the path the scaffold rewriters know.
SKILL_COPY = "features/common/skills/send-message/scripts/message_delivery_hook.py"
SCRIPT_NAME = "message_delivery_hook.py"

SESSION_START_ROW = "message-delivery-session-start"
PER_TURN_ROW = "message-delivery-per-turn"
SESSION_END_ROW = "message-delivery-session-end"
DELIVERY_ROWS = (SESSION_START_ROW, PER_TURN_ROW, SESSION_END_ROW)

WIRING_SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"

PROJECT_ID_ENV = "AI_BADGER_PROJECT_ID"
RACCOON_BANK_ENV = "AI_BADGER_RACCOON_DB"
USER_ROOT_ENV = "AI_BADGER_USER_ROOT"
HOLD_ENV = "AI_BADGER_TEST_HOLD"
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"


# ---------------------------------------------------------------------------
# fixtures + helpers — env-redirected roots only; the real stores are never touched
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_bus_env(monkeypatch):
    """A developer shell must not poison the subprocess leg: the explicit project
    override, a real raccoon bank and a live test hold stay out unless a test sets them."""
    for var in (PROJECT_ID_ENV, RACCOON_BANK_ENV, HOLD_ENV, PROJECT_DIR_ENV):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def user_root(tmp_path, monkeypatch) -> Path:
    """The bus lives in a redirected user DB."""
    root = tmp_path / "user-root"
    monkeypatch.setenv(USER_ROOT_ENV, str(root))
    return root


def _manifest() -> dict:
    return json.loads((ROOT / MANIFEST_PATH).read_text(encoding="utf-8"))


def _hooks_json() -> dict:
    return json.loads((ROOT / HOOKS_JSON_PATH).read_text(encoding="utf-8"))


def _rows_by_name() -> dict:
    return {row["name"]: row for row in _manifest()["hooks"]}


def _arm(row_name: str, agent: str) -> dict:
    return _rows_by_name()[row_name]["agents"][agent]


def _delivery_commands(event: str) -> list[tuple[dict, str]]:
    """(entry, command) pairs across an event's entries whose command runs the delivery
    script — the same trailing-name match `select_hooks` and the Copilot adjuster use."""
    found = []
    for entry in _hooks_json()["hooks"].get(event, []):
        for hook in entry.get("hooks", []):
            if hook.get("command", "").rstrip('"').endswith(SCRIPT_NAME):
                found.append((entry, hook["command"]))
    return found


def _load(load_script, relpath):
    """Load a welcome-ai-badger script with its sibling modules importable — the
    context-enrichment E2E harness's loader, needed because hook_wiring imports
    scaffold_context from beside itself."""
    for entry in (str(ROOT / WIRING_SCRIPTS), str(ROOT / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(relpath)


def _register_bank(tmp_path, monkeypatch, surface: dict[str, list[str]]) -> Path:
    """A synthetic raccoon bank (the P2 spike's pinned shape) at a redirected path."""
    bank = tmp_path / "raccoon" / "memory.db"
    bank.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(bank)
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS watches (project_id TEXT NOT NULL, path TEXT NOT NULL, "
                 "created_at INTEGER NOT NULL, last_change_ts INTEGER NOT NULL)")
    conn.executemany(
        "INSERT OR REPLACE INTO settings VALUES (?, ?)",
        [(f"ingest.scope.{pid}", json.dumps(paths)) for pid, paths in surface.items()])
    conn.commit()
    conn.close()
    monkeypatch.setenv(RACCOON_BANK_ENV, str(bank))
    return bank


def _scaffold_send_message_scripts(target: Path, extra: dict[str, str]) -> Path:
    """The scaffolded skill scripts a wiring run needs: the REAL send-message pair (the
    existence check and the execution leg both resolve these) plus any named extras."""
    scripts_dir = target / ".ai-badger" / "skills" / "send-message" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name in (SCRIPT_NAME, "badger_store.py"):
        (scripts_dir / name).write_bytes((ROOT / "features/common/skills/send-message/scripts"
                                          / name).read_bytes())
    for rel, source in extra.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())
    return scripts_dir


# ---------------------------------------------------------------------------
# A. manifest rows route the three delivery events per agent (Rule 7 sc.1, F2 fold)
# ---------------------------------------------------------------------------


def test_manifest_routes_the_delivery_events_per_agent():
    """Each delivery row names every hook-capable agent with its own event spelling:
    Claude SessionStart/UserPromptSubmit/SessionEnd, Hermes on_session_start/pre_llm_call/
    on_session_end (P7's landed plugin callbacks, recorded per the #147 lesson), Copilot
    sessionStart/userPromptSubmitted (the F2 fold: one flat hooks array, one editor)."""
    expected = {
        SESSION_START_ROW: {
            "claude": {"type": "hooks-json", "entry": "hooks.json", "event": "SessionStart",
                       "script": SCRIPT_NAME},
            "hermes": {"type": "plugin", "entry": "ai_badger_hooks.py",
                       "method": "on_session_start"},
            "copilot": {"type": "hooks-json", "entry": "hooks.json", "event": "sessionStart",
                        "script": SCRIPT_NAME},
        },
        PER_TURN_ROW: {
            "claude": {"type": "hooks-json", "entry": "hooks.json", "event": "UserPromptSubmit",
                       "script": SCRIPT_NAME},
            "hermes": {"type": "plugin", "entry": "ai_badger_hooks.py",
                       "method": "pre_llm_call"},
            "copilot": {"type": "hooks-json", "entry": "hooks.json", "event": "userPromptSubmitted",
                        "script": SCRIPT_NAME},
        },
        SESSION_END_ROW: {
            "claude": {"type": "hooks-json", "entry": "hooks.json", "event": "SessionEnd",
                       "script": SCRIPT_NAME},
            "hermes": {"type": "plugin", "entry": "ai_badger_hooks.py",
                       "method": "on_session_end"},
        },
    }
    rows = _rows_by_name()
    for row_name, agents in expected.items():
        assert row_name in rows, f"missing manifest row {row_name}"
        for agent, arm in agents.items():
            assert rows[row_name]["agents"].get(agent) == arm, (row_name, agent)


# ---------------------------------------------------------------------------
# B. hooks.json carries the same rows (the #147/#152 silent-no-wire class)
# ---------------------------------------------------------------------------


def test_hooks_json_commands_reconcile_with_the_manifest_rows(load_script):
    """Every claude delivery arm selects exactly one command from the real hooks.json via
    the real selector — a manifest row whose script name matches nothing wires silently
    to nothing, which is the exact defect class issues #147/#152 shipped three times."""
    hook_wiring = _load(load_script, f"{WIRING_SCRIPTS}/hook_wiring.py")
    source_hooks = _hooks_json()["hooks"]
    for row_name in DELIVERY_ROWS:
        arm = _arm(row_name, "claude")
        selected = hook_wiring.select_hooks(source_hooks.get(arm["event"], []), arm["script"])
        commands = [h["command"] for entry in selected for h in entry.get("hooks", [])]
        assert len(commands) == 1, f"{row_name}: {arm['event']} selects {commands}"
        assert commands[0].rstrip('"').endswith(SCRIPT_NAME), commands[0]


# ---------------------------------------------------------------------------
# C. chain-drop guard, wiring half (Rule 7 sc.3): unconditional, plugin-rooted, resolvable
# ---------------------------------------------------------------------------


def test_delivery_rows_are_unconditional_and_plugin_rooted():
    """A claimed delivery step must execute, not be swallowed: no matcher on the entry (a
    matcher like startup|resume would drop compact/clear starts), the path sits under the
    ${CLAUDE_PLUGIN_ROOT}/features/common/skills/ prefix both rewriters rewrite, and the
    named file exists in-tree (a dangling command is a silent skip at scaffold time)."""
    for event in ("SessionStart", "UserPromptSubmit", "SessionEnd"):
        found = _delivery_commands(event)
        assert len(found) == 1, f"{event}: expected one delivery command, got {found}"
        entry, command = found[0]
        if event == "SessionStart":
            assert entry.get("matcher") == "startup|resume", entry
        else:
            assert "matcher" not in entry, f"{event}: delivery row sits behind matcher {entry['matcher']!r}"
        prefix = "${CLAUDE_PLUGIN_ROOT}/features/common/skills/"
        assert prefix in command, f"{event}: command is not plugin-rooted/rewriteable: {command}"
        in_tree = "features/common/skills/" + command.split(prefix, 1)[1].rstrip('"')
        assert (ROOT / in_tree).is_file(), f"{event}: command names a missing file: {in_tree}"


# ---------------------------------------------------------------------------
# D. Claude generated config carries the rows (Rule 7 sc.1; SessionEnd = the R6 close leg)
# ---------------------------------------------------------------------------


def _claude_settings(tmp_path, load_script, root):
    """Run the REAL HookWiring over the REAL manifest/hooks.json against a scaffold-shaped
    target; return the parsed .claude/settings.json."""
    ctx_mod = _load(load_script, f"{WIRING_SCRIPTS}/scaffold_context.py")
    bl = load_script("engine/badger_lib.py")
    hook_wiring = _load(load_script, f"{WIRING_SCRIPTS}/hook_wiring.py")
    target = tmp_path / "proj"
    _scaffold_send_message_scripts(target, {
        ".ai-badger/skills/mcp-index/scripts/context_enrichment_hook.py":
            root / "features/common/skills/mcp-index/scripts/context_enrichment_hook.py",
        ".ai-badger/skills/task/scripts/stop_hook.py":
            root / "features/common/skills/task/scripts/stop_hook.py",
    })
    config = {"$schema": "./schemas/config.schema.json", "agents": ["claude"], "stacks": []}
    ctx = ctx_mod.ScaffoldContext(
        root=root, target=target, aib=target / ".ai-badger", config=config,
        index={}, stacks=[], skills=[], excluded=bl.exclusions(config),
    )
    hook_wiring.HookWiring(ctx).wire()
    return json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_claude_scaffold_wires_delivery_onto_all_three_events(tmp_path, load_script, root):
    """The scaffolded settings.json runs the delivery script on SessionStart,
    UserPromptSubmit AND SessionEnd — the SessionEnd row is the Claude leg of the
    @deferred close-event verification (Rule 6 sc.3): the close event exists in-tree and
    routes to the script whose CLOSE_EVENTS drops the cursor (script half pinned by P4).
    Secondary observable: hooks already living on those events stay wired (no merge drop)."""
    settings = _claude_settings(tmp_path, load_script, root)
    wired = settings.get("hooks", {})

    def _script_of(command: str) -> str:
        """The script a wired command runs — guarded commands repeat the path, so take
        the first *.py match (the established _wired_scripts harness shape)."""
        match = re.search(r"([\w./-]+\.py)", command)
        return match.group(1).rsplit("/", 1)[-1] if match else ""

    for event in ("SessionStart", "UserPromptSubmit", "SessionEnd"):
        commands = [h.get("command", "") for entry in wired.get(event, [])
                    for h in entry.get("hooks", [])]
        delivery = [c for c in commands if _script_of(c) == SCRIPT_NAME]
        assert len(delivery) == 1, f"{event}: delivery wired {delivery}"
        rewritten = f"${'{CLAUDE_PROJECT_DIR}'}/.ai-badger/skills/send-message/scripts/{SCRIPT_NAME}"
        assert rewritten in delivery[0], f"{event}: path not rewritten to the scaffold: {delivery[0]}"
    # Secondary: shared-event neighbours survive the merge.
    for event, neighbour in (("UserPromptSubmit", "context_enrichment_hook.py"),
                             ("SessionEnd", "stop_hook.py")):
        commands = [h.get("command", "") for entry in wired.get(event, [])
                    for h in entry.get("hooks", [])]
        assert any(_script_of(c) == neighbour for c in commands), f"{event}: {neighbour} dropped"


# ---------------------------------------------------------------------------
# E. Copilot generated config + the recorded close-event verdict (F2 fold)
# ---------------------------------------------------------------------------


def test_copilot_scaffold_wires_delivery_and_never_a_close_event(tmp_path, load_script, root):
    """The Copilot config runs the delivery script on sessionStart and userPromptSubmitted
    — and carries NO close event: Copilot's hook inventory has none (the research verdict),
    and inventing one would claim a cleanup that never fires. Its cursors die by the
    4-day TTL backstop (store-level proof: tests/test_message_bus_store.py)."""
    adjust = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    _scaffold_send_message_scripts(target, {})
    result = adjust.adjust({
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["send-message"],
    })
    assert result["applied"], result
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    generated = hooks.get("hooks", {})
    for event in ("sessionStart", "userPromptSubmitted", "sessionEnd"):
        commands = [h.get("bash", "") for h in generated.get(event, [])]
        assert any(c.rstrip('"').endswith(SCRIPT_NAME) for c in commands), \
            f"{event}: delivery or close not wired"
    for event, commands in generated.items():
        if event in ("sessionStart", "userPromptSubmitted", "sessionEnd"):
            continue
        hits = [c for c in commands if SCRIPT_NAME in c.get("bash", "")]
        assert not hits, f"delivery leaked onto {event}"


def test_the_copilot_close_event_verdict_is_recorded(load_script):
    """The verdict is an executable record, not prose: Copilot DOES have a session-end
    event — P8 falsified the research hypothesis against two in-tree sources
    (tooling/validate.py's own task-checkpoint exemption text and changelog 0.50.0 both
    name Copilot's sessionEnd). The session-end row therefore reaches the copilot arm
    with the sessionEnd event, the generator's event_map carries it, and NO exemption
    remains — config-asserted here; the execution leg is P8's generated-artifact E2E."""
    validate = load_script("tooling/validate.py")
    agents = _rows_by_name()[SESSION_END_ROW]["agents"]
    copilot = agents.get("copilot")
    assert copilot, "the copilot close arm went missing — its cursors silently never clean up"
    assert copilot.get("event") == "sessionEnd", copilot
    exemptions = validate.HOOKS_MANIFEST_AGENT_EXEMPTIONS.get(SESSION_END_ROW, {})
    assert "copilot" not in exemptions, "a falsified absence must not keep its exemption"


# ---------------------------------------------------------------------------
# F. unwired-harness safety (Rule 7 sc.2) — the §D-mandated negative-row mutation target
# ---------------------------------------------------------------------------


def test_no_unwired_harness_carries_the_delivery_rows():
    """A harness without wiring must stay row-free: every agent arm running the delivery
    script belongs to a wired harness with that harness's own event/method spelling. The
    §D mutation (a foreign 'codex' arm on a delivery row) reds this; run + revert is
    recorded in the lane report."""
    wired_agents = {"claude", "hermes", "copilot"}
    for row in _manifest()["hooks"]:
        for agent, arm in row.get("agents", {}).items():
            runs_delivery = (arm.get("script") == SCRIPT_NAME
                             or arm.get("method") == "on_session_start_message_delivery")
            if not runs_delivery and not row["name"].startswith("message-delivery"):
                continue
            assert agent in wired_agents, \
                f"{row['name']}: delivery wired for unwired harness {agent!r}"
            if agent == "claude":
                assert arm.get("event") in ("SessionStart", "UserPromptSubmit", "SessionEnd")
            elif agent == "copilot":
                assert arm.get("event") in ("sessionStart", "userPromptSubmitted", "sessionEnd"), \
                    "copilot arms must use Copilot's own event spellings (sessionEnd is " \
                    "real per P8's falsified-hypothesis verdict)"
            elif agent == "hermes":
                assert arm.get("method") in ("on_session_start", "pre_llm_call",
                                             "on_session_end")


# ---------------------------------------------------------------------------
# G. the wired command executes (F9's execution half, placeholder substituted)
# ---------------------------------------------------------------------------


def _wired_command(event: str) -> str:
    """The exact command string hooks.json carries for the event's delivery row."""
    found = _delivery_commands(event)
    assert len(found) == 1, f"{event}: expected one delivery command, got {found}"
    return found[0][1]


def _fire_wired_command(tmp_path, monkeypatch, event: str, session_id: str,
                        repo_dir: Path) -> dict:
    """Run the config's own command (with ${CLAUDE_PLUGIN_ROOT} = this repo) as a host
    would: Claude-shaped stdin, JSON stdout, env-redirected stores. The interpreter is
    this test's python; everything else — path, script, contract — is the wired shape."""
    _register_bank(tmp_path, monkeypatch, {"bus-proj": [str(repo_dir)]})
    argv = shlex.split(_wired_command(event).replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT)))
    argv[0] = os.environ.get("AI_BADGER_TEST_PYTHON", "python3")
    env = {k: v for k, v in os.environ.items()
           if k not in (PROJECT_ID_ENV, HOLD_ENV)}
    env[USER_ROOT_ENV] = os.environ[USER_ROOT_ENV]
    env[RACCOON_BANK_ENV] = os.environ[RACCOON_BANK_ENV]
    env[PROJECT_DIR_ENV] = str(repo_dir)
    proc = subprocess.run(argv, input=json.dumps({
        "hook_event_name": event, "session_id": session_id,
        "cwd": str(repo_dir)}).encode(),
        capture_output=True, env=env, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr.decode()[-400:]
    return json.loads(proc.stdout.decode())


def _documents_of(response: dict) -> list[dict]:
    inner = response.get("hookSpecificOutput")
    assert isinstance(inner, dict), f"no hookSpecificOutput in {response}"
    context = inner.get("additionalContext")
    assert isinstance(context, str) and context, f"no additionalContext in {response}"
    return [json.loads(line) for line in context.splitlines()]


def test_the_wired_start_command_injects_history(user_root, tmp_path, monkeypatch):
    """The command a scaffolded settings.json carries injects unread project mail at
    SessionStart (Rule 7 sc.1, Claude leg) — through the SKILL copy, not the canonical
    hooks-dir file. Secondary observable: the cursor row exists afterwards (delivery
    advanced state; exactly-once has something to be exactly-once about)."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    with contextlib.closing(badger_store.open_user()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="wired start injection", target_project="bus-proj")
    response = _fire_wired_command(tmp_path, monkeypatch, "SessionStart", "S-receiver",
                                   repo_dir)
    assert [d["content"] for d in _documents_of(response)] == ["wired start injection"]
    with contextlib.closing(badger_store.open_user()) as store:
        row = store.conn.execute(
            "SELECT cursor_id FROM cursors WHERE session_id = ?", ("S-receiver",)).fetchone()
    assert row is not None, "start delivery left no cursor"


def test_the_wired_close_command_removes_the_cursor(user_root, tmp_path, monkeypatch):
    """The wired SessionEnd command is executable cursor cleanup (Rule 6 sc.1 through the
    wiring): after a start delivery created the cursor, the close firing removes it and
    answers parseable no-op JSON — the close-event verification record, executed."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    with contextlib.closing(badger_store.open_user()) as store:
        store.send_message(sender_session="S1", sender_project="bus-proj",
                           content="history", target_project="bus-proj")
    _fire_wired_command(tmp_path, monkeypatch, "SessionStart", "S-receiver", repo_dir)
    response = _fire_wired_command(tmp_path, monkeypatch, "SessionEnd", "S-receiver",
                                   repo_dir)
    assert response == {}, f"close should be a no-op response, got {response}"
    with contextlib.closing(badger_store.open_user()) as store:
        row = store.conn.execute(
            "SELECT cursor_id FROM cursors WHERE session_id = ?", ("S-receiver",)).fetchone()
    assert row is None, "the wired close command left the cursor behind"


# ---------------------------------------------------------------------------
# H. copy-skew for the wired copy
# ---------------------------------------------------------------------------


def test_the_skill_copy_is_byte_identical_to_the_canonical_hook():
    """hooks.json commands run the skill-dir copy; P4's canonical is the hooks-dir file.
    A canonical edit without re-landing the copy would wire sessions to yesterday's
    delivery logic — the P4-join lesson, pinned at the byte level."""
    canonical = (ROOT / CANONICAL_HOOK).read_bytes()
    copy = (ROOT / SKILL_COPY).read_bytes()
    assert copy == canonical, (
        f"{SKILL_COPY} drifted from {CANONICAL_HOOK} — re-land the copy in the same "
        f"commit as the canonical edit")
