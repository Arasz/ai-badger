"""The mcp catalog outranks the name heuristics when it describes a tool (ADR-0014, design §5).

`features/<stack>/mcp/<server>/tools.json` is hand-written curation; `_auto_tags` is a substring
guess. Where both have an opinion the catalog wins, and the index records which one spoke.
"""

from __future__ import annotations

import json
from pathlib import Path

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"

# A catalog tool (features/common/mcp/code-review-graph/tools.json) and one the catalog omits.
CURATED_TOOL = "semantic_search_nodes_tool"
UNCURATED_TOOL = "build_or_update_graph_tool"


def _catalog_entry(root: Path, server: str, tool: str) -> dict:
    """The curated entry for one tool, read straight from the shipped catalog."""
    data = json.loads(
        (root / "features" / "common" / "mcp" / server / "tools.json").read_text(encoding="utf-8")
    )
    return next(t for t in data["tools"] if t["name"] == tool)


def _read_index(project: Path) -> dict:
    return json.loads((project / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))


def _write_index(project: Path, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "mcp-tools.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _host_list() -> str:
    """A host tool list covering a curated tool, an uncurated one, and an unknown server."""
    return json.dumps({"servers": [
        {"name": "code-review-graph", "enabled": True, "tools": [
            {"name": CURATED_TOOL, "description": "Search graph nodes semantically."},
            {"name": UNCURATED_TOOL, "description": "Build or update the knowledge graph."},
        ]},
        {"name": "rider", "enabled": True, "tools": [
            {"name": "build_solution", "description": "Compile the solution"},
        ]},
    ]})


def _tool(index: dict, server: str, tool: str) -> dict:
    return next(s for s in index["sources"] if s["name"] == server)["tools"][tool]


# ── init ─────────────────────────────────────────────────────────────────────

def test_init_takes_tags_and_intent_from_the_catalog(tmp_path, load_script, root):
    """A catalog-described tool is indexed with the curated intent, not the host description."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", _host_list()]) == 0

    curated = _catalog_entry(root, "code-review-graph", CURATED_TOOL)
    entry = _tool(_read_index(tmp_path), "code-review-graph", CURATED_TOOL)
    assert entry["intent"] == curated["intent"]
    assert entry["tags"] == curated["tags"]
    assert entry["origin"] == "catalog"


def test_init_falls_back_to_heuristics_for_a_tool_the_catalog_omits(tmp_path, load_script):
    """The catalog is not a completeness claim: an omitted tool still gets heuristic tags."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", _host_list()]) == 0

    entry = _tool(_read_index(tmp_path), "code-review-graph", UNCURATED_TOOL)
    assert entry["tags"] == ["build"]
    assert entry["intent"] == "Build or update the knowledge graph."
    assert entry["origin"] == "heuristic"


def test_init_falls_back_to_heuristics_for_a_server_the_catalog_does_not_know(
        tmp_path, load_script):
    """Heuristics survive as the last resort for the 25 servers ai-badger never declared."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", _host_list()]) == 0

    entry = _tool(_read_index(tmp_path), "rider", "build_solution")
    assert entry["origin"] == "heuristic"
    assert "build" in entry["tags"]


# ── update ───────────────────────────────────────────────────────────────────

def _index_with(tool_entry: dict) -> dict:
    return {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{"name": "code-review-graph", "tools": {CURATED_TOOL: tool_entry}}],
    }


def _one_server_list() -> str:
    return json.dumps({"servers": [
        {"name": "code-review-graph", "enabled": True,
         "tools": [{"name": CURATED_TOOL, "description": "Search graph nodes semantically."}]},
    ]})


def test_update_re_describes_a_heuristically_tagged_tool_from_the_catalog(
        tmp_path, load_script, root, capsys):
    """An index built before the catalog existed is re-described, and says so on stdout."""
    _write_index(tmp_path, _index_with({"tags": ["search"], "intent": "Search graph nodes."}))
    mod = load_script(SCRIPT)

    assert mod.main(["update", "--target", str(tmp_path), "--from-json", _one_server_list()]) == 0

    curated = _catalog_entry(root, "code-review-graph", CURATED_TOOL)
    entry = _tool(_read_index(tmp_path), "code-review-graph", CURATED_TOOL)
    assert entry["intent"] == curated["intent"]
    assert entry["tags"] == curated["tags"]
    assert entry["origin"] == "catalog"
    assert f"code-review-graph:{CURATED_TOOL}" in capsys.readouterr().out


def test_update_leaves_a_manually_curated_tool_alone(tmp_path, load_script):
    """A human who curated a tool outranks the catalog; origin records that they did."""
    mine = {"tags": ["diagnostic"], "intent": "My own wording for this tool.",
            "origin": "manual"}
    _write_index(tmp_path, _index_with(mine))
    mod = load_script(SCRIPT)

    assert mod.main(["update", "--target", str(tmp_path), "--from-json", _one_server_list()]) == 0

    assert _tool(_read_index(tmp_path), "code-review-graph", CURATED_TOOL) == mine


def test_update_keeps_a_removed_marker_while_re_describing(tmp_path, load_script):
    """Re-describing must not resurrect a tool the host no longer exposes."""
    _write_index(tmp_path, _index_with(
        {"tags": ["search"], "intent": "Search graph nodes.", "status": "removed"}))
    mod = load_script(SCRIPT)

    assert mod.main(["update", "--target", str(tmp_path), "--from-json",
                     json.dumps({"servers": [{"name": "code-review-graph", "enabled": True,
                                              "tools": []}]})]) == 0

    entry = _tool(_read_index(tmp_path), "code-review-graph", CURATED_TOOL)
    assert entry["status"] == "removed"


# ── curation wins, and stays won ─────────────────────────────────────────────

def test_tag_marks_the_tool_manual_so_a_later_update_keeps_it(tmp_path, load_script):
    """`mcp-index tag` is the human's route; the next update must not undo it."""
    _write_index(tmp_path, _index_with({"tags": ["search"], "intent": "Search graph nodes."}))
    mod = load_script(SCRIPT)

    assert mod.main(["tag", f"code-review-graph:{CURATED_TOOL}", "diagnostic",
                     "--target", str(tmp_path)]) == 0
    assert _tool(_read_index(tmp_path), "code-review-graph",
                 CURATED_TOOL)["origin"] == "manual"

    assert mod.main(["update", "--target", str(tmp_path), "--from-json", _one_server_list()]) == 0
    assert _tool(_read_index(tmp_path), "code-review-graph", CURATED_TOOL)["tags"] == ["diagnostic"]


def test_intent_marks_the_tool_manual(tmp_path, load_script):
    """Same for a hand-written intent."""
    _write_index(tmp_path, _index_with({"tags": ["search"], "intent": "Search graph nodes."}))
    mod = load_script(SCRIPT)

    assert mod.main(["intent", f"code-review-graph:{CURATED_TOOL}",
                     "The wording I chose myself", "--target", str(tmp_path)]) == 0

    assert _tool(_read_index(tmp_path), "code-review-graph",
                 CURATED_TOOL)["origin"] == "manual"


# ── the catalog itself ───────────────────────────────────────────────────────

def test_every_catalog_intent_fits_the_generated_index(root):
    """The overlay copies intents verbatim, so the catalog is bound by the index's maxLength."""
    schema = json.loads(
        (root / "schemas" / "mcp-tools.schema.json").read_text(encoding="utf-8"))
    limit = schema["$defs"]["toolEntry"]["properties"]["intent"]["maxLength"]

    for path in sorted((root / "features").glob("*/mcp/*/tools.json")):
        for tool in json.loads(path.read_text(encoding="utf-8"))["tools"]:
            assert len(tool["intent"]) <= limit, f"{path}: {tool['name']}"


def test_catalog_is_empty_when_the_framework_is_unreachable(load_script, tmp_path):
    """A scaffolded copy with no framework root degrades to heuristics, not a traceback."""
    mod = load_script(SCRIPT)
    assert mod.load_catalog(None) == {}
    assert mod.load_catalog(tmp_path) == {}
