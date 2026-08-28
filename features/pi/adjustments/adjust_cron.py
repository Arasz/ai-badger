"""Adjustment: install the pi cron extension during scaffold.

The cron extension lives at ~/.pi/agent/extensions/pi-cron/ and provides
Bun.cron() based scheduling with launchd fallback on macOS. All cron jobs
run with no_agent=true by default.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

CRON_EXT_NAME = "pi-cron"
USER_EXTENSIONS_DIR = Path.home() / ".pi" / "agent" / "extensions" / CRON_EXT_NAME


def _install_user_extension(cron_dir: Path, install: bool) -> list[str]:
    """Copy the cron extension to ~/.pi/agent/extensions/pi-cron/.

    A no-op under --no-install: this is user-global state.
    """
    if not install or not cron_dir.is_dir():
        return []

    USER_EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []

    for item in cron_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, USER_EXTENSIONS_DIR / item.name)
            installed.append(item.name)

    return installed


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install the pi cron extension.

    Args:
        context: {
            'config': dict,
            'feature_dir': Path,    # features/pi/adjustments/
            'install': bool,        # False under --no-install
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "pi" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "pi not in config.agents"}

    feature_dir = context["feature_dir"]
    cron_dir = feature_dir.parent / "cron"

    installed = _install_user_extension(cron_dir, context.get("install", True))

    if not installed:
        return {"applied": False, "files": [], "notes": "Cron extension directory not found or empty"}

    return {
        "applied": True,
        "files": [],
        "notes": f"Installed pi cron extension into {USER_EXTENSIONS_DIR}: {', '.join(installed)}",
    }