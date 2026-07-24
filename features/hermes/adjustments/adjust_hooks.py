"""Adjustment: install Hermes plugin hooks during scaffold.

Copies ai_badger_hooks.py and mcp_index_hook.py from features/common/hooks/
to the scaffolded project's plugin directory for Hermes auto-discovery.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install Hermes plugin hooks.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/common/hooks/
            'target_dir': Path,     # .ai-badger/
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    hooks_dir = framework_root / "features" / "common" / "hooks"

    files = []
    for hook_file in ("ai_badger_hooks.py", "mcp_index_hook.py"):
        src = hooks_dir / hook_file
        if src.exists():
            dst = target_dir / "hooks" / hook_file
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target_dir.parent)))

    if files:
        return {"applied": True, "files": files,
                "notes": f"Installed {len(files)} Hermes plugin hooks"}
    return {"applied": False, "files": [], "notes": "No hook files found"}
