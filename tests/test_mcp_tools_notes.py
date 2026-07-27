"""An unparseable catalog file must produce a note, never a silently smaller scaffold.

`mcp-servers.json` and `external-tools.json` decide which MCP servers a project gets. A
typo in either used to `continue` past the parse error with no note, no warning and a zero
exit — the scaffold just quietly lacked servers (review F-24).
"""
from __future__ import annotations

import json
import sys


class _Collector:
    """Minimal stand-in for the Scaffolder attributes the mixin reads."""

    def __init__(self, root, stacks):
        self.root = root
        self.stacks = stacks
        self.notes = []


def _mixin(load_script, root, tmp_path, filename, body):
    # mcp_tools imports its sibling config_guard the way scaffold.py puts it on the path.
    sys.path.insert(0, str(root / "features/common/skills/welcome-ai-badger/scripts"))
    mcp_tools = load_script("features/common/skills/welcome-ai-badger/scripts/mcp_tools.py")
    fake_root = tmp_path / "framework"
    (fake_root / "features" / "python").mkdir(parents=True)
    (fake_root / "features" / "python" / filename).write_text(body, encoding="utf-8")
    collector = _Collector(fake_root, ["python"])
    collector.__class__ = type("Bound", (_Collector, mcp_tools.McpToolsMixin), {})
    return collector


def test_unparseable_mcp_servers_json_is_noted(tmp_path, load_script, root):
    collector = _mixin(load_script, root, tmp_path, "mcp-servers.json", '{"servers": [')

    servers = collector._collect_stack_mcp_servers()  # pylint: disable=protected-access

    assert servers == []
    assert any("mcp-servers.json" in note for note in collector.notes)


def test_unparseable_external_tools_json_is_noted(tmp_path, load_script, root):
    collector = _mixin(load_script, root, tmp_path, "external-tools.json", "not json at all")

    tools = collector._collect_external_tools()  # pylint: disable=protected-access

    assert tools == []
    assert any("external-tools.json" in note for note in collector.notes)


def test_a_readable_file_produces_no_note(tmp_path, load_script, root):
    collector = _mixin(load_script, root, tmp_path, "mcp-servers.json",
                       json.dumps({"servers": [{"name": "one"}]}))

    servers = collector._collect_stack_mcp_servers()  # pylint: disable=protected-access

    assert [s["name"] for s in servers] == ["one"]
    assert collector.notes == []
