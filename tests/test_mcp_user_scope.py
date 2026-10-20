"""A project's own scope decision for a declared MCP server.

A server's scope used to live only in the framework catalog (``stack-mcp.json``), so a
project could not say "this server is mine to register, not yours to write". ``config.mcp.scope``
is that decision: a map of server name to ``user`` or ``project``.

``user`` means: ai-badger writes the server into no project file (.mcp.json,
.github/mcp.json, .pi/mcp.json) and proposes a user-global registration instead
(ADR-0014 decision 6 — ai-badger proposes user-global configuration, it never writes it).
``project`` means the opposite, and it overrides a catalog that says ``user``.

Every case here was written before the code it pins; each names the failure mode it targets.
"""
from __future__ import annotations

import json

from conftest import _test_write

CATALOG_SERVER = "code-review-graph"


def _config(stacks=None, agents=None, scope=None, decline=None):
    """A project config; `scope` and `decline` land in the `mcp` block."""
    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"] if stacks is None else stacks,
        "agents": ["claude", "copilot", "pi"] if agents is None else agents,
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    mcp = {}
    if scope is not None:
        mcp["scope"] = scope
    if decline is not None:
        mcp["decline"] = decline
    if mcp:
        config["mcp"] = mcp
    return config


def _fake_root(tmp_path):
    """A framework root with only an index.json, so a Scaffolder can start on it."""
    _test_write(tmp_path / "index.json",
                json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    return tmp_path


def _declare(tmp_path, stack, *servers):
    stack_dir = tmp_path / "features" / stack
    stack_dir.mkdir(parents=True, exist_ok=True)
    _test_write(stack_dir / "stack-mcp.json", json.dumps({"servers": list(servers)}),
                encoding="utf-8")


def _scaf(make_scaffolder, tmp_path, config=None):
    return make_scaffolder(root=_fake_root(tmp_path),
                           config=_config() if config is None else config)


def _servers(path):
    """The `mcpServers` object of the JSON file at *path*, or {} when it is not there."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})


def _mcp_json(make_scaffolder, tmp_path, config=None):
    scaf = _scaf(make_scaffolder, tmp_path, config)
    scaf.mcp.generate_mcp_json()
    return _servers(make_scaffolder.target / ".mcp.json")


# ── the project says user ────────────────────────────────────────────────────

def test_a_user_scoped_server_stays_out_of_mcp_json(make_scaffolder, tmp_path):
    """The point of the knob: a server the project registers itself is not written."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})

    servers = _mcp_json(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))

    assert "mem" not in servers


def test_a_user_scoped_server_stays_out_of_the_copilot_and_pi_files(make_scaffolder, tmp_path):
    """One scope decision, every project file — not just .mcp.json."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))

    project_servers, user_servers = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_json(project_servers)
    scaf.mcp.generate_pi_mcp_json()

    assert "mem" not in _servers(make_scaffolder.target / ".github" / "mcp.json")
    assert "mem" not in _servers(make_scaffolder.target / ".pi" / "mcp.json")
    assert "mem" in user_servers


def test_an_entry_an_earlier_run_wrote_comes_back_out(make_scaffolder, tmp_path):
    """A project that flips a server to user scope must not keep the old entry."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({
        "mcpServers": {"mem": {"command": "echo mem", "tools": ["*"]}}
    }), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))
    scaf.mcp.generate_mcp_json()

    assert "mem" not in _servers(target / ".mcp.json")


def test_the_removal_note_names_the_server_and_its_scope(make_scaffolder, tmp_path):
    """A silent removal is indistinguishable from a server that was never there."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({
        "mcpServers": {"mem": {"command": "echo mem", "tools": ["*"]}}
    }), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))
    scaf.mcp.generate_mcp_json()

    assert any("mem" in note and "user" in note for note in scaf.ctx.notes)


def test_a_stale_entry_comes_back_out_of_the_copilot_and_pi_files(make_scaffolder, tmp_path):
    """Every project file the scope decision covers, not only .mcp.json.

    The Copilot CLI reads .github/mcp.json and pi reads .pi/mcp.json; a project-scoped
    copy of a user-scoped server in either of them is the same collision.
    """
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    target = make_scaffolder.target
    (target / ".github").mkdir(parents=True, exist_ok=True)
    (target / ".pi").mkdir(parents=True, exist_ok=True)
    _test_write(target / ".github" / "mcp.json", json.dumps({
        "mcpServers": {"mem": {"command": "echo mem", "tools": ["*"]}}
    }), encoding="utf-8")
    _test_write(target / ".pi" / "mcp.json", json.dumps({
        "mcpServers": {"mem": {"command": "echo mem", "exposure": "direct"}}
    }), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))
    project_servers, user_servers = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_json(project_servers)
    scaf.mcp.generate_pi_mcp_json()

    assert "mem" not in _servers(target / ".github" / "mcp.json")
    assert "mem" not in _servers(target / ".pi" / "mcp.json")


def test_a_user_scoped_server_is_still_proposed_for_the_user_global_config(make_scaffolder,
                                                                           tmp_path):
    """User scope is not a silent drop: the operator is told what to register."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))

    _, user_servers = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.propose_claude_mcp_user(user_servers)

    assert any("mem" in note for note in scaf.ctx.notes)


def test_a_hand_written_project_entry_for_a_user_scoped_server_is_removed(make_scaffolder,
                                                                          tmp_path):
    """The scope decision outranks the entry's author: two registrations of one server.

    The project said the server is registered at user scope. A project-scoped entry for
    the same server is the collision the scope decision exists to end — so it goes, and the
    note says why.
    """
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({
        "mcpServers": {"mem": {"type": "http", "url": "https://example.invalid/mem"}}
    }), encoding="utf-8")

    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))
    scaf.mcp.generate_mcp_json()

    assert "mem" not in _servers(target / ".mcp.json")
    assert any("mem" in note for note in scaf.ctx.notes)


# ── precedence ────────────────────────────────────────────────────────────────

def test_decline_wins_over_a_user_scope_override(make_scaffolder, tmp_path):
    """A declined server is refused outright — it is not registered anywhere."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path,
                 _config(scope={"mem": "user"}, decline=["mem"]))

    project_servers, user_servers = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_mcp_json()
    scaf.mcp.propose_claude_mcp_user(user_servers)

    assert "mem" not in project_servers
    assert "mem" not in user_servers
    assert "mem" not in _servers(make_scaffolder.target / ".mcp.json")
    assert not any("mem" in note for note in scaf.ctx.notes)


def test_a_scope_override_can_force_a_user_scoped_catalog_server_back_to_project(make_scaffolder,
                                                                               tmp_path):
    """The framework's default is not the project's: the project decides both ways."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True,
                                  "scope": "user"})

    servers = _mcp_json(make_scaffolder, tmp_path, _config(scope={"mem": "project"}))

    assert servers["mem"]["command"] == "echo"


def test_a_catalog_user_scope_stays_user_without_an_override(make_scaffolder, tmp_path):
    """The catalog's own scope keeps working; the override only adds a way to change it."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True,
                                  "scope": "user"})

    assert _mcp_json(make_scaffolder, tmp_path) == {}


# ── a name nobody declared ───────────────────────────────────────────────────

def test_a_scope_override_for_a_server_nobody_declares_is_reported(make_scaffolder, tmp_path):
    """A typo in the config must not read as a server that is simply not there."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mrm": "user"}))

    scaf.mcp.declared_servers()

    assert any("mrm" in note for note in scaf.ctx.notes)


def test_the_unmatched_name_is_reported_once_per_run(make_scaffolder, tmp_path):
    """The declaration set is read more than once per run; the report is not a per-call echo."""
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mrm": "user"}))

    scaf.mcp.declared_servers()
    scaf.mcp.declared_servers()

    assert len([note for note in scaf.ctx.notes if "mrm" in note]) == 1


def test_a_scope_override_for_a_server_that_is_declared_but_unavailable_is_not_reported(
        make_scaffolder, tmp_path):
    """The server is declared; its binary is missing. That is not an unknown name."""
    _declare(tmp_path, "python", {"name": "mem", "command": "not-a-binary-on-this-path",
                                  "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))

    scaf.mcp.declared_servers()

    assert not any("no declared MCP server matches" in note for note in scaf.ctx.notes)


def test_a_user_scoped_server_is_not_a_project_server(make_scaffolder, tmp_path):
    """The approval route follows the scope: there is no project entry to approve.

    Claude's .claude/settings.json approves the servers this project writes into
    .mcp.json; a user-scoped server is not one of them.
    """
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))

    assert scaf.mcp.project_server_names() == []


def test_the_scope_decision_reaches_the_per_agent_adjustments(make_scaffolder, tmp_path):
    """One scope decision, read by everyone.

    The adjustments that filter by scope (Copilot, Codex) are handed the declaration
    itself, so the project's decision has to be on the declaration — otherwise the
    project file says one thing and the host's own file says another.
    """
    _declare(tmp_path, "python", {"name": "mem", "command": "echo mem", "declare": True})
    scaf = _scaf(make_scaffolder, tmp_path, _config(scope={"mem": "user"}))

    declarations = scaf.mcp.declarations_for_agent("copilot")

    assert declarations["mem"]["scope"] == "user"


# ── the real catalog ─────────────────────────────────────────────────────────

def test_ai_raccoon_is_user_scoped_by_default(root):
    """The catalog default the framework ships: ai-raccoon is registered once, by the user.

    A user who registered ai-raccoon at user scope has to remove the project-scoped copy
    after every refresh otherwise; the default ends that.
    """
    payload = json.loads(
        (root / "features" / "common" / "stack-mcp.json").read_text(encoding="utf-8"))

    raccoon = next(s for s in payload["servers"] if s["name"] == "ai-raccoon")

    assert raccoon.get("scope") == "user"
    assert raccoon.get("declare") is True


def test_the_frameworks_own_tracked_mcp_files_carry_no_ai_raccoon_entry(root):
    """The framework repo is scaffolded by the framework — its own files follow the default.

    `.mcp.json` is gitignored here, so the two tracked files are what the default can be
    seen in.
    """
    for rel in (".github/mcp.json", ".pi/mcp.json"):
        payload = json.loads((root / rel).read_text(encoding="utf-8"))

        assert "ai-raccoon" not in payload.get("mcpServers", {}), rel
