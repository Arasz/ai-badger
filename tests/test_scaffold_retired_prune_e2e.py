"""End to end: a consumer scaffolded before a server was retired is cleaned by one refresh.

Runs ``Scaffolder.run()`` on the real catalog with HOME redirected and
``AI_BADGER_MCP_AVAILABILITY=all``. Every seed of the retired server comes from
the one ``tests/fixtures/retired-*-shapes.json``, whose ``_source`` names the commit or file each
seed was read from; this module never spells the server's name itself (ADR-0048 keeps it out of
the source tree).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT, _test_write as _raw_write
from scaffold_helpers import SCAFFOLD_SCRIPT, _config, build_scaffolder

pytestmark = pytest.mark.retired_prune

# Found by pattern: the fixture's file name carries the server's name.
(FIXTURE_PATH,) = (ROOT / "tests" / "fixtures").glob("retired-*-shapes.json")
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
NAME = FIXTURE["name"]
SKILL = FIXTURE["skill"]
SHAPES = {shape["id"]: shape for shape in FIXTURE["shapes"]}
MCP_FILES = (".mcp.json", ".github/mcp.json", ".pi/mcp.json")
MINE = {"command": "mine-mcp", "args": ["--port", "9"]}
ALLOW_RULE = f"mcp__{NAME}__*"
_INDEX = {}


def _test_write(path: Path, text: str) -> None:
    """``conftest._test_write`` behind a parent ``mkdir``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _raw_write(path, text)


def _guarded(skill: str, script: str) -> dict:
    """A hook entry in the guarded command shape hook wiring writes for *skill*'s *script*."""
    rel = f".ai-badger/skills/{skill}/scripts/{script}"
    command = (f'if [ -f "${{CLAUDE_PROJECT_DIR}}/{rel}" ]; then python3 '
               f'"${{CLAUDE_PROJECT_DIR}}/{rel}"; elif [ -f "{rel}" ]; then python3 "{rel}"; '
               f'else echo \'{{"systemMessage": "ai-badger: {rel} not found - hook skipped"}}\'; '
               f'fi')
    return {"hooks": [{"type": "command", "command": command}]}


@pytest.fixture(name="scaffold")
def _scaffold(load_script, root, tmp_path, monkeypatch):
    """Run the real scaffold over ``tmp_path/proj``; returns ``run(agents, skills) -> notes``."""
    import badger_lib as bl  # pylint: disable=import-outside-toplevel
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    if "index" not in _INDEX:
        _INDEX["index"] = load_script("tooling/index_build.py").build_index(root)
    monkeypatch.setattr(bl, "read_index", lambda _: _INDEX["index"])
    module = load_script(SCAFFOLD_SCRIPT)
    target = tmp_path / "proj"
    target.mkdir()

    def _run(agents, skills=()):
        result = build_scaffolder(module, root=root, target=target,
                                  config=_config(stacks=["python"], agents=list(agents)),
                                  skills=list(skills)).run()
        return list(result["notes"])

    _run.target = target
    return _run


def _seed(target: Path, shape: dict, agents, files=MCP_FILES, hooks=None) -> None:
    """A consumer as an 0.217 scaffold left it: the server, its approvals and its hook."""
    for rel in files:
        _test_write(target / rel, json.dumps(
            {"mcpServers": {NAME: shape["files"][rel], "mine": dict(MINE)}}, indent=2) + "\n")
    events = {"PostToolUse": [FIXTURE["claude_hook"]["PostToolUse"]]}
    for event, entries in (hooks or {}).items():
        events.setdefault(event, []).extend(entries)
    _test_write(target / ".claude" / "settings.json", json.dumps({
        "enabledMcpjsonServers": [NAME],
        "permissions": {"allow": [ALLOW_RULE]},
        "hooks": events,
    }, indent=2) + "\n")
    _test_write(target / ".ai-badger" / "manifest.json", json.dumps({
        "frameworkVersion": "0.217.3", "agents": list(agents), "entries": []}, indent=2) + "\n")


def _section(target: Path, rel: str) -> dict:
    return json.loads((target / rel).read_text(encoding="utf-8"))["mcpServers"]


def _hook_commands(target: Path) -> list:
    hooks = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [hook.get("command", "") for entries in hooks.get("hooks", {}).values()
            for entry in entries for hook in entry.get("hooks", [])]


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_an_old_consumer_is_cleaned(shape, scaffold):
    """Any of the four shipped launches: MCP entries and the hook go, approvals are reported."""
    agents = ["claude", "copilot", "pi"]
    target = scaffold.target
    _seed(target, SHAPES[shape], agents)

    notes = scaffold(agents)

    for rel in MCP_FILES:
        section = _section(target, rel)
        assert NAME not in section, f"{rel} kept the {shape} entry"
        assert section["mine"] == MINE, f"{rel} lost the user's server"
    assert [c for c in _hook_commands(target) if SKILL in c] == [], "the dead hook is still wired"
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert NAME in settings["enabledMcpjsonServers"]
    assert ALLOW_RULE in settings["permissions"]["allow"]
    assert [n for n in notes if "enabledMcpjsonServers" in n and ALLOW_RULE in n], \
        "no note names the stale approvals"


def test_a_cleaned_consumer_is_stable(scaffold):
    """A second refresh changes no byte of the four files the prune touches."""
    agents = ["claude", "copilot", "pi"]
    target = scaffold.target
    _seed(target, SHAPES["shape4"], agents)
    scaffold(agents)
    watched = (*MCP_FILES, ".claude/settings.json")
    before = {rel: (target / rel).read_bytes() for rel in watched}

    scaffold(agents)

    assert [rel for rel in watched if (target / rel).read_bytes() != before[rel]] == []


def test_a_partial_skills_run_keeps_catalogued_hooks(scaffold):
    """`skills=["task"]` leaves send-message undelivered; its hook stays, the dead one goes."""
    target = scaffold.target
    send = _guarded("send-message", "message_delivery_hook.py")
    task = _guarded("task", "stop_hook.py")
    _seed(target, SHAPES["shape4"], ["claude"], files=(".mcp.json",),
          hooks={"Stop": [send, task]})

    scaffold(["claude"], skills=["task"])

    commands = _hook_commands(target)
    assert [c for c in commands if "/send-message/scripts/message_delivery_hook.py" in c], \
        "the hook of a catalogued skill was removed"
    assert NAME not in _section(target, ".mcp.json"), ".mcp.json kept the retired entry"
    assert [c for c in commands if SKILL in c] == [], "the dead hook is still wired"


def test_copilot_hooks_file_is_regenerated(scaffold):
    """The Copilot hooks file is rewritten whole, so an old hook there is already gone."""
    agents = ["claude", "copilot"]
    target = scaffold.target
    _seed(target, SHAPES["shape4"], agents, files=())
    hooks_file = target / ".github" / "hooks" / "ai-badger-hooks.json"
    _test_write(hooks_file, json.dumps(
        {"version": 1, "hooks": {"postToolUse": [FIXTURE["copilot_hook"]["postToolUse"]]}},
        indent=2) + "\n")

    scaffold(agents, skills=["task"])

    text = hooks_file.read_text(encoding="utf-8")
    assert json.loads(text)["hooks"], "the regenerated file wires nothing"
    assert SKILL not in text


def test_a_copilot_only_consumer_is_cleaned(scaffold):
    """Copilot alone: both files it reads are cleaned of the shape-4 entry."""
    target = scaffold.target
    _seed(target, SHAPES["shape4"], ["copilot"], files=(".mcp.json", ".github/mcp.json"))

    scaffold(["copilot"])

    for rel in (".mcp.json", ".github/mcp.json"):
        section = _section(target, rel)
        assert NAME not in section, f"{rel} kept the retired entry"
        assert section["mine"] == MINE
