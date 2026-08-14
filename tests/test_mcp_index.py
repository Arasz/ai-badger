"""Tests for skills/mcp-index/scripts/mcp_index.py.

Covers: init, update, validate, tag, intent, list, and auto-tagging heuristics.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from conftest import _test_write


# ── Helpers ────────────────────────────────────────────────────────────────

def _write_index(project: Path, data: dict) -> Path:
    """Write .ai-badger/mcp-tools.json (the current format) to a project directory."""
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    path = aib / "mcp-tools.json"
    _test_write(path, json.dumps(data, indent=2), encoding="utf-8")
    return path


def _read_index(project: Path) -> dict:
    """Read .ai-badger/mcp-tools.json from a project directory."""
    return json.loads((project / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))


def _write_legacy_yaml(project: Path, data: dict) -> Path:
    """Write a legacy .ai-badger/mcp-tools.yaml, as a pre-migration project would have."""
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    path = aib / "mcp-tools.yaml"
    _test_write(path, yaml.dump(data, sort_keys=False, default_flow_style=False), encoding="utf-8")
    return path


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
                    {"name": "get_solution_projects", "description": "List projects in the solution"},
                    {"name": "list_database_connections", "description": "List configured DB connections"},
                    {"name": "get_log_records", "description": "Fetch IDE log records"},
                ],
            },
            {
                "name": "playwright",
                "enabled": True,
                "tools": [
                    {"name": "browser_navigate", "description": "Navigate to a URL"},
                    {"name": "browser_snapshot", "description": "Capture page snapshot"},
                    {"name": "browser_handle_dialog", "description": "Accept or dismiss a dialog"},
                ],
            },
            {
                "name": "code-review-graph",
                "enabled": True,
                "tools": [
                    {"name": "build_or_update_graph_tool",
                     "description": "Build or update the knowledge graph for this repo"},
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
    """init with --from-json should create .ai-badger/mcp-tools.json."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    assert index["version"] == "0.1.0"
    assert len(index["sources"]) == 3

    rider = next(s for s in index["sources"] if s["name"] == "rider")
    assert len(rider["tools"]) == 10


def test_init_auto_tags_known_tools(tmp_path, load_script):
    """init should auto-tag tools with heuristics, not leave everything as 'general'."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")

    # build_solution → [build] (name contains "build"; no technology guessed — issue #171)
    assert "build" in rider["tools"]["build_solution"]["tags"]
    assert "dotnet" not in rider["tools"]["build_solution"]["tags"]

    # get_file_problems → [diagnostic] (name contains "problem")
    assert "diagnostic" in rider["tools"]["get_file_problems"]["tags"]

    # search_symbol → [semantic, search] (name contains "search" + "symbol")
    assert "search" in rider["tools"]["search_symbol"]["tags"]
    assert "semantic" in rider["tools"]["search_symbol"]["tags"]

    # execute_sql_query → [database, sql] (name contains "sql", a tight alias)
    assert "database" in rider["tools"]["execute_sql_query"]["tags"]
    assert "sql" in rider["tools"]["execute_sql_query"]["tags"]

    # browser_navigate → [browser, navigation] (server is "playwright")
    pw = next(s for s in index["sources"] if s["name"] == "playwright")
    assert "browser" in pw["tools"]["browser_navigate"]["tags"]
    assert "navigation" in pw["tools"]["browser_navigate"]["tags"]


def test_init_auto_tags_do_not_infer_technology_from_name_substrings(tmp_path, load_script):
    """issue #171: a name substring may tell you an *action*, never a *technology*.

    Each case here previously got a technology tag it does not deserve, and each is a real
    tool name from this repo's own index (see the PR description for the before/after diff).
    """
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0
    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")
    crg = next(s for s in index["sources"] if s["name"] == "code-review-graph")
    pw = next(s for s in index["sources"] if s["name"] == "playwright")

    # A knowledge-graph builder for Python/JS is not .NET just because its name contains "build".
    graph_tags = crg["tools"]["build_or_update_graph_tool"]["tags"]
    assert "build" in graph_tags
    assert "dotnet" not in graph_tags

    # Listing a solution's projects doesn't build anything, and isn't dotnet-specific either.
    solution_tags = rider["tools"]["get_solution_projects"]["tags"]
    assert "build" not in solution_tags
    assert "dotnet" not in solution_tags

    # Rider's database tool covers more than SQL engines; "database" substrings alone must not
    # imply the "sql" language tag — only a literal "sql" in the name earns it.
    db_tags = rider["tools"]["list_database_connections"]["tags"]
    assert "database" in db_tags
    assert "sql" not in db_tags

    # "log" inside a name is not OpenTelemetry — it misfired on this repo's own
    # playwright:browser_handle_dialog ("log" inside "dialog") and rider:get_log_records.
    dialog_tags = pw["tools"]["browser_handle_dialog"]["tags"]
    assert "opentelemetry" not in dialog_tags
    assert "tracing" not in dialog_tags
    assert "browser" in dialog_tags  # the server-level rule is unaffected

    log_tags = rider["tools"]["get_log_records"]["tags"]
    assert "opentelemetry" not in log_tags
    assert "tracing" not in log_tags

    # A bare "service" is too generic to mean OpenTelemetry (a DI service, a web service, ...);
    # "span" and the "service_map" compound are precise enough to keep.
    assert "opentelemetry" not in rider["tools"]["get_services"]["tags"]
    assert "opentelemetry" in rider["tools"]["get_spans"]["tags"]
    assert "tracing" in rider["tools"]["get_spans"]["tags"]


def test_init_fallback_to_general(tmp_path, load_script):
    """Tools with no heuristic match should get [general] tag."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")
    assert rider["tools"]["weird_unknown_tool"]["tags"] == ["general"]


def test_init_sets_intent_from_description(tmp_path, load_script):
    """init should use the tool's description as the intent."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    rider = next(s for s in index["sources"] if s["name"] == "rider")
    assert rider["tools"]["build_solution"]["intent"] == "Compile the solution"


def test_init_overwrites_existing(tmp_path, load_script):
    """Running init again should overwrite the existing index."""
    _write_index(tmp_path, {"version": "0.0.0", "generated_at": "old", "sources": []})
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", _mock_mcp_list_json()])
    assert rc == 0

    index = _read_index(tmp_path)
    assert index["version"] == "0.1.0"
    assert len(index["sources"]) == 3


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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate", "--target", str(tmp_path)])
    assert rc != 0


def test_validate_fails_on_missing_index(tmp_path, load_script):
    """validate should fail when the index doesn't exist."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "rider:nonexistent", "dotnet", "--target", str(tmp_path)])
    assert rc != 0


def test_tag_addresses_a_plugin_decorated_server(tmp_path, load_script):
    """A `plugin:<plugin>:<server>` name is the server, not a server called `plugin`."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "plugin:terraform:terraform",
            "tools": {
                "list_workspaces": {"tags": ["general"], "intent": "A tool"},
            },
        }],
    })
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "plugin:terraform:terraform:list_workspaces", "read", "search",
                   "--target", str(tmp_path)])
    assert rc == 0

    tool = _read_index(tmp_path)["sources"][0]["tools"]["list_workspaces"]
    assert set(tool["tags"]) == {"read", "search"}
    assert tool["origin"] == "manual"


def test_tag_names_the_whole_server_when_it_is_absent(tmp_path, load_script, capsys):
    """The 'not found' message must name the server asked for, not its first segment."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{"name": "rider", "tools": {}}],
    })
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "plugin:nope:nope:some_tool", "read", "--target", str(tmp_path)])
    assert rc != 0
    assert "plugin:nope:nope" in capsys.readouterr().err


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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["intent", "rider:tool_a", "short", "--target", str(tmp_path)])
    assert rc != 0


def test_intent_addresses_a_plugin_decorated_server(tmp_path, load_script):
    """`intent` splits a tool reference the same way `tag` does, so it needs the same cover."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "plugin:dotnet-msbuild:binlog",
            "tools": {
                "binlog_overview": {"tags": ["build"], "intent": "Old intent"},
            },
        }],
    })
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["intent", "plugin:dotnet-msbuild:binlog:binlog_overview",
                   "Build status, duration and project count", "--target", str(tmp_path)])
    assert rc == 0

    tool = _read_index(tmp_path)["sources"][0]["tools"]["binlog_overview"]
    assert tool["intent"] == "Build status, duration and project count"
    assert tool["origin"] == "manual"


# ── update ─────────────────────────────────────────────────────────────────

def test_update_adds_new_tools(tmp_path, load_script):
    """update should add tools from MCP config that aren't in the index yet."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "build_solution": {"tags": ["dotnet", "build"], "intent": "Compile the solution"},
            },
        }],
    })
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    # Mock MCP list with additional tools
    mcp_json = json.dumps({
        "servers": [{
            "name": "rider",
            "tools": [
                {"name": "build_solution", "description": "Compile the solution"},
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["list", "--untagged", "--target", str(tmp_path)])
    assert rc == 0

    captured = capsys.readouterr()
    assert "needs_work" in captured.out
    assert "curated_tool" not in captured.out


# ── error cases ────────────────────────────────────────────────────────────

def test_missing_target(tmp_path, load_script):
    """All commands should fail with usage error when --target is missing."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["validate"])
    assert rc == 2  # usage error


def test_unknown_command(tmp_path, load_script):
    """Unknown subcommand should exit with usage error."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
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
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["tag", "rider:tool_a", "--target", str(tmp_path)])
    assert rc == 2


# ── text parsing fallback ────────────────────────────────────────────────────
# The parsers moved to host_listings.py with issue #188; their tests moved with them, to
# tests/test_mcp_index_host_listings.py.

def test_init_with_from_json(tmp_path, load_script):
    """init --from-json creates index from provided JSON (bypasses hermes CLI)."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    data = json.dumps({"servers": [
        {"name": "test-srv", "tools": [
            {"name": "my_tool", "description": "Does stuff"},
        ]},
    ]})
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", data])
    assert rc == 0
    index = _read_index(tmp_path)
    assert len(index["sources"]) == 1
    assert "my_tool" in index["sources"][0]["tools"]

def test_missing_yaml_degrades_with_a_message(load_script, monkeypatch):
    """The script is run directly on whatever python3 is on PATH; a missing dep must explain."""
    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    mcp_index = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    assert mcp_index.yaml is None
    assert "pyyaml" in mcp_index.YAML_MISSING_HINT.lower()


# ── JSON is the format going forward (issue #145) ───────────────────────────

def _valid_index(intent="A perfectly valid intent sentence") -> dict:
    return {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {"build_solution": {"tags": ["dotnet", "build"], "intent": intent}},
        }],
    }


def test_init_writes_json_not_yaml(tmp_path, load_script):
    """init writes .ai-badger/mcp-tools.json; the legacy .yaml path is never created."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json",
                   json.dumps({"servers": [{"name": "s", "tools": [
                       {"name": "t", "description": "Does something useful"}]}]})])
    assert rc == 0
    assert (tmp_path / ".ai-badger" / "mcp-tools.json").exists()
    assert not (tmp_path / ".ai-badger" / "mcp-tools.yaml").exists()


def test_read_index_prefers_json_when_both_exist(tmp_path, load_script):
    """A project mid-migration (both files present) is read from JSON, not YAML."""
    _write_legacy_yaml(tmp_path, _valid_index(intent="from the legacy YAML file"))
    _write_index(tmp_path, _valid_index(intent="from the current JSON file"))
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    rc = mod.main(["list", "--target", str(tmp_path)])
    assert rc == 0


def test_cmd_list_falls_back_to_legacy_yaml_when_no_json_exists(tmp_path, load_script, capsys):
    """A project that never migrated still works via the dual-format reader."""
    _write_legacy_yaml(tmp_path, _valid_index(intent="Compile the whole solution now"))
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    rc = mod.main(["list", "--target", str(tmp_path)])
    assert rc == 0
    assert "rider:build_solution" in capsys.readouterr().out


def test_write_index_migrates_legacy_yaml_to_migrated_suffix(tmp_path, load_script):
    """Any write command renames a legacy mcp-tools.yaml to mcp-tools.yaml.migrated."""
    _write_legacy_yaml(tmp_path, _valid_index())
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    rc = mod.main(["tag", "rider:build_solution", "dotnet", "build", "--target", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / ".ai-badger" / "mcp-tools.json").exists()
    assert (tmp_path / ".ai-badger" / "mcp-tools.yaml.migrated").exists()
    assert not (tmp_path / ".ai-badger" / "mcp-tools.yaml").exists()


def test_write_index_keeps_zero_tool_servers_rather_than_dropping_them(tmp_path, load_script):
    """A server with no tools survives a write: its status is the payload (ADR-0014 §7).

    Rewritten from test_write_index_drops_zero_tool_servers_and_reports_them, which pinned the
    #145 behaviour this change reverses — dropping made "switched off" and "running but
    silent" the same absence.
    """
    data = _valid_index()
    data["sources"].append({"name": "empty-server", "status": "empty", "tools": {}})
    _write_index(tmp_path, data)
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    rc = mod.main(["tag", "rider:build_solution", "dotnet", "build", "--target", str(tmp_path)])
    assert rc == 0

    index = _read_index(tmp_path)
    assert [s["name"] for s in index["sources"]] == ["rider", "empty-server"]
    assert next(s for s in index["sources"] if s["name"] == "empty-server")["status"] == "empty"


def test_write_index_refuses_invalid_data_on_init(tmp_path, load_script):
    """init/update hard-refuse rather than persist a schema-invalid index."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    # An intent under 10 chars fails schemas/mcp-tools.schema.json.
    bad_json = json.dumps({"servers": [{"name": "s", "tools": [
        {"name": "t", "description": "short"}]}]})
    rc = mod.main(["init", "--target", str(tmp_path), "--from-json", bad_json])
    assert rc == 1
    assert not (tmp_path / ".ai-badger" / "mcp-tools.json").exists()


def test_write_index_refuses_when_validation_unavailable_on_init(tmp_path, load_script,
                                                                  monkeypatch):
    """init refuses rather than write unvalidated, and names --root / pip install jsonschema."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    monkeypatch.setattr(mod, "FRAMEWORK_ROOT", None)

    rc = mod.main(["init", "--target", str(tmp_path), "--from-json",
                   json.dumps({"servers": [{"name": "s", "tools": [
                       {"name": "t", "description": "Does something useful"}]}]})])

    assert rc == 1
    assert not (tmp_path / ".ai-badger" / "mcp-tools.json").exists()


def test_tag_writes_unvalidated_with_a_loud_note_when_root_unreachable(tmp_path, load_script,
                                                                       monkeypatch, capsys):
    """tag/intent must not strand a curation edit just because the framework isn't reachable."""
    _write_index(tmp_path, _valid_index())
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    monkeypatch.setattr(mod, "FRAMEWORK_ROOT", None)

    rc = mod.main(["tag", "rider:build_solution", "diagnostic", "--target", str(tmp_path)])

    assert rc == 0
    index = _read_index(tmp_path)
    assert index["sources"][0]["tools"]["build_solution"]["tags"] == ["diagnostic"]
    err = capsys.readouterr().err
    assert "--root" in err and "jsonschema" in err


def test_a_reachable_framework_without_jsonschema_still_degrades(tmp_path, load_script,
                                                                  monkeypatch, capsys):
    """0.93.0 made badger_lib importable without jsonschema; the refusal moved into validate().

    Before that, `import badger_lib` itself raised and `_try_import_badger_lib` returned None.
    Now the import succeeds, so tag/intent must catch the ImportError at the call site or a
    consumer project with no jsonschema gets a traceback instead of the documented note.
    """
    _write_index(tmp_path, _valid_index())
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    def _refuse(*_args, **_kwargs):
        raise ImportError("no module named 'jsonschema'")

    monkeypatch.setattr(mod, "_try_import_badger_lib",
                        lambda: type("bl", (), {"validate": staticmethod(_refuse)}))

    rc = mod.main(["tag", "rider:build_solution", "diagnostic", "--target", str(tmp_path)])

    assert rc == 0
    assert "jsonschema" in capsys.readouterr().err


def test_init_still_refuses_when_jsonschema_is_absent(tmp_path, load_script, monkeypatch):
    """The other half: unavailable must stay a refusal for init, not a silent unvalidated write."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    def _refuse(*_args, **_kwargs):
        raise ImportError("no module named 'jsonschema'")

    monkeypatch.setattr(mod, "_try_import_badger_lib",
                        lambda: type("bl", (), {"validate": staticmethod(_refuse)}))

    rc = mod.main(["init", "--target", str(tmp_path), "--from-json",
                   json.dumps({"servers": [{"name": "s", "tools": [
                       {"name": "t", "description": "Does something useful"}]}]})])

    assert rc == 1
    assert not (tmp_path / ".ai-badger" / "mcp-tools.json").exists()


def test_validation_unavailable_hint_names_root_and_jsonschema(load_script):
    """The hard-refusal message must name the two remedies verbatim (reviewer requirement)."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    assert "--root" in mod.VALIDATION_UNAVAILABLE_HINT
    assert "pip install jsonschema" in mod.VALIDATION_UNAVAILABLE_HINT


# ── mcp-index migrate ────────────────────────────────────────────────────────

def test_cmd_migrate_converts_legacy_yaml_preserving_curated_tags(tmp_path, load_script):
    """migrate reads the legacy YAML and writes JSON with curated tags intact."""
    _write_legacy_yaml(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "build_solution": {
                    "tags": ["dotnet", "build", "csharp"],
                    "intent": "Compile the solution and report errors back",
                },
            },
        }],
    })
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    rc = mod.main(["migrate", "--target", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / ".ai-badger" / "mcp-tools.yaml.migrated").exists()
    assert not (tmp_path / ".ai-badger" / "mcp-tools.yaml").exists()
    index = _read_index(tmp_path)
    tool = index["sources"][0]["tools"]["build_solution"]
    assert set(tool["tags"]) == {"dotnet", "build", "csharp"}
    assert tool["intent"] == "Compile the solution and report errors back"


def test_cmd_migrate_is_noop_when_json_already_exists(tmp_path, load_script):
    """migrate on an already-migrated project reports success without touching anything."""
    _write_index(tmp_path, _valid_index())
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

    rc = mod.main(["migrate", "--target", str(tmp_path)])
    assert rc == 0


def test_cmd_migrate_fails_when_no_index_present(tmp_path, load_script):
    """migrate on a project with neither file present is an error, not a silent no-op."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    rc = mod.main(["migrate", "--target", str(tmp_path)])
    assert rc == 1


def test_cmd_migrate_refuses_without_pyyaml_when_content_is_unparseable(tmp_path, load_script,
                                                                        monkeypatch):
    """The crux failure mode: legacy YAML + no pyyaml + content outside the subset parser."""
    aib = tmp_path / ".ai-badger"
    aib.mkdir(parents=True)
    # A construct outside the subset this parser understands (a YAML flow-style list).
    _test_write(aib / "mcp-tools.yaml", "version: 0.1.0\ngenerated_at: '2026-01-01T00:00:00Z'\nsources: [1, 2, 3]\n", encoding="utf-8")
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    monkeypatch.setattr(mod, "yaml", None)

    rc = mod.main(["migrate", "--target", str(tmp_path)])

    assert rc == 1
    assert not (tmp_path / ".ai-badger" / "mcp-tools.json").exists()
    assert (tmp_path / ".ai-badger" / "mcp-tools.yaml").exists()  # untouched


def test_cmd_migrate_refusal_message_names_both_remedies(tmp_path, load_script, monkeypatch,
                                                          capsys):
    aib = tmp_path / ".ai-badger"
    aib.mkdir(parents=True)
    _test_write(aib / "mcp-tools.yaml", "sources: [1, 2, 3]\n", encoding="utf-8")
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    monkeypatch.setattr(mod, "yaml", None)

    mod.main(["migrate", "--target", str(tmp_path)])

    err = capsys.readouterr().err
    assert "pip install pyyaml" in err
    assert "mcp-index init" in err
    assert "LOSES curated tags" in err


def test_cmd_migrate_succeeds_without_pyyaml_via_the_verified_subset_parser(tmp_path, load_script,
                                                                            monkeypatch):
    """A legacy YAML file within the recognized subset migrates even with no pyyaml at all."""
    _write_legacy_yaml(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "build_solution": {
                    "tags": ["dotnet", "build"],
                    "intent": "Compile the solution and report errors back",
                },
            },
        }],
    })
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    monkeypatch.setattr(mod, "yaml", None)

    rc = mod.main(["migrate", "--target", str(tmp_path)])

    assert rc == 0
    index = _read_index(tmp_path)
    assert index["sources"][0]["tools"]["build_solution"]["tags"] == ["dotnet", "build"]


# ── Legacy YAML subset parser: round-trip verified, never silently wrong ────

def test_subset_parser_reads_this_repos_real_mcp_tools_index(load_script, root):
    """The strongest real-world proof: this repo's own pre-migration index round-trips.

    `.ai-badger/mcp-tools.yaml.migrated` is what `mcp-index migrate` renamed this repo's
    real, hand-curated legacy index to (issue #145) — never deleted, so it doubles as a
    real-world fixture for the parser that reads legacy indexes when pyyaml is absent.
    """
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    fixture = root / ".ai-badger" / "mcp-tools.yaml.migrated"
    if not fixture.exists():
        pytest.skip("no migrated legacy index in this checkout")
    text = fixture.read_text(encoding="utf-8")

    parsed = mod._parse_legacy_yaml_subset(text)

    assert parsed is not None
    assert yaml.safe_load(text) == parsed


def test_subset_parser_returns_none_never_raises_on_malformed_input(load_script):
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    for bad in ("not: valid: yaml: at: all: :::\n", "", "just a scalar\n",
                "sources:\n- name: rider\n    bad indent here\n"):
        assert mod._parse_legacy_yaml_subset(bad) is None


def test_subset_parser_handles_wrapped_unicode_and_special_characters(load_script):
    """Round-trips content pyyaml would double-quote-escape or line-wrap."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    data = {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {
                "t1": {"tags": ["build"], "intent": "Café, naïve, and colons: work fine"},
                "t2": {"tags": ["build"],
                       "intent": "word " * 20 + "wraps past pyyaml's eighty column width"},
            },
        }],
    }
    text = yaml.dump(data, sort_keys=False, default_flow_style=False)

    parsed = mod._parse_legacy_yaml_subset(text)

    assert parsed == data


def test_subset_parser_refuses_rather_than_corrupt_on_unrecognized_shapes(load_script):
    """A 2000-trial randomized fuzz (see PR description) never produced a wrong parse; this
    pins the two concrete shapes it legitimately falls outside of."""
    mod = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")
    # Flow-style collections are not in the subset.
    assert mod._parse_legacy_yaml_subset("a: {b: 1}\n") is None
    assert mod._parse_legacy_yaml_subset("a: [1, 2]\n") is None
