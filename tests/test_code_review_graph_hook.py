"""The code-review-graph refresh hook runs in the background, so an edit never waits on a reparse.

The entry is written by `code-review-graph install`, not the catalog; a reinstall can drop the flag.
"""
from __future__ import annotations

import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / ".claude" / "settings.json"


def _graph_update_hooks() -> list:
    events = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    return [hook
            for group in events.get("PostToolUse", [])
            for hook in group.get("hooks", [])
            if "code-review-graph update" in hook.get("command", "")]


def test_graph_update_hook_is_present():
    assert _graph_update_hooks(), "no code-review-graph update hook in .claude/settings.json"


def test_graph_update_hook_runs_async():
    assert all(hook.get("async") is True for hook in _graph_update_hooks())
