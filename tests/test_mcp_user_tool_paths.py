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
from unittest.mock import patch

import pytest
from conftest import _test_write

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


def _scaf(make_scaffolder, root, target, config):
    index_path = root / "index.json"
    if not index_path.exists():
        _test_write(index_path, json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    return make_scaffolder(root=root, target=target, config=config)


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
    _test_write(exe, "#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


def _mcp_json_for(make_scaffolder, tmp_path, servers, agents=None):
    """Run _generate_mcp_json over *servers* and return (scaffolder, mcpServers dict)."""
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    py_dir = tmp_path / "features" / "python"
    py_dir.mkdir(parents=True, exist_ok=True)
    _test_write(py_dir / "stack-mcp.json", json.dumps({"servers": [dict(s, declare=True) for s in servers]}), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents))
    scaf.mcp.generate_mcp_json()
    written = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    return scaf, written["mcpServers"]


# ── the rewrite ──────────────────────────────────────────────────────────────

def test_dotnet_tool_becomes_home_relative(tmp_path, monkeypatch, load_script, make_scaffolder):
    """A bare command found in ~/.dotnet/tools is emitted as ${HOME}/.dotnet/tools/<name>."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")

    _, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "roslyn", "command": "cwm-roslyn-navigator"}])

    assert servers["roslyn"]["command"] == "${HOME}/.dotnet/tools/cwm-roslyn-navigator"


def test_local_bin_tool_becomes_home_relative(tmp_path, monkeypatch, load_script, make_scaffolder):
    """A bare command found in ~/.local/bin is emitted as ${HOME}/.local/bin/<name>."""
    _, local = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(local, "some-user-tool")

    _, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "user-tool", "command": "some-user-tool"}])

    assert servers["user-tool"]["command"] == "${HOME}/.local/bin/some-user-tool"


def test_system_tool_on_path_is_left_bare(tmp_path, monkeypatch, load_script, make_scaffolder):
    """python3 resolves outside the user tool dirs — it must stay bare and portable."""
    if shutil.which("python3") is None:
        pytest.skip("python3 not on PATH")
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)

    scaf, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "sys", "command": "python3"}])

    assert servers["sys"]["command"] == "python3"
    assert not [n for n in scaf.notes if "python3" in n]


def test_command_with_a_path_separator_is_untouched(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """An already-pathed command is the author's explicit choice."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")

    _, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "roslyn", "command": "/opt/bin/cwm-roslyn-navigator"}])

    assert servers["roslyn"]["command"] == "/opt/bin/cwm-roslyn-navigator"


def test_already_expandable_command_is_untouched(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """A command already written as ${...} is never rewritten a second time."""
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)

    _, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "roslyn", "command": "${HOME}/.dotnet/tools/cwm-roslyn-navigator"}])

    assert servers["roslyn"]["command"] == "${HOME}/.dotnet/tools/cwm-roslyn-navigator"


def test_unresolvable_command_is_noted(tmp_path, monkeypatch, load_script, make_scaffolder):
    """A command that resolves nowhere must be reported, not silently written."""
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)

    scaf, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "ghost", "command": "definitely-not-installed-anywhere"}])

    assert servers["ghost"]["command"] == "definitely-not-installed-anywhere"
    note = next(n for n in scaf.notes if "definitely-not-installed-anywhere" in n)
    assert "ghost" in note
    assert "fail to start" in note


def test_availability_override_all_skips_the_filesystem_probe(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """`=all` must be host-independent: no probe, no rewrite, no not-found note.

    The freshness guard re-scaffolds with AI_BADGER_MCP_AVAILABILITY=all so the comparison
    is deterministic, but the ${HOME} rewrite probed the host filesystem: a command found in
    a user tool dir on the author's machine became `${HOME}/...` while the same tree on CI
    (binary absent) kept the bare command — making .github/mcp.json's #193 verdict depend on
    the host (guard failed on main after #300; same latent bug). `=all` means every declared
    server is available: commands stay exactly as declared, and nothing is "not found".
    """
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")

    scaf, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "user-tool", "command": "some-user-tool"},
        {"name": "ghost", "command": "definitely-not-installed-anywhere"}])

    assert servers["user-tool"]["command"] == "some-user-tool"
    assert servers["ghost"]["command"] == "definitely-not-installed-anywhere"
    assert not any("fail to start" in n for n in scaf.notes)


def test_availability_override_none_still_probes_and_notes(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """`=none` is not a determinism override: the normal probe and note stay.

    `=none` declines every server, so nothing reaches the generated file — the rewrite path
    is exercised directly instead, and must still probe and note like a normal run.
    """
    _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "none")
    scaf = _scaf(make_scaffolder, tmp_path, tmp_path / "proj", _config())

    rewritten = scaf.mcp._home_relative_command("ghost", "definitely-not-installed-anywhere")

    assert rewritten == "definitely-not-installed-anywhere"
    assert any("fail to start" in n for n in scaf.notes)


def test_availability_override_all_keeps_hermes_in_both_mcp_files(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """Under `=all` the two files agree on hermes, so #193 does not drop it — the same
    tree every host produces, which is what the freshness guard commits."""
    dotnet, local = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(local, "hermes")
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    py_dir = tmp_path / "features" / "python"
    py_dir.mkdir(parents=True, exist_ok=True)
    _test_write(py_dir / "stack-mcp.json", json.dumps({"servers": [
            {"name": "code-review-graph", "command": "code-review-graph serve", "declare": True},
            {"name": "hermes", "command": "hermes mcp serve", "declare": True}]}), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["claude", "copilot"]))
    scaf.mcp.generate_mcp_json()
    project, _ = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_json(project)

    copilot = json.loads((target / ".github" / "mcp.json").read_text(encoding="utf-8"))
    assert "hermes" in copilot["mcpServers"]


def test_args_are_preserved_through_the_rewrite(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """Only the executable is rewritten; its arguments survive intact."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "sometool")

    _, servers = _mcp_json_for(make_scaffolder, tmp_path, [
        {"name": "flagged", "command": "sometool --flag"}])

    assert servers["flagged"]["command"] == "${HOME}/.dotnet/tools/sometool"
    assert servers["flagged"]["args"] == ["--flag"]


def test_multiword_command_rewrites_its_executable(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """A user-tool command with inline arguments still probes its executable."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "sometool")
    scaf = _scaf(make_scaffolder, tmp_path, tmp_path / "proj", _config())

    assert scaf.mcp._home_relative_command("flagged", "sometool --flag") == (
        "${HOME}/.dotnet/tools/sometool --flag")


# ── scope of the rewrite ─────────────────────────────────────────────────────

def test_a_rewritten_command_leaves_the_copilot_file_undeclared(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """`${HOME}` is documented for `.mcp.json` and for nothing Copilot reads, and Copilot reads
    `.mcp.json` — so the rewrite makes this the one file that declares the server (#193)."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["copilot"]))
    scaf.mcp.generate_copilot_mcp_json(
        {"roslyn": {"name": "roslyn", "command": "cwm-roslyn-navigator"}})

    assert not (target / ".github" / "mcp.json").exists()
    assert any("roslyn" in note and "193" in note for note in scaf.notes)


def test_the_claude_user_proposal_keeps_the_bare_command(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """Only .mcp.json documents ${VAR} expansion — the ~/.claude proposal names the command bare."""
    dotnet, _ = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    _install(dotnet, "cwm-roslyn-navigator")
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["claude"]))
        scaf.mcp.propose_claude_mcp_user(
            {"roslyn": {"name": "roslyn", "command": "cwm-roslyn-navigator", "scope": "user"}})

    proposal = [n for n in scaf.notes if "~/.claude/settings.json" in n]
    assert len(proposal) == 1
    assert '"command": "cwm-roslyn-navigator"' in proposal[0]
    assert not (home / ".claude").exists()
