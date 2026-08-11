"""The legacy MCP declaration files are gone, and so is the reader that outlived them.

Steps 4 and 8 of the MCP rebuild (ADR-0014 §8). Step 4 deleted
`features/common/mcp-servers.json`, `features/common/external-tools.json`, its schema and the
`config.externalTools` key, and left both readers standing for one release. Step 8 removes the
readers, `mcp-servers.schema.json` and the `{{EXTERNAL_MCP_INSTRUCTIONS}}` slot. A stack that
still ships either file is now named in a scaffold note instead of being quietly read — the
opposite failure mode from silence, which is this repository's recurring one.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config
from conftest import _test_write

CATALOG_SERVER = "code-review-graph"
RETIRED = ("mcp-servers.json", "external-tools.json")


def _mcp(make_scaffolder, **kwargs):
    return make_scaffolder(config=_config(agents=["claude"]), **kwargs).mcp


def _stack_shipping(tmp_path, filename, payload):
    """A framework root whose `python` stack still ships one retired declaration file."""
    _test_write(tmp_path / "index.json", json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    stack = tmp_path / "features" / "python"
    stack.mkdir(parents=True, exist_ok=True)
    _test_write(stack / filename, json.dumps(payload), encoding="utf-8")
    return tmp_path


def _legacy_scaffolder(make_scaffolder, tmp_path, filename, payload):
    return make_scaffolder(root=_stack_shipping(tmp_path, filename, payload),
                           config=_config(stacks=["python"], agents=["claude"]))


# ── D1: the empty mcp-servers.json catalog file ──────────────────────────────

def test_the_empty_common_mcp_servers_json_is_gone(root):
    """`{"servers": []}` was byte-equivalent to absence, so absence is what it becomes."""
    assert not (root / "features" / "common" / "mcp-servers.json").exists()


def test_no_stack_ships_an_mcp_servers_json_either(root):
    assert sorted((root / "features").glob("*/mcp-servers.json")) == []


def test_the_legacy_mcp_servers_schema_is_gone(root):
    """The mechanism's schema outlived the mechanism by four steps; step 8 is its end."""
    assert not (root / "schemas" / "mcp-servers.schema.json").exists()


# ── D2: external-tools.json, its schema, and the config key ──────────────────

def test_the_external_tools_catalog_file_is_gone(root):
    assert not (root / "features" / "common" / "external-tools.json").exists()
    assert sorted((root / "features").glob("*/external-tools.json")) == []


def test_the_external_tools_schema_is_gone(root):
    assert not (root / "schemas" / "external-tools.schema.json").exists()


def test_validate_all_no_longer_claims_to_cover_either_legacy_schema(root, load_script):
    validate = load_script("tooling/validate.py")

    assert "external-tools.schema.json" not in validate.SCHEMA_INSTANCES
    assert "mcp-servers.schema.json" not in validate.SCHEMA_INSTANCES
    assert validate.undecided_schemas(root) == []


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


# ── D5: the readers themselves ───────────────────────────────────────────────

def test_no_legacy_reader_survives_on_mcp_tools(make_scaffolder):
    """`declared_servers` is catalog-only now; nothing else may read the retired shapes."""
    retired = {"collect_stack_mcp_servers", "collect_external_tools", "merge_external_tools",
               "merge_mcp_servers", "fill_merged_external_tools", "fill_instruction_sources"}

    assert retired & set(dir(make_scaffolder.module.McpTools)) == set()


def test_the_only_script_naming_either_retired_file_is_the_one_that_refuses_it(
        root, load_script):
    """The filenames survive as a refusal list, not as a path any code still opens."""
    scripts = root / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts"
    offenders = sorted(path.name for path in scripts.glob("*.py")
                       if any(f in path.read_text(encoding="utf-8") for f in RETIRED))

    assert offenders == ["mcp_tools.py"]
    assert load_script(
        "features/common/skills/welcome-ai-badger/scripts/mcp_tools.py"
    ).RETIRED_DECLARATION_FILES == RETIRED


def test_the_context_no_longer_caches_merged_external_tools(load_script, root):
    """Both cache fields went with the reader that filled them."""
    ctx_module = load_script(
        "features/common/skills/welcome-ai-badger/scripts/scaffold_context.py")
    fields = set(ctx_module.ScaffoldContext.__dataclass_fields__)

    assert {"merged_external_tools", "external_tools_merged"} & fields == set()


# ── the loud failure a stale consumer overlay gets ───────────────────────────

def test_a_stack_still_shipping_mcp_servers_json_is_named_not_read(make_scaffolder, tmp_path):
    """A file no reader consults must be reported, not silently ignored (ADR-0014 step 8)."""
    scaf = _legacy_scaffolder(make_scaffolder, tmp_path, "mcp-servers.json",
                              {"servers": [{"name": "old", "command": "echo old"}]})

    declared = scaf.mcp.declared_servers()

    assert "old" not in declared
    assert any("features/python/mcp-servers.json" in n for n in scaf.notes)


def test_a_stack_still_shipping_external_tools_json_is_named_not_read(make_scaffolder,
                                                                      tmp_path):
    scaf = _legacy_scaffolder(make_scaffolder, tmp_path, "external-tools.json", {"tools": [{
        "name": "legacy-tool", "package": "p", "command": "echo legacy",
        "instructions": "## MCP Tools: legacy-tool\n\nNo longer injected.\n",
        "generate_mcp_json": True,
    }]})

    declared = scaf.mcp.declared_servers()

    assert "legacy-tool" not in declared
    assert any("features/python/external-tools.json" in n for n in scaf.notes)


def test_the_note_points_at_the_file_that_replaces_it(make_scaffolder, tmp_path):
    """Naming the retired file without naming its replacement leaves the reader stuck."""
    scaf = _legacy_scaffolder(make_scaffolder, tmp_path, "mcp-servers.json", {"servers": []})

    scaf.mcp.declared_servers()

    note = next(n for n in scaf.notes if "mcp-servers.json" in n)
    assert "stack-mcp.json" in note


def test_the_retired_file_is_named_once_however_often_the_declarations_are_read(
        make_scaffolder, tmp_path):
    """One scaffold run reads `declared_servers` three times; the operator sees one note."""
    scaf = _legacy_scaffolder(make_scaffolder, tmp_path, "external-tools.json", {"tools": []})

    scaf.mcp.declared_servers()
    scaf.mcp.declared_servers()
    scaf.mcp.declarations_for_agent("claude")

    assert len([n for n in scaf.notes if "external-tools.json" in n]) == 1


def test_an_unparseable_retired_file_is_still_named(make_scaffolder, tmp_path):
    """The check is presence, not content — a retired file is never parsed again."""
    root = _stack_shipping(tmp_path, "mcp-servers.json", {"servers": []})
    _test_write(root / "features" / "python" / "mcp-servers.json", '{"servers": [', encoding="utf-8")
    scaf = make_scaffolder(root=root, config=_config(stacks=["python"], agents=["claude"]))

    scaf.mcp.declared_servers()

    assert any("features/python/mcp-servers.json" in n for n in scaf.notes)


def test_this_framework_ships_neither_file_so_the_note_never_fires(make_scaffolder):
    mcp = _mcp(make_scaffolder)

    mcp.declared_servers()

    assert [n for n in mcp.ctx.notes if any(f in n for f in RETIRED)] == []


# ── the retired instruction slot ─────────────────────────────────────────────

def test_no_template_carries_the_retired_slot(root):
    """One server, one block, one slot — the second slot existed only for the legacy reader."""
    templates = sorted((root / "features").glob("*/templates/*.tmpl"))
    assert templates, "no agent templates found"

    for tmpl in templates:
        assert "EXTERNAL_MCP_INSTRUCTIONS" not in tmpl.read_text(encoding="utf-8"), tmpl


def test_the_computed_slots_no_longer_offer_the_retired_name(make_scaffolder):
    scaf = make_scaffolder(config=_config(agents=["claude"]), install=True)
    scaf.mcp.fill_mcp_described()

    slots = scaf.rendering.compute_doc_slots([], [])

    assert "EXTERNAL_MCP_INSTRUCTIONS" not in slots
    assert "This project has a knowledge graph" in slots["MCP_INSTRUCTIONS"]


# ── what is left standing ────────────────────────────────────────────────────

def test_the_catalog_is_now_the_only_thing_declaring_the_graph(make_scaffolder):
    declared = _mcp(make_scaffolder).declared_servers()

    assert CATALOG_SERVER in declared
    assert declared[CATALOG_SERVER]["command"] == "code-review-graph serve"
