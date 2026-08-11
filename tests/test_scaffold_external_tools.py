"""The declared MCP server reaching CLAUDE.md and .mcp.json.

`external-tools.json` was deleted from the framework in step 4 of the MCP rebuild (ADR-0014)
and its reader in step 8, so what these tests exercise is the catalog path alone.
"""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import importlib
import json
from unittest.mock import patch

from scaffold_helpers import _config
from conftest import _test_write


# ---------------------------------------------------------------------- the declared server
def test_scaffold_injects_the_declared_server_into_claude_md(make_scaffolder):
    """The server the mcp catalog declares is auto-injected."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["task"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "code-review-graph" in claude_md, "Catalog tool not injected into CLAUDE.md"


def test_scaffold_catalog_tool_generates_mcp_json(make_scaffolder):
    """A catalog server with `declare: true` produces a .mcp.json entry."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["task"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    mcp_json = target / ".mcp.json"
    assert mcp_json.exists(), ".mcp.json not created"
    mcp = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "code-review-graph" in mcp.get("mcpServers", {})


def test_the_catalog_declaration_is_what_reaches_a_stack_scoped_scaffold(make_scaffolder,
                                                                         tmp_path):
    """What `collect_external_tools` used to do for a stack, `stack-mcp.json` does now."""
    _test_write(tmp_path / "index.json", json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    stack = tmp_path / "features" / "python"
    stack.mkdir(parents=True)
    _test_write(stack / "stack-mcp.json", json.dumps({"servers": [{
        "name": "stack-tool", "command": "echo stack-tool", "declare": True,
    }]}), encoding="utf-8")

    scaf = make_scaffolder(root=tmp_path, config=_config(stacks=["python"], agents=["claude"]))

    assert [s["name"] for s in scaf.mcp.collect_catalog_mcp_servers()] == ["stack-tool"]


def test_check_dependencies_surfaces_optional_hints_as_notes(make_scaffolder):
    """Optional-dependency hints (e.g. code-review-graph[embeddings]) must reach scaffold notes
    so the user is told about silently-degraded semantic search, not left to discover it later."""
    dependency_check = importlib.import_module("dependency_check")


    hint = "code-review-graph-embeddings: not installed. Install with: /venv/bin/python3 -m pip install ..."

    def fake_run_dependency_check(root_, target_, features=None, allow_install=False):
        return {"installed": [], "already_present": [], "errors": [], "hints": [hint]}

    with patch.object(dependency_check, "run_dependency_check", side_effect=fake_run_dependency_check), \
         patch.object(dependency_check, "get_venv_python", return_value=None):
        scaf = make_scaffolder(config=_config(), skills=["code-review-graph"])
        scaf._check_dependencies()

    assert any(hint in n for n in scaf.notes)
