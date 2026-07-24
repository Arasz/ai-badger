"""Adjustment: embed Hermes delegation model into task skill.

Reads the Hermes task extension (extension.md) and appends its content
to the task skill during scaffold, so the scaffolded skill contains
Hermes-specific delegation patterns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Embed Hermes delegation model into task skill.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,
            'target_dir': Path,
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    framework_root = context["framework_root"]
    ext_md = framework_root / "features" / "hermes" / "skills" / "task-extensions" / "hermes" / "extension.md"

    if not ext_md.exists():
        return {"applied": False, "files": [], "notes": "extension.md not found"}

    # The extension.md content is appended to the task skill during scaffold
    # by scaffold.py's extension embedding logic. This adjustment ensures
    # the extension is recognized as active.
    return {"applied": True, "files": [str(ext_md)],
            "notes": "Hermes task extension.md registered for embedding"}
