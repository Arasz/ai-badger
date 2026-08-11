"""Guards against clobbering config files the framework did not author (F-02).

An unreadable config must never be treated as an empty one and rewritten, and a
parseable user-scope config must be backed up before it is modified.  Every test
here redirects ``Path.home()`` at ``tmp_path`` — none may touch the real $HOME.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
# pylint: disable=protected-access  # scaffolder internals are the unit under test
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import _test_write

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _config(agents=None):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` and the HOME env vars into tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home
    return home


def _scaf(make_scaffolder, root, target, config):
    index_path = root / "index.json"
    if not index_path.exists():
        _test_write(index_path, json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8")
    return make_scaffolder(root=root, target=target, config=config)


def _mentions(notes, *fragments):
    return any(all(f in note for f in fragments) for note in notes)


def _place_hook_scripts(root, target):
    """Create the scaffolded scripts the framework's hooks.json names — wire_hooks skips absent
    ones, so a project with none of them wires nothing and never reaches settings.json."""
    source = json.loads(
        (root / "features" / "common" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for entries in source.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                rel = hook["command"].split("/features/common/skills/", 1)[-1].rstrip('"')
                script = target / ".ai-badger" / "skills" / rel
                script.parent.mkdir(parents=True, exist_ok=True)
                _test_write(script, "", encoding="utf-8")


# ── project .claude/settings.json (hook_wiring) ───────────────────────────────

@pytest.mark.usefixtures("fake_home")
def test_wire_hooks_aborts_on_unparseable_settings(tmp_path, root, make_scaffolder):
    """An unparseable project settings.json is left byte-identical and reported."""
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    settings_path = target / ".claude" / "settings.json"
    original = b'{"permissions":{"deny":["Bash"]}},,,'
    _test_write(settings_path, original)
    _place_hook_scripts(root, target)

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["claude"]))
    scaf.wire_hooks()

    assert settings_path.read_bytes() == original
    assert _mentions(scaf.notes, "settings.json", "refused")


# ── ~/.hermes/config.yaml (mcp_tools) ─────────────────────────────────────────

def test_the_hermes_user_config_is_neither_read_nor_written(root, fake_home, make_scaffolder):
    """A whole scaffold run never opens ~/.hermes/config.yaml (ADR-0014 decision 6).

    Until 0.51.0 this merged a `scope: user` server into it, backup and all. An unparseable
    file proves the new contract, exactly as the Claude case below does: a merge would have had
    to parse it, and a refusal note would have had to read it.
    """
    config_path = fake_home / ".hermes" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    original = b"mcp_servers: {broken: [\n"
    _test_write(config_path, original)

    scaf = _scaf(make_scaffolder, root, make_scaffolder.target, _config(agents=["hermes"]))
    scaf.run(generated_at="2026-07-30T00:00:00Z")

    assert config_path.read_bytes() == original
    assert list(config_path.parent.glob("config.yaml.bak-*")) == []
    assert not _mentions(scaf.notes, "config.yaml", "refused")


# ── ~/.claude/settings.json (mcp_tools) ───────────────────────────────────────

def test_user_settings_are_neither_read_nor_written(root, fake_home, make_scaffolder):
    """The strongest form of the F-02 guard: a user-scoped server never opens the file.

    Until ADR-0014 decision 6 this merged into ~/.claude/settings.json and backed it up.
    An unparseable file proves the new contract — a merge would have had to parse it, and a
    refusal note would have had to read it; neither happens, and the proposal still lands.
    """
    target = make_scaffolder.target
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original = b'{"permissions":{"deny":["Bash"]}},,,'
    _test_write(settings_path, original)

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["claude"]))
    scaf.mcp.propose_claude_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}}
    )

    assert settings_path.read_bytes() == original
    assert list(settings_path.parent.glob("settings.json.bak-*")) == []
    assert not _mentions(scaf.notes, "settings.json", "refused")
    assert _mentions(scaf.notes, "~/.claude/settings.json", "never writes")


# ── project .mcp.json and .github/mcp.json (mcp_tools) ────────────────────────

@pytest.mark.usefixtures("fake_home")
def test_unparseable_mcp_json_is_never_rewritten(tmp_path, make_scaffolder):
    """An unparseable .mcp.json is left byte-identical and reported."""
    target = make_scaffolder.target
    stack_dir = tmp_path / "features" / "python"
    stack_dir.mkdir(parents=True)
    _test_write(stack_dir / "stack-mcp.json", json.dumps({"servers": [{"name": "pyright", "command": "uvx mcp-server-pyright",
                                 "declare": True}]}), encoding="utf-8")
    mcp_path = target / ".mcp.json"
    original = b'{"mcpServers": {"mine": {"command": "x"}},,,'
    _test_write(mcp_path, original)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    assert mcp_path.read_bytes() == original
    assert _mentions(scaf.notes, ".mcp.json", "refused")


@pytest.mark.usefixtures("fake_home")
def test_unparseable_copilot_mcp_json_is_never_rewritten(tmp_path, make_scaffolder):
    """An unparseable .github/mcp.json is left byte-identical."""
    target = make_scaffolder.target
    config_path = target / ".github" / "mcp.json"
    config_path.parent.mkdir(parents=True)
    original = b'{"mcpServers": {"mine": {"command": "x"}},,,'
    _test_write(config_path, original)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["copilot"]))
    scaf.mcp.generate_copilot_mcp_json(
        {"srv": {"name": "srv", "command": "echo hi"}}
    )

    assert config_path.read_bytes() == original
    assert _mentions(scaf.notes, "mcp.json", "refused")
