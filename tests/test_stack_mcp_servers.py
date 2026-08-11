"""Tests for stack-declared MCP server scaffolding.

Verifies that `stack-mcp.json` files in feature directories are collected, resolved into one
declaration set, split by scope, and scaffolded into the two config files ai-badger owns
(.mcp.json and .github/mcp.json). Every case here was written against the retired
`mcp-servers.json` reader and migrated onto the catalog declaration in ADR-0014 step 8. The
user-global destinations are proposals: ~/.claude/settings.json here, ~/.hermes/config.yaml in
tests/test_adjust_mcp_hermes.py.
"""
# pylint: disable=protected-access  # exercises the Scaffolder MCP mixin directly; see pyproject.toml
from __future__ import annotations

import json
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
    """Render *server* into all three destinations; return their entries for it.

    The Claude user destination is a proposal note rather than a file (ADR-0014 decision 6),
    so its entry is read back out of the note — the rendering it characterises is the same.
    The `tools` allowlist is dropped from the two project files: it belongs to the hosts that
    read them, and these cases characterise command splitting, cwd and env.
    """
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    _write_mcp_servers(tmp_path / "features" / "python", [server])
    by_name = {server["name"]: server}

    with patch("pathlib.Path.home", return_value=home):
        scaf = _scaf(make_scaffolder, tmp_path, target,
                     _config(stacks=["python"], agents=["claude", "copilot", "hermes"]))
        scaf.mcp.generate_mcp_json()
        scaf.mcp.generate_copilot_mcp_json(by_name)
        scaf.mcp.propose_claude_mcp_user(by_name)

    name = server["name"]

    def _json_entry(path):
        return json.loads(path.read_text(encoding="utf-8"))["mcpServers"][name]

    copilot = _json_entry(target / ".github" / "mcp.json")
    assert copilot.pop("tools") == ["*"]
    mcp_json = _json_entry(target / ".mcp.json")
    assert mcp_json.pop("tools") == ["*"]
    proposal = next(n for n in scaf.notes if "~/.claude/settings.json" in n)
    return {
        "mcp_json": mcp_json,
        "copilot": copilot,
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
