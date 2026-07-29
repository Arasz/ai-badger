"""Adjustment: symlink ai-badger skills into .junie/skills/ for JetBrains Junie.

Junie discovers project-scope skills from <projectRoot>/.junie/skills/<name>/SKILL.md
(project wins over the user-scope ~/.junie/skills/, which ai-badger does not manage). This
adjustment symlinks each scaffolded skill into the project discovery path.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Symlink skills for Junie project-scope discovery.

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
    if "junie" not in context.get("config", {}).get("agents", []):
        return {"applied": False, "files": [], "notes": "junie not in config.agents"}

    target_dir = context["target_dir"]
    target = context["target"]
    skills = context.get("skills", [])

    junie_skills = target / ".junie" / "skills"
    junie_skills.mkdir(parents=True, exist_ok=True)

    skills_root = target_dir / "skills"
    owned_targets = _manifest_targets(target_dir)

    linked, refused = [], []
    for skill_name in skills:
        src = skills_root / skill_name
        if not src.is_dir():
            continue

        # Required for Junie discovery — "a folder without it is not recognized as a skill."
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            continue

        dst = junie_skills / skill_name
        if dst.exists() or dst.is_symlink():
            if not _ours(dst, skills_root, owned_targets):
                refused.append(skill_name)
                continue
            _remove(dst)

        dst.symlink_to(os.path.relpath(src, dst.parent))
        linked.append(skill_name)

    pruned = _prune(junie_skills, skills, skills_root, owned_targets)
    left = _owned_entries(junie_skills, skills_root, owned_targets) if not skills else []

    notes = []
    if linked:
        notes.append(f"Symlinked {len(linked)} skill(s) into .junie/skills/")
    if pruned:
        notes.append(
            f"removed {', '.join('.junie/skills/' + n for n in pruned)} — no longer "
            f"delivered to this project"
        )
    if left:
        notes.append(
            f"skills is empty — left {len(left)} link(s) untouched "
            f"({', '.join('.junie/skills/' + n for n in left)}); to stop delivering a "
            f"skill use config.exclude.skills instead"
        )
    if refused:
        notes.append(
            f"left {', '.join(sorted(refused))} in .junie/skills/ untouched — not placed by "
            f"ai-badger; remove by hand to let Junie discover the scaffolded skill"
        )
    return {
        "applied": bool(linked or pruned),
        "files": [f".junie/skills/{name}" for name in linked],
        "notes": "; ".join(notes) or "No skills with SKILL.md found",
    }


def _owned_entries(discovery_dir: Path, skills_root: Path, owned_targets: set) -> list:
    """Names of entries in `discovery_dir` that ai-badger placed."""
    return [e.name for e in sorted(discovery_dir.iterdir())
            if _ours(e, skills_root, owned_targets)]


def _prune(discovery_dir: Path, skills, skills_root: Path, owned_targets: set) -> list:
    """Remove links ai-badger placed for skills it no longer delivers, and only those.

    A skill the project declined, or one deleted upstream, otherwise leaves a symlink to
    nothing; ownership is the same test the link path applies before replacing anything.
    An empty `skills` is not evidence the project stopped wanting them — only
    `config.exclude.skills` is (#129) — so an empty list prunes nothing owned.
    """
    if not skills:
        return []
    pruned = []
    for entry in sorted(discovery_dir.iterdir()):
        if entry.name in skills or not _ours(entry, skills_root, owned_targets):
            continue
        _remove(entry)
        pruned.append(entry.name)
    return pruned


def _manifest_targets(target_dir: Path) -> set:
    """Targets recorded in .ai-badger/manifest.json — paths ai-badger placed."""
    manifest = target_dir / "manifest.json"
    if not manifest.is_file():
        return set()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(entry.get("target", "")) for entry in data.get("entries", [])}


def _ours(dst: Path, skills_root: Path, owned_targets: set) -> bool:
    """True only for a destination ai-badger placed: our symlink, or a recorded target.

    Everything else — a hand-authored directory, a plain file, a symlink pointing
    elsewhere — belongs to the user. `.junie/skills/` is Junie's own convention, so a
    collision there is expected rather than exceptional.
    """
    if f".junie/skills/{dst.name}" in owned_targets:
        return True
    if not dst.is_symlink():
        return False
    try:
        dst.resolve().relative_to(skills_root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _remove(dst: Path) -> None:
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    else:
        shutil.rmtree(dst)
