"""Tests for stack-declared MCP server scaffolding.

Verifies that `stack-mcp.json` files in feature directories are collected, resolved into one
declaration set, split by scope, and scaffolded into the three config files ai-badger owns
(.mcp.json, .github/mcp.json and the pi-native .pi/mcp.json). Every case here was written against the retired
`mcp-servers.json` reader and migrated onto the catalog declaration in ADR-0014 step 8. The
user-global destinations are proposals: ~/.claude/settings.json here, ~/.hermes/config.yaml in
tests/test_adjust_mcp_hermes.py.
"""
# pylint: disable=protected-access  # exercises the Scaffolder MCP mixin directly; see pyproject.toml
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import _test_write

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
        _test_write(index_path, json.dumps({
            "frameworkVersion": "0.1.0",
            "stacks": {},
        }), encoding="utf-8")
    return make_scaffolder(root=root, target=target, config=config)


def _write_mcp_servers(stack_dir, servers):
    """Declare *servers* in a stack's stack-mcp.json, every one of them with `declare: true`.

    The describe-only half of the same file — a name with no `declare` — is
    tests/test_mcp_declared_servers.py's `test_a_describe_only_declaration_is_not_written`.
    """
    stack_dir.mkdir(parents=True, exist_ok=True)
    data = {"servers": [dict(srv, declare=True) for srv in servers]}
    (stack_dir / "stack-mcp.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── collect_catalog_mcp_servers ───────────────────────────────────────────────

def test_collect_from_common(root, make_scaffolder):
    """Common stack-mcp.json is read."""
    target = make_scaffolder.target

    common_dir = root / "features" / "common"
    common_file = common_dir / "stack-mcp.json"
    original = common_file.read_text(encoding="utf-8") if common_file.exists() else None
    try:
        _write_mcp_servers(common_dir, [
            {"name": "baseline", "command": "echo baseline"}
        ])
        scaf = _scaf(make_scaffolder, root, target, _config())
        result = scaf.mcp.collect_catalog_mcp_servers()
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
    result = scaf.mcp.collect_catalog_mcp_servers()
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
    result = scaf.mcp.collect_catalog_mcp_servers()
    assert len(result) == 1
    assert result[0]["command"] == "echo github-version"


def test_collect_missing_file_skipped(tmp_path, make_scaffolder):
    """Stack without stack-mcp.json is silently skipped."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    py_dir.mkdir(parents=True)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python"]))
    result = scaf.mcp.collect_catalog_mcp_servers()
    assert result == []


def test_collect_empty_servers(tmp_path, make_scaffolder):
    """Empty servers array returns empty list."""
    target = make_scaffolder.target

    py_dir = tmp_path / "features" / "python"
    _write_mcp_servers(py_dir, [])

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python"]))
    result = scaf.mcp.collect_catalog_mcp_servers()
    assert result == []


# ── declared_servers ──────────────────────────────────────────────────────────

def test_one_declaration_becomes_one_entry_keyed_by_name(tmp_path, make_scaffolder):
    """The merge the retired `merge_mcp_servers` did: a list in, a dict by name out."""
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python",
                       [{"name": "pyright", "command": "uvx mcp-server-pyright"}])

    declared = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python"])).mcp.declared_servers()

    assert list(declared) == ["pyright"]
    assert declared["pyright"]["command"] == "uvx mcp-server-pyright"


def test_no_declaration_at_all_declares_nothing(tmp_path, make_scaffolder):
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(stacks=["python"]))

    assert scaf.mcp.declared_servers() == {}


def test_the_same_name_in_two_stacks_resolves_to_one_declaration(tmp_path, make_scaffolder):
    """The conflict the two retired readers resolved between themselves is now one file's."""
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python",
                       [{"name": "tool-x", "command": "echo python"}])
    _write_mcp_servers(tmp_path / "features" / "github",
                       [{"name": "tool-x", "command": "echo github"}])

    declared = _scaf(make_scaffolder, tmp_path, target,
                      _config(stacks=["python", "github"])).mcp.declared_servers()

    assert list(declared) == ["tool-x"]
    assert declared["tool-x"]["command"] == "echo github"


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


def test_two_declarations_in_one_stack_both_reach_mcp_json(tmp_path, make_scaffolder):
    """One file declaring two servers writes two entries — the retired two-reader merge's job."""
    target = make_scaffolder.target

    _write_mcp_servers(tmp_path / "features" / "python", [
        {"name": "pyright", "command": "uvx mcp-server-pyright"},
        {"name": "shared", "command": "echo shared"},
    ])

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "pyright" in mcp["mcpServers"]
    assert mcp["mcpServers"]["shared"]["args"] == ["shared"]


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
    assert mcp["mcpServers"]["shared"]["args"] == ["v2"]


def test_mcp_json_merge_preserves_existing(tmp_path, make_scaffolder):
    """Pre-existing .mcp.json entries not overwritten."""
    target = make_scaffolder.target

    existing = {"mcpServers": {"my-server": {"command": "echo existing"}}}
    _test_write(target / ".mcp.json", json.dumps(existing), encoding="utf-8")

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


# ── Hermes: no destination of its own (proposed by its adjustment, step 7) ───

def test_no_scaffold_step_writes_the_hermes_user_config(tmp_path, make_scaffolder):
    """Hermes has no project route, so ADR-0014 decision 6 leaves nothing here to write.

    The `mcp_servers:` snippet a Hermes project gets instead is
    `features/hermes/adjustments/adjust_mcp.py` (tests/test_adjust_mcp_hermes.py).
    """
    target = make_scaffolder.target
    home = tmp_path / "home"
    home.mkdir()
    _write_mcp_servers(tmp_path / "features" / "python",
                       [{"name": "srv", "command": "echo", "scope": "user"}])

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                     _config(stacks=["python"], agents=["hermes"]))
        scaf.run(generated_at="2026-07-30T00:00:00Z")

    assert not (home / ".hermes" / "config.yaml").exists()
    assert not hasattr(scaf.mcp, "scaffold_hermes_mcp_user")


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
    _test_write(home / ".claude" / "settings.json", existing, encoding="utf-8")

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


# ── Copilot: .github/mcp.json, the file the CLI reads (#189) ─────────────────

def test_copilot_mcp_json_generated(tmp_path, make_scaffolder):
    """.github/mcp.json created when copilot in agents."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"pyright": {"name": "pyright", "command": "uvx mcp-server-pyright"}}
    scaf.mcp.generate_copilot_mcp_json(servers)

    config_path = target / ".github" / "mcp.json"
    assert config_path.exists()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert "pyright" in cfg["mcpServers"]


def test_copilot_mcp_json_not_created_for_claude_only(tmp_path, make_scaffolder):
    """No copilot config if copilot not in agents."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    servers = {"pyright": {"name": "pyright", "command": "uvx mcp-server-pyright"}}
    scaf.mcp.generate_copilot_mcp_json(servers)

    assert not (target / ".github" / "mcp.json").exists()


def test_copilot_mcp_json_merge_preserves_existing(tmp_path, make_scaffolder):
    """Existing copilot config entries preserved."""
    target = make_scaffolder.target
    github_dir = target / ".github"
    github_dir.mkdir(parents=True)

    existing = {"mcpServers": {"old": {"command": "echo old"}}}
    _test_write(github_dir / "mcp.json", json.dumps(existing), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"new": {"name": "new", "command": "echo new"}}
    scaf.mcp.generate_copilot_mcp_json(servers)

    cfg = json.loads((github_dir / "mcp.json").read_text(encoding="utf-8"))
    assert "old" in cfg["mcpServers"]
    assert "new" in cfg["mcpServers"]


def test_copilot_env_propagated(tmp_path, make_scaffolder):
    """env field appears in copilot config."""
    target = make_scaffolder.target

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    servers = {"github": {"name": "github", "command": "npx -y @modelcontextprotocol/server-github",
                           "env": {"GITHUB_TOKEN": "test"}}}
    scaf.mcp.generate_copilot_mcp_json(servers)

    cfg = json.loads((target / ".github" / "mcp.json").read_text(encoding="utf-8"))
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
    assert mcp["mcpServers"]["code-review-graph"]["command"] == "code-review-graph"
    assert mcp["mcpServers"]["code-review-graph"]["args"] == ["serve"]


def test_no_mcp_json_when_no_servers(tmp_path, make_scaffolder):
    """Nothing declared anywhere -> no .mcp.json."""
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


def test_mcp_json_uses_copilot_overrides_when_claude_is_not_configured(tmp_path, make_scaffolder):
    """Copilot CLI reads `.mcp.json` too, so with no Claude configured it is Copilot's (#193)."""
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "copilot-resolved"


def test_mcp_json_applies_no_override_when_neither_reader_is_configured(tmp_path,
                                                                       make_scaffolder):
    """Its readers are Claude Code and the Copilot CLI; a Hermes-only project has neither."""
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["hermes"]))
    scaf.mcp.generate_mcp_json()

    mcp = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["fs"]["command"] == "npx"
    assert any(".mcp.json" in note for note in scaf.notes)


# ── one shared file, one launch every reader can start (pi reads it too) ──────

def _anchored_task_graph_server():
    """The catalog's task-graph shape: project-relative base, anchored Claude override."""
    return [{
        "name": "task-graph",
        "command": "uv run --script .ai-badger/skills/demo/task_graph_server.py",
        "agentOverrides": {
            "claude": {
                "command": "uv",
                "args": ["run", "--script",
                         "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/demo/task_graph_server.py"],
            },
        },
    }]


def test_mcp_json_keeps_claudes_anchor_with_pi_configured(
        tmp_path, make_scaffolder, monkeypatch, load_script):
    """Native pi reads .pi/mcp.json, never .mcp.json (F1/F2), so with pi configured this file
    stays Claude's: the ${CLAUDE_PROJECT_DIR} anchor survives and the fork-era 'dropped for
    pi' resolution is gone."""
    _no_user_tool_dirs(monkeypatch, load_script)
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _anchored_task_graph_server())
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude", "pi"]))
    scaf.mcp.generate_mcp_json()

    entry = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"]["task-graph"]
    assert entry["args"] == ["run", "--script",
                             "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/demo/task_graph_server.py"]
    assert not any("resolves its agent overrides for" in note for note in scaf.notes)


def test_mcp_json_keeps_claudes_anchor_for_a_claude_only_project(
        tmp_path, make_scaffolder, monkeypatch, load_script):
    """A claude-only project resolves for Claude exactly as before (F-22)."""
    _no_user_tool_dirs(monkeypatch, load_script)
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _anchored_task_graph_server())
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    entry = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"]["task-graph"]
    assert entry["args"] == ["run", "--script",
                             "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/demo/task_graph_server.py"]


def test_mcp_json_pi_only_project_gets_base_launches_with_override_note(
        tmp_path, make_scaffolder, monkeypatch, load_script):
    """pi's project reader is .pi/mcp.json, not .mcp.json: a pi-only project configures none
    of .mcp.json's readers (claude, copilot), so the base declaration renders and the
    'written without agent overrides' note fires."""
    _no_user_tool_dirs(monkeypatch, load_script)
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _anchored_task_graph_server())
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["pi"]))
    scaf.mcp.generate_mcp_json()

    entry = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"]["task-graph"]
    assert entry["args"] == ["run", "--script",
                             ".ai-badger/skills/demo/task_graph_server.py"]
    assert any("written without agent overrides" in note for note in scaf.notes)


def test_copilot_mcp_json_uses_copilot_overrides(tmp_path, make_scaffolder):
    """With Claude also configured, `.mcp.json` resolves for Claude and this file is skipped
    instead of contradicting it (#193) — tests/test_one_declaration_per_server.py."""
    target = make_scaffolder.target
    _write_mcp_servers(tmp_path / "features" / "python", _both_agents_server())

    scaf = _scaf(make_scaffolder, tmp_path, target,
                  _config(stacks=["python"], agents=["copilot"]))
    scaf.mcp.generate_copilot_mcp_json(scaf.mcp.declared_servers())

    cfg = json.loads((target / ".github" / "mcp.json").read_text(encoding="utf-8"))
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
    The `tools` allowlist is dropped from the two Claude/Copilot project files and the pi
    `exposure` default from `.pi/mcp.json`: both belong to the hosts that read them, and these
    cases characterise command splitting, cwd and env.
    """
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    by_name = {server["name"]: server}

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                     _config(stacks=["python"], agents=["claude", "copilot", "hermes", "pi"]))
        scaf.mcp.generate_mcp_json()
        scaf.mcp.generate_copilot_mcp_json(by_name)
        scaf.mcp.generate_pi_mcp_json()
        scaf.mcp.propose_claude_mcp_user(by_name)

    name = server["name"]

    def _json_entry(path):
        return json.loads(path.read_text(encoding="utf-8"))["mcpServers"][name]

    copilot = _json_entry(target / ".github" / "mcp.json")
    assert copilot.pop("tools") == ["*"]
    mcp_json = _json_entry(target / ".mcp.json")
    assert mcp_json.pop("tools") == ["*"]
    pi_mcp = _json_entry(target / ".pi" / "mcp.json")
    assert pi_mcp.pop("exposure") == "direct"
    proposal = next(n for n in scaf.notes if "~/.claude/settings.json" in n)
    return {
        "mcp_json": mcp_json,
        "copilot": copilot,
        "pi_mcp": pi_mcp,
        "claude_user": json.loads(proposal.split("yourself: ", 1)[1])["mcpServers"][name],
    }


_SPLIT_CASES = [
    # command, the entry every destination renders for it
    ("uvx mcp-server-pyright", {"command": "uvx", "args": ["mcp-server-pyright"]}),
    ("npx -y @modelcontextprotocol/server-github",
     {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}),
    ("node /opt/mcp/server.js", {"command": "node", "args": ["/opt/mcp/server.js"]}),
    ("echo v2", {"command": "echo", "args": ["v2"]}),
    ("hermes mcp serve", {"command": "hermes", "args": ["mcp", "serve"]}),
    ("pyright-mcp", {"command": "pyright-mcp"}),
]


@pytest.mark.parametrize("command,everywhere", _SPLIT_CASES)
def test_one_splitter_renders_the_same_executable_everywhere(
        command, everywhere, tmp_path, monkeypatch, load_script, make_scaffolder):
    """Two files that split a command differently declare different servers (#193)."""
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        make_scaffolder, tmp_path, {"name": "srv", "command": command}, home)

    for destination, entry in entries.items():
        assert entry == everywhere, destination


def _scaffold_mcp_json_from(make_scaffolder, tmp_path, target, server):
    """Run only the .mcp.json generation, as though scaffolded from *target*."""
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    scaf = _scaf(make_scaffolder, tmp_path, target,
                 _config(stacks=["python"], agents=["claude"]))
    scaf.mcp.generate_mcp_json()
    return scaf


class TestCwdIsNotGenerated:
    """.mcp.json is tracked, so a refresh must not carry a machine-specific cwd."""

    @staticmethod
    def _project(tmp_path, name):
        target = tmp_path / name
        (target / ".ai-badger").mkdir(parents=True, exist_ok=True)
        return target

    def test_a_cwd_pointing_at_a_live_checkout_is_removed(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        _no_user_tool_dirs(monkeypatch, load_script)
        main = self._project(tmp_path, "proj")
        worktree = self._project(tmp_path, "wt")
        server = {"name": "srv", "command": "uvx mcp-server-pyright"}
        _scaffold_mcp_json_from(make_scaffolder, tmp_path, main, server)
        _test_write(worktree / ".mcp.json", (main / ".mcp.json").read_text(encoding="utf-8"), encoding="utf-8")

        _scaffold_mcp_json_from(make_scaffolder, tmp_path, worktree, server)

        assert "cwd" not in json.loads(
            (worktree / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["srv"]

    def test_a_cwd_pointing_nowhere_is_removed(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        _no_user_tool_dirs(monkeypatch, load_script)
        target = self._project(tmp_path, "proj")
        _test_write(target / ".mcp.json", json.dumps({"mcpServers": {"srv": {
            "command": "uvx", "args": ["mcp-server-pyright"],
            "cwd": str(tmp_path / "deleted-worktree")}}}), encoding="utf-8")

        _scaffold_mcp_json_from(
            make_scaffolder, tmp_path, target, {"name": "srv", "command": "uvx mcp-server-pyright"})

        assert "cwd" not in json.loads(
            (target / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["srv"]

    def test_a_first_scaffold_does_not_pin_the_project_it_ran_from(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        _no_user_tool_dirs(monkeypatch, load_script)
        target = self._project(tmp_path, "proj")

        _scaffold_mcp_json_from(
            make_scaffolder, tmp_path, target, {"name": "srv", "command": "uvx mcp-server-pyright"})

        assert "cwd" not in json.loads(
            (target / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["srv"]

    def test_everything_but_cwd_is_still_refreshed(
            self, tmp_path, monkeypatch, load_script, make_scaffolder):
        """Preserving cwd must not freeze the rest of a stale entry."""
        _no_user_tool_dirs(monkeypatch, load_script)
        main = self._project(tmp_path, "proj")
        _test_write(main / ".mcp.json", json.dumps({"mcpServers": {"srv": {
            "command": "stale-command", "cwd": str(main)}}}), encoding="utf-8")

        _scaffold_mcp_json_from(
            make_scaffolder, tmp_path, main, {"name": "srv", "command": "uvx mcp-server-pyright"})

        entry = json.loads((main / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["srv"]
        assert entry["command"] == "uvx"
        assert "cwd" not in entry


def test_no_mcp_destination_pins_the_project_cwd(tmp_path, monkeypatch, load_script, make_scaffolder):
    """Every generated config stays portable across checkouts and worktrees."""
    _no_user_tool_dirs(monkeypatch, load_script)
    home = tmp_path / "home"
    home.mkdir()

    entries = _render_everywhere(
        make_scaffolder, tmp_path, {"name": "srv", "command": "uvx mcp-server-pyright"}, home)

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


# ── pi: .pi/mcp.json, the project config native pi reads (F1) ────────────────

def _pi_json(target):
    """The parsed .pi/mcp.json under *target*, or {} when the destination wrote nothing."""
    path = target / ".pi" / "mcp.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pi_scaffolder(make_scaffolder, tmp_path, declared, agents=("pi",), declined=()):
    """Declare *declared* and build a Scaffolder with pi configured (optionally declining)."""
    _write_mcp_servers(tmp_path / "features" / "python", declared)
    config = _config(stacks=["python"], agents=list(agents))
    if declined:
        config["mcp"] = {"decline": list(declined)}
    return _scaf(make_scaffolder, tmp_path, make_scaffolder.target, config)


def _seed_pi(target, section):
    """Write an existing .pi/mcp.json with *section* as its mcpServers mapping."""
    (target / ".pi").mkdir(parents=True, exist_ok=True)
    _test_write(target / ".pi" / "mcp.json",
                json.dumps({"mcpServers": section}, indent=2) + "\n", encoding="utf-8")


def test_pi_mcp_json_written_for_pi_agent(tmp_path, make_scaffolder, monkeypatch):
    """A pi-configured project gets .pi/mcp.json; native pi never reads .mcp.json (F1)."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "pyright", "command": "uvx mcp-server-pyright"}])

    scaf.mcp.generate_pi_mcp_json()

    assert (make_scaffolder.target / ".pi" / "mcp.json").is_file()
    entry = _pi_json(make_scaffolder.target)["mcpServers"]["pyright"]
    assert entry["command"] == "uvx"
    assert any("trusted project" in note for note in scaf.notes)


def test_pi_mcp_json_not_created_without_pi_agent(tmp_path, make_scaffolder, monkeypatch):
    """Gated on config.agents like every requires_reader destination."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "pyright", "command": "uvx mcp-server-pyright"}],
                          agents=("claude",))

    scaf.mcp.generate_pi_mcp_json()

    assert not (make_scaffolder.target / ".pi" / "mcp.json").exists()


def test_pi_mcp_json_splits_shell_string_command(tmp_path, make_scaffolder, monkeypatch):
    """pi takes one executable plus args, never a shell string (F4/F8): the three shapes."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [
        {"name": "task-graph",
         "command": "uv run --script .ai-badger/skills/demo/task_graph_server.py"},
        {"name": "graph", "command": "code-review-graph serve"},
        {"name": "raccoon", "command": "ai-raccoon"},
        {"name": "explicit", "command": "uv", "args": ["run", "--script", "my script.py"]},
    ])

    scaf.mcp.generate_pi_mcp_json()

    entries = _pi_json(make_scaffolder.target)["mcpServers"]
    assert entries["task-graph"] == {
        "command": "uv",
        "args": ["run", "--script", ".ai-badger/skills/demo/task_graph_server.py"],
        "exposure": "direct",
    }
    assert entries["graph"] == {"command": "code-review-graph", "args": ["serve"],
                                "exposure": "direct"}
    assert entries["raccoon"] == {"command": "ai-raccoon", "exposure": "direct"}
    # an explicit args array is never split: its element keeps its space
    assert entries["explicit"] == {"command": "uv", "args": ["run", "--script", "my script.py"],
                                   "exposure": "direct"}


@pytest.mark.parametrize("override,expected", [
    ("", "~/.dotnet/tools/cwm-roslyn-navigator"),
    ("all", "cwm-roslyn-navigator"),
])
def test_pi_mcp_json_uses_tilde_home_form_not_dollar_home(
        override, expected, tmp_path, monkeypatch, load_script, make_scaffolder):
    """pi expands `~` in command/args/cwd; `${HOME}` stays literal, so pi must never emit it.
    The AI_BADGER_MCP_AVAILABILITY override gates the rewrite exactly as it gates `${HOME}`."""
    load_script(SCAFFOLD)
    dotnet = tmp_path / "fake-home" / ".dotnet" / "tools"
    dotnet.mkdir(parents=True)
    exe = dotnet / "cwm-roslyn-navigator"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(sys.modules["mcp_tools"], "USER_TOOL_DIRS",
                        ((dotnet, "${HOME}/.dotnet/tools"),))
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", override)
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "roslyn", "command": "cwm-roslyn-navigator"}])

    scaf.mcp.generate_pi_mcp_json()

    entry = _pi_json(make_scaffolder.target)["mcpServers"]["roslyn"]
    assert entry["command"] == expected
    assert "${HOME}" not in json.dumps(entry)


def test_pi_mcp_json_carries_no_tools_array(tmp_path, make_scaffolder, monkeypatch):
    """`tools` is the fork filter pi does not read (F4)."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "srv", "command": "uvx srv"}])

    scaf.mcp.generate_pi_mcp_json()

    assert "tools" not in _pi_json(make_scaffolder.target)["mcpServers"]["srv"]


def test_pi_mcp_json_new_entries_default_to_direct_exposure(
        tmp_path, make_scaffolder, monkeypatch):
    """pi's `codemode` default leaves tools undeclared; `direct` is what the model can call."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "srv", "command": "uvx srv"}])

    scaf.mcp.generate_pi_mcp_json()

    assert _pi_json(make_scaffolder.target)["mcpServers"]["srv"]["exposure"] == "direct"


def test_pi_mcp_json_inherits_no_claude_anchor(tmp_path, make_scaffolder, monkeypatch):
    """Resolve agentOverrides for pi's own reader, never Claude's ${CLAUDE_PROJECT_DIR} (F8)."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, _anchored_task_graph_server())

    scaf.mcp.generate_pi_mcp_json()

    entry = _pi_json(make_scaffolder.target)["mcpServers"]["task-graph"]
    assert entry["command"] == "uv"
    assert entry["args"] == ["run", "--script", ".ai-badger/skills/demo/task_graph_server.py"]
    assert "${CLAUDE_PROJECT_DIR}" not in json.dumps(entry)


def test_pi_mcp_json_records_generated_config(tmp_path, make_scaffolder, monkeypatch):
    """Every write is recorded for the manifest's generatedConfig (#194)."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "srv", "command": "uvx srv"}])

    scaf.mcp.generate_pi_mcp_json()

    assert [r for r in scaf.generated_config.all_records([])
            if r["path"] == ".pi/mcp.json"] == [{
        "path": ".pi/mcp.json", "destination": ".pi/mcp.json",
        "frameworkVersion": scaf.index["frameworkVersion"],
    }]


def test_pi_native_existing_entry_survives_scaffold_byte_identical(
        tmp_path, make_scaffolder, monkeypatch):
    """F11(a): an entry already present survives re-scaffold byte-identical, decorations and all."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    recorded = {"command": "code-review-graph", "args": ["serve"],
                "exposure": "deferred", "toolExposure": {"get_*": "codemode"},
                "enabled": False}
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "code-review-graph", "command": "code-review-graph serve"}])
    path = make_scaffolder.target / ".pi" / "mcp.json"
    _seed_pi(make_scaffolder.target, {"code-review-graph": recorded})
    before = path.read_bytes()

    scaf.mcp.generate_pi_mcp_json()

    assert path.read_bytes() == before
    assert _pi_json(make_scaffolder.target)["mcpServers"]["code-review-graph"] == recorded


_PI_REFERENCE_STATE = {
    "autoEnableCodemode": False,
    "mcpServers": {
        "ai-raccoon": {"command": "ai-raccoon", "exposure": "direct"},
        "task-graph": {
            "command": "uv",
            "args": ["run", "--script",
                     ".ai-badger/skills/task-decomposition/scripts/task_graph_server.py"],
            "exposure": "direct",
        },
        "semantica": {
            "command": "semantica-mcp",
            "env": {"SEMANTICA_DISABLE_PROGRESS": "1"},
            "exposure": "direct",
        },
        "code-review-graph": {
            "command": "code-review-graph",
            "args": ["serve"],
            "exposure": "deferred",
            "toolExposure": {"search_*": "codemode", "delete_*": "hidden"},
        },
        "playwright": {
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest"],
            "exposure": "deferred",
            "toolExposure": {"browser_*": "direct"},
            "customField": {"kept": True},
        },
    },
}

_PI_REFERENCE_CATALOG = [
    {"name": "ai-raccoon", "command": "ai-raccoon"},
    {"name": "task-graph",
     "command": "uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_server.py"},
    {"name": "semantica", "command": "semantica-mcp",
     "env": {"SEMANTICA_DISABLE_PROGRESS": "1"}},
    {"name": "code-review-graph", "command": "code-review-graph serve"},
    {"name": "playwright", "command": "npx -y @playwright/mcp@latest"},
]


def test_pi_native_reference_state_survives_deep_equal(tmp_path, make_scaffolder, monkeypatch):
    """The sibling's tuned state — 3 direct + 2 deferred, toolExposure maps and unknown keys —
    survives whole (F6/F10/F11). A merge that preserves exposure but drops toolExposure or an
    unknown key fails this deep-equal."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, _PI_REFERENCE_CATALOG)
    target = make_scaffolder.target
    (target / ".pi").mkdir(parents=True, exist_ok=True)
    _test_write(target / ".pi" / "mcp.json",
                json.dumps(_PI_REFERENCE_STATE, indent=2) + "\n", encoding="utf-8")

    scaf.mcp.generate_pi_mcp_json()

    assert _pi_json(target) == _PI_REFERENCE_STATE


def test_pi_native_new_entry_gets_template(tmp_path, make_scaffolder, monkeypatch):
    """F11(b): a declared server absent from the file is appended with today's template."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    existing = {"known": {"command": "known-server", "exposure": "deferred"}}
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [
        {"name": "known", "command": "known-server"},
        {"name": "fresh", "command": "uvx fresh-server --flag"},
    ])
    _seed_pi(make_scaffolder.target, existing)

    scaf.mcp.generate_pi_mcp_json()

    after = _pi_json(make_scaffolder.target)["mcpServers"]
    assert after["known"] == existing["known"]
    assert after["fresh"] == {"command": "uvx", "args": ["fresh-server", "--flag"],
                              "exposure": "direct"}


def test_pi_native_unknown_entry_survives(tmp_path, make_scaffolder, monkeypatch):
    """F11(c): the merge is a union — a user-added server is never dropped or rewritten."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    personal = {"command": "my-personal-server", "args": ["--mine"], "enabled": True,
                "unknownKey": {"nested": [1, 2]}}
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "known", "command": "known-server"}])
    _seed_pi(make_scaffolder.target, {"personal": personal})

    scaf.mcp.generate_pi_mcp_json()

    assert _pi_json(make_scaffolder.target)["mcpServers"]["personal"] == personal


def test_pi_native_declined_server_removed(tmp_path, make_scaffolder, monkeypatch):
    """F11(d): config.mcp.decline still removes its named servers, with a note (#186)."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "code-review-graph", "command": "code-review-graph serve"},
                           {"name": "keep", "command": "uvx keep"}],
                          declined=("code-review-graph",))
    _seed_pi(make_scaffolder.target, {
        "code-review-graph": {"command": "code-review-graph", "args": ["serve"],
                              "exposure": "direct"},
        "keep": {"command": "uvx", "args": ["keep"], "exposure": "direct"},
    })

    scaf.mcp.generate_pi_mcp_json()

    after = _pi_json(make_scaffolder.target)["mcpServers"]
    assert "code-review-graph" not in after
    assert "keep" in after
    assert any("declined" in note and "code-review-graph" in note for note in scaf.notes)


def test_pi_native_unavailable_tuned_entry_removed(tmp_path, make_scaffolder, monkeypatch):
    """F11(e): a template-identical entry is removed when its executable is unavailable even
    when exposure/toolExposure/enabled are tuned away from the template — decorations never
    shield it, and never count toward identity."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [
        {"name": "ghost", "command": "ghost-mcp serve",
         "availability": {"command": "definitely-not-a-real-executable"}},
    ])
    _seed_pi(make_scaffolder.target, {
        "ghost": {"command": "ghost-mcp", "args": ["serve"], "exposure": "deferred",
                  "toolExposure": {"x_*": "hidden"}, "enabled": False},
    })

    scaf.mcp.generate_pi_mcp_json()

    assert "ghost" not in _pi_json(make_scaffolder.target)["mcpServers"]
    assert any("unavailable" in note and "ghost" in note for note in scaf.notes)


def test_pi_native_unavailable_tilde_form_entry_removed(
        tmp_path, make_scaffolder, monkeypatch, load_script):
    """F11(e) two-phase: the `~/` home form a run wrote while the executable existed is still
    today's template once the executable is gone — removed with the unavailable note, never
    kept as a hand edit. A one-template comparison renders the bare command in phase 2, sees a
    launch difference, and leaves the dead entry behind (MUST 1)."""
    load_script(SCAFFOLD)
    dotnet = tmp_path / "fake-home" / ".dotnet" / "tools"
    dotnet.mkdir(parents=True)
    exe = dotnet / "ghost-mcp"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(sys.modules["mcp_tools"], "USER_TOOL_DIRS",
                        ((dotnet, "${HOME}/.dotnet/tools"),))
    monkeypatch.setenv("PATH", os.pathsep.join([str(dotnet), os.environ.get("PATH", "")]))
    monkeypatch.delenv("AI_BADGER_MCP_AVAILABILITY", raising=False)
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [
        {"name": "ghost", "command": "ghost-mcp serve",
         "availability": {"command": "ghost-mcp"}},
    ])

    # phase 1: the executable is present, so the recorded launch is the portable `~/` form
    scaf.mcp.generate_pi_mcp_json()
    assert _pi_json(make_scaffolder.target)["mcpServers"]["ghost"]["command"] == \
        "~/.dotnet/tools/ghost-mcp"

    # phase 2: the executable is gone — the entry is dead, not hand-edited
    exe.unlink()
    scaf.mcp.generate_pi_mcp_json()

    assert "ghost" not in _pi_json(make_scaffolder.target)["mcpServers"]
    assert any("unavailable" in note and "ghost" in note for note in scaf.notes)


def test_pi_native_user_scoped_unavailable_entry_survives(
        tmp_path, make_scaffolder, monkeypatch):
    """A `scope: user` declaration is outside `.pi/mcp.json`'s project-scoped contract: its
    name must never reach the pi drop pass, so a user-placed template-identical entry — one
    this destination never wrote — survives (SHOULD 1)."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [
        {"name": "ghost", "command": "ghost-mcp serve", "scope": "user",
         "availability": {"command": "definitely-not-a-real-executable"}},
    ])
    recorded = {"command": "ghost-mcp", "args": ["serve"], "exposure": "direct"}
    _seed_pi(make_scaffolder.target, {"ghost": recorded})

    scaf.mcp.generate_pi_mcp_json()

    assert _pi_json(make_scaffolder.target)["mcpServers"]["ghost"] == recorded


_HAND_EDITED_LAUNCHES = {
    "args": {"command": "ghost-mcp", "args": ["serve", "--project", "."]},
    "env": {"command": "ghost-mcp", "args": ["serve"], "env": {"GHOST_TOKEN": "x"}},
    "cwd": {"command": "ghost-mcp", "args": ["serve"], "cwd": "/elsewhere"},
}


@pytest.mark.parametrize("dimension,edited", sorted(_HAND_EDITED_LAUNCHES.items()))
def test_pi_native_unavailable_hand_edited_entry_kept_with_note(
        dimension, edited, tmp_path, make_scaffolder, monkeypatch):
    """F11(f): an unavailable entry whose launch was hand-edited is kept with a note."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [
        {"name": "ghost", "command": "ghost-mcp serve",
         "availability": {"command": "definitely-not-a-real-executable"}},
    ])
    _seed_pi(make_scaffolder.target, {"ghost": edited})

    scaf.mcp.generate_pi_mcp_json()

    assert _pi_json(make_scaffolder.target)["mcpServers"]["ghost"] == edited, dimension
    note = next(n for n in scaf.notes if "ghost" in n)
    assert "hand edit" in note


def test_pi_native_second_render_leaves_file_bytes_unchanged(
        tmp_path, make_scaffolder, monkeypatch):
    """F11 idempotence: a second render of one unchanged file changes no bytes and leaves no
    backup sibling — the writer's re-serialization is accepted at entry level (MUST-risk 3).
    The trust-gate note is per-run state, not per-write: it fires once across both renders."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _pi_scaffolder(make_scaffolder, tmp_path, [{"name": "srv", "command": "uvx srv"}])
    scaf.mcp.generate_pi_mcp_json()
    path = make_scaffolder.target / ".pi" / "mcp.json"
    first = path.read_bytes()

    scaf.mcp.generate_pi_mcp_json()

    assert path.read_bytes() == first
    assert sorted(p.name for p in path.parent.iterdir()) == ["mcp.json"]
    assert sum("trusted project" in note for note in scaf.notes) == 1


def test_pi_native_template_drift_noted_not_applied(tmp_path, make_scaffolder, monkeypatch):
    """F11(a): a launch that differs from today's template is noted, never rewritten."""
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    recorded = {"command": "code-review-graph", "args": ["serve", "--watch"]}
    scaf = _pi_scaffolder(make_scaffolder, tmp_path,
                          [{"name": "code-review-graph", "command": "code-review-graph serve"}])
    _seed_pi(make_scaffolder.target, {"code-review-graph": recorded})

    scaf.mcp.generate_pi_mcp_json()

    assert _pi_json(make_scaffolder.target)["mcpServers"]["code-review-graph"] == recorded
    note = next(n for n in scaf.notes if "template" in n)
    assert "code-review-graph" in note
    assert "kept" in note
