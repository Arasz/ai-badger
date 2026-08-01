"""One server, one declaration per host (issue #193).

Copilot CLI reads `.github/mcp.json` *and* `.mcp.json` (looked up from the cwd upward), and
their precedence is undocumented. A server the two files describe differently therefore has no
knowable configuration, so ai-badger never writes one: the entries are identical apart from
the destination-specific `tools` allowlist, and a server whose two renderings cannot be reconciled
is declared once, in `.mcp.json`, with a note.
"""
# pylint: disable=protected-access  # exercises the Scaffolder MCP mixin directly; see pyproject.toml
from __future__ import annotations

import json
import sys

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _config(agents=None):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": list(agents) if agents is not None else ["claude", "copilot"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaffold(make_scaffolder, tmp_path, servers, agents=None):
    """Declare *servers* and run both project MCP writers, in scaffold.run()'s order."""
    index_path = tmp_path / "index.json"
    if not index_path.exists():
        index_path.write_text(json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}),
                              encoding="utf-8")
    stack = tmp_path / "features" / "python"
    stack.mkdir(parents=True, exist_ok=True)
    (stack / "stack-mcp.json").write_text(
        json.dumps({"servers": [dict(srv, declare=True) for srv in servers]}), encoding="utf-8")

    scaf = make_scaffolder(root=tmp_path, target=make_scaffolder.target,
                           config=_config(agents))
    scaf.mcp.generate_mcp_json()
    project, _user = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_json(project)
    return scaf


def _servers_in(target, relative):
    path = target / relative
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]


def _mcp_json(target):
    return _servers_in(target, ".mcp.json")


def _github_mcp_json(target):
    return _servers_in(target, ".github/mcp.json")


def _fake_tool_dirs(monkeypatch, load_script, tmp_path):
    """Point USER_TOOL_DIRS at an empty tmp dir and return it."""
    load_script(SCAFFOLD)
    dotnet = tmp_path / "fake-home" / ".dotnet" / "tools"
    dotnet.mkdir(parents=True)
    monkeypatch.setattr(sys.modules["mcp_tools"], "USER_TOOL_DIRS",
                        ((dotnet, "${HOME}/.dotnet/tools"),))
    return dotnet


# ── the two files agree ──────────────────────────────────────────────────────

def test_the_two_files_declare_the_same_server_identically(
        tmp_path, make_scaffolder):
    """Precedence stops mattering when there is nothing for it to choose between."""
    target = make_scaffolder.target

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "pyright", "command": "uvx mcp-server-pyright",
         "env": {"TOKEN": "${MCP_TOKEN}"}}])

    ours = dict(_mcp_json(target)["pyright"])
    assert "cwd" not in ours
    assert ours == _github_mcp_json(target)["pyright"]


def test_a_stale_cwd_on_a_declared_server_does_not_survive_a_rescaffold(
        tmp_path, make_scaffolder):
    """#287: `.mcp.json` is tracked, so one machine's `cwd` must not outlive the refresh."""
    target = make_scaffolder.target
    servers = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    _scaffold(make_scaffolder, tmp_path, servers)

    path = target / ".mcp.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mcpServers"]["pyright"]["cwd"] = "/Users/someone-else/checkout"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    _scaffold(make_scaffolder, tmp_path, servers)

    assert "cwd" not in _mcp_json(target)["pyright"]


def test_a_server_ai_badger_does_not_declare_keeps_its_own_cwd(tmp_path, make_scaffolder):
    """The file is merged, not owned: a hand-added server's `cwd` is the author's to set."""
    target = make_scaffolder.target
    servers = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    _scaffold(make_scaffolder, tmp_path, servers)

    path = target / ".mcp.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mcpServers"]["hand-added"] = {"command": "serve", "cwd": "/srv/deliberate"}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    _scaffold(make_scaffolder, tmp_path, servers)

    assert _mcp_json(target)["hand-added"]["cwd"] == "/srv/deliberate"


def test_the_tools_allowlist_reaches_the_file_both_hosts_read(tmp_path, make_scaffolder):
    """`tools` is Copilot's key, and Copilot reads `.mcp.json`; Claude Code ignores it."""
    target = make_scaffolder.target

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}])

    assert _mcp_json(target)["pyright"]["tools"] == ["*"]


def test_a_command_with_spaces_is_split_the_same_way_in_both_files(tmp_path, make_scaffolder):
    """The two splitters disagreed on a command with no package-shaped argument; now one."""
    target = make_scaffolder.target

    _scaffold(make_scaffolder, tmp_path, [{"name": "hermes", "command": "hermes mcp serve"}])

    assert _mcp_json(target)["hermes"]["command"] == "hermes"
    assert _mcp_json(target)["hermes"]["args"] == ["mcp", "serve"]
    assert _github_mcp_json(target)["hermes"] == {
        "command": "hermes", "args": ["mcp", "serve"], "tools": ["*"]}


def test_an_explicit_args_array_is_still_never_split(tmp_path, make_scaffolder):
    """A declaration that spells out `args` keeps its command whole, in both files."""
    target = make_scaffolder.target

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "spaced", "command": "/opt/my tools/srv", "args": ["--serve"]}])

    assert _mcp_json(target)["spaced"]["command"] == "/opt/my tools/srv"
    assert _github_mcp_json(target)["spaced"]["command"] == "/opt/my tools/srv"


# ── the divergences that cannot be reconciled ────────────────────────────────

def test_a_server_the_hosts_resolve_differently_is_declared_once(tmp_path, make_scaffolder):
    """Per-agent overrides cannot reach Copilot through a file Claude also owns."""
    target = make_scaffolder.target

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "fs", "command": "npx -y server-filesystem",
         "agentOverrides": {"claude": {"command": "claude-resolved"},
                            "copilot": {"command": "copilot-resolved"}}}])

    assert _mcp_json(target)["fs"]["command"] == "claude-resolved"
    assert "fs" not in _github_mcp_json(target)


def test_the_single_declaration_is_explained_in_a_note(tmp_path, make_scaffolder):
    scaf = _scaffold(make_scaffolder, tmp_path, [
        {"name": "fs", "command": "npx -y server-filesystem",
         "agentOverrides": {"copilot": {"command": "copilot-resolved"}}}])

    note = next(n for n in scaf.notes if "'fs'" in n and "193" in n)
    assert ".github/mcp.json" in note
    assert ".mcp.json" in note
    assert "command" in note


def test_an_earlier_runs_divergent_entry_is_removed(tmp_path, make_scaffolder):
    """Merge-only would have left the contradiction this release exists to remove."""
    target = make_scaffolder.target
    (target / ".github").mkdir(parents=True, exist_ok=True)
    (target / ".github" / "mcp.json").write_text(json.dumps({"mcpServers": {
        "fs": {"command": "copilot-resolved", "tools": ["*"]},
        "keeper": {"command": "echo"}}}), encoding="utf-8")

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "fs", "command": "npx -y server-filesystem",
         "agentOverrides": {"copilot": {"command": "copilot-resolved"}}}])

    assert "fs" not in _github_mcp_json(target)
    assert "keeper" in _github_mcp_json(target)


def test_a_home_relative_command_is_declared_once(
        tmp_path, monkeypatch, load_script, make_scaffolder):
    """`${HOME}` is documented for `.mcp.json` and for nothing Copilot reads."""
    target = make_scaffolder.target
    dotnet = _fake_tool_dirs(monkeypatch, load_script, tmp_path)
    exe = dotnet / "cwm-roslyn-navigator"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "roslyn", "command": "cwm-roslyn-navigator"}])

    assert _mcp_json(target)["roslyn"]["command"] == "${HOME}/.dotnet/tools/cwm-roslyn-navigator"
    assert "roslyn" not in _github_mcp_json(target)


# ── the file both hosts read is resolved for whichever host is configured ────

def test_a_copilot_only_project_resolves_mcp_json_with_copilots_overrides(
        tmp_path, make_scaffolder):
    """With no Claude configured, the only agent reading `.mcp.json` is the Copilot CLI."""
    target = make_scaffolder.target

    _scaffold(make_scaffolder, tmp_path, [
        {"name": "fs", "command": "npx -y server-filesystem",
         "agentOverrides": {"claude": {"command": "claude-resolved"},
                            "copilot": {"command": "copilot-resolved"}}}],
              agents=["copilot"])

    assert _mcp_json(target)["fs"]["command"] == "copilot-resolved"
    assert _github_mcp_json(target)["fs"]["command"] == "copilot-resolved"
