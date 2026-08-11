"""An unparseable catalog file must produce a note, never a silently smaller scaffold.

`stack-mcp.json` decides which MCP servers a project gets. A typo in it used to `continue`
past the parse error with no note, no warning and a zero exit — the scaffold just quietly
lacked servers (review F-24). The two retired files this case was first written against are
now reported on sight, without being parsed at all (ADR-0014 step 8).
"""
from __future__ import annotations

import json

from test_scaffold_context import _hand_built_context, _load
from conftest import _test_write


def _mcp_tools(load_script, root, tmp_path, filename, body):
    """An McpTools built on a context whose framework root holds one catalog file."""
    fake_root = tmp_path / "framework"
    (fake_root / "features" / "python").mkdir(parents=True)
    _test_write(fake_root / "features" / "python" / filename, body, encoding="utf-8")
    ctx = _hand_built_context(load_script, root, tmp_path / "proj")
    ctx.root = fake_root
    ctx.stacks = ["python"]
    return _load(load_script, root, "mcp_tools").McpTools(ctx), ctx


def test_unparseable_stack_mcp_json_is_noted(tmp_path, load_script, root):
    mcp, ctx = _mcp_tools(load_script, root, tmp_path, "stack-mcp.json", '{"servers": [')

    servers = mcp.collect_catalog_mcp_servers()

    assert servers == []
    assert any("stack-mcp.json" in note for note in ctx.notes)


def test_a_retired_external_tools_json_is_named_rather_than_parsed(tmp_path, load_script, root):
    """Its reader is gone, so `not json at all` is reported for existing, not for parsing."""
    mcp, ctx = _mcp_tools(load_script, root, tmp_path, "external-tools.json",
                          "not json at all")

    declared = mcp.declared_servers()

    assert declared == {}
    assert any("external-tools.json" in note for note in ctx.notes)


def test_a_readable_file_produces_no_note(tmp_path, load_script, root):
    mcp, ctx = _mcp_tools(load_script, root, tmp_path, "stack-mcp.json",
                          json.dumps({"servers": [{"name": "one"}]}))

    servers = mcp.collect_catalog_mcp_servers()

    assert [s["name"] for s in servers] == ["one"]
    assert ctx.notes == []
