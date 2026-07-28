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
        index_path.write_text(
            json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}), encoding="utf-8"
        )
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
                script.write_text("", encoding="utf-8")


# ── project .claude/settings.json (hook_wiring) ───────────────────────────────

@pytest.mark.usefixtures("fake_home")
def test_wire_hooks_aborts_on_unparseable_settings(tmp_path, root, make_scaffolder):
    """An unparseable project settings.json is left byte-identical and reported."""
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    settings_path = target / ".claude" / "settings.json"
    original = b'{"permissions":{"deny":["Bash"]}},,,'
    settings_path.write_bytes(original)
    _place_hook_scripts(root, target)

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["claude"]))
    scaf.wire_hooks()

    assert settings_path.read_bytes() == original
    assert _mentions(scaf.notes, "settings.json", "refused")


# ── ~/.hermes/config.yaml (mcp_tools) ─────────────────────────────────────────

def test_hermes_user_config_yaml_error_does_not_escape_run(root, fake_home, make_scaffolder):
    """A malformed ~/.hermes/config.yaml yields a note, not a YAMLError."""
    pytest.importorskip("yaml")
    target = make_scaffolder.target
    config_path = fake_home / ".hermes" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    original = b"mcp:\n  servers: {broken: [\n"
    config_path.write_bytes(original)

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["hermes"]))
    scaf.mcp.scaffold_hermes_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}}
    )

    assert config_path.read_bytes() == original
    assert _mentions(scaf.notes, "config.yaml", "refused")


def test_yaml_parsing_to_a_list_does_not_raise(root, fake_home, make_scaffolder):
    """A config.yaml whose top level is a list is refused, not AttributeError'd."""
    pytest.importorskip("yaml")
    target = make_scaffolder.target
    config_path = fake_home / ".hermes" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    original = b"- one\n- two\n"
    config_path.write_bytes(original)

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["hermes"]))
    scaf.mcp.scaffold_hermes_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}}
    )

    assert config_path.read_bytes() == original
    assert _mentions(scaf.notes, "config.yaml", "refused")


# ── ~/.claude/settings.json (mcp_tools) ───────────────────────────────────────

def test_valid_user_settings_survive_with_backup(root, fake_home, make_scaffolder):
    """A parseable ~/.claude/settings.json keeps its keys and is backed up first."""
    target = make_scaffolder.target
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original = {"permissions": {"deny": ["Bash(rm:*)"]}, "env": {"FOO": "bar"}}
    settings_path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["claude"]))
    scaf.mcp.scaffold_claude_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}}
    )

    written = json.loads(settings_path.read_text(encoding="utf-8"))
    assert written["permissions"] == original["permissions"]
    assert written["env"] == original["env"]
    assert "srv" in written["mcpServers"]

    backups = list(settings_path.parent.glob("settings.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_unparseable_user_settings_are_never_rewritten(root, fake_home, make_scaffolder):
    """An unparseable ~/.claude/settings.json is left byte-identical and reported."""
    target = make_scaffolder.target
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original = b'{"permissions":{"deny":["Bash"]}},,,'
    settings_path.write_bytes(original)

    scaf = _scaf(make_scaffolder, root, target, _config(agents=["claude"]))
    scaf.mcp.scaffold_claude_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}}
    )

    assert settings_path.read_bytes() == original
    assert _mentions(scaf.notes, "settings.json", "refused")


# ── project .mcp.json and .github/copilot/mcp-config.json (mcp_tools) ─────────

@pytest.mark.usefixtures("fake_home")
def test_unparseable_mcp_json_is_never_rewritten(tmp_path, make_scaffolder):
    """An unparseable .mcp.json is left byte-identical and reported."""
    target = make_scaffolder.target
    stack_dir = tmp_path / "features" / "python"
    stack_dir.mkdir(parents=True)
    (stack_dir / "mcp-servers.json").write_text(
        json.dumps({"servers": [{"name": "pyright", "command": "uvx mcp-server-pyright"}]}),
        encoding="utf-8",
    )
    mcp_path = target / ".mcp.json"
    original = b'{"mcpServers": {"mine": {"command": "x"}},,,'
    mcp_path.write_bytes(original)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["claude"]))
    scaf.mcp.generate_mcp_json()

    assert mcp_path.read_bytes() == original
    assert _mentions(scaf.notes, ".mcp.json", "refused")


@pytest.mark.usefixtures("fake_home")
def test_unparseable_copilot_mcp_config_is_never_rewritten(tmp_path, make_scaffolder):
    """An unparseable .github/copilot/mcp-config.json is left byte-identical."""
    target = make_scaffolder.target
    config_path = target / ".github" / "copilot" / "mcp-config.json"
    config_path.parent.mkdir(parents=True)
    original = b'{"mcpServers": {"mine": {"command": "x"}},,,'
    config_path.write_bytes(original)

    scaf = _scaf(make_scaffolder, tmp_path, target, _config(agents=["copilot"]))
    scaf.mcp.generate_copilot_mcp_config(
        {"srv": {"name": "srv", "command": "echo hi"}}
    )

    assert config_path.read_bytes() == original
    assert _mentions(scaf.notes, "mcp-config.json", "refused")
