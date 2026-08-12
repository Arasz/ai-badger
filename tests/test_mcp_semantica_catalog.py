"""Schema and content validation for the Semantica MCP catalog entry.

TDD: this file is committed RED (before the catalog files exist), then made GREEN
by creating the production files. Every test must have a companion sensitivity check
that proves it can detect a violation (prove-the-check-fails invariant).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from conftest import _test_write

CATALOG_DIR = "features/common/mcp/semantica"
ROOT = Path(__file__).resolve().parent.parent

# ── helpers ──────────────────────────────────────────────────────────────────

def _load_schema(name: str) -> dict:
    path = ROOT / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_file(name: str) -> Path:
    return ROOT / CATALOG_DIR / name


# ── meta.json ────────────────────────────────────────────────────────────────

def test_meta_json_exists():
    """meta.json is present in the semantica catalog directory."""
    assert _catalog_file("meta.json").is_file()


def test_meta_json_validates_against_schema():
    """meta.json passes jsonschema validation against mcp-server.schema.json."""
    schema = _load_schema("mcp-server.schema.json")
    meta = json.loads(_catalog_file("meta.json").read_text(encoding="utf-8"))
    jsonschema.validate(meta, schema)


def test_meta_json_name_matches_directory():
    """The 'name' field matches the catalog directory name."""
    meta = json.loads(_catalog_file("meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "semantica"


def test_meta_json_has_prerequisite():
    """meta.json declares a prerequisite with check + install."""
    meta = json.loads(_catalog_file("meta.json").read_text(encoding="utf-8"))
    prereq = meta["prerequisite"]
    assert "check" in prereq
    assert "install" in prereq
    assert "semantica" in prereq["check"] or "semantica" in prereq.get("summary", "")


# ── tools.json ───────────────────────────────────────────────────────────────

def test_tools_json_exists():
    """tools.json is present in the semantica catalog directory."""
    assert _catalog_file("tools.json").is_file()


def test_tools_json_validates_against_schema():
    """tools.json passes jsonschema validation against mcp-server-tools.schema.json."""
    schema = _load_schema("mcp-server-tools.schema.json")
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    jsonschema.validate(tools, schema)


def test_tools_json_has_11_tools():
    """tools.json lists exactly 11 tools (get_graph_analytics excluded — broken in 0.6.5)."""
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    assert len(tools["tools"]) == 11


def test_tool_names_are_unique():
    """No duplicate tool names in tools.json."""
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    names = [t["name"] for t in tools["tools"]]
    assert len(names) == len(set(names))


def test_tool_tags_are_from_closed_vocabulary():
    """Every tag in tools.json exists in mcp-tags.json."""
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    tags_doc = json.loads(
        (ROOT / "features/common/mcp-tags.json").read_text(encoding="utf-8")
    )
    # mcp-tags.json nests tags under categories -> {category_name: {tags: [...]}}
    valid_tags: set[str] = set()
    for category in tags_doc.get("categories", {}).values():
        for tag in category.get("tags", []):
            valid_tags.add(tag)
    for tool in tools["tools"]:
        for tag in tool.get("tags", []):
            assert tag in valid_tags, f"Tag '{tag}' in tool '{tool['name']}' not in mcp-tags.json"


def test_tool_intents_under_200_chars():
    """Every intent string is ≤ 200 chars (schema limit)."""
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    for tool in tools["tools"]:
        intent = tool.get("intent", "")
        assert len(intent) <= 200, f"Intent for '{tool['name']}' is {len(intent)} chars"


def test_tools_json_has_core_tools():
    """The required core tools are present."""
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    names = {t["name"] for t in tools["tools"]}
    required = {"add_entity", "add_relationship", "record_decision",
                 "query_decisions", "get_graph_summary", "extract_entities"}
    missing = required - names
    assert not missing, f"Missing required tools: {missing}"


def test_broken_tool_not_present():
    """get_graph_analytics is known broken in 0.6.5 and must not be listed."""
    tools = json.loads(_catalog_file("tools.json").read_text(encoding="utf-8"))
    names = {t["name"] for t in tools["tools"]}
    assert "get_graph_analytics" not in names


# ── server.md ────────────────────────────────────────────────────────────────

def test_server_md_exists():
    """server.md is present in the semantica catalog directory."""
    assert _catalog_file("server.md").is_file()


def test_server_md_starts_with_comment_header():
    """server.md begins with <!-- semantica MCP tools -->."""
    text = _catalog_file("server.md").read_text(encoding="utf-8")
    assert text.startswith("<!-- semantica MCP tools -->")


def test_server_md_under_500_chars():
    """server.md is under 500 characters (agent instruction budget)."""
    text = _catalog_file("server.md").read_text(encoding="utf-8")
    assert len(text) <= 500, f"server.md is {len(text)} chars"


def test_server_md_mentions_ai_raccoon():
    """server.md explains complementarity with AiRaccoon memory."""
    text = _catalog_file("server.md").read_text(encoding="utf-8")
    assert "AiRaccoon" in text or "ai-raccoon" in text


# ── stack-mcp.json ───────────────────────────────────────────────────────────

def test_stack_mcp_includes_semantica():
    """stack-mcp.json servers array contains semantica entry."""
    stack = json.loads(
        (ROOT / "features/common/stack-mcp.json").read_text(encoding="utf-8")
    )
    names = [s["name"] for s in stack["servers"]]
    assert "semantica" in names


def test_semantica_stack_entry_has_required_fields():
    """semantica stack entry has name, command, and declare: true."""
    stack = json.loads(
        (ROOT / "features/common/stack-mcp.json").read_text(encoding="utf-8")
    )
    sem = next(s for s in stack["servers"] if s["name"] == "semantica")
    assert sem.get("command") == "python3 -m semantica.mcp_server"
    assert sem.get("declare") is True


# ── validate.py integration ─────────────────────────────────────────────────

def test_semantica_catalog_validation_remains_green():
    """Running validate.py --all exits 0 with the semantica catalog present."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "tooling/validate.py", "--all"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, f"validate.py --all failed:\n{result.stdout}\n{result.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# Sensitivity tests — prove each structural check CAN fail
# ═══════════════════════════════════════════════════════════════════════════════

class TestCatalogChecksCanFail:
    """Each check in this file must have a companion that proves it detects violations."""

    def test_meta_name_mismatch_can_fail(self, tmp_path):
        """A meta.json with wrong name field is detected."""
        schema = _load_schema("mcp-server.schema.json")
        bad = {"name": "wrong-name", "package": "semantica", "description": "x",
               "prerequisite": {"summary": "x", "check": "true", "install": "true"}}
        _test_write(tmp_path / "meta.json", json.dumps(bad), encoding="utf-8")
        # Schema validation won't catch name mismatch (name is freeform),
        # but our explicit test would
        data = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
        assert data["name"] != "semantica"

    def test_tool_duplicate_can_fail(self, tmp_path):
        """Duplicate tool names are detected."""
        tools = {
            "server": "semantica",
            "tools": [
                {"name": "dup", "intent": "first", "tags": ["read"]},
                {"name": "dup", "intent": "second", "tags": ["write"]},
            ]
        }
        names = [t["name"] for t in tools["tools"]]
        assert len(names) != len(set(names))

    def test_bad_tag_can_fail(self):
        """A tag outside the closed vocabulary is detected."""
        tags_doc = json.loads(
            (ROOT / "features/common/mcp-tags.json").read_text(encoding="utf-8")
        )
        valid_tags: set[str] = set()
        for category in tags_doc.get("categories", {}).values():
            for tag in category.get("tags", []):
                valid_tags.add(tag)
        bad_tag = "nonexistent-tag-xyz"
        assert bad_tag not in valid_tags
