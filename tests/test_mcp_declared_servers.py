"""One launch declaration, three readers, and legacy losing on conflict.

Step 3 of the MCP rebuild (ADR-0014). `stack-mcp.json`'s `declare: true` joins the legacy
`mcp-servers.json` and `external-tools.json` readers; a catalog declaration beats both, and a
project's own `config.externalTools` entry still beats all three. `collect_stack_mcp_servers`
and `merge_mcp_servers` keep working untouched from the outside — the ~60 tests in
tests/test_stack_mcp_servers.py are the check on that.
"""
from __future__ import annotations

import json

CATALOG_SERVER = "code-review-graph"


def _config(stacks=None, agents=None, external_tools=None):
    cfg = {
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
    if external_tools is not None:
        cfg["externalTools"] = external_tools
    return cfg


def _fake_root(tmp_path):
    """A framework root with only an index.json, so a Scaffolder can start on it."""
    (tmp_path / "index.json").write_text(
        json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    return tmp_path


def _write(tmp_path, stack, filename, payload):
    stack_dir = tmp_path / "features" / stack
    stack_dir.mkdir(parents=True, exist_ok=True)
    (stack_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _declare(tmp_path, stack, *servers):
    _write(tmp_path, stack, "stack-mcp.json", {"servers": list(servers)})


def _legacy_servers(tmp_path, stack, *servers):
    _write(tmp_path, stack, "mcp-servers.json", {"servers": list(servers)})


def _legacy_tools(tmp_path, stack, *tools):
    _write(tmp_path, stack, "external-tools.json", {"tools": list(tools)})


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

    assert servers["shared"]["command"] == "echo github"


# ── the legacy readers, still working ────────────────────────────────────────

def test_a_legacy_mcp_servers_declaration_still_reaches_mcp_json(make_scaffolder, tmp_path):
    _legacy_servers(tmp_path, "python", {"name": "pyright", "command": "uvx mcp-server-pyright"})

    assert "pyright" in _mcp_json(make_scaffolder, tmp_path)


def test_a_legacy_external_tools_declaration_still_reaches_mcp_json(make_scaffolder, tmp_path):
    _legacy_tools(tmp_path, "python", {
        "name": "legacy-tool", "package": "p", "command": "echo legacy",
        "instructions": "x", "generate_mcp_json": True,
    })

    assert "legacy-tool" in _mcp_json(make_scaffolder, tmp_path)


def test_the_two_collectors_stay_separate(make_scaffolder, tmp_path):
    """Neither legacy collector learns about stack-mcp.json; composition happens above them."""
    _legacy_servers(tmp_path, "python", {"name": "old", "command": "echo old"})
    _declare(tmp_path, "python", {"name": "new", "command": "echo new", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path)

    assert [s["name"] for s in scaf.mcp.collect_stack_mcp_servers()] == ["old"]
    assert [s["name"] for s in scaf.mcp.collect_catalog_mcp_servers()] == ["new"]
    assert set(scaf.mcp.declared_servers()) == {"old", "new"}


# ── precedence ───────────────────────────────────────────────────────────────

def test_the_catalog_beats_legacy_mcp_servers_on_the_same_name(make_scaffolder, tmp_path):
    _legacy_servers(tmp_path, "python", {"name": "shared", "command": "echo legacy"})
    _declare(tmp_path, "python", {"name": "shared", "command": "echo catalog",
                                  "declare": True})

    assert _mcp_json(make_scaffolder, tmp_path)["shared"]["command"] == "echo catalog"


def test_the_catalog_beats_a_legacy_external_tool_on_the_same_name(make_scaffolder, tmp_path):
    _legacy_tools(tmp_path, "python", {
        "name": "shared", "package": "p", "command": "echo legacy",
        "instructions": "x", "generate_mcp_json": True,
    })
    _declare(tmp_path, "python", {"name": "shared", "command": "echo catalog",
                                  "declare": True})

    assert _mcp_json(make_scaffolder, tmp_path)["shared"]["command"] == "echo catalog"


def test_a_projects_own_external_tools_entry_beats_the_catalog(make_scaffolder, tmp_path):
    """The user's word is the last one — the same precedence the instructions slot uses."""
    _declare(tmp_path, "python", {"name": "shared", "command": "echo catalog",
                                  "declare": True})
    user = [{"name": "shared", "package": "p", "command": "echo user",
             "instructions": "", "generate_mcp_json": True}]

    servers = _mcp_json(make_scaffolder, tmp_path, _config(external_tools=user))

    assert servers["shared"]["command"] == "echo user"


def test_a_projects_entry_declining_mcp_json_silences_the_catalog_too(make_scaffolder,
                                                                      tmp_path):
    """Omitting generate_mcp_json is how a project opts out — the pre-step-3 behaviour, kept.

    Reasserting the catalog's declaration over that silence would have been a consumer-visible
    break in an additive step (tests/test_external_mcp_tools.py pins the same rule).
    """
    _declare(tmp_path, "python", {"name": "shared", "command": "echo catalog",
                                  "declare": True})
    user = [{"name": "shared", "package": "p", "command": "echo user", "instructions": ""}]

    assert _mcp_json(make_scaffolder, tmp_path, _config(external_tools=user)) == {}


# ── the real catalog: byte identity ──────────────────────────────────────────

def _real_mcp_json(make_scaffolder):
    scaf = make_scaffolder(config=_config(agents=["claude"]), install=True)
    scaf.run(generated_at="2026-07-30T00:00:00Z")
    return (make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8")


def test_the_generated_mcp_json_is_byte_identical_to_the_legacy_path(make_scaffolder,
                                                                     monkeypatch):
    """The one server the catalog declares must land exactly where external-tools.json put it."""
    after = _real_mcp_json(make_scaffolder)

    monkeypatch.setattr(make_scaffolder.module.McpTools, "collect_catalog_mcp_servers",
                        lambda self: [])
    before = _real_mcp_json(make_scaffolder)

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

    assert declared[CATALOG_SERVER]["command"] == "python3 -m code_review_graph serve"
    assert declared[CATALOG_SERVER].get("declare") is True


# ── the other destinations see it too ────────────────────────────────────────

def test_the_copilot_config_is_written_from_the_same_declaration_set(make_scaffolder,
                                                                     tmp_path):
    _declare(tmp_path, "python", {"name": "pyright", "command": "uvx mcp-server-pyright",
                                  "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["copilot"]))

    project, _ = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_config(project)

    config = json.loads((make_scaffolder.target / ".github" / "copilot" / "mcp-config.json")
                        .read_text(encoding="utf-8"))
    assert "pyright" in config["mcpServers"]
