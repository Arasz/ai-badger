"""Tests for stack-declared MCP server scaffolding.

Verifies that mcp-servers.json files in feature directories are collected,
merged with externalTools, split by scope, and scaffolded into agent-specific
config files (.mcp.json, ~/.hermes/config.yaml, ~/.claude/settings.json,
.github/copilot/mcp-config.json).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


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
    had_common = common_file.exists()
    try:
        _write_mcp_servers(common_dir, [
            {"name": "baseline", "command": "echo baseline"}
        ])
        scaf = _scaf(scaffold, root, target, _config())
        result = scaf._collect_stack_mcp_servers()
        assert len(result) == 1
        assert result[0]["name"] == "baseline"
    finally:
        if not had_common and common_file.exists():
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
    result = scaf._collect_stack_mcp_servers()
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
    result = scaf._collect_stack_mcp_servers()
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
    result = scaf._collect_stack_mcp_servers()
    assert result == []


def test_collect_empty_servers(tmp_path, load_script, root):
    """Empty servers array returns empty list."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [])

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=["python"]))
    result = scaf._collect_stack_mcp_servers()
    assert result == []


# ── _merge_mcp_servers ────────────────────────────────────────────────────────

def test_merge_stack_only(tmp_path, load_script, root):
    """Stack server with no externalTool appears in merged dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    stack = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    merged = scaf._merge_mcp_servers(stack, [])
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
    merged = scaf._merge_mcp_servers([], tools)
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
    merged = scaf._merge_mcp_servers(stack, tools)
    assert merged["tool-x"]["command"] == "echo user"


def test_merge_empty_stacks(tmp_path, load_script, root):
    """No stack servers -> only externalTools in result."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    tools = [{"name": "crg", "package": "p", "command": "echo crg",
              "instructions": "", "generate_mcp_json": True}]
    merged = scaf._merge_mcp_servers([], tools)
    assert list(merged.keys()) == ["crg"]


def test_merge_empty_tools(tmp_path, load_script, root):
    """No externalTools -> only stack servers in result."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    stack = [{"name": "pyright", "command": "uvx mcp-server-pyright"}]
    merged = scaf._merge_mcp_servers(stack, [])
    assert list(merged.keys()) == ["pyright"]


# ── _split_servers_by_scope ──────────────────────────────────────────────────

def test_split_default_scope_is_project(tmp_path, load_script, root):
    """Server without scope field goes to project dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo"}}
    project, user = scaf._split_servers_by_scope(servers)
    assert "x" in project
    assert "x" not in user


def test_split_project_scope(tmp_path, load_script, root):
    """Explicit project scope goes to project dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo", "scope": "project"}}
    project, user = scaf._split_servers_by_scope(servers)
    assert "x" in project
    assert "x" not in user


def test_split_user_scope(tmp_path, load_script, root):
    """User scope goes to user dict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaf = _scaf(scaffold, root, target, _config())

    servers = {"x": {"name": "x", "command": "echo", "scope": "user"}}
    project, user = scaf._split_servers_by_scope(servers)
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
    project, user = scaf._split_servers_by_scope(servers)
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
    scaf._generate_mcp_json()

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
    scaf._generate_mcp_json()

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
    scaf._generate_mcp_json()

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
    scaf._generate_mcp_json()

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
    scaf._generate_mcp_json()

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
    scaf._generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "npx"
    assert mcp["mcpServers"]["fs"]["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_mcp_json_not_created_when_empty(tmp_path, load_script, root):
    """No project-scoped servers -> no .mcp.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = _scaf(scaffold, tmp_path, target, _config(stacks=[], agents=["claude"]))
    scaf._generate_mcp_json()

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
        scaf._scaffold_hermes_mcp_user(
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
        scaf._scaffold_hermes_mcp_user(
            {"new-server": {"name": "new-server", "command": "echo new", "scope": "user"}}
        )

    cfg = yaml.safe_load((hermes_dir / "config.yaml").read_text(encoding="utf-8"))
    assert "existing-server" in cfg["mcp"]["servers"]
    assert "new-server" in cfg["mcp"]["servers"]


def test_hermes_user_server_creates_config_if_missing(tmp_path, load_script, root):
    """If ~/.hermes/config.yaml doesn't exist, it's created."""
    yaml = pytest.importorskip("yaml")
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(scaffold, tmp_path, target,
                      _config(stacks=["python"], agents=["hermes"]))
        scaf._scaffold_hermes_mcp_user(
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
        scaf._scaffold_hermes_mcp_user(
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
    scaf._generate_mcp_json()

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
        scaf._scaffold_claude_mcp_user(
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
        scaf._scaffold_claude_mcp_user(
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
        scaf._scaffold_claude_mcp_user(
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
    scaf._generate_copilot_mcp_config(servers)

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
    scaf._generate_copilot_mcp_config(servers)

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
    scaf._generate_copilot_mcp_config(servers)

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
    scaf._generate_copilot_mcp_config(servers)

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
        result = scaf.run()

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
    scaf._generate_mcp_json()

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
    scaf._generate_mcp_json()

    assert not (target / ".mcp.json").exists()
