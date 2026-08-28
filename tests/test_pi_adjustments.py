"""Tests for pi agent adjustments: MCP, hooks, task, cron."""
from __future__ import annotations

import json
import os
from pathlib import Path


def test_adjust_mcp_no_pi_in_config(load_script):
    """adjust_mcp returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {"config": {"agents": ["claude"]}, "mcp_declarations": {}, "mcp_declined": []}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_mcp_no_declarations(load_script):
    """adjust_mcp returns unapplied when no MCP servers declared."""
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {"config": {"agents": ["pi"]}, "mcp_declarations": {}, "mcp_declined": []}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_mcp_proposes_servers(load_script):
    """adjust_mcp returns applied with notes when pi and servers declared."""
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {
            "filesystem": {"command": "npx -y @modelcontextprotocol/server-filesystem /tmp"},
        },
        "mcp_declined": [],
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert "MCP server" in result["notes"]


def test_adjust_mcp_respects_decline(load_script):
    """adjust_mcp excludes declined servers from proposal."""
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {
            "filesystem": {"command": "npx server"},
            "github": {"command": "npx server-github"},
        },
        "mcp_declined": ["github"],
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert "github" in result["notes"]


def test_adjust_hooks_no_pi(load_script):
    """adjust_hooks returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_hooks.py")
    context = {"config": {"agents": ["claude"]}, "install": False}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_hooks_with_pi(load_script, root):
    """adjust_hooks copies hook scripts into target when pi in config."""
    adjust = load_script("features/pi/adjustments/adjust_hooks.py")
    target_dir = root / ".ai-badger"
    context = {
        "config": {"agents": ["pi"]},
        "framework_root": root,
        "feature_dir": root / "features" / "pi" / "adjustments",
        "target_dir": target_dir,
        "install": False,
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert len(result["files"]) > 0
    # Check at least one known hook was copied
    hook_files = [f for f in result["files"] if "hook" in f]
    assert len(hook_files) > 0


def test_adjust_task_no_pi(load_script):
    """adjust_task returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_task.py")
    context = {"config": {"agents": ["claude"]}, "skills": ["task"]}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_task_with_pi(load_script, root):
    """adjust_task copies pi_session_source.py when pi in config."""
    adjust = load_script("features/pi/adjustments/adjust_task.py")
    target_dir = root / ".ai-badger"
    context = {
        "config": {"agents": ["pi"]},
        "framework_root": root,
        "feature_dir": root / "features" / "pi" / "adjustments",
        "target_dir": target_dir,
        "skills": ["task"],
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert "pi_session_source" in result["notes"]


def test_adjust_cron_no_pi(load_script):
    """adjust_cron returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_cron.py")
    context = {"config": {"agents": ["claude"]}, "install": False}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_cron_with_pi_no_cron_dir(load_script, tmp_path):
    """adjust_cron returns unapplied when cron directory missing."""
    adjust = load_script("features/pi/adjustments/adjust_cron.py")
    feature_dir = tmp_path
    context = {
        "config": {"agents": ["pi"]},
        "feature_dir": feature_dir,
        "install": False,
    }
    result = adjust.adjust(context)
    assert not result["applied"]


def test_pi_session_source_register(load_script):
    """pi_session_source.register() wires the pi source into tracker_lib."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    calls = []
    class FakeTrackerLib:
        @staticmethod
        def register_session_source(name, env_var, resolve, checkpoint, resume, delegation_usage):
            calls.append((name, env_var, resolve, checkpoint, resume, delegation_usage))

    session_source.register(FakeTrackerLib)
    assert len(calls) == 1
    assert calls[0][0] == "pi"
    assert calls[0][1] == "PI_SESSION_ID"


def test_pi_session_source_resolve(load_script, monkeypatch):
    """_resolve returns session id from env var."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    monkeypatch.setenv("PI_SESSION_ID", "test-session-123")
    result = session_source._resolve()
    assert result["sessionId"] == "test-session-123"


def test_pi_session_source_resolve_empty(load_script, monkeypatch):
    """_resolve returns empty dict when env var not set."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    monkeypatch.delenv("PI_SESSION_ID", raising=False)
    result = session_source._resolve()
    assert result == {}


def test_pi_session_source_zeroed_checkpoint(load_script):
    """_zeroed_checkpoint returns all-zero checkpoint."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    checkpoint = session_source._zeroed_checkpoint("sess-1")
    assert checkpoint["contextTokens"] == 0
    assert checkpoint["cumulative"]["inputTokens"] == 0
    assert checkpoint["cumulative"]["outputTokens"] == 0