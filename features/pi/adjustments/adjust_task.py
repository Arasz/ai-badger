"""Adjustment: install the pi session source into the scaffolded task skill.

pi has no session database (no state.db equivalent), so the pi session source
is minimal: it reads the PI_SESSION_ID env var and provides a resume command.
Token tracking is not available for pi sessions — the tracker will report zeroes
for pi tasks.
"""
from __future__ import annotations

import shutil
from typing import Any, Dict

SESSION_SOURCE_SRC = "pi_session_source.py"
SESSION_SOURCE_DEST = ".ai-badger/skills/task/scripts/pi_session_source.py"


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Copy the pi session source module into the scaffolded task skill scripts.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/pi/adjustments/
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "pi" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "pi not in config.agents"}
    if "task" not in (context.get("skills") or []):
        return {"applied": False, "files": [],
                "notes": "task skill not delivered — nothing to install into"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    src = framework_root / "features" / "pi" / "adjustments" / SESSION_SOURCE_SRC

    if not src.exists():
        return {"applied": False, "files": [],
                "notes": "pi_session_source.py not found"}

    dst = target_dir / "skills" / "task" / "scripts" / "pi_session_source.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "applied": True,
        "files": [SESSION_SOURCE_DEST],
        "notes": "Installed pi session source into .ai-badger/skills/task/scripts/ as "
                 "pi_session_source.py — the <agent>_session_source.py name tracker_lib.py discovers",
    }