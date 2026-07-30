"""Tests for the Copilot MCP config ai-badger writes — `.github/mcp.json` (issue #189).

`.github/copilot/mcp-config.json`, the file ai-badger wrote until 0.51.0, is read by no
Copilot surface. The Copilot CLI's repo-committed config is `.github/mcp.json`: top-level
`mcpServers`, per-server `tools` array, `"*"` for everything
(docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

LEGACY = Path(".github") / "copilot" / "mcp-config.json"
CURRENT = Path(".github") / "mcp.json"


def _config(stacks=None, agents=None, mcp=None):
    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": stacks if stacks is not None else ["python"],
        "agents": agents if agents is not None else ["copilot"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if mcp is not None:
        config["mcp"] = mcp
    return config


def _scaf(make_scaffolder, tmp_path, config):
    index_path = tmp_path / "index.json"
    if not index_path.exists():
        index_path.write_text(json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}),
                              encoding="utf-8")
    return make_scaffolder(root=tmp_path, target=make_scaffolder.target, config=config)


def _servers(**overrides):
    server = {"name": "pyright", "command": "uvx mcp-server-pyright"}
    server.update(overrides)
    return {server["name"]: server}


def _written(target: Path) -> dict:
    return json.loads((target / CURRENT).read_text(encoding="utf-8"))


# ── the retarget ─────────────────────────────────────────────────────────────

def test_the_declared_server_lands_in_github_mcp_json(make_scaffolder, tmp_path):
    """The whole of #189: the file Copilot CLI actually reads."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert _written(target)["mcpServers"]["pyright"]["command"] == "uvx"
    assert _written(target)["mcpServers"]["pyright"]["args"] == ["mcp-server-pyright"]


def test_the_dead_path_is_never_written_again(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert not (target / LEGACY).exists()


def test_every_declared_server_gets_the_full_tool_allowlist(make_scaffolder, tmp_path):
    """The per-server `tools` array is the Copilot-only field; `"*"` is every tool."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert _written(target)["mcpServers"]["pyright"]["tools"] == ["*"]


def test_no_other_destination_grows_a_tools_array(make_scaffolder, tmp_path):
    """`.mcp.json` is Claude Code's schema and has no `tools` key to grow."""
    target = make_scaffolder.target
    stack = tmp_path / "features" / "python"
    stack.mkdir(parents=True)
    (stack / "mcp-servers.json").write_text(
        json.dumps({"servers": [{"name": "pyright", "command": "uvx mcp-server-pyright"}]}),
        encoding="utf-8")
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["claude"]))

    scaf.mcp.generate_mcp_json()

    entry = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["pyright"]
    assert "tools" not in entry


def test_nothing_is_written_without_the_copilot_agent(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["claude"]))

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert not (target / CURRENT).exists()


def test_an_existing_hand_added_server_survives_the_merge(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    (target / ".github").mkdir(parents=True, exist_ok=True)
    (target / CURRENT).write_text(
        json.dumps({"mcpServers": {"mine": {"command": "echo mine", "tools": ["a"]}}}),
        encoding="utf-8")
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    servers = _written(target)["mcpServers"]
    assert servers["mine"] == {"command": "echo mine", "tools": ["a"]}
    assert "pyright" in servers


def test_env_still_reaches_the_entry(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers(env={"TOKEN": "${MCP_TOKEN}"}))

    assert _written(target)["mcpServers"]["pyright"]["env"] == {"TOKEN": "${MCP_TOKEN}"}


def test_the_copilot_overrides_are_the_ones_applied(make_scaffolder, tmp_path):
    """One file, one reading agent, its overrides (F-22)."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config(agents=["copilot", "claude"]))

    scaf.mcp.generate_copilot_mcp_json(_servers(agentOverrides={
        "claude": {"command": "claude-resolved"},
        "copilot": {"command": "copilot-resolved"},
    }))

    assert _written(target)["mcpServers"]["pyright"]["command"] == "copilot-resolved"


# ── the stale dead file ──────────────────────────────────────────────────────

def _legacy(target: Path, payload) -> Path:
    path = target / LEGACY
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_a_generated_dead_file_is_removed_with_a_backup(make_scaffolder, tmp_path):
    """The file ai-badger wrote is cleaned up on re-scaffold, never silently destroyed."""
    target = make_scaffolder.target
    original = {"mcpServers": {"code-review-graph": {"command": "python3", "args": ["-m", "x"]}}}
    path = _legacy(target, original)
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert not path.exists()
    backups = list(path.parent.glob("mcp-config.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_removing_the_dead_file_is_reported(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    _legacy(target, {"mcpServers": {}})
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert any("mcp-config.json" in note and "189" in note for note in scaf.notes)


def test_a_hand_authored_dead_file_is_reported_not_deleted(make_scaffolder, tmp_path):
    """A key ai-badger's writer never emits means someone else authored the file."""
    target = make_scaffolder.target
    original = {"mcpServers": {"remote": {"type": "http", "url": "https://example.invalid/mcp"}}}
    path = _legacy(target, original)
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(path.parent.glob("mcp-config.json.bak-*")) == []
    assert any("mcp-config.json" in note and "left in place" in note for note in scaf.notes)


def test_a_dead_file_with_extra_top_level_keys_is_reported_not_deleted(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    path = _legacy(target, {"mcpServers": {}, "inputs": []})
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert path.exists()
    assert any("left in place" in note for note in scaf.notes)


def test_an_unreadable_dead_file_is_reported_not_deleted(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    original = b'{"mcpServers": {"mine": {"command": "x"}},,,'
    path = _legacy(target, original)
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert path.read_bytes() == original
    assert any("left in place" in note for note in scaf.notes)


def test_the_dead_file_is_retired_even_when_there_is_nothing_to_declare(make_scaffolder,
                                                                       tmp_path):
    """A project that stopped declaring servers still gets the dead file cleaned up."""
    target = make_scaffolder.target
    path = _legacy(target, {"mcpServers": {}})
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json({})

    assert not path.exists()


def test_an_absent_dead_file_produces_no_note(make_scaffolder, tmp_path):
    scaf = _scaf(make_scaffolder, tmp_path, _config())

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert not any("mcp-config.json" in note for note in scaf.notes)


# ── `config.mcp.decline` on the Copilot host (issue #186) ────────────────────

def test_a_declined_server_is_left_out_of_github_mcp_json(make_scaffolder, tmp_path):
    """Copilot's decline route is exclusion: an undeclared server registers from no file of ours."""
    target = make_scaffolder.target
    scaf = _scaf(make_scaffolder, tmp_path, _config(mcp={"decline": ["pyright"]}))

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert not (target / CURRENT).exists()


def test_a_previously_declared_server_is_removed_once_declined(make_scaffolder, tmp_path):
    """Merge-only would have left the entry behind, and Copilot would still register it."""
    target = make_scaffolder.target
    (target / ".github").mkdir(parents=True, exist_ok=True)
    (target / CURRENT).write_text(
        json.dumps({"mcpServers": {"pyright": {"command": "uvx", "tools": ["*"]},
                                   "keeper": {"command": "echo"}}}), encoding="utf-8")
    scaf = _scaf(make_scaffolder, tmp_path, _config(mcp={"decline": ["pyright"]}))

    scaf.mcp.generate_copilot_mcp_json(_servers())

    servers = _written(target)["mcpServers"]
    assert "pyright" not in servers
    assert "keeper" in servers


def test_removing_a_declined_entry_is_reported(make_scaffolder, tmp_path):
    target = make_scaffolder.target
    (target / ".github").mkdir(parents=True, exist_ok=True)
    (target / CURRENT).write_text(
        json.dumps({"mcpServers": {"pyright": {"command": "uvx"}}}), encoding="utf-8")
    scaf = _scaf(make_scaffolder, tmp_path, _config(mcp={"decline": ["pyright"]}))

    scaf.mcp.generate_copilot_mcp_json(_servers())

    assert any("declined" in note and "pyright" in note for note in scaf.notes)


# ── the shape predicate, on its own ──────────────────────────────────────────

@pytest.mark.parametrize("data,generated", [
    ({}, True),
    ({"mcpServers": {}}, True),
    ({"mcpServers": {"a": {"command": "x"}}}, True),
    ({"mcpServers": {"a": {"command": "x", "args": ["y"], "env": {}, "cwd": "/p",
                           "tools": ["*"]}}}, True),
    ({"mcpServers": {"a": {"command": "x", "type": "local"}}}, False),
    ({"mcpServers": {"a": {"url": "https://example.invalid"}}}, False),
    ({"mcpServers": []}, False),
    ({"mcpServers": {"a": "echo"}}, False),
    ({"mcpServers": {}, "servers": {}}, False),
])
def test_only_generated_entries_recognises_ai_badgers_own_shape(data, generated, load_script):
    """The authorship test behind the removal: ai-badger writes these keys and no others."""
    load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    import mcp_tools  # pylint: disable=import-outside-toplevel

    assert mcp_tools.only_generated_entries(data) is generated
