"""An unparseable catalog file must produce a note, never a silently smaller scaffold.

`mcp-servers.json` and `external-tools.json` decide which MCP servers a project gets. A
typo in either used to `continue` past the parse error with no note, no warning and a zero
exit — the scaffold just quietly lacked servers (review F-24).
"""
from __future__ import annotations

import json

from test_scaffold_context import _hand_built_context, _load


def _mcp_tools(load_script, root, tmp_path, filename, body):
    """An McpTools built on a context whose framework root holds one catalog file."""
    fake_root = tmp_path / "framework"
    (fake_root / "features" / "python").mkdir(parents=True)
    (fake_root / "features" / "python" / filename).write_text(body, encoding="utf-8")
    ctx = _hand_built_context(load_script, root, tmp_path / "proj")
    ctx.root = fake_root
    ctx.stacks = ["python"]
    return _load(load_script, root, "mcp_tools").McpTools(ctx), ctx


def test_unparseable_mcp_servers_json_is_noted(tmp_path, load_script, root):
    mcp, ctx = _mcp_tools(load_script, root, tmp_path, "mcp-servers.json", '{"servers": [')

    servers = mcp.collect_stack_mcp_servers()

    assert servers == []
    assert any("mcp-servers.json" in note for note in ctx.notes)


def test_unparseable_external_tools_json_is_noted(tmp_path, load_script, root):
    mcp, ctx = _mcp_tools(load_script, root, tmp_path, "external-tools.json", "not json at all")

    tools = mcp.collect_external_tools()

    assert tools == []
    assert any("external-tools.json" in note for note in ctx.notes)


def test_a_readable_file_produces_no_note(tmp_path, load_script, root):
    mcp, ctx = _mcp_tools(load_script, root, tmp_path, "mcp-servers.json",
                          json.dumps({"servers": [{"name": "one"}]}))

    servers = mcp.collect_stack_mcp_servers()

    assert [s["name"] for s in servers] == ["one"]
    assert ctx.notes == []
