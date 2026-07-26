"""Adjustment: install Hermes plugin hooks during scaffold.

Copies the framework hook modules into the project's .ai-badger/hooks/ and — because
Hermes loads plugins only from ~/.hermes/plugins/ — into that user-scope directory too.
Rationale: docs/research/hermes-learned-skills-sync.md correction C5.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

PROJECT_HOOKS = ("ai_badger_hooks.py", "mcp_index_hook.py")
USER_PLUGINS = ("ai_badger_hooks.py", "learned_skills_sync.py")


def _install_user_plugins(hooks_dir: Path) -> List[str]:
    """Copy (and refresh) the Hermes plugin modules into ~/.hermes/plugins/."""
    plugins_dir = Path.home() / ".hermes" / "plugins"
    installed: List[str] = []
    for name in USER_PLUGINS:
        src = hooks_dir / name
        if not src.is_file():
            continue
        plugins_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugins_dir / name)
        installed.append(name)
    return installed


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install Hermes plugin hooks.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/hermes/adjustments/
            'target_dir': Path,     # .ai-badger/
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "hermes" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "hermes not in config.agents"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    hooks_dir = framework_root / "features" / "common" / "hooks"

    files = []
    for hook_file in PROJECT_HOOKS:
        src = hooks_dir / hook_file
        if src.exists():
            dst = target_dir / "hooks" / hook_file
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target_dir.parent)))

    # User-scope copies are deliberately absent from 'files': the scaffolder records every
    # returned file relative to the project target, which a home path cannot be.
    installed = _install_user_plugins(hooks_dir)

    notes = []
    if files:
        notes.append(f"Installed {len(files)} Hermes plugin hooks")
    if installed:
        notes.append("installed into ~/.hermes/plugins: " + ", ".join(installed))
    if not notes:
        return {"applied": False, "files": [], "notes": "No hook files found"}
    return {"applied": True, "files": files, "notes": "; ".join(notes)}
