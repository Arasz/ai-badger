"""Tests for stack-declared MCP server scaffolding.

Verifies that mcp-servers.json files in feature directories are collected, merged with the
legacy external-tools.json entries, split by scope, and scaffolded into agent-specific config
files (.mcp.json, ~/.hermes/config.yaml, ~/.claude/settings.json,
.github/copilot/mcp-config.json).
"""
# pylint: disable=protected-access  # exercises the Scaffolder MCP mixin directly; see pyproject.toml
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _config(stacks=None, agents=None):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": stacks if stacks is not None else ["python"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaf(make_scaffolder, root, target, config):
    """Create a Scaffolder with standard test args.

    If root is a tmp_path (no index.json), create a minimal one so the
    Scaffolder can initialize.
    """
    index_path = root / "index.json"
    if not index_path.exists():
        index_path.write_text(json.dumps({
            "frameworkVersion": "0.1.0",
            "stacks": {},
        }), encoding="utf-8")
    return make_scaffolder(root=root, target=target, config=config)


def _write_mcp_servers(stack_dir, servers):
    """Write a mcp-servers.json file in a stack directory."""
    stack_dir.mkdir(parents=True, exist_ok=True)
    data = {"servers": servers}
    (stack_dir / "mcp-servers.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


# ── _collect_stack_mcp_servers ────────────────────────────────────────────────

def test_collect_from_common(root, make_scaffolder):
    """Common mcp-servers.json is read."""
    target = make_scaffolder.target

    common_dir = root / "features" / "common"
    common_file = common_dir / "mcp-servers.json"
    original = common_file.read_text(encoding="utf-8") if common_file.exists() else None
    try:
        _write_mcp_servers(common_dir, [
            {"name": "baseline", "command": "echo baseline"}
        ])
        scaf = _scaf(make_scaffolder, root, target, _config())
        result = scaf.mcp.collect_stack_mcp_servers()
        assert len(result) == 1
        assert result[0]["name"] == "baseline"
    finally:
        if original is not None:
            common_file.write_text(original, encoding="utf-8")
        elif common_file.exists():
            common_file.unlink()


def test_collect_from_multiple_stacks(tmp_path, make_scaffolder):
    """Servers from multiple stacks are collected."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    gh_dir = tmp_path / "features" / "github"
    _write_mcp_servers(py_dir, [{"name": "pyright", "command": "uvx mcp-server-pyright"}])
    _write_mcp_servers(gh_dir, [{"name": "github-mcp", "command": "npx -y @modelcontextprotocol/server-github"}])

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python", "github"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    names = [s["name"] for s in result]
    assert "pyright" in names
    assert "github-mcp" in names


def test_collect_cross_stack_dedup_last_writer_wins(tmp_path, make_scaffolder):
    """Same name in two stacks -> later stack wins."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    gh_dir = tmp_path / "features" / "github"
    _write_mcp_servers(py_dir, [{"name": "shared", "command": "echo python-version"}])
    _write_mcp_servers(gh_dir, [{"name": "shared", "command": "echo github-version"}])

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python", "github"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    assert len(result) == 1
    assert result[0]["command"] == "echo github-version"


def test_collect_missing_file_skipped(tmp_path, make_scaffolder):
    """Stack without mcp-servers.json is silently skipped."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    py_dir.mkdir(parents=True)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    assert result == []


def test_collect_empty_servers(tmp_path, make_scaffolder):
    """Empty servers array returns empty list."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [])

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    assert result == []


# ── _merge_mcp_servers ────────────────────────────────────────────────────────

def test_merge_stack_only(root, make_scaffolder):
    """Stack server with no externalTool appears in merged dict."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    stack = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    merged = scaf.mcp.merge_mcp_servers(stack, [])
    assert "pyright" in merged
    assert merged["pyright"]["command"] == "uvx mcp-server-pyright"


def test_merge_user_only(root, make_scaffolder):
    """ExternalTool with no stack server appears in merged dict."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    tools = [{"name": "crg", "package": "code-review-graph",
              "command": "uvx code-review-graph serve", "instructions": "x",
              "generate_mcp_json": True}]
    merged = scaf.mcp.merge_mcp_servers([], tools)
    assert "crg" in merged


def test_merge_user_wins_on_conflict(root, make_scaffolder):
    """Same name in both -> the external-tools.json entry is used."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    stack = [{"name": "tool-x", "command": "echo stack"}]
    tools = [{"name": "tool-x", "package": "p", "command": "echo user",
              "instructions": "", "generate_mcp_json": True}]
    merged = scaf.mcp.merge_mcp_servers(stack, tools)
    assert merged["tool-x"]["command"] == "echo user"


def test_merge_empty_stacks(root, make_scaffolder):
    """No stack servers -> only external tools in result."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    tools = [{"name": "crg", "package": "p", "command": "echo crg",
              "instructions": "", "generate_mcp_json": True}]
    merged = scaf.mcp.merge_mcp_servers([], tools)
    assert list(merged.keys()) == ["crg"]


def test_merge_empty_tools(root, make_scaffolder):
    """No external tools -> only stack servers in result."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    stack = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    merged = scaf.mcp.merge_mcp_servers(stack, [])
    assert list(merged.keys()) == ["pyright"]


# ── _split_servers_by_scope ──────────────────────────────────────────────────

def test_split_default_scope_is_project(root, make_scaffolder):
    """Server without scope field goes to project dict."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo"}}
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert "x" in project
    assert "x" not in user


def test_split_project_scope(root, make_scaffolder):
    """Explicit project scope goes to project dict."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo", "scope": "project"}}
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert "x" in project
    assert "x" not in user


def test_split_user_scope(root, make_scaffolder):
    """User scope goes to user dict."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo", "scope": "user"}}
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert "x" not in project
    assert "x" in user


def test_split_mixed_scopes(root, make_scaffolder):
    """Mixed servers split correctly into two dicts."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, root, target, _config())

    servers = {
        "a": {"name": "a", "command": "echo", "scope": "project"},
        "b": {"name": "b", "command": "echo", "scope": "user"},
        "c": {"name": "c", "command": "echo"},
    }
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert set(project.keys()) == {"a", "c"}
    assert set(user.keys()) == {"b"}


# ── .mcp.json generation ─────────────────────────────────────────────────────

def test_stack_mcp_generates_mcp_json(tmp_path, make_scaffolder):
    """Stack servers with scope: project produce .mcp.json."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}
    ])

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]
    assert mcp["mcpServers"]["pyright"]["command"] == "uvx"


def test_stack_and_external_tools_merge_in_mcp_json(tmp_path, make_scaffolder):
    """Both legacy readers appear in .mcp.json; external-tools.json wins on conflict."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"},
        {"name": "shared", "command": "echo stack"},
    ])
    (py_dir / "external-tools.json").write_text(json.dumps({"tools": [{
        "name": "shared", "package": "p", "command": "echo user",
        "instructions": "", "generate_mcp_json": True,
    }]}), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]
    assert mcp["mcpServers"]["shared"]["command"] == "echo user"


def test_mcp_json_no_duplicate_from_two_stacks(tmp_path, make_scaffolder):
    """Same server from two stacks -> one entry in .mcp.json."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    gh_dir = tmp_path / "features" / "github"
    _write_mcp_servers(py_dir, [{"name": "shared", "command": "echo v1"}])
    _write_mcp_servers(gh_dir, [{"name": "shared", "command": "echo v2"}])

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python", "github"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert list(mcp["mcpServers"].keys()).count("shared") == 1
    assert mcp["mcpServers"]["shared"]["command"] == "echo v2"


def test_mcp_json_merge_preserves_existing(tmp_path, make_scaffolder):
    """Pre-existing .mcp.json entries not overwritten."""
    target = make_scaffolder.target

    existing = {"mcpServers": {"my-server": {"command": "echo existing"}}}
    (target / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [{"name": "pyright", "command": "uvx mcp-server-pyright"}])

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "my-server" in mcp["mcpServers"]
    assert "pyright" in mcp["mcpServers"]


def test_mcp_json_env_propagated(tmp_path, make_scaffolder):
    """env field from stack server appears in .mcp.json entry."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [{
        "name": "github", "command": "npx -y @modelcontextprotocol/server-github",
        "env": {"GITHUB_TOKEN": "test"},
    }])

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["github"]["env"] == {"GITHUB_TOKEN": "test"}


def test_mcp_json_agent_override_applied(tmp_path, make_scaffolder):
    """agentOverrides.claude overrides command for Claude."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [{
        "name": "fs",
        "command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
        "agentOverrides": {
            "claude": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
        },
    }])

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "npx"
    assert mcp["mcpServers"]["fs"]["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_mcp_json_not_created_when_empty(tmp_path, make_scaffolder):
    """No project-scoped servers -> no .mcp.json."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=[], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    assert not (target / ".mcp.json").exists()


# ── Hermes user-scoped ───────────────────────────────────────────────────────

def test_hermes_user_server_writes_config_yaml(tmp_path, make_scaffolder):
    """scope: user server is written to ~/.hermes/config.yaml mcp.servers."""
    yaml = pytest.importorskip("yaml")
    target = make_scaffolder.target
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"hermes-mcp": {"name": "hermes-mcp", "command": "hermes mcp serve", "scope": "user"}}
        )

    config_path = home / ".hermes" / "config.yaml"
    assert config_path.exists()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "mcp" in cfg
    assert "hermes-mcp" in cfg["mcp"]["servers"]


def test_hermes_user_server_merge_preserves_existing(tmp_path, make_scaffolder):
    """Existing entries in config.yaml mcp.servers are preserved."""
    yaml = pytest.importorskip("yaml")
    target = make_scaffolder.target
    home = tmp_path / "home"
    home.mkdir()
    hermes_dir = home / ".hermes"
    hermes_dir.mkdir()

    existing = {"mcp": {"servers": {"existing-server": {"command": "echo existing"}}}}
    (hermes_dir / "config.yaml").write_text(yaml.safe_dump(existing), encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"new-server": {"name": "new-server", "command": "echo new", "scope": "user"}}
        )

    cfg = yaml.safe_load((hermes_dir / "config.yaml").read_text(encoding="utf-8"))
    assert "existing-server" in cfg["mcp"]["servers"]
    assert "new-server" in cfg["mcp"]["servers"]


def test_hermes_user_server_creates_config_if_missing(tmp_path, make_scaffolder):
    """If ~/.hermes/config.yaml doesn't exist, it's created."""
    pytest.importorskip("yaml")
    target = make_scaffolder.target
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"srv": {"name": "srv", "command": "echo", "scope": "user"}}
        )

    config_path = home / ".hermes" / "config.yaml"
    assert config_path.exists()


def test_hermes_user_server_no_write_without_hermes_agent(tmp_path, make_scaffolder):
    """If hermes not in config.agents, no config.yaml write."""
    target = make_scaffolder.target
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python"], agents=["claude"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"srv": {"name": "srv", "command": "echo", "scope": "user"}}
        )

    assert not (home / ".hermes" / "config.yaml").exists()


def test_hermes_project_server_writes_mcp_json(tmp_path, make_scaffolder):
    """scope: project server goes to .mcp.json, not config.yaml."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}
    ])

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["hermes"]))
    scaf.mcp.generate_mcp_json()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]


# ── Claude user-scoped: proposed, never written (ADR-0014 decision 6) ────────

def _claude_user_proposal(tmp_path, make_scaffolder, servers, agents=("claude",)):
    """Propose *servers* for ~/.claude/settings.json; return (home, matching notes)."""
    target = make_scaffolder.target
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                     _config(stacks=["python"], agents=list(agents)))
        scaf.mcp.propose_claude_mcp_user(servers)

    return home, [n for n in scaf.notes if "~/.claude/settings.json" in n]


def test_claude_user_server_is_proposed_not_written(tmp_path, make_scaffolder):
    """scope: user server reaches the operator as a note; the file is never created."""
    home, proposal = _claude_user_proposal(
        tmp_path, make_scaffolder, {"srv": {"name": "srv", "command": "echo", "scope": "user"}})

    assert len(proposal) == 1
    assert '"srv"' in proposal[0]
    assert not (home / ".claude" / "settings.json").exists()


def test_claude_user_proposal_does_not_touch_an_existing_file(tmp_path, make_scaffolder):
    """The user's own mcpServers are neither read nor rewritten to add ours."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    existing = json.dumps({"mcpServers": {"old": {"command": "echo old"}}})
    (home / ".claude" / "settings.json").write_text(existing, encoding="utf-8")

    _, proposal = _claude_user_proposal(
        tmp_path, make_scaffolder, {"new": {"name": "new", "command": "echo new",
                                            "scope": "user"}})

    assert (home / ".claude" / "settings.json").read_text(encoding="utf-8") == existing
    assert '"new"' in proposal[0]


def test_claude_user_server_not_proposed_without_claude_agent(tmp_path, make_scaffolder):
    """If claude not in agents, no proposal and no file."""
    home, proposal = _claude_user_proposal(
        tmp_path, make_scaffolder,
        {"srv": {"name": "srv", "command": "echo", "scope": "user"}}, agents=("hermes",))

    assert proposal == []
    assert not (home / ".claude" / "settings.json").exists()


# ── Copilot ──────────────────────────────────────────────────────────────────

def test_copilot_config_generated(tmp_path, make_scaffolder):
    """.github/copilot/mcp-config.json created when copilot in agents."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"pyright": {"name": "pyright", "command": "uvx mcp-server-pyright"}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    config_path = target / ".github" / "copilot" / "mcp-config.json"
    assert config_path.exists()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert "pyright" in cfg["mcpServers"]


def test_copilot_config_not_created_for_claude_only(tmp_path, make_scaffolder):
    """No copilot config if copilot not in agents."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    servers = {"pyright": {"name": "pyright", "command": "uvx mcp-server-pyright"}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    assert not (target / ".github" / "copilot" / "mcp-config.json").exists()


def test_copilot_config_merge_preserves_existing(tmp_path, make_scaffolder):
    """Existing copilot config entries preserved."""
    target = make_scaffolder.target
    copilot_dir = target / ".github" / "copilot"
    copilot_dir.mkdir(parents=True)

    existing = {"mcpServers": {"old": {"command": "echo old"}}}
    (copilot_dir / "mcp-config.json").write_text(json.dumps(existing), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"new": {"name": "new", "command": "echo new"}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    cfg = json.loads((copilot_dir / "mcp-config.json").read_text(encoding="utf-8"))
    assert "old" in cfg["mcpServers"]
    assert "new" in cfg["mcpServers"]


def test_copilot_env_propagated(tmp_path, make_scaffolder):
    """env field appears in copilot config."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"github": {"name": "github", "command": "npx -y @modelcontextprotocol/server-github",
                           "env": {"GITHUB_TOKEN": "test"}}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    cfg = json.loads((target / ".github" / "copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["github"]["env"] == {"GITHUB_TOKEN": "test"}


# ── Integration ──────────────────────────────────────────────────────────────

def test_full_scaffold_with_stack_mcp(tmp_path, make_scaffolder):
    """End-to-end: config with python stack -> .mcp.json has pyright."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}
    ])

    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python"], agents=["claude"]))
        scaf.run()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]


def test_the_shipped_catalog_declaration_still_works(root, make_scaffolder):
    """Regression: code-review-graph still generates .mcp.json, now from the mcp catalog."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, root, target, _config(stacks=[], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "code-review-graph" in mcp["mcpServers"]


def test_no_mcp_json_when_no_servers(tmp_path, make_scaffolder):
    """No stack servers + no external tools -> no .mcp.json."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=[], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    assert not (target / ".mcp.json").exists()


# ── .mcp.json override policy (F-22) ──────────────────────────────────────────

def _both_agents_server():
    return [{
        "name": "fs",
        "command": "npx -y server-filesystem /tmp",
        "agentOverrides": {
            "claude": {"command": "claude-resolved"},
            "copilot": {"command": "copilot-resolved"},
        },
    }]


def test_mcp_json_uses_claude_overrides_regardless_of_agent_order(tmp_path, make_scaffolder):
    """.mcp.json is Claude Code's project-scope file — list order must not decide (F-22)."""
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot", "claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "claude-resolved"


def test_mcp_json_applies_no_override_when_claude_is_not_configured(tmp_path, make_scaffolder):
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "npx"
    assert any(".mcp.json" in note for note in scaf.notes)


def test_copilot_config_uses_copilot_overrides(tmp_path, make_scaffolder):
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot", "claude"]))
    servers = {s["name"]: s for s in scaf.mcp.collect_stack_mcp_servers()}
    scaf.mcp.generate_copilot_mcp_config(servers)

    cfg = json.loads(
        (target / ".github" / "copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["fs"]["command"] == "copilot-resolved"


# ── how each destination renders one server (WP46 characterisation) ───────────

def _no_user_tool_dirs(monkeypatch, load_script):
    """Empty USER_TOOL_DIRS so these cases exercise splitting, not the ${HOME} rewrite."""
    load_script(SCAFFOLD)
    monkeypatch.setattr(sys.modules["mcp_tools"], "USER_TOOL_DIRS", ())


def _render_everywhere(make_scaffolder, tmp_path, server, home):
    """Render *server* into all four destinations; return their entries for it.

    The Claude user destination is a proposal note rather than a file (ADR-0014 decision 6),
    so its entry is read back out of the note — the rendering it characterises is the same.
    """
    yaml = pytest.importorskip("yaml")
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    by_name = {server["name"]: server}

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                     _config(stacks=["python"], agents=["claude", "copilot", "hermes"]))
        scaf.mcp.generate_mcp_json()
        scaf.mcp.generate_copilot_mcp_config(by_name)
        scaf.mcp.propose_claude_mcp_user(by_name)
        scaf.mcp.scaffold_hermes_mcp_user(by_name)

    name = server["name"]

    def _json_entry(path):
        return json.loads(path.read_text(encoding="utf-8"))["mcpServers"][name]

    proposal = next(n for n in scaf.notes if "~/.claude/settings.json" in n)
    return {
        "mcp_json": _json_entry(target / ".mcp.json"),
        "copilot": _json_entry(target / ".github" / "copilot" / "mcp-config.json"),
        "claude_user": json.loads(proposal.split("yourself: ", 1)[1])["mcpServers"][name],
        "hermes_user": yaml.safe_load(
            (home / ".hermes" / "config.yaml").read_text(encoding="utf-8"))["mcp"]["servers"][name],
    }


_SPLIT_CASES = [
    # command, .mcp.json entry (minus cwd), entry in every other destination
    ("uvx mcp-server-pyright",
     {"command": "uvx", "args": ["mcp-server-pyright"]},
     {"command": "uvx", "args": ["mcp-server-pyright"]}),
    ("npx -y @modelcontextprotocol/server-github",
     {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
     {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}),
    ("node /opt/mcp/server.js",
     {"command": "node", "args": ["/opt/mcp/server.js"]},
     {"command": "node", "args": ["/opt/mcp/server.js"]}),
    # No package-shaped argument: .mcp.json keeps the whole string, the others split it.
    ("echo v2", {"command": "echo v2"}, {"command": "echo", "args": ["v2"]}),
    ("hermes mcp serve",
     {"command": "hermes mcp serve"},
     {"command": "hermes", "args": ["mcp", "serve"]}),
    ("pyright-mcp", {"command": "pyright-mcp"}, {"command": "pyright-mcp"}),
]


@pytest.mark.parametrize("command,in_mcp_json,elsewhere", _SPLIT_CASES)
def test_the_two_command_splitters_agree_or_are_documented_to_differ(
        command, in_mcp_json, elsewhere, tmp_path, monkeypatch, load_script, make_scaffolder):
    """.mcp.json splits a command only on package-shaped args; every other destination splits on whitespace."""
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        make_scaffolder, tmp_path, {"name": "srv", "command": command}, home)

    assert {k: v for k, v in entries.pop("mcp_json").items() if k != "cwd"} == in_mcp_json
    for destination, entry in entries.items():
        assert entry == elsewhere, destination


def _scaffold_mcp_json_from(make_scaffolder, tmp_path, target, server):
    """Run only the .mcp.json generation, as though scaffolded from *target*."""
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    scaf = _scaf(make_scaffolder, tmp_path, target,
                 _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()
    return scaf


class TestCwdSurvivesAScaffoldFromAnotherCheckout:
    """.mcp.json is tracked, so a refresh run from a worktree must not restage its cwd."""

    @staticmethod
    def _project(tmp_path, name):
        target = tmp_path / name
        (target / ".ai-badger").mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _cwd_of(target, name="srv"):
        return json.loads(
            (target / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][name]["cwd"]

    def test_a_cwd_pointing_at_a_live_checkout_is_left_alone(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        _no_user_tool_dirs(monkeypatch, load_script)
        main = self._project(tmp_path, "proj")
        worktree = self._project(tmp_path, "wt")
        server = {"name": "srv", "command": "uvx mcp-server-pyright"}
        _scaffold_mcp_json_from(make_scaffolder, tmp_path, main, server)
        (worktree / ".mcp.json").write_text(
            (main / ".mcp.json").read_text(encoding="utf-8"), encoding="utf-8")

        _scaffold_mcp_json_from(make_scaffolder, tmp_path, worktree, server)

        assert self._cwd_of(worktree) == str(main)

    def test_a_cwd_pointing_nowhere_is_replaced(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        _no_user_tool_dirs(monkeypatch, load_script)
        target = self._project(tmp_path, "proj")
        (target / ".mcp.json").write_text(json.dumps({"mcpServers": {"srv": {
            "command": "uvx", "args": ["mcp-server-pyright"],
            "cwd": str(tmp_path / "deleted-worktree")}}}), encoding="utf-8")

        _scaffold_mcp_json_from(
            make_scaffolder, tmp_path, target, {"name": "srv", "command": "uvx mcp-server-pyright"})

        assert self._cwd_of(target) == str(target)

    def test_a_first_scaffold_pins_the_project_it_ran_from(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        _no_user_tool_dirs(monkeypatch, load_script)
        target = self._project(tmp_path, "proj")

        _scaffold_mcp_json_from(
            make_scaffolder, tmp_path, target, {"name": "srv", "command": "uvx mcp-server-pyright"})

        assert self._cwd_of(target) == str(target)

    def test_everything_but_cwd_is_still_refreshed(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        """Preserving cwd must not freeze the rest of a stale entry."""
        _no_user_tool_dirs(monkeypatch, load_script)
        main = self._project(tmp_path, "proj")
        (main / ".mcp.json").write_text(json.dumps({"mcpServers": {"srv": {
            "command": "stale-command", "cwd": str(main)}}}), encoding="utf-8")

        _scaffold_mcp_json_from(
            make_scaffolder, tmp_path, main, {"name": "srv", "command": "uvx mcp-server-pyright"})

        entry = json.loads((main / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["srv"]
        assert entry["command"] == "uvx"
        assert entry["cwd"] == str(main)


def test_only_mcp_json_pins_the_project_cwd(tmp_path, monkeypatch, load_script, make_scaffolder):
    """The other three configs are read by agents that supply their own working directory."""
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        make_scaffolder, tmp_path, {"name": "srv", "command": "uvx mcp-server-pyright"}, home)

    assert entries.pop("mcp_json")["cwd"] == str(tmp_path / "proj")
    for destination, entry in entries.items():
        assert "cwd" not in entry, destination


def test_env_reaches_every_destination(tmp_path, monkeypatch, load_script, make_scaffolder):
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        make_scaffolder, tmp_path, {"name": "srv", "command": "uvx mcp-server-pyright",
         "env": {"TOKEN": "not-a-real-token"}}, home)

    for destination, entry in entries.items():
        assert entry["env"] == {"TOKEN": "not-a-real-token"}, destination
