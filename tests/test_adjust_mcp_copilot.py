"""Tests for features/copilot/adjustments/adjust_mcp.py — the coding agent is propose-only.

The Copilot **coding agent** takes MCP configuration from the repository settings UI and from
no repo file, so ai-badger can only print the JSON an admin pastes. Two verified constraints
shape the snippet: the per-server `tools` array is required, and secrets must be referenced by
a `COPILOT_MCP_*`-prefixed name
(docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp).
The Copilot **CLI** is a different surface and gets a real file, `.github/mcp.json`.
"""
from __future__ import annotations

import json
from pathlib import Path

ADJUSTER = "features/copilot/adjustments/adjust_mcp.py"


def _context(root: Path, target: Path, *, agents=("copilot",), declarations=None,
             declined=()) -> dict:
    if declarations is None:
        declarations = {"code-review-graph": {
            "name": "code-review-graph", "command": "python3 -m code_review_graph serve"}}
    config = {"agents": list(agents)}
    if declined:
        config["mcp"] = {"decline": list(declined)}
    return {
        "framework_root": root,
        "config": config,
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": [],
        "index": {},
        "mcp_servers": sorted(declarations),
        "mcp_declarations": declarations,
        "mcp_declined": list(declined),
    }


def _snippet(root: Path, target: Path, load_script, **kwargs) -> dict:
    adjust_mcp = load_script(ADJUSTER)
    notes = adjust_mcp.adjust(_context(root, target, **kwargs))["notes"]
    return json.loads(notes[notes.index("{"):notes.rindex("}") + 1])


def test_the_snippet_carries_the_launch_config(tmp_path, root, load_script):
    servers = _snippet(root, tmp_path, load_script)["mcpServers"]

    assert servers["code-review-graph"]["command"] == "python3"
    assert servers["code-review-graph"]["args"] == ["-m", "code_review_graph", "serve"]


def test_the_tools_array_is_present_because_the_coding_agent_requires_it(tmp_path, root,
                                                                        load_script):
    servers = _snippet(root, tmp_path, load_script)["mcpServers"]

    assert servers["code-review-graph"]["tools"] == ["*"]


def test_a_secret_reference_is_renamed_to_the_copilot_mcp_prefix(tmp_path, root, load_script):
    """The coding agent only resolves `COPILOT_MCP_*` secrets, so the snippet must ask for one."""
    servers = _snippet(root, tmp_path, load_script, declarations={"srv": {
        "name": "srv", "command": "echo", "env": {"API_KEY": "${MCP_SRV_API_KEY}"}}})["mcpServers"]

    assert servers["srv"]["env"] == {"API_KEY": "$COPILOT_MCP_MCP_SRV_API_KEY"}


def test_an_already_prefixed_secret_is_left_alone(tmp_path, root, load_script):
    servers = _snippet(root, tmp_path, load_script, declarations={"srv": {
        "name": "srv", "command": "echo",
        "env": {"API_KEY": "$COPILOT_MCP_SRV_KEY"}}})["mcpServers"]

    assert servers["srv"]["env"] == {"API_KEY": "$COPILOT_MCP_SRV_KEY"}


def test_a_literal_env_value_is_not_turned_into_a_secret(tmp_path, root, load_script):
    servers = _snippet(root, tmp_path, load_script, declarations={"srv": {
        "name": "srv", "command": "echo", "env": {"MODE": "readonly"}}})["mcpServers"]

    assert servers["srv"]["env"] == {"MODE": "readonly"}


def test_the_note_names_the_surface_that_cannot_be_written(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)

    notes = adjust_mcp.adjust(_context(root, tmp_path))["notes"]

    assert "repository settings" in notes
    assert "coding agent" in notes


def test_a_user_scoped_declaration_is_not_proposed_as_repository_configuration(
        tmp_path, root, load_script):
    """`scope: user` names a user-global file; the settings UI is a repository surface."""
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(_context(root, tmp_path, declarations={
        "srv": {"name": "srv", "command": "echo", "scope": "user"}}))

    assert not result["applied"]


def test_a_declined_server_is_never_proposed(tmp_path, root, load_script):
    """Issue #186 on the Copilot host: decline is exclusion, on both Copilot surfaces."""
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(
        _context(root, tmp_path, declined=("code-review-graph",)))

    assert "mcpServers" not in result["notes"]


def test_the_declined_names_are_reported_with_their_runtime_deny_flag(tmp_path, root,
                                                                     load_script):
    """Copilot's only documented block for a server from elsewhere is a runtime flag."""
    adjust_mcp = load_script(ADJUSTER)

    notes = adjust_mcp.adjust(_context(
        root, tmp_path,
        declarations={"keep": {"name": "keep", "command": "echo"}},
        declined=("rider",)))["notes"]

    assert "--deny-tool" in notes
    assert "rider" in notes


def test_nothing_is_written_and_nothing_is_recorded(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(_context(root, target))

    assert result["files"] == []
    assert list(target.iterdir()) == []


def test_not_applied_without_the_copilot_agent(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(_context(root, tmp_path, agents=("claude",)))

    assert not result["applied"]


def test_not_applied_with_nothing_declared(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(_context(root, tmp_path, declarations={}))

    assert not result["applied"]
