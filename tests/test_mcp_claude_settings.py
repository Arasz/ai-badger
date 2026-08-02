"""What a Claude scaffold does about MCP: approve in the project, propose for the user.

Two halves of ADR-0014 decision 6 for the Claude host — ai-badger writes the project settings
file it owns, and only *proposes* the user-global one. The end-to-end case is the one that
matters: a real `scaf.run()` over this framework's own catalog must leave the approval in
`.claude/settings.json`, not merely make an adjuster capable of it.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _config(agents=("claude",), stacks=("python",), mcp=None) -> dict:
    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": list(stacks),
        "agents": list(agents),
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if mcp is not None:
        config["mcp"] = mcp
    return config


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` and the HOME env vars into tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _settings(target: Path) -> dict:
    return json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))


# ── the whole scaffold, over this framework's own catalog ─────────────────────

@pytest.mark.usefixtures("fake_home")
def test_a_full_scaffold_approves_the_declared_server(make_scaffolder):
    """`features/common/stack-mcp.json` declares code-review-graph; the run must approve it."""
    target = make_scaffolder.target
    (target / ".claude").mkdir(parents=True, exist_ok=True)
    (target / ".claude" / "settings.json").write_text(
        json.dumps({"env": {"MARK": "kept"}}), encoding="utf-8")

    scaf = make_scaffolder(config=_config())
    scaf.run(generated_at="2026-07-30T00:00:00Z")

    settings = _settings(target)
    assert "code-review-graph" in settings["enabledMcpjsonServers"]
    assert "mcp__code-review-graph__*" in settings["permissions"]["allow"]
    assert settings["env"] == {"MARK": "kept"}, "existing settings must survive the merge"


@pytest.mark.usefixtures("fake_home")
def test_a_full_scaffold_declines_the_declared_server_when_config_says_so(make_scaffolder):
    """A declined server is denied project-wide and blocked from the project `.mcp.json`."""
    scaf = make_scaffolder(config=_config(mcp={"decline": ["code-review-graph"]}))
    scaf.run(generated_at="2026-07-30T00:00:00Z")

    settings = _settings(make_scaffolder.target)
    assert settings["permissions"]["deny"] == ["mcp__code-review-graph__*"]
    assert settings["disabledMcpjsonServers"] == ["code-review-graph"]
    assert "mcp__code-review-graph__*" not in settings["permissions"].get("allow", [])


# ── the user-global half: proposed, never written ─────────────────────────────

def test_a_user_scoped_server_is_proposed_never_written(fake_home, make_scaffolder):
    """`~/.claude/settings.json` is the user's file: ai-badger prints the snippet instead."""
    scaf = make_scaffolder(config=_config())

    scaf.mcp.propose_claude_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}})

    assert not (fake_home / ".claude" / "settings.json").exists()
    proposal = [n for n in scaf.notes if "~/.claude/settings.json" in n]
    assert len(proposal) == 1
    assert '"srv"' in proposal[0]
    assert "never writes" in proposal[0]


def test_an_existing_user_settings_file_is_not_touched(fake_home, make_scaffolder):
    """Not even a merge, and not even a backup — the previous behaviour did both."""
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original = json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}}, indent=2) + "\n"
    settings_path.write_text(original, encoding="utf-8")
    scaf = make_scaffolder(config=_config())

    scaf.mcp.propose_claude_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}})

    assert settings_path.read_text(encoding="utf-8") == original
    assert list(settings_path.parent.glob("settings.json.bak-*")) == []


def test_nothing_is_proposed_without_a_user_scoped_server(fake_home, make_scaffolder):
    scaf = make_scaffolder(config=_config())

    scaf.mcp.propose_claude_mcp_user({})

    assert [n for n in scaf.notes if "~/.claude/settings.json" in n] == []
    assert not (fake_home / ".claude").exists()


def test_nothing_is_proposed_when_claude_is_not_configured(fake_home, make_scaffolder):
    scaf = make_scaffolder(config=_config(agents=("hermes",)))

    scaf.mcp.propose_claude_mcp_user(
        {"srv": {"name": "srv", "command": "echo hi", "scope": "user"}})

    assert [n for n in scaf.notes if "~/.claude/settings.json" in n] == []
    assert not (fake_home / ".claude").exists()
