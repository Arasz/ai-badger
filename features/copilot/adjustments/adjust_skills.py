"""Adjustment: symlink ai-badger skills into .github/skills/ for Copilot CLI.

Copilot discovers skills from .github/skills/*/SKILL.md. This adjustment
symlinks each scaffolded skill into the Copilot discovery path.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Symlink skills for Copilot CLI discovery.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
            'skills': list[str],
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    if "copilot" not in context.get("config", {}).get("agents", []):
        return {"applied": False, "files": [], "notes": "copilot not in config.agents"}

    target_dir = context["target_dir"]
    target = context["target"]
    skills = context.get("skills", [])

    github_skills = target / ".github" / "skills"
    github_skills.mkdir(parents=True, exist_ok=True)

    linked = []
    for skill_name in skills:
        src = target_dir / "skills" / skill_name
        if not src.is_dir():
            continue

        # Check if skill has SKILL.md (required for Copilot discovery)
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            continue

        dst = github_skills / skill_name
        # Remove stale symlink or directory
        if dst.is_symlink():
            dst.unlink()
        elif dst.is_dir():
            import shutil
            shutil.rmtree(dst)

        dst.symlink_to(os.path.relpath(src, dst.parent))
        linked.append(skill_name)

    if linked:
        return {
            "applied": True,
            "files": [f".github/skills/{name}" for name in linked],
            "notes": f"Symlinked {len(linked)} skill(s) into .github/skills/",
        }
    return {"applied": False, "files": [], "notes": "No skills with SKILL.md found"}
