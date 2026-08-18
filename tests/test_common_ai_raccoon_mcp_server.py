"""Behavioral contract for the optional common AiRaccoon memory-server declaration."""
from __future__ import annotations

import json
import sys
from conftest import _test_write


AI_RACCOON = "ai-raccoon"
AI_RACCOON_COMMAND = "ai-raccoon"  # zero-arg stdio launch — no args!
AI_RACCOON_AVAILABILITY = {"command": "ai-raccoon"}
HERMES = "hermes"
CODE_REVIEW_GRAPH = "code-review-graph"

AI_RACCOON_TOOLS = {
    "memory_write",
    "memory_search",
    "memory_list",
    "memory_stats",
    "memory_share",
    "memory_delete",
    "memory_delete_context",
    "memory_ingest_file",
    "memory_ingest_directory",
    "memory_embed_pending",
    "memory_workspace_begin",
    "memory_workspace_status",
    "memory_workspace_consolidate",
    "memory_workspace_discard",
    "memory_sweep",
    "memory_sync",
    "memory_watch_add",
    "memory_watch_status",
    "memory_watch_remove",
}


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


def _patch_ai_raccoon_lookup(monkeypatch, load_script, ai_raccoon_path):
    """Patch the shutil lookup used by the loaded mcp_tools module, never the host PATH."""
    load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    mcp_tools = sys.modules["mcp_tools"]

    def fake_which(command):
        if command == AI_RACCOON:
            return ai_raccoon_path
        if command == HERMES:
            return "/fake/hermes"
        if command == CODE_REVIEW_GRAPH:
            return "/fake/code-review-graph"
        return None

    monkeypatch.setattr(mcp_tools.shutil, "which", fake_which)


def test_common_catalog_declares_ai_raccoon_with_conditional_availability(root, load_script):
    bl = load_script("engine/badger_lib.py")
    catalog = bl.load_json(root / "features" / "common" / "stack-mcp.json")

    entry = next(server for server in catalog["servers"] if server["name"] == AI_RACCOON)

    assert entry["declare"] is True
    assert entry["command"] == AI_RACCOON_COMMAND
    assert entry["availability"] == AI_RACCOON_AVAILABILITY


def test_stack_mcp_schema_accepts_command_availability_metadata(root, load_script):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "stack-mcp.schema.json")
    instance = {
        "servers": [{
            "name": AI_RACCOON,
            "command": AI_RACCOON_COMMAND,
            "declare": True,
            "availability": AI_RACCOON_AVAILABILITY,
        }]
    }

    assert bl.validate(instance, schema) == []


def test_ai_raccoon_catalog_is_indexed_with_its_metadata_files(root, load_script):
    bl = load_script("engine/badger_lib.py")
    items = bl.feature_items(bl.read_index(root), "common", "mcp")
    server = root / "features" / "common" / "mcp" / AI_RACCOON

    assert {"name": AI_RACCOON, "path": f"features/common/mcp/{AI_RACCOON}"} in items
    assert (server / "meta.json").is_file()
    assert (server / "tools.json").is_file()
    assert (server / "server.md").is_file()


def test_ai_raccoon_meta_json_pins_the_migrated_package_id(root, load_script):
    bl = load_script("engine/badger_lib.py")
    meta = bl.load_json(root / "features" / "common" / "mcp" / AI_RACCOON / "meta.json")

    assert meta["package"] == "ai-raccoon"
    assert meta["prerequisite"]["install"] == "dotnet tool install -g ai-raccoon"


def test_installed_ai_raccoon_is_declared_and_split_into_mcp_json(
        monkeypatch, load_script, make_scaffolder):
    _patch_ai_raccoon_lookup(monkeypatch, load_script, "/fake/ai-raccoon")
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()
    assert declared[AI_RACCOON]["command"] == AI_RACCOON_COMMAND

    scaf.mcp.generate_mcp_json()
    generated = json.loads((make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8"))

    # Zero-arg command: the rendered entry carries no "args" key. Host-dependent
    # ${HOME} rewrite is neutralized by the suite's session-scoped HOME redirection.
    assert generated["mcpServers"][AI_RACCOON] == {
        "command": "ai-raccoon",
        "tools": ["*"],
    }
    assert HERMES in generated["mcpServers"]
    assert CODE_REVIEW_GRAPH in generated["mcpServers"]


def test_unavailable_ai_raccoon_is_omitted_while_others_remain(
        monkeypatch, load_script, make_scaffolder):
    _patch_ai_raccoon_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()
    assert AI_RACCOON not in declared
    assert HERMES in declared
    assert CODE_REVIEW_GRAPH in declared

    scaf.mcp.generate_mcp_json()
    generated = json.loads((make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8"))

    assert AI_RACCOON not in generated["mcpServers"]
    assert HERMES in generated["mcpServers"]
    assert generated["mcpServers"][HERMES]["command"] == HERMES
    assert generated["mcpServers"][HERMES]["args"] == ["mcp", "serve"]
    assert CODE_REVIEW_GRAPH in generated["mcpServers"]


def test_unavailable_ai_raccoon_is_removed_from_an_existing_generated_config(
        monkeypatch, load_script, make_scaffolder):
    _patch_ai_raccoon_lookup(monkeypatch, load_script, "/fake/ai-raccoon")
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()

    _patch_ai_raccoon_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    generated = json.loads((make_scaffolder.target / ".mcp.json").read_text(encoding="utf-8"))

    assert AI_RACCOON not in generated["mcpServers"]
    assert CODE_REVIEW_GRAPH in generated["mcpServers"]


def test_unavailable_ai_raccoon_does_not_remove_a_user_authored_entry(
        monkeypatch, load_script, make_scaffolder):
    _patch_ai_raccoon_lookup(monkeypatch, load_script, None)
    target = make_scaffolder.target
    _test_write(target / ".mcp.json", json.dumps({"mcpServers": {
        AI_RACCOON: {"type": "http", "url": "https://example.invalid/ai-raccoon"},
        "mine": {"command": "echo mine"},
    }}), encoding="utf-8")

    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    generated = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))

    assert generated["mcpServers"][AI_RACCOON]["type"] == "http"
    assert generated["mcpServers"]["mine"] == {"command": "echo mine"}


def test_unavailable_ai_raccoon_removes_a_home_relative_generated_entry(
        monkeypatch, load_script, make_scaffolder):
    _patch_ai_raccoon_lookup(monkeypatch, load_script, "/fake/ai-raccoon")
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    target = make_scaffolder.target
    generated = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    generated["mcpServers"][AI_RACCOON]["command"] = "${HOME}/.dotnet/tools/ai-raccoon"
    _test_write(target / ".mcp.json", json.dumps(generated), encoding="utf-8")

    _patch_ai_raccoon_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)
    scaf.mcp.generate_mcp_json()
    generated = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))

    assert AI_RACCOON not in generated["mcpServers"]


def test_catalog_validation_tracks_the_new_stack_mcp_metadata(root, load_script):
    validate = load_script("tooling/validate.py")

    assert "stack-mcp.schema.json" in validate.SCHEMA_INSTANCES
    assert validate.undecided_schemas(root) == []


def test_availability_override_all_forces_every_declared_server(
        monkeypatch, load_script, make_scaffolder):
    """The freshness guard's deterministic comparison: 'all' ignores the PATH probe."""
    _patch_ai_raccoon_lookup(monkeypatch, load_script, None)
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()

    assert AI_RACCOON in declared
    assert HERMES in declared
    assert CODE_REVIEW_GRAPH in declared


def test_availability_override_none_forces_nothing_declared(
        monkeypatch, load_script, make_scaffolder):
    _patch_ai_raccoon_lookup(monkeypatch, load_script, "/fake/ai-raccoon")
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "none")
    scaf = _scaffold(make_scaffolder)

    declared = scaf.mcp.declared_servers()

    assert AI_RACCOON not in declared
    assert HERMES not in declared
    assert CODE_REVIEW_GRAPH not in declared


def test_availability_override_unset_falls_back_to_path_probe(
        monkeypatch, load_script, make_scaffolder):
    """No override: the PATH probe decides, as before (default behavior unchanged)."""
    monkeypatch.delenv("AI_BADGER_MCP_AVAILABILITY", raising=False)
    _patch_ai_raccoon_lookup(monkeypatch, load_script, "/fake/ai-raccoon")
    scaf = _scaffold(make_scaffolder)
    assert AI_RACCOON in scaf.mcp.declared_servers()

    _patch_ai_raccoon_lookup(monkeypatch, load_script, None)
    scaf = _scaffold(make_scaffolder)
    assert AI_RACCOON not in scaf.mcp.declared_servers()


def test_catalog_validation_remains_green(root, load_script):
    validate = load_script("tooling/validate.py")
    assert validate.validate_all(root) == 0


def test_ai_raccoon_tools_json_carries_the_nineteen_curated_intents(root, load_script):
    bl = load_script("engine/badger_lib.py")
    tools = bl.load_json(root / "features" / "common" / "mcp" / AI_RACCOON / "tools.json")
    taxonomy = bl.load_json(root / "features" / "common" / "mcp-tags.json")
    valid_tags = {tag for cat in taxonomy["categories"].values() for tag in cat["tags"]}

    names = {tool["name"] for tool in tools["tools"]}
    assert names == AI_RACCOON_TOOLS
    for tool in tools["tools"]:
        assert len(tool["intent"]) <= 200, tool["name"]
        assert set(tool.get("tags", [])) <= valid_tags, tool["name"]


def test_ai_raccoon_memory_skill_is_indexed(root, load_script):
    bl = load_script("engine/badger_lib.py")
    items = bl.feature_items(bl.read_index(root), "common", "skills")
    skill = root / "features" / "common" / "skills" / "ai-raccoon-memory"

    assert {"name": "ai-raccoon-memory", "path": "features/common/skills/ai-raccoon-memory",
            "scope": "default"} in items
    assert (skill / "SKILL.md").is_file()


def test_ai_raccoon_memory_skill_watch_ritual_names_semantica_dir(root):
    """The watch-on-docs ritual also watches the .semantica/ directory."""
    skill_md = root / "features" / "common" / "skills" / "ai-raccoon-memory" / "SKILL.md"
    body = skill_md.read_text(encoding="utf-8")
    assert ".semantica/" in body
    assert "memory_watch_add" in body


def test_ai_raccoon_memory_skill_watch_ritual_detects_missing_semantica_dir():
    """A watch ritual that never names .semantica/ is detected as wrong."""
    body = "## 1. Watch-on-docs ritual\n\nmemory_watch_add(projectId, <abs path to docs>)\n"
    assert ".semantica/" not in body
