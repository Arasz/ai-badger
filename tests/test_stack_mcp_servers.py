"""Tests for stack-declared MCP server scaffolding.

Verifies that mcp-servers.json files in feature directories are collected,
merged with externalTools, split by scope, and scaffolded into agent-specific
config files (.mcp.json, ~/.hermes/config.yaml, ~/.claude/settings.json,
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


def _config(stacks=None, agents=None, external_tools=None):
    cfg = {
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
    if external_tools is not None:
        cfg["externalTools"] = external_tools
    return cfg


def _scaf(scaffold, root, target, config):
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
    return scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=[], install=False)


def _write_mcp_servers(stack_dir, servers):
    """Write a mcp-servers.json file in a stack directory."""
    stack_dir.mkdir(parents=True, exist_ok=True)
    data = {"servers": servers}
    (stack_dir / "mcp-servers.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


# ── _collect_stack_mcp_servers ────────────────────────────────────────────────

def test_collect_from_common(tmp_path, load_script, root):
    """Common mcp-servers.json is read."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    common_dir = root / "features" / "common"
    common_file = common_dir / "mcp-servers.json"
    original = common_file.read_text(encoding="utf-8") if common_file.exists() else None
    try:
        _write_mcp_servers(common_dir, [
            {"name": "baseline", "command": "echo baseline"}
        ])
        scaf = _scaf(scaffold, root, target, _config())
        result = scaf.mcp.collect_stack_mcp_servers()
        assert len(result) == 1
        assert result[0]["name"] == "baseline"
    finally:
        if original is not None:
            common_file.write_text(original, encoding="utf-8")
        elif common_file.exists():
            common_file.unlink()


def test_collect_from_multiple_stacks(tmp_path, load_script, root):
    """Servers from multiple stacks are collected."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    gh_dir = tmp_path / "features" / "github"
    _write_mcp_servers(py_dir, [{"name": "pyright", "command": "uvx mcp-server-pyright"}])
    _write_mcp_servers(gh_dir, [{"name": "github-mcp", "command": "npx -y @modelcontextprotocol/server-github"}])

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=["python", "github"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    names = [s["name"] for s in result]
    assert "pyright" in names
    assert "github-mcp" in names


def test_collect_cross_stack_dedup_last_writer_wins(tmp_path, load_script, root):
    """Same name in two stacks -> later stack wins."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    gh_dir = tmp_path / "features" / "github"
    _write_mcp_servers(py_dir, [{"name": "shared", "command": "echo python-version"}])
    _write_mcp_servers(gh_dir, [{"name": "shared", "command": "echo github-version"}])

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=["python", "github"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    assert len(result) == 1
    assert result[0]["command"] == "echo github-version"


def test_collect_missing_file_skipped(tmp_path, load_script, root):
    """Stack without mcp-servers.json is silently skipped."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    py_dir.mkdir(parents=True)

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=["python"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    assert result == []


def test_collect_empty_servers(tmp_path, load_script, root):
    """Empty servers array returns empty list."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [])

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=["python"]))
    result = scaf.mcp.collect_stack_mcp_servers()
    assert result == []


# ── _merge_mcp_servers ────────────────────────────────────────────────────────

def test_merge_stack_only(tmp_path, load_script, root):
    """Stack server with no externalTool appears in merged dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    stack = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    merged = scaf.mcp.merge_mcp_servers(stack, [])
    assert "pyright" in merged
    assert merged["pyright"]["command"] == "uvx mcp-server-pyright"


def test_merge_user_only(tmp_path, load_script, root):
    """ExternalTool with no stack server appears in merged dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    tools = [{"name": "crg", "package": "code-review-graph",
              "command": "uvx code-review-graph serve", "instructions": "x",
              "generate_mcp_json": True}]
    merged = scaf.mcp.merge_mcp_servers([], tools)
    assert "crg" in merged


def test_merge_user_wins_on_conflict(tmp_path, load_script, root):
    """Same name in both -> externalTools entry is used."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    stack = [{"name": "tool-x", "command": "echo stack"}]
    tools = [{"name": "tool-x", "package": "p", "command": "echo user",
              "instructions": "", "generate_mcp_json": True}]
    merged = scaf.mcp.merge_mcp_servers(stack, tools)
    assert merged["tool-x"]["command"] == "echo user"


def test_merge_empty_stacks(tmp_path, load_script, root):
    """No stack servers -> only externalTools in result."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    tools = [{"name": "crg", "package": "p", "command": "echo crg",
              "instructions": "", "generate_mcp_json": True}]
    merged = scaf.mcp.merge_mcp_servers([], tools)
    assert list(merged.keys()) == ["crg"]


def test_merge_empty_tools(tmp_path, load_script, root):
    """No externalTools -> only stack servers in result."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    stack = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    merged = scaf.mcp.merge_mcp_servers(stack, [])
    assert list(merged.keys()) == ["pyright"]


# ── _split_servers_by_scope ──────────────────────────────────────────────────

def test_split_default_scope_is_project(tmp_path, load_script, root):
    """Server without scope field goes to project dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo"}}
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert "x" in project
    assert "x" not in user


def test_split_project_scope(tmp_path, load_script, root):
    """Explicit project scope goes to project dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo", "scope": "project"}}
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert "x" in project
    assert "x" not in user


def test_split_user_scope(tmp_path, load_script, root):
    """User scope goes to user dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo", "scope": "user"}}
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert "x" not in project
    assert "x" in user


def test_split_mixed_scopes(tmp_path, load_script, root):
    """Mixed servers split correctly into two dicts."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {
        "a": {"name": "a", "command": "echo", "scope": "project"},
        "b": {"name": "b", "command": "echo", "scope": "user"},
        "c": {"name": "c", "command": "echo"},
    }
    project, user = scaf.mcp.split_servers_by_scope(servers)
    assert set(project.keys()) == {"a", "c"}
    assert set(user.keys()) == {"b"}


# ── .mcp.json generation ─────────────────────────────────────────────────────

def test_stack_mcp_generates_mcp_json(tmp_path, load_script, root):
    """Stack servers with scope: project produce .mcp.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}
    ])

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]
    assert mcp["mcpServers"]["pyright"]["command"] == "uvx"


def test_stack_and_external_tools_merge_in_mcp_json(tmp_path, load_script, root):
    """Both sources appear in .mcp.json; user wins on conflict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"},
        {"name": "shared", "command": "echo stack"},
    ])

    external = [{
        "name": "shared", "package": "p", "command": "echo user",
        "instructions": "", "generate_mcp_json": True,
    }]

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"], external_tools=external))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]
    assert mcp["mcpServers"]["shared"]["command"] == "echo user"


def test_mcp_json_no_duplicate_from_two_stacks(tmp_path, load_script, root):
    """Same server from two stacks -> one entry in .mcp.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    gh_dir = tmp_path / "features" / "github"
    _write_mcp_servers(py_dir, [{"name": "shared", "command": "echo v1"}])
    _write_mcp_servers(gh_dir, [{"name": "shared", "command": "echo v2"}])

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python", "github"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert list(mcp["mcpServers"].keys()).count("shared") == 1
    assert mcp["mcpServers"]["shared"]["command"] == "echo v2"


def test_mcp_json_merge_preserves_existing(tmp_path, load_script, root):
    """Pre-existing .mcp.json entries not overwritten."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    existing = {"mcpServers": {"my-server": {"command": "echo existing"}}}
    (target / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [{"name": "pyright", "command": "uvx mcp-server-pyright"}])

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "my-server" in mcp["mcpServers"]
    assert "pyright" in mcp["mcpServers"]


def test_mcp_json_env_propagated(tmp_path, load_script, root):
    """env field from stack server appears in .mcp.json entry."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [{
        "name": "github", "command": "npx -y @modelcontextprotocol/server-github",
        "env": {"GITHUB_TOKEN": "test"},
    }])

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["github"]["env"] == {"GITHUB_TOKEN": "test"}


def test_mcp_json_agent_override_applied(tmp_path, load_script, root):
    """agentOverrides.claude overrides command for Claude."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [{
        "name": "fs",
        "command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
        "agentOverrides": {
            "claude": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
        },
    }])

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "npx"
    assert mcp["mcpServers"]["fs"]["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_mcp_json_not_created_when_empty(tmp_path, load_script, root):
    """No project-scoped servers -> no .mcp.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=[], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    assert not (target / ".mcp.json").exists()


# ── Hermes user-scoped ───────────────────────────────────────────────────────

def test_hermes_user_server_writes_config_yaml(tmp_path, load_script, root):
    """scope: user server is written to ~/.hermes/config.yaml mcp.servers."""
    yaml = pytest.importorskip("yaml")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"hermes-mcp": {"name": "hermes-mcp", "command": "hermes mcp serve", "scope": "user"}}
        )

    config_path = home / ".hermes" / "config.yaml"
    assert config_path.exists()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "mcp" in cfg
    assert "hermes-mcp" in cfg["mcp"]["servers"]


def test_hermes_user_server_merge_preserves_existing(tmp_path, load_script, root):
    """Existing entries in config.yaml mcp.servers are preserved."""
    yaml = pytest.importorskip("yaml")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    hermes_dir = home / ".hermes"
    hermes_dir.mkdir()

    existing = {"mcp": {"servers": {"existing-server": {"command": "echo existing"}}}}
    (hermes_dir / "config.yaml").write_text(yaml.safe_dump(existing), encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"new-server": {"name": "new-server", "command": "echo new", "scope": "user"}}
        )

    cfg = yaml.safe_load((hermes_dir / "config.yaml").read_text(encoding="utf-8"))
    assert "existing-server" in cfg["mcp"]["servers"]
    assert "new-server" in cfg["mcp"]["servers"]


def test_hermes_user_server_creates_config_if_missing(tmp_path, load_script, root):
    """If ~/.hermes/config.yaml doesn't exist, it's created."""
    pytest.importorskip("yaml")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"srv": {"name": "srv", "command": "echo", "scope": "user"}}
        )

    config_path = home / ".hermes" / "config.yaml"
    assert config_path.exists()


def test_hermes_user_server_no_write_without_hermes_agent(tmp_path, load_script, root):
    """If hermes not in config.agents, no config.yaml write."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["claude"]))
        scaf.mcp.scaffold_hermes_mcp_user(
            {"srv": {"name": "srv", "command": "echo", "scope": "user"}}
        )

    assert not (home / ".hermes" / "config.yaml").exists()


def test_hermes_project_server_writes_mcp_json(tmp_path, load_script, root):
    """scope: project server goes to .mcp.json, not config.yaml."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}
    ])

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["hermes"]))
    scaf.mcp.generate_mcp_json()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]


# ── Claude user-scoped ───────────────────────────────────────────────────────

def test_claude_user_server_writes_settings_json(tmp_path, load_script, root):
    """scope: user server written to ~/.claude/settings.json mcpServers."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["claude"]))
        scaf.mcp.scaffold_claude_mcp_user(
            {"srv": {"name": "srv", "command": "echo", "scope": "user"}}
        )

    settings_path = home / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "srv" in settings["mcpServers"]


def test_claude_user_server_merge_preserves_existing(tmp_path, load_script, root):
    """Existing mcpServers entries preserved."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    claude_dir = home / ".claude"
    claude_dir.mkdir()

    existing = {"mcpServers": {"old": {"command": "echo old"}}}
    (claude_dir / "settings.json").write_text(json.dumps(existing), encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["claude"]))
        scaf.mcp.scaffold_claude_mcp_user(
            {"new": {"name": "new", "command": "echo new", "scope": "user"}}
        )

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert "old" in settings["mcpServers"]
    assert "new" in settings["mcpServers"]


def test_claude_user_server_no_write_without_claude_agent(tmp_path, load_script, root):
    """If claude not in agents, no settings.json write."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf.mcp.scaffold_claude_mcp_user(
            {"srv": {"name": "srv", "command": "echo", "scope": "user"}}
        )

    assert not (home / ".claude" / "settings.json").exists()


# ── Copilot ──────────────────────────────────────────────────────────────────

def test_copilot_config_generated(tmp_path, load_script, root):
    """.github/copilot/mcp-config.json created when copilot in agents."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"pyright": {"name": "pyright", "command": "uvx mcp-server-pyright"}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    config_path = target / ".github" / "copilot" / "mcp-config.json"
    assert config_path.exists()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert "pyright" in cfg["mcpServers"]


def test_copilot_config_not_created_for_claude_only(tmp_path, load_script, root):
    """No copilot config if copilot not in agents."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    servers = {"pyright": {"name": "pyright", "command": "uvx mcp-server-pyright"}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    assert not (target / ".github" / "copilot" / "mcp-config.json").exists()


def test_copilot_config_merge_preserves_existing(tmp_path, load_script, root):
    """Existing copilot config entries preserved."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    copilot_dir = target / ".github" / "copilot"
    copilot_dir.mkdir(parents=True)

    existing = {"mcpServers": {"old": {"command": "echo old"}}}
    (copilot_dir / "mcp-config.json").write_text(json.dumps(existing), encoding="utf-8")

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"new": {"name": "new", "command": "echo new"}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    cfg = json.loads((copilot_dir / "mcp-config.json").read_text(encoding="utf-8"))
    assert "old" in cfg["mcpServers"]
    assert "new" in cfg["mcpServers"]


def test_copilot_env_propagated(tmp_path, load_script, root):
    """env field appears in copilot config."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"github": {"name": "github", "command": "npx -y @modelcontextprotocol/server-github",
                           "env": {"GITHUB_TOKEN": "test"}}}
    scaf.mcp.generate_copilot_mcp_config(servers)

    cfg = json.loads((target / ".github" / "copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["github"]["env"] == {"GITHUB_TOKEN": "test"}


# ── Integration ──────────────────────────────────────────────────────────────

def test_full_scaffold_with_stack_mcp(tmp_path, load_script, root):
    """End-to-end: config with python stack -> .mcp.json has pyright."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [
        {"name": "pyright", "command": "uvx mcp-server-pyright"}
    ])

    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["claude"]))
        scaf.run()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]


def test_existing_external_tools_still_work(tmp_path, load_script, root):
    """Regression: code-review-graph from externalTools still generates .mcp.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    external = [{
        "name": "code-review-graph",
        "package": "code-review-graph",
        "command": "uvx code-review-graph serve",
        "instructions": "## CRG\nUse graph tools.",
        "generate_mcp_json": True,
    }]

    scaf = _scaf(scaffold, root, target,
                  _config(stacks=[], agents=["claude"], external_tools=external))
    scaf.mcp.generate_mcp_json()

    mcp_path = target / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "code-review-graph" in mcp["mcpServers"]


def test_no_mcp_json_when_no_servers(tmp_path, load_script, root):
    """No stack servers + no externalTools -> no .mcp.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=[], agents=["claude"]))
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


def test_mcp_json_uses_claude_overrides_regardless_of_agent_order(tmp_path, load_script, root):
    """.mcp.json is Claude Code's project-scope file — list order must not decide (F-22)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot", "claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "claude-resolved"


def test_mcp_json_applies_no_override_when_claude_is_not_configured(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(scaffold, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "npx"
    assert any(".mcp.json" in note for note in scaf.notes)


def test_copilot_config_uses_copilot_overrides(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(scaffold, tmp_path, target,
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


def _render_everywhere(tmp_path, load_script, server, home):
    """Render *server* into all four destinations; return their entries for it."""
    yaml = pytest.importorskip("yaml")
    scaffold = load_script(SCAFFOLD)
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    by_name = {server["name"]: server}

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                     _config(stacks=["python"], agents=["claude", "copilot", "hermes"]))
        scaf.mcp.generate_mcp_json()
        scaf.mcp.generate_copilot_mcp_config(by_name)
        scaf.mcp.scaffold_claude_mcp_user(by_name)
        scaf.mcp.scaffold_hermes_mcp_user(by_name)

    name = server["name"]

    def _json_entry(path):
        return json.loads(path.read_text(encoding="utf-8"))["mcpServers"][name]

    return {
        "mcp_json": _json_entry(target / ".mcp.json"),
        "copilot": _json_entry(target / ".github" / "copilot" / "mcp-config.json"),
        "claude_user": _json_entry(home / ".claude" / "settings.json"),
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
        command, in_mcp_json, elsewhere, tmp_path, monkeypatch, load_script, root):
    """.mcp.json splits a command only on package-shaped args; every other destination splits on whitespace."""
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        tmp_path, load_script, {"name": "srv", "command": command}, home)

    assert {k: v for k, v in entries.pop("mcp_json").items() if k != "cwd"} == in_mcp_json
    for destination, entry in entries.items():
        assert entry == elsewhere, destination


def _scaffold_mcp_json_from(tmp_path, load_script, target, server):
    """Run only the .mcp.json generation, as though scaffolded from *target*."""
    scaffold = load_script(SCAFFOLD)
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    scaf = _scaf(scaffold, tmp_path, target,
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
            self, tmp_path, monkeypatch, load_script, root):
        _no_user_tool_dirs(monkeypatch, load_script)
        main = self._project(tmp_path, "proj")
        worktree = self._project(tmp_path, "wt")
        server = {"name": "srv", "command": "uvx mcp-server-pyright"}
        _scaffold_mcp_json_from(tmp_path, load_script, main, server)
        (worktree / ".mcp.json").write_text(
            (main / ".mcp.json").read_text(encoding="utf-8"), encoding="utf-8")

        _scaffold_mcp_json_from(tmp_path, load_script, worktree, server)

        assert self._cwd_of(worktree) == str(main)

    def test_a_cwd_pointing_nowhere_is_replaced(
            self, tmp_path, monkeypatch, load_script, root):
        _no_user_tool_dirs(monkeypatch, load_script)
        target = self._project(tmp_path, "proj")
        (target / ".mcp.json").write_text(json.dumps({"mcpServers": {"srv": {
            "command": "uvx", "args": ["mcp-server-pyright"],
            "cwd": str(tmp_path / "deleted-worktree")}}}), encoding="utf-8")

        _scaffold_mcp_json_from(
            tmp_path, load_script, target, {"name": "srv", "command": "uvx mcp-server-pyright"})

        assert self._cwd_of(target) == str(target)

    def test_a_first_scaffold_pins_the_project_it_ran_from(
            self, tmp_path, monkeypatch, load_script, root):
        _no_user_tool_dirs(monkeypatch, load_script)
        target = self._project(tmp_path, "proj")

        _scaffold_mcp_json_from(
            tmp_path, load_script, target, {"name": "srv", "command": "uvx mcp-server-pyright"})

        assert self._cwd_of(target) == str(target)

    def test_everything_but_cwd_is_still_refreshed(
            self, tmp_path, monkeypatch, load_script, root):
        """Preserving cwd must not freeze the rest of a stale entry."""
        _no_user_tool_dirs(monkeypatch, load_script)
        main = self._project(tmp_path, "proj")
        (main / ".mcp.json").write_text(json.dumps({"mcpServers": {"srv": {
            "command": "stale-command", "cwd": str(main)}}}), encoding="utf-8")

        _scaffold_mcp_json_from(
            tmp_path, load_script, main, {"name": "srv", "command": "uvx mcp-server-pyright"})

        entry = json.loads((main / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["srv"]
        assert entry["command"] == "uvx"
        assert entry["cwd"] == str(main)


def test_only_mcp_json_pins_the_project_cwd(tmp_path, monkeypatch, load_script, root):
    """The other three configs are read by agents that supply their own working directory."""
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        tmp_path, load_script,
        {"name": "srv", "command": "uvx mcp-server-pyright"}, home)

    assert entries.pop("mcp_json")["cwd"] == str(tmp_path / "proj")
    for destination, entry in entries.items():
        assert "cwd" not in entry, destination


def test_env_reaches_every_destination(tmp_path, monkeypatch, load_script, root):
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        tmp_path, load_script,
        {"name": "srv", "command": "uvx mcp-server-pyright",
         "env": {"TOKEN": "not-a-real-token"}}, home)

    for destination, entry in entries.items():
        assert entry["env"] == {"TOKEN": "not-a-real-token"}, destination
