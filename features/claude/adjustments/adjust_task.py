"""Adjustment: install the Claude session source into the scaffolded task skill.

The claude-specific task-tracking code (transcript reading, session resolution from
CLAUDE_CODE_SESSION_ID and current-session.json) lives in claude_session_source.py — the
`<agent>_session_source.py` contract name the common tracker_lib.py discovers — and must not
ship in the common task skill scripts. This adjustment copies it into the scaffolded
`.ai-badger/skills/task/scripts/claude_session_source.py`, where tracker_lib's discovery
import finds and registers it. Same mechanism the hermes adjustment uses; no agent is special.
"""
from __future__ import annotations

import shutil
from typing import Any, Dict

SESSION_SOURCE_SRC = "claude_session_source.py"
SESSION_SOURCE_DEST = ".ai-badger/skills/task/scripts/claude_session_source.py"


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Copy the claude session source module into the scaffolded task skill scripts.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/claude/adjustments/
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "claude" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "claude not in config.agents"}
    if "task" not in (context.get("skills") or []):
        return {"applied": False, "files": [],
                "notes": "task skill not delivered — nothing to install into"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    src = framework_root / "features" / "claude" / "adjustments" / SESSION_SOURCE_SRC

    if not src.exists():
        return {"applied": False, "files": [],
                "notes": "claude_session_source.py not found"}

    dst = target_dir / "skills" / "task" / "scripts" / "claude_session_source.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {"applied": True, "files": [SESSION_SOURCE_DEST],
            "notes": "Installed claude session source into .ai-badger/skills/task/scripts/"}
