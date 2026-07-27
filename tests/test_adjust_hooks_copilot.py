"""Tests for features/copilot/adjustments/adjust_hooks.py: Copilot hook wiring.

Covers the one property the generated .github/hooks/ai-badger-hooks.json must hold: each
manifest entry contributes its own script's command, never a sibling's. SessionStart carries
more than one command since F-07 split session recording from drift notice, so a wiring path
that copied the whole event would silently mislabel one as the other.
"""
from __future__ import annotations

import json


def _context(root, target) -> dict:
    return {
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["task"],
    }


def test_copilot_session_start_wires_drift_notice_not_session_tracking(tmp_path, load_script,
                                                                        root):
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    result = adjust_hooks.adjust(_context(root, target))

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    commands = [h["bash"] for h in hooks["hooks"]["sessionStart"]]
    assert [c.rsplit("/", 1)[-1] for c in commands] == ["drift_notice_hook.py"]
