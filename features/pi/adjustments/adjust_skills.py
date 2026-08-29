"""Adjustment: merge this project's .ai-badger/skills/ path into pi's settings skills array.

pi does not read `.claude/skills/`; its own discovery paths are `~/.pi/agent/skills/`,
`~/.agents/skills/`, project `.pi/skills/` / `.agents/skills/` (both trust-gated), package
`skills/` directories, the settings `skills` array, and `--skill <path>`. ai-badger delivers
skills to `.ai-badger/skills/`, which is none of those — without this adjustment pi gets no
skills at all. The settings `skills` array is the one route that is not trust-gated, so it is
what makes this project's skills load headless too; merging this project's absolute
`.ai-badger/skills/` path into it via the shared `pi_settings` helper is the fix.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pi_settings  # pylint: disable=wrong-import-position


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the project's .ai-badger/skills/ path into ~/.pi/agent/settings.json.

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

    if not context.get("install", True):
        return {
            "applied": False, "files": [],
            "notes": f"skills path not merged into {pi_settings.SETTINGS_PATH} (--no-install)",
        }

    skills_dir = str(context["target_dir"] / "skills")
    settings = pi_settings.load_settings(pi_settings.SETTINGS_PATH)
    settings = pi_settings.merge_skills_path(settings, skills_dir)
    pi_settings.write_settings(pi_settings.SETTINGS_PATH, settings)

    return {
        "applied": True,
        "files": [],
        "notes": f"Merged {skills_dir} into {pi_settings.SETTINGS_PATH}'s skills array",
    }
