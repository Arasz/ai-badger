"""One launch declaration, one reader.

Steps 3 and 8 of the MCP rebuild (ADR-0014). `stack-mcp.json`'s `declare: true` joined two
legacy readers in step 3, outranked both in step 4, and is the only one left after step 8 —
tests/test_mcp_legacy_files_removed.py owns what a stack still shipping a retired file gets.
"""
from __future__ import annotations

import json
from conftest import _test_write

CATALOG_SERVER = "code-review-graph"


def _config(stacks=None, agents=None):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"] if stacks is None else stacks,
        "agents": ["claude"] if agents is None else agents,
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _fake_root(tmp_path):
    """A framework root with only an index.json, so a Scaffolder can start on it."""
    _test_write(tmp_path / "index.json", json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    return tmp_path


def _write(tmp_path, stack, filename, payload):
    stack_dir = tmp_path / "features" / stack
    stack_dir.mkdir(parents=True, exist_ok=True)
    _test_write(stack_dir / filename, json.dumps(payload, indent=2), encoding="utf-8")


def _declare(tmp_path, stack, *servers):
    _write(tmp_path, stack, "stack-mcp.json", {"servers": list(servers)})


def _scaf(make_scaffolder, tmp_path, config=None):
    return make_scaffolder(root=_fake_root(tmp_path),
                           config=_config() if config is None else config)


def _mcp_json(make_scaffolder, tmp_path, config=None):
    scaf = _scaf(make_scaffolder, tmp_path, config)
    scaf.mcp.generate_mcp_json()
    path = make_scaffolder.target / ".mcp.json"
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"] if path.exists() else {}


# ── the new reader ───────────────────────────────────────────────────────────

def test_a_catalog_declaration_reaches_mcp_json(make_scaffolder, tmp_path):
    _declare(tmp_path, "python", {"name": "pyright", "command": "uvx mcp-server-pyright",
                                  "declare": True})

    servers = _mcp_json(make_scaffolder, tmp_path)

    assert servers["pyright"]["command"] == "uvx"
    assert servers["pyright"]["args"] == ["mcp-server-pyright"]


def test_a_describe_only_declaration_is_not_written(make_scaffolder, tmp_path):
    """Naming a server says it is relevant. Writing its launch config is the louder claim."""
    _declare(tmp_path, "python", {"name": "rider"},
             {"name": "playwright", "command": "npx -y playwright-mcp", "declare": False})

    assert _mcp_json(make_scaffolder, tmp_path) == {}


def test_env_and_agent_overrides_survive_a_catalog_declaration(make_scaffolder, tmp_path):
    _declare(tmp_path, "python", {
        "name": "fs",
        "command": "npx -y server-filesystem",
        "declare": True,
        "env": {"TOKEN": "not-a-real-token"},
        "agentOverrides": {"claude": {"command": "claude-resolved"}},
    })

    entry = _mcp_json(make_scaffolder, tmp_path)["fs"]

    assert entry["command"] == "claude-resolved"
    assert entry["env"] == {"TOKEN": "not-a-real-token"}


def test_a_user_scoped_catalog_declaration_stays_out_of_mcp_json(make_scaffolder, tmp_path):
    _declare(tmp_path, "python", {"name": "hermes-side", "command": "echo x",
                                  "declare": True, "scope": "user"})
    scaf = _scaf(make_scaffolder, tmp_path)

    project, user = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())

    assert "hermes-side" in user
    assert "hermes-side" not in project


def test_a_later_stack_wins_over_an_earlier_one(make_scaffolder, tmp_path):
    _declare(tmp_path, "python", {"name": "shared", "command": "echo python", "declare": True})
    _declare(tmp_path, "github", {"name": "shared", "command": "echo github", "declare": True})

    servers = _mcp_json(make_scaffolder, tmp_path,
                        _config(stacks=["python", "github"]))

    assert servers["shared"]["args"] == ["github"]


# ── one collector, and only one ──────────────────────────────────────────────

def test_the_catalog_collector_is_the_whole_of_the_declaration_set(make_scaffolder, tmp_path):
    """Step 8: what `declared_servers` returns is what one `stack-mcp.json` reader found."""
    _declare(tmp_path, "python", {"name": "new", "command": "echo new", "declare": True},
             {"name": "described-only"})
    scaf = _scaf(make_scaffolder, tmp_path)

    assert [s["name"] for s in scaf.mcp.collect_catalog_mcp_servers()] == ["new",
                                                                          "described-only"]
    assert set(scaf.mcp.declared_servers()) == {"new"}


# ── the real catalog: byte identity ──────────────────────────────────────────

def _real_mcp_json(make_scaffolder):
    scaf = make_scaffolder(config=_config(agents=["claude"]), install=True)
    scaf.run(generated_at="2026-07-30T00:00:00Z")
    return (make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8")


def test_the_generated_mcp_json_is_byte_identical_across_two_renders(make_scaffolder):
    """`.mcp.json` is untracked, so a double render is what byte-identity means for it."""
    before = _real_mcp_json(make_scaffolder)

    after = _real_mcp_json(make_scaffolder)

    assert after == before
    assert CATALOG_SERVER in json.loads(after)["mcpServers"]


def test_the_byte_identity_check_can_fail(make_scaffolder, monkeypatch):
    """A check that cannot fail is not a check (0.21.0)."""
    before = _real_mcp_json(make_scaffolder)

    module = make_scaffolder.module
    real = module.McpTools.collect_catalog_mcp_servers
    monkeypatch.setattr(module.McpTools, "collect_catalog_mcp_servers",
                        lambda self: [dict(s, command="echo perturbed") for s in real(self)])
    after = _real_mcp_json(make_scaffolder)

    assert after != before


def test_the_real_declaration_comes_from_the_catalog_now(make_scaffolder):
    scaf = make_scaffolder(config=_config(agents=["claude"]))

    declared = scaf.mcp.declared_servers()

    assert declared[CATALOG_SERVER]["command"] == "code-review-graph serve"
    assert declared[CATALOG_SERVER].get("declare") is True


# ── the other destinations see it too ────────────────────────────────────────

def test_the_copilot_config_is_written_from_the_same_declaration_set(make_scaffolder,
                                                                     tmp_path):
    _declare(tmp_path, "python", {"name": "pyright", "command": "uvx mcp-server-pyright",
                                  "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["copilot"]))

    project, _ = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_json(project)

    config = json.loads((make_scaffolder.target / ".github" / "mcp.json")
                        .read_text(encoding="utf-8"))
    assert "pyright" in config["mcpServers"]
