"""Tests for skills/mcp-index/scripts/mcp_index.py.

Covers: init, update, validate, tag, intent, list, and auto-tagging heuristics.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml


# ── Helpers ────────────────────────────────────────────────────────────────

def _write_index(project: Path, data: dict) -> Path:
    """Write .ai-badger/mcp-tools.yaml to a project directory."""
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    path = aib / "mcp-tools.yaml"
    path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    return path


def _read_index(project: Path) -> dict:
    """Read .ai-badger/mcp-tools.yaml from a project directory."""
    return yaml.safe_load((project / ".ai-badger" / "mcp-tools.yaml").read_text(encoding="utf-8"))


def _mock_mcp_list_json() -> str:
    """Return a minimal hermes mcp list --json output with sample tools."""
    return json.dumps({
        "servers": [
            {
                "name": "rider",
                "url": "http://127.0.0.1:64342/stream",
                "enabled": True,
                "tools": [
                    {"name": "build_solution", "description": "Compile the solution"},
                    {"name": "get_file_problems", "description": "Analyze a file for errors"},
                    {"name": "search_symbol", "description": "Find a symbol by name"},
                    {"name": "execute_sql_query", "description": "Run SQL against a DB connection"},
                    {"name": "get_services", "description": "List OTel services"},
                    {"name": "get_spans", "description": "Query tracing spans"},
                    {"name": "weird_unknown_tool", "description": "Does something obscure"},
                ],
            },
            {
                "name": "playwright",
                "enabled": True,
                "tools": [
                    {"name": "browser_navigate", "description": "Navigate to a URL"},
                    {"name": "browser_snapshot", "description": "Capture page snapshot"},
                ],
            },
        ],
    })


def _mock_mcp_tags_json() -> dict:
    """Return the tag taxonomy matching features/common/mcp-tags.json."""
    return {
        "categories": {
            "language": {"tags": ["csharp", "typescript", "sql"]},
            "action": {"tags": ["search", "diagnostic", "build", "run", "read", "write", "navigation", "terminal"]},
            "domain": {"tags": ["dotnet", "database", "tracing", "opentelemetry", "browser", "semantic", "files"]},
            "meta": {"tags": ["batch", "slow", "unsafe"]},
        },
    }


def _all_valid_tags(taxonomy: dict) -> set[str]:
    """Flatten all valid tags from the taxonomy."""
    return {t for cat in taxonomy["categories"].values() for t in cat["tags"]}


# ── init ───────────────────────────────────────────────────────────────────

def test_init_creates_index(tmp_path, load_script):
    """init with --from-json should create .ai-badger/mcp-tools.yaml."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    assert index["version"] == "0.1.0"
    assert len(index["sources"]) == 2

    rider = next(s for s in index["sources"] if s["name"] == "rider")
    assert len(rider["tools"]) == 7


def test_init_auto_tags_known_tools(tmp_path, load_script):
    """init should auto-tag tools with heuristics, not leave everything as 'general'."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")

    # build_solution → [dotnet, build] (name contains "build" + "solution")
    assert "dotnet" in rider["tools"]["build_solution"]["tags"]
    assert "build" in rider["tools"]["build_solution"]["tags"]

    # get_file_problems → [diagnostic] (name contains "problem")
    assert "diagnostic" in rider["tools"]["get_file_problems"]["tags"]

    # search_symbol → [semantic, search] (name contains "search" + "symbol")
    assert "search" in rider["tools"]["search_symbol"]["tags"]
    assert "semantic" in rider["tools"]["search_symbol"]["tags"]

    # execute_sql_query → [database, sql] (name contains "sql")
    assert "database" in rider["tools"]["execute_sql_query"]["tags"]
    assert "sql" in rider["tools"]["execute_sql_query"]["tags"]

    # browser_navigate → [browser, navigation] (server is "playwright")
    pw = next(s for s in index["sources"] if s["name"] == "playwright")
    assert "browser" in pw["tools"]["browser_navigate"]["tags"]
    assert "navigation" in pw["tools"]["browser_navigate"]["tags"]


def test_init_fallback_to_general(tmp_path, load_script):
    """Tools with no heuristic match should get [general] tag."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")
    assert rider["tools"]["weird_unknown_tool"]["tags"] == ["general"]


def test_init_sets_intent_from_description(tmp_path, load_script):
    """init should use the tool's description as the intent."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")
    assert rider["tools"]["build_solution"]["intent"] == "Compile the solution"


def test_init_overwrites_existing(tmp_path, load_script):
    """Running init again should overwrite the existing index."""
    _write_index(tmp_path, {"version": "0.0.0", "generated_at": "old", "sources": []})
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    assert index["version"] == "0.1.0"
    assert len(index["sources"]) == 2


# ── validate ───────────────────────────────────────────────────────────────

def test_validate_passes_on_valid_index(tmp_path, load_script):
    """validate should exit 0 on a fully-tagged index."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": ["dotnet", "build"], "intent": "Build the solution"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate", "--target", str(tmp_path)])
    assert rc == 0


def test_validate_fails_on_untagged_tool(tmp_path, load_script):
    """validate should fail when a tool has [general] tag."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": ["general"], "intent": "A general tool"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate", "--target", str(tmp_path)])
    assert rc != 0


def test_validate_fails_on_missing_index(tmp_path, load_script):
    """validate should fail when the index doesn't exist."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate", "--target", str(tmp_path)])
    assert rc != 0


def test_validate_fails_on_empty_tags(tmp_path, load_script):
    """validate should fail when a tool has empty tags list."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": [], "intent": "A tool"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate", "--target", str(tmp_path)])
    assert rc != 0


# ── tag ────────────────────────────────────────────────────────────────────

def test_tag_sets_tags(tmp_path, load_script):
    """tag should update tags for a specific tool."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": ["general"], "intent": "A tool"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "rider:tool_a", "dotnet", "build", "--target", str(tmp_path)])
    assert rc == 0

    index = _read_index(tmp_path)
    tool = index["sources"][0]["tools"]["tool_a"]
    assert set(tool["tags"]) == {"dotnet", "build"}


def test_tag_rejects_invalid_tag(tmp_path, load_script):
    """tag should fail when given a tag not in the taxonomy."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": ["general"], "intent": "A tool"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "rider:tool_a", "not-a-real-tag", "--target", str(tmp_path)])
    assert rc != 0


def test_tag_fails_on_unknown_tool(tmp_path, load_script):
    """tag should fail when the tool doesn't exist in the index."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {},
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "rider:nonexistent", "dotnet", "--target", str(tmp_path)])
    assert rc != 0


# ── intent ─────────────────────────────────────────────────────────────────

def test_intent_sets_intent(tmp_path, load_script):
    """intent should update the intent for a specific tool."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": ["dotnet"], "intent": "Old intent"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["intent", "rider:tool_a", "New improved intent for this tool", "--target", str(tmp_path)])
    assert rc == 0

    index = _read_index(tmp_path)
    assert index["sources"][0]["tools"]["tool_a"]["intent"] == "New improved intent for this tool"


def test_intent_rejects_too_short(tmp_path, load_script):
    """intent should fail when the intent string is too short (<10 chars)."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "tool_a": {"tags": ["dotnet"], "intent": "Old intent"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["intent", "rider:tool_a", "short", "--target", str(tmp_path)])
    assert rc != 0


# ── update ─────────────────────────────────────────────────────────────────

def test_update_adds_new_tools(tmp_path, load_script):
    """update should add tools from MCP config that aren't in the index yet."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "build_solution": {"tags": ["dotnet", "build"], "intent": "Compile"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")

    # Mock MCP list with additional tools
    mcp_json = json.dumps({
        "servers": [{
            "name": "rider",
            "tools": [
                {"name": "build_solution", "description": "Compile"},
                {"name": "get_file_problems", "description": "Check errors"},
                {"name": "search_symbol", "description": "Search symbols"},
            ],
        }],
    })

    rc = mod.main(["update", "--target", str(tmp_path), "--from-json", mcp_json])
    assert rc == 0

    index = _read_index(tmp_path)
    tools = index["sources"][0]["tools"]
    assert len(tools) == 3
    assert "build_solution" in tools
    assert "get_file_problems" in tools
    assert "search_symbol" in tools


def test_update_marks_removed_tools(tmp_path, load_script):
    """update should mark tools no longer in MCP config as removed."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "old_tool": {"tags": ["dotnet"], "intent": "Old tool that got removed"},
                "current_tool": {"tags": ["dotnet"], "intent": "Still here"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")

    mcp_json = json.dumps({
        "servers": [{
            "name": "rider",
            "tools": [
                {"name": "current_tool", "description": "Still here"},
            ],
        }],
    })

    rc = mod.main(["update", "--target", str(tmp_path), "--from-json", mcp_json])
    assert rc == 0

    index = _read_index(tmp_path)
    tools = index["sources"][0]["tools"]
    assert tools["old_tool"].get("status") == "removed"
    assert tools["current_tool"].get("status", "active") == "active"


def test_update_preserves_manual_tags(tmp_path, load_script):
    """update should preserve manually-set tags on existing tools."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "my_tool": {"tags": ["diagnostic", "csharp"], "intent": "My custom tool"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")

    mcp_json = json.dumps({
        "servers": [{
            "name": "rider",
            "tools": [
                {"name": "my_tool", "description": "My custom tool"},
            ],
        }],
    })

    rc = mod.main(["update", "--target", str(tmp_path), "--from-json", mcp_json])
    assert rc == 0

    index = _read_index(tmp_path)
    tool = index["sources"][0]["tools"]["my_tool"]
    assert set(tool["tags"]) == {"diagnostic", "csharp"}
    assert tool["intent"] == "My custom tool"


# ── list ───────────────────────────────────────────────────────────────────

def test_list_outputs_all_tools(tmp_path, load_script, capsys):
    """list should print all tools grouped by server."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [
            {
                "name": "rider",
                "tools": {
                    "tool_a": {"tags": ["dotnet", "build"], "intent": "First tool"},
                    "tool_b": {"tags": ["diagnostic"], "intent": "Second tool"},
                },
            },
            {
                "name": "playwright",
                "tools": {
                    "tool_c": {"tags": ["browser", "navigation"], "intent": "Third tool"},
                },
            },
        ],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["list", "--target", str(tmp_path)])
    assert rc == 0

    captured = capsys.readouterr()
    assert "rider:tool_a" in captured.out
    assert "dotnet, build" in captured.out
    assert "rider:tool_b" in captured.out
    assert "playwright:tool_c" in captured.out


def test_list_filters_by_tag(tmp_path, load_script, capsys):
    """list --tag should only show tools with that tag."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [
            {
                "name": "rider",
                "tools": {
                    "tool_a": {"tags": ["dotnet", "build"], "intent": "First"},
                    "tool_b": {"tags": ["diagnostic"], "intent": "Second"},
                },
            },
        ],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["list", "--tag", "diagnostic", "--target", str(tmp_path)])
    assert rc == 0

    captured = capsys.readouterr()
    assert "tool_b" in captured.out
    assert "tool_a" not in captured.out


def test_list_untagged_flag(tmp_path, load_script, capsys):
    """list --untagged should only show tools with [general] tag."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "curated_tool": {"tags": ["dotnet"], "intent": "Curated"},
                "needs_work": {"tags": ["general"], "intent": "Needs curation"},
            },
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["list", "--untagged", "--target", str(tmp_path)])
    assert rc == 0

    captured = capsys.readouterr()
    assert "needs_work" in captured.out
    assert "curated_tool" not in captured.out


# ── error cases ────────────────────────────────────────────────────────────

def test_missing_target(tmp_path, load_script):
    """All commands should fail with usage error when --target is missing."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate"])
    assert rc == 2  # usage error


def test_unknown_command(tmp_path, load_script):
    """Unknown subcommand should exit with usage error."""
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["nonexistent", "--target", str(tmp_path)])
    assert rc == 2


def test_tag_without_tags(tmp_path, load_script):
    """tag command without tag arguments should fail."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {"tool_a": {"tags": ["general"], "intent": "A"}},
        }],
    })
    mod = load_script("skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "rider:tool_a", "--target", str(tmp_path)])
    assert rc == 2