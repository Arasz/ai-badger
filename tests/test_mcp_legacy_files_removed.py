"""The legacy MCP declaration files are gone, and every reader survives their absence.

Step 4 of the MCP rebuild (ADR-0014 §8): D1 deletes the empty
`features/common/mcp-servers.json`, D2 deletes `features/common/external-tools.json`, its
schema and the `config.externalTools` key, D3 drops `targetAgents` from
`mcp-servers.schema.json`. The reader code stays until step 8, so a reader whose input file no
longer exists must find nothing rather than complain — and the one server the catalog declares
must still reach `.mcp.json` and every agent file.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config

CATALOG_SERVER = "code-review-graph"


def _mcp(make_scaffolder, **kwargs):
    return make_scaffolder(config=_config(agents=["claude"]), **kwargs).mcp


# ── D1: the empty mcp-servers.json catalog file ──────────────────────────────

def test_the_empty_common_mcp_servers_json_is_gone(root):
    """`{"servers": []}` was byte-equivalent to absence, so absence is what it becomes."""
    assert not (root / "features" / "common" / "mcp-servers.json").exists()


def test_no_stack_ships_an_mcp_servers_json_either(root):
    assert sorted((root / "features").glob("*/mcp-servers.json")) == []


def test_the_mcp_servers_reader_finds_nothing_and_says_nothing(make_scaffolder):
    """The mechanism stays until step 8; a missing input is silence, not a note."""
    mcp = _mcp(make_scaffolder)

    assert mcp.collect_stack_mcp_servers() == []
    assert [n for n in mcp.ctx.notes if "mcp-servers.json" in n] == []


# ── D2: external-tools.json, its schema, and the config key ──────────────────

def test_the_external_tools_catalog_file_is_gone(root):
    assert not (root / "features" / "common" / "external-tools.json").exists()
    assert sorted((root / "features").glob("*/external-tools.json")) == []


def test_the_external_tools_schema_is_gone(root):
    assert not (root / "schemas" / "external-tools.schema.json").exists()


def test_validate_all_no_longer_claims_to_cover_it(root, load_script):
    validate = load_script("tooling/validate.py")

    assert "external-tools.schema.json" not in validate.SCHEMA_INSTANCES
    assert validate.undecided_schemas(root) == []


def test_the_external_tools_reader_finds_nothing_and_says_nothing(make_scaffolder):
    mcp = _mcp(make_scaffolder)

    assert mcp.collect_external_tools() == []
    assert [n for n in mcp.ctx.notes if "external-tools.json" in n] == []


def test_the_config_schema_no_longer_carries_external_tools(root, load_script):
    """The key had zero users across all four measured consumer configs (design §1.2)."""
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "config.schema.json")

    assert "externalTools" not in schema["properties"]


def test_a_config_still_declaring_external_tools_is_refused(root, load_script):
    """`additionalProperties: false` turns the removal into a loud break, not a silent no-op."""
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "config.schema.json")
    config = _config()
    config["externalTools"] = [{"name": "x", "package": "p", "command": "c",
                                "instructions": "i"}]

    assert bl.validate(config, schema) != []


def test_nothing_reads_the_config_key_any_more(root):
    """A key the schema refuses cannot reach a scaffold, so no code may branch on it."""
    scripts = root / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts"
    offenders = [path.name for path in sorted(scripts.glob("*.py"))
                 if "externalTools" in path.read_text(encoding="utf-8")]

    assert offenders == []


def test_the_config_only_merge_helper_is_gone(make_scaffolder):
    """`merge_external_tools` merged the config key over the catalog; the key is gone."""
    assert not hasattr(make_scaffolder.module.McpTools, "merge_external_tools")


# ── D3: targetAgents ─────────────────────────────────────────────────────────

def test_target_agents_is_refused_by_the_legacy_schema(root, load_script):
    """It validated and was read by nothing; `stack-mcp.json` never carried it (ADR-0014)."""
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "mcp-servers.schema.json")

    assert bl.validate({"servers": [{"name": "x", "command": "echo",
                                     "targetAgents": ["claude"]}]}, schema) != []
    assert bl.validate({"servers": [{"name": "x", "command": "echo"}]}, schema) == []


# ── what is left standing ────────────────────────────────────────────────────

def test_the_catalog_is_now_the_only_thing_declaring_the_graph(make_scaffolder):
    declared = _mcp(make_scaffolder).declared_servers()

    assert set(declared) == {CATALOG_SERVER}
    assert declared[CATALOG_SERVER]["command"] == "python3 -m code_review_graph serve"


def test_the_legacy_instruction_slot_renders_empty_now(make_scaffolder):
    """Nothing feeds `EXTERNAL_MCP_INSTRUCTIONS` in this repo; the catalog slot carries it all."""
    scaf = make_scaffolder(config=_config(agents=["claude"]), install=True)
    scaf.mcp.fill_instruction_sources()

    slots = scaf.rendering.compute_doc_slots([], [])

    assert scaf.ctx.merged_external_tools == []
    assert slots["EXTERNAL_MCP_INSTRUCTIONS"] == ""
    assert "This project has a knowledge graph" in slots["MCP_INSTRUCTIONS"]


def test_a_stack_that_still_ships_external_tools_json_still_reaches_the_agent_file(
        make_scaffolder, tmp_path):
    """The reader is deprecated, not disconnected — step 8 removes it, not step 4."""
    (tmp_path / "index.json").write_text(
        json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    stack = tmp_path / "features" / "python"
    stack.mkdir(parents=True)
    (stack / "external-tools.json").write_text(json.dumps({"tools": [{
        "name": "legacy-tool", "package": "p", "command": "echo legacy",
        "instructions": "## MCP Tools: legacy-tool\n\nStill injected.\n",
        "generate_mcp_json": True,
    }]}), encoding="utf-8")
    scaf = make_scaffolder(root=tmp_path, config=_config(stacks=["python"], agents=["claude"]))
    scaf.mcp.fill_instruction_sources()

    slots = scaf.rendering.compute_doc_slots([], [])

    assert "Still injected." in slots["EXTERNAL_MCP_INSTRUCTIONS"]
    assert "legacy-tool" in scaf.mcp.declared_servers()
