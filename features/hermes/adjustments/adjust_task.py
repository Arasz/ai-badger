"""Adjustment: install the Hermes session source into the scaffolded task skill.

The hermes-specific task-tracking code (state.db path, SQLite parsing, delegation usage)
lives in hermes_session_source.py — the `<agent>_session_source.py` contract name the
common tracker_lib.py discovers — and must not ship in the common task skill scripts. This
adjustment copies it into the scaffolded `.ai-badger/skills/task/scripts/hermes_session_source.py`,
where tracker_lib's discovery import finds and registers it. Also confirms the Hermes task
extension (extension.md) exists for embedding into the skill.
"""
from __future__ import annotations

import shutil
from typing import Any, Dict

SESSION_SOURCE_SRC = "hermes_session_source.py"
SESSION_SOURCE_DEST = ".ai-badger/skills/task/scripts/hermes_session_source.py"


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Copy the hermes session source module into the scaffolded task skill scripts.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/hermes/adjustments/
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "hermes" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "hermes not in config.agents"}
    if "task" not in (context.get("skills") or []):
        return {"applied": False, "files": [],
                "notes": "task skill not delivered — nothing to install into"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    src = framework_root / "features" / "hermes" / "adjustments" / SESSION_SOURCE_SRC

    ext_md = framework_root / "features" / "common" / "skills" / "task" / "extensions" / "hermes" / "extension.md"
    notes = []
    if not ext_md.exists():
        notes.append("extension.md not found; hermes task extension not embedded")

    if not src.exists():
        return {"applied": False, "files": [],
                "notes": "hermes_session_source.py not found"}

    dst = target_dir / "skills" / "task" / "scripts" / "hermes_session_source.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    notes.append(
        "Installed hermes session source into .ai-badger/skills/task/scripts/ as "
        "hermes_session_source.py — the <agent>_session_source.py name tracker_lib.py discovers")
    return {"applied": True, "files": [SESSION_SOURCE_DEST], "notes": " ".join(notes)}
