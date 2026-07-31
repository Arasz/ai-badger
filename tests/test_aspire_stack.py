"""The aspire stack and the MCP server the Aspire CLI ships.

Detection is by filename only. The marker that most precisely identifies an AppHost — the
`Aspire.AppHost.Sdk` reference — lives *inside* the csproj, and `stack.schema.json` is explicit
that content facts belong in `detect.py`'s dependency pass rather than in a glob signal.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DETECT = "features/common/skills/welcome-ai-badger/scripts/detect.py"


def _real_index():
    return json.loads((ROOT / "index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", [
    "apphost.cs",            # single-file AppHost, Aspire 13+
    "AppHost.cs",            # the 13.0 project template
    "AppHost.csproj",
    "MyApp.AppHost.csproj",  # the classic <Solution>.AppHost naming
])
def test_an_apphost_marks_a_repository_as_aspire(tmp_path, load_script, filename):
    detect = load_script(DETECT)
    (tmp_path / filename).write_text("x", encoding="utf-8")

    assert "aspire" in detect.detect_stacks(tmp_path, _real_index())


def test_a_dotnet_repository_without_an_apphost_is_not_aspire(tmp_path, load_script):
    """`aspire` must not fire on every .NET repo, or the MCP prose reaches projects with no AppHost."""
    detect = load_script(DETECT)
    (tmp_path / "MyApp.csproj").write_text("x", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, _real_index())

    assert "dotnet" in stacks
    assert "aspire" not in stacks


def test_aspire_implies_dotnet(load_script):
    """An AppHost is a .NET project; scaffolding aspire alone would miss the dotnet stack."""
    detect = load_script(DETECT)

    assert "dotnet" in detect.expand_requires(["aspire"], _real_index())


class TestTheServerIsDeclaredAsTheCliDocuments:
    """Config verified against https://aspire.dev/get-started/aspire-mcp-server/."""

    def _declaration(self):
        data = json.loads((ROOT / "features/aspire/stack-mcp.json").read_text(encoding="utf-8"))
        return next(s for s in data["servers"] if s["name"] == "aspire")

    def test_it_launches_the_cli_agent_subcommand(self):
        assert self._declaration()["command"] == "aspire agent mcp"

    def test_it_is_declared_so_ai_badger_writes_its_launch_config(self):
        """The CLI ships the server, so a project on this stack should get it wired."""
        assert self._declaration()["declare"] is True

    def test_every_indexed_tool_carries_an_intent_and_tags(self):
        tools = json.loads(
            (ROOT / "features/aspire/mcp/aspire/tools.json").read_text(encoding="utf-8"))
        assert tools["server"] == "aspire"
        for tool in tools["tools"]:
            assert tool["intent"].strip(), tool["name"]
            assert tool["tags"], tool["name"]

    def test_the_catalog_indexes_the_server_under_the_aspire_stack(self):
        stack = _real_index()["stacks"]["aspire"]
        assert [s["name"] for s in stack["mcp"]] == ["aspire"]
