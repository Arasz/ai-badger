"""The task-graph catalog packet and its declaration (plan S8, ADR-0014).

`task-graph` is the MCP server the `task-decomposition` skill drives. The catalog packet
describes it and `features/common/stack-mcp.json` declares it, so every scaffolded project
gets launch config written for it.

The declaration is deliberately **not** gated on `uv` being installed (plan DR3): an
availability miss would silently omit the entry from `.mcp.json`, so the prerequisite is
carried by the scaffold note instead. The two fixtures below control mcp_tools' PATH probe
and assert both halves — uv resolvable, and uv missing.
"""
from __future__ import annotations

import json
import shutil
import sys

import pytest

SERVER = "task-graph"
SERVER_DIR = f"features/common/mcp/{SERVER}"
SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
LAUNCH_SCRIPT = ".ai-badger/skills/task-decomposition/scripts/task_graph_server.py"
# The launch every file reader gets: `uv run --no-project python -c CODE`, where CODE walks up
# from the session's cwd to the nearest project script and runs it with `uv run --script`. Hosts
# spawn MCP servers in the session's cwd, and Claude Code leaves ${CLAUDE_PROJECT_DIR} unexpanded
# in `.mcp.json`, so the launch finds the project itself, with no shell and no git.
WALK_UP_CODE = (
    "import os,sys,subprocess;from pathlib import Path;"
    f"r='{LAUNCH_SCRIPT}';"
    "c=Path.cwd();"
    "f=next((d/r for d in (c,*c.parents) if (d/r).is_file()),None);"
    "f or sys.exit('task-graph: '+r+' not found at or above '+str(c));"
    "sys.exit(subprocess.call([os.environ.get('UV','uv'),'run','--script',str(f)]))"
)
WALK_UP_ARGS = ["run", "--no-project", "python", "-c", WALK_UP_CODE]
WALK_UP_LAUNCH = {"command": "uv", "args": WALK_UP_ARGS}
CLAUDE_ENTRY = COPILOT_ENTRY = {**WALK_UP_LAUNCH, "tools": ["*"]}
# The prerequisite text test_mcp_prerequisites.py requires every declared server to carry.
PREREQUISITE_SUMMARY = (
    "uv on PATH; the server and its pydantic env are fetched on first launch (PEP 723); "
    "the launch walks up from the session directory to the project, so any subdirectory works "
    "on every OS"
)
UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"
# Byte-for-byte what note_declared_prerequisites() renders for the meta.json this packet ships.
EXPECTED_NOTE = (
    f"prerequisite — {SERVER} needs {PREREQUISITE_SUMMARY}; check: uv --version; "
    f"install: {UV_INSTALL}; local: {UV_INSTALL}; global: {UV_INSTALL}. "
    "ai-badger declares the server, it does not install it."
)
FROZEN_TOOLS = [
    "plan_create", "plan_replace", "plan_get", "plan_export", "step_get", "step_start",
    "step_complete", "step_fail", "step_skip", "ac_check", "steps_ready",
    "progress_checklist",
]
EXPECTED_TAGS = {
    "plan_create": {"write", "build"},
    "plan_replace": {"write", "build"},
    "plan_get": {"read"},
    "plan_export": {"read", "files"},
    "step_get": {"read", "navigation"},
    "step_start": {"write"},
    "step_complete": {"write"},
    "step_fail": {"write", "diagnostic"},
    "step_skip": {"write"},
    "ac_check": {"write", "diagnostic"},
    "steps_ready": {"read", "navigation", "diagnostic"},
    "progress_checklist": {"read"},
}


def _config(agents):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": list(agents),
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaffold(make_scaffolder, agents):
    """One full scaffolding run, the note set left on ``scaf.ctx.notes``."""
    scaf = make_scaffolder(config=_config(agents), install=True)
    scaf.run(generated_at="2026-09-28T00:00:00Z")
    return scaf


def _servers(make_scaffolder, relative):
    path = make_scaffolder.target / relative
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]


class _ProbedShutil:
    """mcp_tools' ``shutil`` with a controlled ``which``; everything else is the real module."""

    def __init__(self, available):
        self._available = available

    def which(self, command, *args, **kwargs):  # noqa: ARG002 — shutil.which signature
        return f"/usr/bin/{command}" if command in self._available else None

    def __getattr__(self, name):
        return getattr(shutil, name)


def _control_path_probe(load_script, monkeypatch, available):
    """Patch only mcp_tools' own PATH probe, and its user-tool-dir scan with it."""
    load_script(SCAFFOLD)
    mcp_tools = sys.modules["mcp_tools"]
    monkeypatch.delenv("AI_BADGER_MCP_AVAILABILITY", raising=False)
    monkeypatch.setattr(mcp_tools, "USER_TOOL_DIRS", ())
    monkeypatch.setattr(mcp_tools, "shutil", _ProbedShutil(available))


@pytest.fixture
def uv_on_path(load_script, monkeypatch):
    _control_path_probe(load_script, monkeypatch, {"uv"})


@pytest.fixture
def uv_missing(load_script, monkeypatch):
    _control_path_probe(load_script, monkeypatch, set())


# ── the catalog packet ───────────────────────────────────────────────────────

def test_the_catalog_directory_carries_the_packet_files(root):
    server_dir = root / SERVER_DIR

    assert (server_dir / "meta.json").is_file()
    assert (server_dir / "server.md").is_file()
    assert (server_dir / "tools.json").is_file()
    meta = json.loads((server_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == server_dir.name == SERVER


def test_the_meta_declares_the_uv_prerequisite_and_no_package(root):
    """`uv run --script` is the only install step: nothing is distributed under a package name."""
    meta = json.loads((root / SERVER_DIR / "meta.json").read_text(encoding="utf-8"))

    assert "package" not in meta
    assert meta["prerequisite"]["summary"] == PREREQUISITE_SUMMARY
    assert meta["prerequisite"]["check"] == "uv --version"
    assert meta["prerequisite"]["install"] == UV_INSTALL
    for scope in ("local", "global"):
        assert meta["prerequisite"][scope]["check"] == "uv --version"
        assert meta["prerequisite"][scope]["install"] == UV_INSTALL


def test_the_meta_server_md_and_tools_validate_against_their_schemas(root, load_script):
    bl = load_script("engine/badger_lib.py")
    server_dir = root / SERVER_DIR

    meta = bl.load_json(server_dir / "meta.json")
    tools = bl.load_json(server_dir / "tools.json")
    assert bl.validate(meta, bl.load_json(root / "schemas" / "mcp-server.schema.json")) == []
    assert bl.validate(
        tools, bl.load_json(root / "schemas" / "mcp-server-tools.schema.json")) == []


def test_server_md_stays_within_the_line_budget(root):
    text = (root / SERVER_DIR / "server.md").read_text(encoding="utf-8")

    assert text.startswith(f"<!-- {SERVER} MCP tools -->")
    assert len(text.strip().splitlines()) <= 15


def test_the_curated_tools_are_the_frozen_twelve_with_closed_tags_and_bounded_intents(
        root, load_script):
    """The twelve frozen names, each intent short enough for the generated index it seeds."""
    bl = load_script("engine/badger_lib.py")
    taxonomy = bl.load_json(root / "features" / "common" / "mcp-tags.json")
    vocabulary = {tag for cat in taxonomy["categories"].values() for tag in cat["tags"]}
    tools = bl.load_json(root / SERVER_DIR / "tools.json")

    assert tools["server"] == SERVER
    assert [tool["name"] for tool in tools["tools"]] == FROZEN_TOOLS
    for tool in tools["tools"]:
        assert len(tool["intent"]) <= 200, tool["name"]
        assert tool["intent"].strip(), tool["name"]
        assert set(tool["tags"]) == EXPECTED_TAGS[tool["name"]], tool["name"]
        assert set(tool["tags"]) <= vocabulary, tool["name"]


# ── the declaration ──────────────────────────────────────────────────────────

def test_the_common_stack_declares_task_graph_without_an_availability_gate(root, load_script):
    """No availability gate: a miss would silently omit the entry (plan DR3)."""
    bl = load_script("engine/badger_lib.py")
    declaration = bl.load_json(root / "features" / "common" / "stack-mcp.json")
    entry = next(s for s in declaration["servers"] if s["name"] == SERVER)

    assert entry == {
        "name": SERVER,
        "command": "uv",
        "args": WALK_UP_ARGS,
        "declare": True,
    }
    assert bl.validate(
        declaration, bl.load_json(root / "schemas" / "stack-mcp.schema.json")) == []


def test_the_launch_code_survives_windows_command_line_quoting():
    """Windows re-quotes argv into one command line; these characters are what it mangles."""
    assert not set('"\\%^&|<>!') & set(WALK_UP_ARGS[-1])


def test_hermes_is_proposed_the_same_launch(make_scaffolder, uv_on_path):
    """Hermes gets no override: it walks up from its own working directory like the rest."""
    scaf = _scaffold(make_scaffolder, ["claude"])

    entry = scaf.mcp.declarations_for_agent("hermes")[SERVER]

    assert {key: entry[key] for key in ("command", "args")} == WALK_UP_LAUNCH


def test_the_index_lists_the_server(root, load_script):
    bl = load_script("engine/badger_lib.py")

    items = bl.feature_items(bl.read_index(root), "common", "mcp")

    assert {"name": SERVER, "path": SERVER_DIR} in items


# ── two fixtures, the prerequisite environment controlled ────────────────────

def test_with_uv_the_claude_declaration_is_written(make_scaffolder, uv_on_path):
    scaf = _scaffold(make_scaffolder, ["claude"])

    assert _servers(make_scaffolder, ".mcp.json")[SERVER] == CLAUDE_ENTRY
    assert not any(f"'{SERVER}'" in note and "was not found" in note for note in scaf.ctx.notes)


def test_with_uv_the_copilot_declaration_is_written(make_scaffolder, uv_on_path):
    scaf = _scaffold(make_scaffolder, ["copilot"])

    assert _servers(make_scaffolder, ".mcp.json")[SERVER] == COPILOT_ENTRY
    assert _servers(make_scaffolder, ".github/mcp.json")[SERVER] == COPILOT_ENTRY
    assert not any(f"'{SERVER}'" in note and "was not found" in note for note in scaf.ctx.notes)


def test_without_uv_the_declaration_is_still_written_and_the_note_is_exact(
        make_scaffolder, uv_missing):
    """The AC that makes DR3 falsifiable: no gate, and the warning is the note."""
    scaf = _scaffold(make_scaffolder, ["claude"])

    assert _servers(make_scaffolder, ".mcp.json")[SERVER] == CLAUDE_ENTRY
    # The probe really was controlled: without this the note could pass on a machine that has uv.
    assert any("'uv' was not found" in note for note in scaf.ctx.notes)
    prerequisite_notes = [n for n in scaf.ctx.notes if n.startswith(f"prerequisite — {SERVER} ")]
    assert prerequisite_notes == [EXPECTED_NOTE]


def test_the_combined_claude_copilot_scaffold_keeps_both_usable_entries(
        make_scaffolder, uv_on_path):
    """Copilot CLI reads both files; `.mcp.json` must not hide its entry.

    Both entries carry the same launch, so the one-declaration drop does not fire while uv
    resolves on PATH; it fires only when uv lives in a user tool dir (see the next test).
    """
    scaf = _scaffold(make_scaffolder, ["claude", "copilot"])

    assert _servers(make_scaffolder, ".mcp.json")[SERVER] == CLAUDE_ENTRY
    assert _servers(make_scaffolder, ".github/mcp.json")[SERVER] == COPILOT_ENTRY
    assert not any("declared only in" in note and SERVER in note for note in scaf.ctx.notes)


def test_the_pi_declaration_carries_the_same_launch(make_scaffolder, uv_on_path):
    _scaffold(make_scaffolder, ["pi"])

    entry = _servers(make_scaffolder, ".pi/mcp.json")[SERVER]
    assert {key: entry[key] for key in ("command", "args")} == WALK_UP_LAUNCH


def test_a_uv_in_the_user_tool_dir_is_declared_once_in_mcp_json(
        tmp_path, load_script, monkeypatch, make_scaffolder):
    """uv under `~/.local/bin` is home-relative, which only `.mcp.json` expands: one declaration."""
    load_script(SCAFFOLD)
    mcp_tools = sys.modules["mcp_tools"]
    monkeypatch.delenv("AI_BADGER_MCP_AVAILABILITY", raising=False)
    tool_dir = tmp_path / "fake-home" / ".local" / "bin"
    tool_dir.mkdir(parents=True)
    uv = tool_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setattr(mcp_tools, "USER_TOOL_DIRS", ((tool_dir, "${HOME}/.local/bin"),))
    monkeypatch.setattr(mcp_tools, "shutil", _ProbedShutil(set()))

    scaf = _scaffold(make_scaffolder, ["claude", "copilot"])

    assert _servers(make_scaffolder, ".mcp.json")[SERVER]["command"] == "${HOME}/.local/bin/uv"
    assert SERVER not in _servers(make_scaffolder, ".github/mcp.json")
    assert any("declared only in" in note and SERVER in note for note in scaf.ctx.notes)
