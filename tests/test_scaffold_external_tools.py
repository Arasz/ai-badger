"""External tools: catalog injection into CLAUDE.md, .mcp.json generation, user overrides."""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import importlib
import json
from unittest.mock import patch

from scaffold_helpers import _config


# ---------------------------------------------------------------------- external tools catalog
def test_scaffold_injects_catalog_external_tool_into_claude_md(make_scaffolder):
    """External tools from features/common/external-tools.json are auto-injected."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["task"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "code-review-graph" in claude_md, "Catalog tool not injected into CLAUDE.md"


def test_scaffold_catalog_tool_generates_mcp_json(make_scaffolder):
    """Catalog tools with generate_mcp_json produce .mcp.json entries."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["task"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    mcp_json = target / ".mcp.json"
    assert mcp_json.exists(), ".mcp.json not created"
    mcp = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "code-review-graph" in mcp.get("mcpServers", {})


def test_scaffold_user_external_tools_override_catalog(make_scaffolder):
    """config.externalTools overrides catalog tools on name conflict."""
    target = make_scaffolder.target

    config = _config(agents=["claude"])
    config["externalTools"] = [{
        "name": "code-review-graph",
        "package": "code-review-graph",
        "command": "custom-command",
        "instructions": "CUSTOM INSTRUCTIONS",
        "generate_mcp_json": True,
    }]

    scaf = make_scaffolder(config=config, skills=["task"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "CUSTOM INSTRUCTIONS" in claude_md, "User override not applied"
    assert "MCP Tools: code-review-graph" not in claude_md, "Catalog instructions not overridden"


def test_collect_external_tools_reads_common_catalog(make_scaffolder):
    """_collect_external_tools reads features/common/external-tools.json."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["task"])
    tools = scaf.mcp.collect_external_tools()
    names = [t["name"] for t in tools]
    assert "code-review-graph" in names


def test_check_dependencies_surfaces_optional_hints_as_notes(make_scaffolder):
    """Optional-dependency hints (e.g. code-review-graph[embeddings]) must reach scaffold notes
    so the user is told about silently-degraded semantic search, not left to discover it later."""
    dependency_check = importlib.import_module("dependency_check")

    target = make_scaffolder.target

    hint = "code-review-graph-embeddings: not installed. Install with: /venv/bin/python3 -m pip install ..."

    def fake_run_dependency_check(root_, target_, features=None, allow_install=False):
        return {"installed": [], "already_present": [], "errors": [], "hints": [hint]}

    with patch.object(dependency_check, "run_dependency_check", side_effect=fake_run_dependency_check), \
         patch.object(dependency_check, "get_venv_python", return_value=None):
        scaf = make_scaffolder(config=_config(), skills=["code-review-graph"])
        scaf._check_dependencies()

    assert any(hint in n for n in scaf.notes)


def test_merge_external_tools_user_overrides_catalog(load_script):
    """_merge_external_tools: user tools override catalog on name conflict."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    catalog = [{"name": "tool-a", "package": "p", "command": "c1", "instructions": "orig"}]
    user = [{"name": "tool-a", "package": "p", "command": "c2", "instructions": "override"}]

    merged = scaffold.McpTools.merge_external_tools(catalog, user)
    assert len(merged) == 1
    assert merged[0]["command"] == "c2"
    assert merged[0]["instructions"] == "override"
