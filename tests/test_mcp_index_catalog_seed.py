"""A server listed without tool detail is seeded from the mcp catalog.

`hermes mcp list --json` was the only listing that carried tool names, and it no longer exists
(#188). Every remaining listing names servers only, so a catalog-described server used to land in
the index with `tools: {}` — the curation in `features/<stack>/mcp/<server>/tools.json` could
never reach a project. Seeding closes that gap: the catalog is the description of record when the
host declines to enumerate.

The seed is a floor, not an override. A listing that *does* carry tool detail is authoritative —
including when it says the server exposes nothing — so the catalog never contradicts it.
"""

from __future__ import annotations

import json
from pathlib import Path
from conftest import _test_write

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"

# A server the shipped catalog describes (features/common/mcp/semantica/tools.json).
CATALOG_SERVER = "semantica"


def _catalog_tools(root: Path, server: str) -> dict:
    data = json.loads(
        (root / "features" / "common" / "mcp" / server / "tools.json").read_text(encoding="utf-8")
    )
    return {t["name"]: t for t in data["tools"]}


def _read_index(project: Path) -> dict:
    return json.loads((project / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))


def _write_index(project: Path, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    _test_write(aib / "mcp-tools.json", json.dumps(data, indent=2), encoding="utf-8")


def _source(index: dict, name: str) -> dict:
    return next(s for s in index["sources"] if s["name"] == name)


def _names_only(*servers: str) -> str:
    """A listing shaped like `claude mcp list`: server names, no tool detail."""
    return json.dumps({"servers": [
        {"name": s, "enabled": True, "tools": [], "tools_known": False} for s in servers
    ]})


def _with_tools(server: str, *tools: str) -> str:
    """A listing that does carry tool detail."""
    return json.dumps({"servers": [
        {"name": server, "enabled": True, "tools": [
            {"name": t, "description": f"Does {t}."} for t in tools
        ]},
    ]})


# ── init ─────────────────────────────────────────────────────────────────────

def test_init_seeds_a_toolless_server_from_the_catalog(tmp_path, load_script, root):
    """A names-only listing still yields the catalog's tools, marked as catalog-sourced."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json",
                     _names_only(CATALOG_SERVER)]) == 0

    curated = _catalog_tools(root, CATALOG_SERVER)
    tools = _source(_read_index(tmp_path), CATALOG_SERVER)["tools"]
    assert set(tools) == set(curated), "every catalog tool should be seeded"
    for name, entry in tools.items():
        assert entry["origin"] == "catalog"
        assert entry["intent"] == curated[name]["intent"]
        assert entry["tags"] == curated[name]["tags"]


def test_init_leaves_an_uncatalogued_toolless_server_empty(tmp_path, load_script):
    """Seeding invents nothing: no catalog entry means no tools."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json",
                     _names_only("a-server-the-catalog-does-not-know")]) == 0

    src = _source(_read_index(tmp_path), "a-server-the-catalog-does-not-know")
    assert src["tools"] == {}


def test_init_does_not_seed_when_the_listing_carries_tool_detail(tmp_path, load_script, root):
    """A listing that enumerates tools is authoritative — the catalog does not add to it."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json",
                     _with_tools(CATALOG_SERVER, "record_decision")]) == 0

    tools = _source(_read_index(tmp_path), CATALOG_SERVER)["tools"]
    assert set(tools) == {"record_decision"}, "an enumerated listing is the whole truth"
    assert len(_catalog_tools(root, CATALOG_SERVER)) > 1, "guard: the catalog knows more"


# ── update ───────────────────────────────────────────────────────────────────

def test_update_seeds_a_source_the_listing_left_toolless(tmp_path, load_script, root):
    """The gap this fixes: an existing empty source gains the catalog's tools."""
    _write_index(tmp_path, {"version": "0.1.0", "generated_at": "2026-01-01T00:00:00Z",
                            "sources": [{"name": CATALOG_SERVER, "status": "unknown",
                                         "tools": {}}]})
    mod = load_script(SCRIPT)
    assert mod.main(["update", "--target", str(tmp_path), "--from-json",
                     _names_only(CATALOG_SERVER)]) == 0

    tools = _source(_read_index(tmp_path), CATALOG_SERVER)["tools"]
    assert set(tools) == set(_catalog_tools(root, CATALOG_SERVER))


def test_update_never_overwrites_a_manual_curation(tmp_path, load_script):
    """A human outranks the catalog: an existing manual entry survives the seed untouched."""
    manual = {"tags": ["read"], "intent": "Mine, not the catalog's.", "origin": "manual"}
    _write_index(tmp_path, {"version": "0.1.0", "generated_at": "2026-01-01T00:00:00Z",
                            "sources": [{"name": CATALOG_SERVER, "status": "unknown",
                                         "tools": {"record_decision": dict(manual)}}]})
    mod = load_script(SCRIPT)
    assert mod.main(["update", "--target", str(tmp_path), "--from-json",
                     _names_only(CATALOG_SERVER)]) == 0

    assert _source(_read_index(tmp_path), CATALOG_SERVER)["tools"]["record_decision"] == manual


def test_update_seeding_is_idempotent(tmp_path, load_script):
    """A second update reports no changes — the seed must not churn the index every run."""
    _write_index(tmp_path, {"version": "0.1.0", "generated_at": "2026-01-01T00:00:00Z",
                            "sources": [{"name": CATALOG_SERVER, "status": "unknown",
                                         "tools": {}}]})
    mod = load_script(SCRIPT)
    listing = _names_only(CATALOG_SERVER)
    assert mod.main(["update", "--target", str(tmp_path), "--from-json", listing]) == 0
    first = (tmp_path / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8")
    assert mod.main(["update", "--target", str(tmp_path), "--from-json", listing]) == 0

    assert (tmp_path / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8") == first


def test_update_does_not_resurrect_a_removed_tool(tmp_path, load_script):
    """A tool retired on purpose stays retired; the seed must not undo that judgement."""
    retired = {"tags": ["read"], "intent": "Gone from the server.", "origin": "catalog",
               "status": "removed"}
    _write_index(tmp_path, {"version": "0.1.0", "generated_at": "2026-01-01T00:00:00Z",
                            "sources": [{"name": CATALOG_SERVER, "status": "unknown",
                                         "tools": {"record_decision": dict(retired)}}]})
    mod = load_script(SCRIPT)
    assert mod.main(["update", "--target", str(tmp_path), "--from-json",
                     _names_only(CATALOG_SERVER)]) == 0

    entry = _source(_read_index(tmp_path), CATALOG_SERVER)["tools"]["record_decision"]
    assert entry["status"] == "removed"
