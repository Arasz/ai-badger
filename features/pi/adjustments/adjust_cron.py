"""Adjustment: install the pi cron extension during scaffold.

The cron extension lives at ~/.pi/agent/extensions/pi-cron/ and provides
Bun.cron() based scheduling with launchd fallback on macOS. A job is scheduled
unless it explicitly sets noAgent: false — that is the rule cron/index.ts
implements, not a bare truthiness check on the noAgent field.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

CRON_EXT_NAME = "pi-cron"
USER_EXTENSIONS_DIR = Path.home() / ".pi" / "agent" / "extensions" / CRON_EXT_NAME


def _install_user_extension(cron_dir: Path, install: bool) -> Tuple[list[str], Optional[str]]:
    """Copy the cron extension to ~/.pi/agent/extensions/pi-cron/.

    Returns (installed_filenames, error_note). install=False is a documented no-op — this is
    user-global state, deliberately left untouched — and returns ([], None), not an error. A
    missing cron_dir under install=True is reported as an ERROR note naming the path: the
    prior silent `[]` return let a missing extension (and its missing run-job.ts, F2a) ship
    with a generic, path-free "not found or empty" note.
    """
    if not install:
        return [], None

    if not cron_dir.is_dir():
        return [], f"ERROR: pi cron extension directory not found: {cron_dir}"

    USER_EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []

    for item in cron_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, USER_EXTENSIONS_DIR / item.name)
            installed.append(item.name)

    return installed, None


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
    install = context.get("install", True)

    installed, install_error = _install_user_extension(cron_dir, install)

    notes = []
    if install_error:
        notes.append(install_error)
    if installed:
        notes.append(
            f"Installed pi cron extension into {USER_EXTENSIONS_DIR}: {', '.join(installed)}")

    if not notes:
        notes.append("Cron extension not installed (--no-install)" if not install
                      else "Cron extension directory not found or empty")

    return {"applied": bool(installed), "files": [], "notes": "; ".join(notes)}
