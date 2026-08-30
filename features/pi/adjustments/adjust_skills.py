"""Adjustment: migration-only removal of this project's skills path from pi's settings.json.

pi does not read `.claude/skills/`; its own discovery paths are `~/.pi/agent/skills/`,
`~/.agents/skills/`, project `.pi/skills/` / `.agents/skills/` (both trust-gated), package
`skills/` directories, the settings `skills` array, and `--skill <path>`. The installed
ai-badger adapter contributes `<project>/.ai-badger/skills/` itself via its ungated
`resources_discover` handler (plan M4/ADR-0023), so the settings `skills` array entry this
scaffold once merged in is legacy state: a re-scaffold removes it and touches nothing else.

Per-extension version gate (plan M5, R8+R9): removal runs only when the installed adapter —
~/.pi/agent/extensions/ai-badger/ — carries the resources_discover capability marker
(.ai-badger-capability-resources-discover). An adapter without it cannot contribute the
project skills path, so removing the settings entry would leave the project with NO skills at
all — skip-with-warning instead. The gate is deliberately per-extension: a project-scope-capable
pi-mcp-tools fork says nothing about the adapter's skills capability, and vice versa.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pi_settings  # pylint: disable=wrong-import-position

ADAPTER_DIR = Path.home() / ".pi" / "agent" / "extensions" / "ai-badger"
CAPABILITY_MARKER = ADAPTER_DIR / ".ai-badger-capability-resources-discover"

GATE_WARNING = (
    "The installed ai-badger adapter at {dir} predates the resources_discover skills "
    "contribution (capability marker .ai-badger-capability-resources-discover missing), so "
    "the settings.json skills array is still the only route this project's skills load "
    "through — the entry was left in place. Re-run after updating the adapter to migrate it "
    "off the global key."
)
REMOVED_NOTE = (
    "Removed {path} from {settings}'s skills array: the installed adapter contributes the "
    "project skills path itself via resources_discover, so the global entry is legacy "
    "scaffold state."
)
NOT_PRESENT_NOTE = (
    "{path}: not present in {settings}'s skills array — nothing to remove."
)


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Remove this project's .ai-badger/skills/ path from ~/.pi/agent/settings.json.

    Args:
        context: {
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'install': bool,        # False under --no-install
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "pi" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "pi not in config.agents"}

    skills_dir = str(context["target_dir"] / "skills")

    if not context.get("install", True):
        return {
            "applied": False, "files": [],
            "notes": (f"--no-install: nothing written. A subsequent install run would remove "
                      f"{skills_dir} from {pi_settings.SETTINGS_PATH}'s skills array "
                      f"(removal proposal only)"),
        }

    if not CAPABILITY_MARKER.exists():
        return {
            "applied": False, "files": [],
            "notes": GATE_WARNING.format(dir=ADAPTER_DIR),
        }

    settings = pi_settings.load_settings(pi_settings.SETTINGS_PATH)
    settings, removed = pi_settings.remove_skills_path(settings, skills_dir)
    if removed:
        pi_settings.write_settings(pi_settings.SETTINGS_PATH, settings)
        notes = REMOVED_NOTE.format(path=skills_dir, settings=pi_settings.SETTINGS_PATH)
    else:
        notes = NOT_PRESENT_NOTE.format(path=skills_dir, settings=pi_settings.SETTINGS_PATH)

    return {
        "applied": True,
        "files": [],
        "notes": notes,
    }
