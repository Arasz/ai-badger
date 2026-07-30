"""`config.mcp.decline` stops the declaration itself — the last half of issue #186.

Step 6 made a declined server *denied* on the Claude host while still writing its launch config
into `.mcp.json`. Denying a server ai-badger just declared is a contradiction the files should
not carry, and on Copilot — whose only committable block is not declaring it — leaving the entry
behind means the decline does nothing at all.
"""
from __future__ import annotations

import json
from pathlib import Path

MCP_JSON = Path(".mcp.json")
COPILOT = Path(".github") / "mcp.json"


def _config(agents=None, decline=None):
    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": agents if agents is not None else ["claude", "copilot"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if decline is not None:
        config["mcp"] = {"decline": list(decline)}
    return config


def _declare(tmp_path, *servers):
    stack = tmp_path / "features" / "python"
    stack.mkdir(parents=True, exist_ok=True)
    (stack / "stack-mcp.json").write_text(
        json.dumps({"servers": [dict(s, declare=True) for s in servers]}), encoding="utf-8")


def _scaf(make_scaffolder, tmp_path, config):
    index_path = tmp_path / "index.json"
    if not index_path.exists():
        index_path.write_text(json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}),
                              encoding="utf-8")
    return make_scaffolder(root=tmp_path, target=make_scaffolder.target, config=config)


def test_a_declined_server_is_not_declared_at_all(make_scaffolder, tmp_path):
    """The one sentence: a declined server is not a declared server."""
    _declare(tmp_path, {"name": "keep", "command": "echo keep"},
             {"name": "drop", "command": "echo drop"})
    scaf = _scaf(make_scaffolder, tmp_path, _config(decline=["drop"]))

    assert set(scaf.mcp.declared_servers()) == {"keep"}


def test_a_declined_server_never_reaches_mcp_json(make_scaffolder, tmp_path):
    _declare(tmp_path, {"name": "keep", "command": "echo keep"},
             {"name": "drop", "command": "echo drop"})
    scaf = _scaf(make_scaffolder, tmp_path, _config(decline=["drop"]))

    scaf.mcp.generate_mcp_json()

    servers = json.loads((make_scaffolder.target / MCP_JSON).read_text(encoding="utf-8"))
    assert set(servers["mcpServers"]) == {"keep"}


def test_declining_a_server_removes_the_entry_a_previous_scaffold_wrote(make_scaffolder,
                                                                       tmp_path):
    """Merge-only would keep launching it; the decline has to reach the file that exists."""
    target = make_scaffolder.target
    _declare(tmp_path, {"name": "keep", "command": "echo keep"})
    (target / MCP_JSON).write_text(json.dumps({"mcpServers": {
        "keep": {"command": "echo keep"}, "drop": {"command": "echo drop"}}}), encoding="utf-8")
    scaf = _scaf(make_scaffolder, tmp_path, _config(decline=["drop"]))

    scaf.mcp.generate_mcp_json()

    servers = json.loads((target / MCP_JSON).read_text(encoding="utf-8"))["mcpServers"]
    assert "drop" not in servers
    assert "keep" in servers


def test_a_server_declined_but_never_declared_leaves_the_file_untouched(make_scaffolder,
                                                                       tmp_path):
    """Nothing is created just to remove a name that was never there."""
    _declare(tmp_path)
    scaf = _scaf(make_scaffolder, tmp_path, _config(decline=["rider"]))

    scaf.mcp.generate_mcp_json()

    assert not (make_scaffolder.target / MCP_JSON).exists()


def test_the_declined_list_is_read_from_config(make_scaffolder, tmp_path):
    scaf = _scaf(make_scaffolder, tmp_path, _config(decline=["rider", "", "playwright"]))

    assert scaf.mcp.declined_servers() == ["rider", "playwright"]


def test_no_decline_key_declines_nothing(make_scaffolder, tmp_path):
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    assert scaf.mcp.declined_servers() == []


# ── what the adjusters are handed ────────────────────────────────────────────

def test_an_adjustment_receives_the_launch_config_resolved_for_its_own_agent(make_scaffolder,
                                                                            tmp_path):
    """An adjustment is loaded by path and cannot resolve stack-mcp.json itself."""
    _declare(tmp_path, {"name": "srv", "command": "generic", "agentOverrides": {
        "hermes": {"command": "hermes-resolved"}, "copilot": {"command": "copilot-resolved"}}})
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["hermes", "copilot"]))

    hermes = scaf.mcp.declarations_for_agent("hermes")
    copilot = scaf.mcp.declarations_for_agent("copilot")

    assert hermes["srv"]["command"] == "hermes-resolved"
    assert copilot["srv"]["command"] == "copilot-resolved"


def test_a_declined_server_is_not_in_the_declarations_an_adjustment_sees(make_scaffolder,
                                                                        tmp_path):
    _declare(tmp_path, {"name": "drop", "command": "echo drop"})
    scaf = _scaf(make_scaffolder, tmp_path, _config(decline=["drop"]))

    assert scaf.mcp.declarations_for_agent("hermes") == {}


def test_a_user_scoped_declaration_still_reaches_an_adjustment(make_scaffolder, tmp_path):
    """Hermes has no project route, so scope has nothing to select on there."""
    _declare(tmp_path, {"name": "srv", "command": "echo", "scope": "user"})
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["hermes"]))

    assert scaf.mcp.declarations_for_agent("hermes")["srv"]["scope"] == "user"


def _install_probe_adjustment(tmp_path: Path, agent: str) -> None:
    """A throwaway adjustment for *agent* that dumps the context keys it was handed."""
    directory = tmp_path / "features" / agent / "adjustments"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "adjustment.json").write_text(json.dumps({"agent": agent, "adjustments": [
        {"feature": "mcp", "description": "probe", "script": "adjust_probe.py"}]}),
        encoding="utf-8")
    (directory / "adjust_probe.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "def adjust(context):\n"
        "    Path(context['framework_root'], 'probe.json').write_text(json.dumps({\n"
        "        'mcp_declarations': context['mcp_declarations'],\n"
        "        'mcp_declined': context['mcp_declined'],\n"
        "        'mcp_servers': context['mcp_servers'],\n"
        "    }), encoding='utf-8')\n"
        "    return {'applied': False, 'files': [], 'notes': 'probe'}\n",
        encoding="utf-8")


def test_the_adjustment_context_carries_the_declarations_and_the_declines(make_scaffolder,
                                                                         tmp_path):
    """Both new keys reach `adjust(context)` — the Hermes and Copilot proposals need them."""
    _declare(tmp_path, {"name": "srv", "command": "echo srv"},
             {"name": "rider", "command": "echo rider"})
    _install_probe_adjustment(tmp_path, "hermes")
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["hermes"], decline=["rider"]))

    scaf.run_adjustments()

    seen = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert seen["mcp_declarations"]["srv"]["command"] == "echo srv"
    assert seen["mcp_declined"] == ["rider"]
    assert seen["mcp_servers"] == ["srv"]
