"""A bare MCP command that lives in a user tool directory must not depend on PATH.

`.mcp.json` is launched by whatever process starts the agent, which may never have sourced a
login shell profile — so `~/.dotnet/tools` and `~/.local/bin` are frequently absent from PATH
and the server silently never starts.  Commands found there are emitted as `${HOME}`-relative
paths, which Claude Code expands and which stay portable across machines.
"""
# pylint: disable=protected-access  # exercises the Scaffolder MCP mixin directly; see pyproject.toml
from __future__ import annotations

import json
import shutil
import sys

import pytest

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _config(agents=None):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaf(scaffold, root, target, config):
    index_path = root / "index.json"
    if not index_path.exists():
        index_path.write_text(
            json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    return scaffold.Scaffolder(root=root, target=target, config=config,
                               skills=[], install=False)


def _fake_tool_dirs(monkeypatch, load_script, tmp_path):
    """Point USER_TOOL_DIRS at empty tmp dirs; return (dotnet_dir, local_dir)."""
    load_script(SCAFFOLD)
    mcp_tools = sys.modules["mcp_tools"]
    dotnet = tmp_path / "fake-home" / ".dotnet" / "tools"
    local = tmp_path / "fake-home" / ".local" / "bin"
    dotnet.mkdir(parents=True)
    local.mkdir(parents=True)
    monkeypatch.setattr(mcp_tools, "USER_TOOL_DIRS", (
        (dotnet, "${HOME}/.dotnet/tools"),
        (local, "${HOME}/.local/bin"),
    ))
    return dotnet, local


def _install(directory, name):
    exe = directory / name
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


def _mcp_json_for(load_script, tmp_path, servers, agents=None):
    """Run _generate_mcp_json over *servers* and return (scaffolder, mcpServers dict)."""
    scaffold = load_script(SCAFFOLD)
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    py_dir = tmp_path / "features" / "python"
    py_dir.mkdir(parents=True, exist_ok=True)
    (py_dir / "mcp-servers.json").write_text(
        json.dumps({"servers": servers}), encoding="utf-8")

    scaf = _scaf(scaffold, tmp_path, target, _config(agents))
    scaf._generate_mcp_json()
    written = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    return scaf, written["mcpServers"]


# ── the rewrite ──────────────────────────────────────────────────────────────

def test_dotnet_tool_becomes_home_relative(tmp_path, monkeypatch, load_script):
    """A bare command found in ~/.dotnet/tools is emitted as ${HOME}/.dotnet/tools/<name>."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")

    _, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "roslyn", "command": "cwm-roslyn-navigator"}])

    assert servers["roslyn"]["command"] == "${HOME}/.dotnet/tools/cwm-roslyn-navigator"


def test_local_bin_tool_becomes_home_relative(tmp_path, monkeypatch, load_script):
    """A bare command found in ~/.local/bin is emitted as ${HOME}/.local/bin/<name>."""
    _, local = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(local, "some-user-tool")

    _, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "user-tool", "command": "some-user-tool"}])

    assert servers["user-tool"]["command"] == "${HOME}/.local/bin/some-user-tool"


def test_system_tool_on_path_is_left_bare(tmp_path, monkeypatch, load_script):
    """python3 resolves outside the user tool dirs — it must stay bare and portable."""
    if shutil.which("python3") is None:
        pytest.skip("python3 not on PATH")
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)

    scaf, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "sys", "command": "python3"}])

    assert servers["sys"]["command"] == "python3"
    assert not [n for n in scaf.notes if "python3" in n]


def test_command_with_a_path_separator_is_untouched(tmp_path, monkeypatch, load_script):
    """An already-pathed command is the author's explicit choice."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")

    _, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "roslyn", "command": "/opt/bin/cwm-roslyn-navigator"}])

    assert servers["roslyn"]["command"] == "/opt/bin/cwm-roslyn-navigator"


def test_already_expandable_command_is_untouched(tmp_path, monkeypatch, load_script):
    """A command already written as ${...} is never rewritten a second time."""
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)

    _, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "roslyn", "command": "${HOME}/.dotnet/tools/cwm-roslyn-navigator"}])

    assert servers["roslyn"]["command"] == "${HOME}/.dotnet/tools/cwm-roslyn-navigator"


def test_unresolvable_command_is_noted(tmp_path, monkeypatch, load_script):
    """A command that resolves nowhere must be reported, not silently written."""
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)

    scaf, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "ghost", "command": "definitely-not-installed-anywhere"}])

    assert servers["ghost"]["command"] == "definitely-not-installed-anywhere"
    note = next(n for n in scaf.notes if "definitely-not-installed-anywhere" in n)
    assert "ghost" in note
    assert "fail to start" in note


def test_args_are_preserved_through_the_rewrite(tmp_path, monkeypatch, load_script):
    """Only the executable is rewritten; its arguments survive intact."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "sometool")

    _, servers = _mcp_json_for(load_script, tmp_path, [
        {"name": "flagged", "command": "sometool --flag"}])

    assert servers["flagged"]["command"] == "${HOME}/.dotnet/tools/sometool"
    assert servers["flagged"]["args"] == ["--flag"]


# ── scope of the rewrite ─────────────────────────────────────────────────────

def test_copilot_config_keeps_the_bare_command(tmp_path, monkeypatch, load_script):
    """Copilot's MCP config uses ${input:}/${env:} syntax — a bare ${HOME} would not expand."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")
    scaffold = load_script(SCAFFOLD)
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)

    scaf = _scaf(scaffold, tmp_path, target, _config(agents=["copilot"]))
    scaf._generate_copilot_mcp_config(
        {"roslyn": {"name": "roslyn", "command": "cwm-roslyn-navigator"}})

    cfg = json.loads(
        (target / ".github" / "copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["roslyn"]["command"] == "cwm-roslyn-navigator"
