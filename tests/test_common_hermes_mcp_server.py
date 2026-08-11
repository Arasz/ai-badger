"""Behavioral contract for the optional common Hermes MCP server declaration."""
from __future__ import annotations

import json
import sys
from conftest import _test_write


HERMES = "hermes"
HERMES_COMMAND = "hermes mcp serve"
HERMES_AVAILABILITY = {"command": "hermes"}
CODE_REVIEW_GRAPH = "code-review-graph"


def _config() -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaffold(make_scaffolder):
    return make_scaffolder(config=_config())


def _patch_hermes_lookup(monkeypatch, load_script, hermes_path):
    """Patch the shutil lookup used by the loaded mcp_tools module, never the host PATH."""
    load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    mcp_tools = sys.modules["mcp_tools"]

    def fake_which(command):
        if command == HERMES:
            return hermes_path
        if command == CODE_REVIEW_GRAPH:
            return "/fake/code-review-graph"
        return None

    monkeypatch.setattr(mcp_tools.shutil, "which", fake_which)


def test_common_catalog_declares_hermes_with_conditional_availability(root, load_script):
    bl = load_script("engine/badger_lib.py")
    catalog = bl.load_json(root / "features" / "common" / "stack-mcp.json")

    entry = next(server for server in catalog["servers"] if server["name"] == HERMES)

    assert entry["declare"] is True
    assert entry["command"] == HERMES_COMMAND
    assert entry["availability"] == HERMES_AVAILABILITY


def test_stack_mcp_schema_accepts_command_availability_metadata(root, load_script):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "stack-mcp.schema.json")
    instance = {
        "servers": [{
            "name": HERMES,
            "command": HERMES_COMMAND,
            "declare": True,
            "availability": HERMES_AVAILABILITY,
        }]
    }

    assert bl.validate(instance, schema) == []


def test_hermes_catalog_is_indexed_with_its_metadata_files(root, load_script):
    bl = load_script("engine/badger_lib.py")
    items = bl.feature_items(bl.read_index(root), "common", "mcp")
    server = root / "features" / "common" / "mcp" / HERMES

    assert {"name": HERMES, "path": f"features/common/mcp/{HERMES}"} in items
    assert (server / "meta.json").is_file()
    assert (server / "tools.json").is_file()
    assert (server / "server.md").is_file()


def test_installed_hermes_is_declared_and_split_into_mcp_json(
        monkeypatch, load_script, make_scaffolder):
    _patch_hermes_lookup(monkeypatch, load_script, "/fake/hermes")
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()
    assert declared[HERMES]["command"] == HERMES_COMMAND

    scaf.mcp.generate_mcp_json()
    generated = json.loads((make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8"))

    assert generated["mcpServers"][HERMES] == {
        "command": HERMES,
        "args": ["mcp", "serve"],
        "tools": ["*"],
    }
    assert CODE_REVIEW_GRAPH in generated["mcpServers"]


def test_unavailable_hermes_is_omitted_while_code_review_graph_remains(
        monkeypatch, load_script, make_scaffolder):
    _patch_hermes_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()
    assert HERMES not in declared
    assert CODE_REVIEW_GRAPH in declared

    scaf.mcp.generate_mcp_json()
    generated = json.loads((make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8"))

    assert HERMES not in generated["mcpServers"]
    assert CODE_REVIEW_GRAPH in generated["mcpServers"]
    assert generated["mcpServers"][CODE_REVIEW_GRAPH]["command"] == CODE_REVIEW_GRAPH
    assert generated["mcpServers"][CODE_REVIEW_GRAPH]["args"] == ["serve"]


def test_unavailable_hermes_is_removed_from_an_existing_generated_config(
        monkeypatch, load_script, make_scaffolder):
    _patch_hermes_lookup(monkeypatch, load_script, "/fake/hermes")
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()

    _patch_hermes_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    generated = json.loads((make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8"))

    assert HERMES not in generated["mcpServers"]
    assert CODE_REVIEW_GRAPH in generated["mcpServers"]


def test_unavailable_hermes_does_not_remove_a_user_authored_entry(
        monkeypatch, load_script, make_scaffolder):
    _patch_hermes_lookup(monkeypatch, load_script, None)
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({"mcpServers": {
        HERMES: {"type": "http", "url": "https://example.invalid/hermes"},
        "mine": {"command": "echo mine"},
    }}), encoding="utf-8")

    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    generated = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))

    assert generated["mcpServers"][HERMES]["type"] == "http"
    assert generated["mcpServers"]["mine"] == {"command": "echo mine"}


def test_unavailable_hermes_removes_a_home_relative_generated_entry(
        monkeypatch, load_script, make_scaffolder):
    _patch_hermes_lookup(monkeypatch, load_script, "/fake/hermes")
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    target = make_scaffolder.target
    generated = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    generated["mcpServers"][HERMES]["command"] = "${HOME}/.local/bin/hermes"
    _test_write(target / ".mcp.json", json.dumps(generated), encoding="utf-8")

    _patch_hermes_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    generated = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))

    assert HERMES not in generated["mcpServers"]


def test_catalog_validation_tracks_the_new_stack_mcp_metadata(root, load_script):
    validate = load_script("tooling/validate.py")

    assert "stack-mcp.schema.json" in validate.SCHEMA_INSTANCES
    assert validate.undecided_schemas(root) == []


def test_availability_override_all_forces_every_declared_server(
        monkeypatch, load_script, make_scaffolder):
    """The freshness guard's deterministic comparison: 'all' ignores the PATH probe."""
    _patch_hermes_lookup(monkeypatch, load_script, None)
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()

    assert HERMES in declared
    assert CODE_REVIEW_GRAPH in declared


def test_availability_override_none_forces_nothing_declared(
        monkeypatch, load_script, make_scaffolder):
    _patch_hermes_lookup(monkeypatch, load_script, "/fake/hermes")
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "none")
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()

    assert HERMES not in declared
    assert CODE_REVIEW_GRAPH not in declared


def test_availability_override_unset_falls_back_to_path_probe(
        monkeypatch, load_script, make_scaffolder):
    """No override: the PATH probe decides, as before (default behavior unchanged)."""
    monkeypatch.delenv("AI_BADGER_MCP_AVAILABILITY", raising=False)
    _patch_hermes_lookup(monkeypatch, load_script, "/fake/hermes")
    scaf = _scaffold(make_scaffolder)
    assert HERMES in scaf.mcp.declared_servers()

    _patch_hermes_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)
    assert HERMES not in scaf.mcp.declared_servers()


def test_catalog_validation_remains_green(root, load_script):
    validate = load_script("tooling/validate.py")
    assert validate.validate_all(root) == 0

