"""Adjustment: install pi extension hooks during scaffold.

pi loads extensions from ~/.pi/agent/extensions/ (user scope) as TypeScript
modules. Unlike Hermes plugins, pi extensions are single-file .ts modules loaded
by jiti (no plugin.yaml, no __init__.py). The ai-badger hooks are Python scripts
that pi cannot run directly — they need a TypeScript adapter that shells out to
python3.

This adjustment ships the TypeScript adapter extension and the Python hook scripts
it delegates to. The adapter translates pi event shapes to Claude-shaped JSON
that the existing Python hooks expect, and maps their JSON responses back to pi's
return format.

Extension structure:
  ~/.pi/agent/extensions/ai-badger/
    adapter.ts        # main entry, event translation + shell-out
    package.json      # declares adapter.ts as pi extension
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

ADAPTER_DIR = "adapter"
USER_EXTENSIONS_DIR = Path.home() / ".pi" / "agent" / "extensions" / "ai-badger"


def _framework_version(framework_root: Path) -> str:
    try:
        return (framework_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _install_user_extension(framework_root: Path, adapter_dir: Path, install: bool) -> list[str]:
    """Copy the pi extension adapter to ~/.pi/agent/extensions/ai-badger/.

    A no-op under --no-install: this is user-global state.
    """
    if not install:
        return []

    if not adapter_dir.is_dir():
        return []

    USER_EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []

    for item in adapter_dir.iterdir():
        if item.is_file() and item.suffix in (".ts", ".json"):
            shutil.copy2(item, USER_EXTENSIONS_DIR / item.name)
            installed.append(item.name)

    return installed


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install pi extension hooks.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/pi/adjustments/
            'target_dir': Path,     # .ai-badger/
            'install': bool,        # False under --no-install
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "pi" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "pi not in config.agents"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    adapter_dir = context["feature_dir"] / ADAPTER_DIR

    # Copy hook scripts into .ai-badger/hooks/ for the project
    hooks_dir = framework_root / "features" / "common" / "hooks"
    files = []
    hook_scripts = [
        "ai_badger_hooks.py",
        "mcp_index_hook.py",
        "debug_log.py",
        "grounded_feedback.py",
        "hermes_isolation.py",
    ]
    for hook_file in hook_scripts:
        src = hooks_dir / hook_file
        if src.exists():
            dst = target_dir / "hooks" / hook_file
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target_dir.parent)))

    # Install user-scope extension
    installed = _install_user_extension(framework_root, adapter_dir,
                                        context.get("install", True))

    notes = []
    if files:
        notes.append(f"Installed {len(files)} hook script(s) into .ai-badger/hooks/")
    if installed:
        notes.append(
            f"Installed pi extension adapter into {USER_EXTENSIONS_DIR}: "
            + ", ".join(installed)
        )
    if not notes:
        return {"applied": False, "files": [], "notes": "No hook files found"}

    return {"applied": True, "files": files, "notes": "; ".join(notes)}