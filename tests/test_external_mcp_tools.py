"""Tests for external MCP tool integration in ai-badger scaffold.

Verifies that externalTools config drives CLAUDE.md instruction injection,
.mcp.json portable command generation, and schema validation.
"""
from __future__ import annotations

import json

import pytest


def _config(stacks=None, source_control=None, commands=None, agents=None,
            external_tools=None) -> dict:
    cfg = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": stacks if stacks is not None else ["python"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": source_control if source_control is not None else
            {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": commands if commands is not None else {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if external_tools is not None:
        cfg["externalTools"] = external_tools
    return cfg


# ── CLAUDE.md instruction rendering ──────────────────────────────────────────

def test_external_tools_instructions_rendered_in_claude_md(make_scaffolder):
    """Config with externalTools produces MCP instructions in CLAUDE.md."""
    target = make_scaffolder.target

    tools = [
        {
            "name": "code-review-graph",
            "package": "code-review-graph",
            "command": "uvx code-review-graph serve",
            "instructions": (
                "## MCP Tools: code-review-graph\n\n"
                "Use graph tools before Grep/Glob/Read.\n"
            ),
        }
    ]
    cfg = _config(external_tools=tools)
    scaf = make_scaffolder(config=cfg, install=True)
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    claude_md = (target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## MCP Tools: code-review-graph" in claude_md
    assert "Use graph tools before Grep/Glob/Read" in claude_md


def test_no_external_tools_no_extra_section(make_scaffolder):
    """Config without externalTools still gets catalog tools injected."""
    target = make_scaffolder.target

    cfg = _config()
    scaf = make_scaffolder(config=cfg, install=True)
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    claude_md = (target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8")
    # Catalog tools (code-review-graph) are auto-injected even without config.externalTools
    assert "code-review-graph" in claude_md


def test_multiple_external_tools_rendered(make_scaffolder):
    """Multiple externalTools each get their own section."""
    target = make_scaffolder.target

    tools = [
        {
            "name": "code-review-graph",
            "package": "code-review-graph",
            "command": "uvx code-review-graph serve",
            "instructions": "## MCP Tools: code-review-graph\n\nGraph tools.\n",
        },
        {
            "name": "another-tool",
            "package": "another-tool",
            "command": "uvx another-tool serve",
            "instructions": "## MCP Tools: another-tool\n\nOther tools.\n",
        },
    ]
    cfg = _config(external_tools=tools)
    scaf = make_scaffolder(config=cfg, install=True)
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    claude_md = (target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## MCP Tools: code-review-graph" in claude_md
    assert "## MCP Tools: another-tool" in claude_md


# ── .mcp.json generation ──────────────────────────────────────────────────────

def test_external_tools_generates_mcp_json(make_scaffolder):
    """externalTools with generate_mcp_json produces a portable .mcp.json."""
    target = make_scaffolder.target

    tools = [
        {
            "name": "code-review-graph",
            "package": "code-review-graph",
            "command": "uvx code-review-graph serve",
            "generate_mcp_json": True,
            "instructions": "Graph tools.\n",
        }
    ]
    cfg = _config(external_tools=tools)
    scaf = make_scaffolder(config=cfg, install=True)
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    mcp_json_path = target / ".mcp.json"
    assert mcp_json_path.exists(), ".mcp.json should be generated"
    mcp = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    assert "code-review-graph" in mcp["mcpServers"]
    server = mcp["mcpServers"]["code-review-graph"]
    # Should use uvx, not hardcoded venv path
    assert server["command"] == "uvx"
    assert "code-review-graph" in server["args"]


def test_external_tools_no_mcp_json_when_not_requested(make_scaffolder):
    """externalTools without generate_mcp_json does not create .mcp.json."""
    target = make_scaffolder.target

    tools = [
        {
            "name": "code-review-graph",
            "package": "code-review-graph",
            "command": "uvx code-review-graph serve",
            "instructions": "Graph tools.\n",
        }
    ]
    cfg = _config(external_tools=tools)
    scaf = make_scaffolder(config=cfg, install=True)
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    # No .mcp.json should be generated (user manages it manually or via hermes mcp add)
    mcp_json_path = target / ".mcp.json"
    assert not mcp_json_path.exists()


# ── HERMES.md also gets instructions ──────────────────────────────────────────

def test_external_tools_instructions_in_hermes_md(make_scaffolder):
    """externalTools instructions also appear in HERMES.md for Hermes agent."""
    target = make_scaffolder.target

    tools = [
        {
            "name": "code-review-graph",
            "package": "code-review-graph",
            "command": "uvx code-review-graph serve",
            "instructions": "## MCP Tools: code-review-graph\n\nUse graph first.\n",
        }
    ]
    cfg = _config(external_tools=tools, agents=["hermes"])
    scaf = make_scaffolder(config=cfg, install=True)
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    hermes_md = (target / ".ai-badger" / "HERMES.md").read_text(encoding="utf-8")
    assert "## MCP Tools: code-review-graph" in hermes_md


# ── Schema validation ─────────────────────────────────────────────────────────

def test_config_schema_accepts_external_tools():
    """config.schema.json validates an externalTools array."""
    schema_path = root_path / "schemas" / "config.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "externalTools" in schema["properties"]


def test_config_schema_rejects_unknown_external_tool_fields():
    """externalTools items reject fields not in the schema."""
    schema_path = root_path / "schemas" / "config.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    tool_schema = schema["properties"]["externalTools"]["items"]
    assert tool_schema.get("additionalProperties") is False


# ── Helper for schema tests ───────────────────────────────────────────────────

root_path = pytest.importorskip("pathlib").Path(__file__).resolve().parents[1]


def test_catalog_tool_instructions_stay_within_a_line_budget(root):
    """Injected instructions land verbatim in every agent file — keep them policy, not manuals.

    A tool's own schema already describes it; restating that here costs every session.
    """
    catalog = json.loads((root / "features" / "common" / "external-tools.json")
                         .read_text(encoding="utf-8"))
    oversized = {}
    for tool in catalog.get("externalTools", catalog.get("tools", [])):
        text = tool.get("instructions") or ""
        lines = len(text.splitlines())
        if lines > 15:
            oversized[tool.get("name", "?")] = lines
    assert not oversized, (
        f"instruction blocks over the 15-line budget: {oversized}. "
        "Drop tool tables and workflow lists; keep the when-to-use policy."
    )
