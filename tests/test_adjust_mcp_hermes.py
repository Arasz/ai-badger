"""Tests for features/hermes/adjustments/adjust_mcp.py — a proposal, never a write.

Hermes reads MCP servers from `~/.hermes/config.yaml` `mcp_servers` and has no project route
at all, so ADR-0014 decision 6 leaves ai-badger nothing to write. The proposal is a
ready-to-paste snippet: `{command|url, args, headers, enabled}` per server, and per-server
`tools` include/exclude globs applied at registration — which is Hermes's decline route.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import _test_write

ADJUSTER = "features/hermes/adjustments/adjust_mcp.py"


def _context(root: Path, target: Path, *, agents=("hermes",), declarations=None,
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


def _proposal(root: Path, target: Path, load_script, **kwargs) -> str:
    adjust_mcp = load_script(ADJUSTER)
    return adjust_mcp.adjust(_context(root, target, **kwargs))["notes"]


# ── it proposes ──────────────────────────────────────────────────────────────

def test_the_snippet_is_a_paste_ready_mcp_servers_block(tmp_path, root, load_script):
    """The key Hermes actually reads is top-level `mcp_servers`, not `mcp.servers`."""
    notes = _proposal(root, tmp_path, load_script)

    assert "mcp_servers:" in notes
    assert "  code-review-graph:" in notes
    assert '    command: "python3"' in notes
    assert '    args: ["-m", "code_review_graph", "serve"]' in notes
    assert "    enabled: true" in notes


def _yaml_blocks(notes: str):
    """Every `mcp_servers:` block in the note, with the surrounding prose stripped."""
    blocks, current = [], None
    for line in notes.splitlines():
        if line.startswith("mcp_servers:"):
            current = [line]
            blocks.append(current)
        elif current is not None and (not line.strip() or line.startswith(" ")):
            current.append(line)
        else:
            current = None
    return ["\n".join(block) for block in blocks]


def test_the_snippet_parses_as_the_yaml_hermes_would_read(tmp_path, root, load_script):
    """A snippet the operator pastes must be valid YAML, whatever built it."""
    yaml = pytest.importorskip("yaml")
    notes = _proposal(root, tmp_path, load_script)

    block = yaml.safe_load(_yaml_blocks(notes)[0])

    assert block["mcp_servers"]["code-review-graph"] == {
        "command": "python3", "args": ["-m", "code_review_graph", "serve"], "enabled": True}


def test_env_is_carried_into_the_snippet(tmp_path, root, load_script):
    notes = _proposal(root, tmp_path, load_script, declarations={"srv": {
        "name": "srv", "command": "echo", "env": {"TOKEN": "${MCP_SRV_API_KEY}"}}})

    assert "    env:" in notes
    assert '      TOKEN: "${MCP_SRV_API_KEY}"' in notes


def test_a_command_with_no_arguments_omits_the_args_key(tmp_path, root, load_script):
    notes = _proposal(root, tmp_path, load_script,
                      declarations={"srv": {"name": "srv", "command": "hermes-mcp"}})

    assert '    command: "hermes-mcp"' in notes
    assert "args:" not in notes


def test_the_proposal_keeps_the_bare_command(tmp_path, root, load_script):
    """No `${HOME}` rewrite: only `.mcp.json` documents `${VAR}` expansion (0.28.0)."""
    notes = _proposal(root, tmp_path, load_script, declarations={
        "roslyn": {"name": "roslyn", "command": "cwm-roslyn-navigator"}})

    assert '    command: "cwm-roslyn-navigator"' in notes
    assert "${HOME}" not in notes


def test_the_note_says_ai_badger_will_not_write_the_file(tmp_path, root, load_script):
    notes = _proposal(root, tmp_path, load_script)

    assert "~/.hermes/config.yaml" in notes
    assert "never writes" in notes


# ── it never writes ──────────────────────────────────────────────────────────

def test_no_file_is_created_anywhere(tmp_path, root, load_script, monkeypatch):
    """The write this replaces created `~/.hermes/config.yaml` and backed it up."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _proposal(root, tmp_path / "proj", load_script)

    assert not (home / ".hermes").exists()


def test_an_existing_config_is_neither_read_nor_rewritten(tmp_path, root, load_script,
                                                          monkeypatch):
    """An unparseable file proves it: a merge would have had to parse it."""
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    config_path = home / ".hermes" / "config.yaml"
    original = b"mcp_servers: {broken: [\n"
    _test_write(config_path, original)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    notes = _proposal(root, tmp_path / "proj", load_script)

    assert config_path.read_bytes() == original
    assert list((home / ".hermes").glob("config.yaml.bak-*")) == []
    assert "refused" not in notes


def test_nothing_is_recorded_as_an_ai_badger_owned_file(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(_context(root, tmp_path))

    assert result["files"] == []


# ── the decline route: exclude globs (issue #186) ────────────────────────────

def test_a_declined_server_is_proposed_as_a_tools_exclude(tmp_path, root, load_script):
    """Hermes prunes at registration, so an excluded tool never reaches the model."""
    notes = _proposal(root, tmp_path, load_script, declined=("rider",))

    assert "  rider:" in notes
    assert "    tools:" in notes
    assert '      exclude: ["*"]' in notes


def test_a_declined_server_is_not_proposed_with_a_launch_command(tmp_path, root, load_script):
    """It is the user's own entry; the proposal adds an exclude, never a command."""
    notes = _proposal(root, tmp_path, load_script, declined=("rider",))
    rider = notes.split("  rider:", 1)[1]

    assert "command:" not in rider


def test_declining_a_declared_server_drops_it_from_the_launch_block(tmp_path, root, load_script):
    notes = _proposal(root, tmp_path, load_script, declined=("code-review-graph",))

    assert "enabled: true" not in notes
    assert '      exclude: ["*"]' in notes


def test_the_exclude_block_parses_too(tmp_path, root, load_script):
    yaml = pytest.importorskip("yaml")
    notes = _proposal(root, tmp_path, load_script, declined=("rider",))

    block = yaml.safe_load(_yaml_blocks(notes)[-1])

    assert block["mcp_servers"]["rider"]["tools"]["exclude"] == ["*"]


# ── when it does not apply ───────────────────────────────────────────────────

def test_not_applied_without_the_hermes_agent(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(_context(root, tmp_path, agents=("claude",)))

    assert not result["applied"]


def test_not_applied_with_nothing_declared_or_declined(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)

    result = adjust_mcp.adjust(_context(root, tmp_path, declarations={}))

    assert not result["applied"]
    assert "mcp_servers:" not in result["notes"]


def test_the_snippet_needs_no_yaml_library(tmp_path, root, load_script, monkeypatch):
    """pyyaml is an optional dependency; a proposal that needs it is a proposal that vanishes."""
    monkeypatch.setitem(__import__("sys").modules, "yaml", None)

    notes = _proposal(root, tmp_path, load_script)

    assert "mcp_servers:" in notes
