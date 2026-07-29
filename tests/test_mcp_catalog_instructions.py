"""The mcp catalog supplies the agent-file MCP instructions, byte for byte.

Step 2 of the MCP rebuild (ADR-0014). `code-review-graph`'s instructions blob moves out of
`features/common/external-tools.json`'s escaped JSON string and into
`features/common/mcp/code-review-graph/server.md`. The migration is only safe if the rendered
agent files do not move a single byte, so that is what these tests assert — twice, two
different ways, plus a sensitivity check that proves the assertion can fail.
"""
from __future__ import annotations

import json

import pytest

CATALOG_SERVER = "code-review-graph"

# The exact bytes origin/main rendered around the MCP slot, captured from a scaffold run before
# any of step 2 was written. Frozen deliberately: the whole point is that this does not move.
GOLDEN_MCP_REGION = (
    "- `e:` / `extension:` — a request to expand the current task's scope.\n"
    "\n"
    "<!-- code-review-graph MCP tools -->\n"
    "## MCP Tools: code-review-graph\n"
    "\n"
    "**This project has a knowledge graph. Reach for the code-review-graph MCP tools before\n"
    "Grep/Glob/Read** — they cost fewer tokens and return structural context (callers,\n"
    "dependents, test coverage) that file scanning cannot. Fall back to Grep/Glob/Read only\n"
    "where the graph doesn't reach.\n"
    "\n"
    "Entry points: `semantic_search_nodes_tool` to locate code, `query_graph_tool` to trace\n"
    "callers/callees/imports/tests, `detect_changes_tool` for review, `get_impact_radius_tool`\n"
    "for blast radius, `get_architecture_overview_tool` for structure. Each tool's own\n"
    "description covers the rest; the graph auto-updates on file change.\n"
    "\n"
    "\n"
    "\n"
    "## Framework\n"
)


def _config(stacks=None, agents=None, external_tools=None) -> dict:
    cfg = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"] if stacks is None else stacks,
        "agents": ["claude", "hermes"] if agents is None else agents,
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if external_tools is not None:
        cfg["externalTools"] = external_tools
    return cfg


def _render(make_scaffolder, **kwargs):
    """Run one scaffold and return {'CLAUDE.md': text, 'HERMES.md': text, '.mcp.json': text}."""
    scaf = make_scaffolder(config=kwargs.pop("config", _config()), install=True, **kwargs)
    scaf.run(generated_at="2026-07-30T00:00:00Z")
    target = make_scaffolder.target
    mcp_json = target / ".mcp.json"
    return {
        "CLAUDE.md": (target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8"),
        "HERMES.md": (target / ".ai-badger" / "HERMES.md").read_text(encoding="utf-8"),
        ".mcp.json": mcp_json.read_text(encoding="utf-8") if mcp_json.exists() else None,
        "scaffolder": scaf,
    }


def _legacy_only(monkeypatch, module):
    """Silence the catalog, leaving exactly the pre-step-2 code path behind."""
    monkeypatch.setattr(module.McpTools, "collect_catalog_mcp_servers", lambda self: [])


# ── byte identity, whole document ────────────────────────────────────────────

@pytest.mark.parametrize("document", ["CLAUDE.md", "HERMES.md"])
def test_the_rendered_document_is_byte_identical_to_the_legacy_path(make_scaffolder,
                                                                     monkeypatch, document):
    """Catalog-sourced and external-tools-sourced renders must not differ by one byte."""
    after = _render(make_scaffolder)[document]

    _legacy_only(monkeypatch, make_scaffolder.module)
    before = _render(make_scaffolder)[document]

    assert after == before


def test_the_generated_mcp_json_is_byte_identical_to_the_legacy_path(make_scaffolder,
                                                                     monkeypatch):
    """Step 2 moves the prose only; the launch declaration still comes from the legacy reader."""
    after = _render(make_scaffolder)[".mcp.json"]

    _legacy_only(monkeypatch, make_scaffolder.module)
    before = _render(make_scaffolder)[".mcp.json"]

    assert after == before
    assert CATALOG_SERVER in json.loads(after)["mcpServers"]


# ── byte identity, against the frozen golden ─────────────────────────────────

@pytest.mark.parametrize("document", ["CLAUDE.md", "HERMES.md"])
def test_the_mcp_region_matches_the_bytes_captured_before_the_migration(make_scaffolder,
                                                                        document):
    """Guards against both paths changing together, which whole-document equality cannot see."""
    rendered = _render(make_scaffolder)[document]

    assert GOLDEN_MCP_REGION in rendered


def test_the_byte_identity_check_can_fail(make_scaffolder, monkeypatch):
    """A check that cannot fail is not a check (0.21.0). One edited word must break it."""
    module = make_scaffolder.module
    real = module.McpTools._server_instructions
    monkeypatch.setattr(module.McpTools, "_server_instructions",
                        lambda self, name: real(self, name).replace("knowledge graph",
                                                                    "knowledge graphs"))

    rendered = _render(make_scaffolder)["CLAUDE.md"]

    assert GOLDEN_MCP_REGION not in rendered


# ── where the text now comes from ────────────────────────────────────────────

def test_the_prose_is_read_from_the_catalog_and_the_legacy_block_stops_rendering(
        make_scaffolder):
    """Same bytes, different source file — that is the whole of step 2."""
    result = _render(make_scaffolder)
    ctx = result["scaffolder"].ctx

    described = {s["name"]: s for s in ctx.mcp_described}
    assert CATALOG_SERVER in described
    assert "knowledge graph" in described[CATALOG_SERVER]["instructions"]
    assert result["CLAUDE.md"].count("## MCP Tools: code-review-graph") == 1


def test_a_projects_own_external_tools_entry_still_overrides_the_catalog(make_scaffolder):
    """config.externalTools is the user's word and outranks anything the catalog ships."""
    tools = [{
        "name": CATALOG_SERVER,
        "package": CATALOG_SERVER,
        "command": "uvx code-review-graph serve",
        "instructions": "## MCP Tools: code-review-graph\n\nProject-specific wording.\n",
    }]

    rendered = _render(make_scaffolder, config=_config(external_tools=tools))["CLAUDE.md"]

    assert "Project-specific wording." in rendered
    assert "This project has a knowledge graph" not in rendered
    assert rendered.count("## MCP Tools: code-review-graph") == 1


def test_a_declared_server_the_catalog_does_not_describe_is_reported(make_scaffolder,
                                                                     monkeypatch):
    """A name with no features/*/mcp/<name>/ behind it is an authoring slip, not silence."""
    module = make_scaffolder.module
    monkeypatch.setattr(module.McpTools, "collect_catalog_mcp_servers",
                        lambda self: [{"name": "ghost-server"}])

    scaf = _render(make_scaffolder)["scaffolder"]

    assert any("ghost-server" in note for note in scaf.notes)


def test_the_real_catalog_reports_no_missing_server_directory(make_scaffolder):
    scaf = _render(make_scaffolder)["scaffolder"]

    assert not [n for n in scaf.notes if "names no mcp catalog entry" in n]


# ── the templates ────────────────────────────────────────────────────────────

def test_both_slots_sit_adjacent_in_every_template(root):
    """Adjacent on one line is what lets an empty new slot render byte-identically."""
    templates = sorted((root / "features").glob("*/templates/*.tmpl"))
    assert templates, "no agent templates found"

    for tmpl in templates:
        text = tmpl.read_text(encoding="utf-8")
        assert "{{MCP_INSTRUCTIONS}}{{EXTERNAL_MCP_INSTRUCTIONS}}" in text, tmpl


def test_the_new_slot_is_computed_so_no_literal_placeholder_survives(make_scaffolder):
    rendered = _render(make_scaffolder)

    for document in ("CLAUDE.md", "HERMES.md"):
        assert "{{" not in rendered[document]


# ── the catalog content ──────────────────────────────────────────────────────

def test_the_common_stack_declares_code_review_graph(root, load_script):
    bl = load_script("engine/badger_lib.py")
    declared = bl.load_json(root / "features" / "common" / "stack-mcp.json")

    entry = next(s for s in declared["servers"] if s["name"] == CATALOG_SERVER)
    assert entry["declare"] is True
    assert entry["command"] == "python3 -m code_review_graph serve"


def test_the_catalog_directory_carries_all_three_files(root):
    server = root / "features" / "common" / "mcp" / CATALOG_SERVER

    assert (server / "meta.json").is_file()
    assert (server / "tools.json").is_file()
    assert (server / "server.md").is_file()


def test_the_index_lists_the_server(root, load_script):
    bl = load_script("engine/badger_lib.py")

    items = bl.feature_items(bl.read_index(root), "common", "mcp")

    assert {"name": CATALOG_SERVER, "path": f"features/common/mcp/{CATALOG_SERVER}"} in items


def test_the_package_moved_out_of_external_tools_and_into_meta(root, load_script):
    """`package` is a property of the server, not of one stack's use of it."""
    bl = load_script("engine/badger_lib.py")
    meta = bl.load_json(root / "features" / "common" / "mcp" / CATALOG_SERVER / "meta.json")

    assert meta["name"] == CATALOG_SERVER
    assert meta["package"] == CATALOG_SERVER


def test_every_shipped_server_md_stays_within_the_line_budget(root):
    """It lands verbatim in every agent file, every session — policy, not a manual."""
    oversized = {
        path.parent.name: len(path.read_text(encoding="utf-8").strip().splitlines())
        for path in sorted((root / "features").glob("*/mcp/*/server.md"))
        if len(path.read_text(encoding="utf-8").strip().splitlines()) > 15
    }

    assert not oversized, f"server.md over the 15-line budget: {oversized}"


def test_the_curated_tool_intents_use_the_shipped_tag_vocabulary(root, load_script):
    """tools.json is authored against features/common/mcp-tags.json, a closed set."""
    bl = load_script("engine/badger_lib.py")
    taxonomy = bl.load_json(root / "features" / "common" / "mcp-tags.json")
    valid = {tag for cat in taxonomy["categories"].values() for tag in cat["tags"]}

    for path in sorted((root / "features").glob("*/mcp/*/tools.json")):
        for tool in bl.load_json(path)["tools"]:
            assert set(tool.get("tags", [])) <= valid, f"{path}: {tool['name']}"
            assert tool["intent"].strip(), f"{path}: {tool['name']} has no intent"


# ── the two catalog schemas ──────────────────────────────────────────────────

class TestMcpServerSchemas:
    def _schema(self, root, load_script, name):
        bl = load_script("engine/badger_lib.py")
        return bl, bl.load_json(root / "schemas" / name)

    def test_meta_requires_a_name(self, root, load_script):
        bl, schema = self._schema(root, load_script, "mcp-server.schema.json")

        assert bl.validate({}, schema) != []
        assert bl.validate({"name": "x"}, schema) == []

    def test_meta_refuses_an_unknown_field(self, root, load_script):
        bl, schema = self._schema(root, load_script, "mcp-server.schema.json")

        assert bl.validate({"name": "x", "instructions": "y"}, schema) != []

    def test_tools_requires_a_name_and_an_intent_per_tool(self, root, load_script):
        bl, schema = self._schema(root, load_script, "mcp-server-tools.schema.json")

        assert bl.validate({"server": "x", "tools": [{"name": "t"}]}, schema) != []
        assert bl.validate(
            {"server": "x", "tools": [{"name": "t", "intent": "does a thing"}]}, schema) == []

    def test_tools_refuses_an_unknown_field(self, root, load_script):
        bl, schema = self._schema(root, load_script, "mcp-server-tools.schema.json")

        instance = {"server": "x", "tools": [{"name": "t", "intent": "i", "description": "d"}]}
        assert bl.validate(instance, schema) != []

    def test_validate_all_covers_both(self, root, load_script):
        validate = load_script("tooling/validate.py")

        assert "mcp-server.schema.json" in validate.SCHEMA_INSTANCES
        assert "mcp-server-tools.schema.json" in validate.SCHEMA_INSTANCES
        assert validate.undecided_schemas(root) == []
