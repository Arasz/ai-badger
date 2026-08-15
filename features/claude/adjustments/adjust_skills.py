"""Adjustment: symlink ai-badger skills into .claude/skills/ for Claude Code.

Claude Code discovers skills from .claude/skills/*/SKILL.md. This adjustment
symlinks each scaffolded skill into the Claude Code discovery path.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Symlink skills for Claude Code discovery.

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
    if "claude" not in context.get("config", {}).get("agents", []):
        return {"applied": False, "files": [], "notes": "claude not in config.agents"}

    target_dir = context["target_dir"]
    target = context["target"]
    skills = context.get("skills", [])

    claude_skills = target / ".claude" / "skills"
    claude_skills.mkdir(parents=True, exist_ok=True)

    skills_root = target_dir / "skills"
    owned_targets = _manifest_targets(target_dir)

    linked, refused = [], []
    for skill_name in skills:
        src = skills_root / skill_name
        if not src.is_dir():
            continue

        # Check if skill has SKILL.md (required for Claude Code discovery)
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            continue

        dst = claude_skills / skill_name
        if dst.exists() or dst.is_symlink():
            if not _ours(dst, skills_root, owned_targets):
                refused.append(skill_name)
                continue
            _remove(dst)

        dst.symlink_to(os.path.relpath(src, dst.parent))
        linked.append(skill_name)

    # `prune` is the scaffolder saying whether `skills` is evidence of what this project
    # wants. A run that could not read the manifest still delivers its stacks' skills, so a
    # non-empty list is not proof on its own — see Scaffolder.prune_discovery (#129).
    may_prune = context.get("prune", True) and bool(skills)
    pruned = _prune(claude_skills, skills, skills_root, owned_targets) if may_prune else []
    left = [] if may_prune else _owned_entries(claude_skills, skills_root, owned_targets)

    notes = []
    if linked:
        notes.append(f"Symlinked {len(linked)} skill(s) into .claude/skills/")
    if pruned:
        notes.append(
            f"removed {', '.join('.claude/skills/' + n for n in pruned)} — no longer "
            f"delivered to this project"
        )
    if left:
        notes.append(
            f"this run cannot vouch for the delivered list — left {len(left)} link(s) untouched "
            f"({', '.join('.claude/skills/' + n for n in left)}); to stop delivering a "
            f"skill use config.exclude.skills instead"
        )
    if refused:
        shadowed = ", ".join(f".claude/skills/{name}" for name in sorted(refused))
        notes.append(
            f"left {shadowed} untouched — not placed by ai-badger, so it shadows the "
            f"managed skill and will not follow releases; remove by hand to let Claude "
            f"Code discover the scaffolded skill"
        )
    return {
        "applied": bool(linked or pruned),
        "files": [f".claude/skills/{name}" for name in linked],
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

    Everything else — a hand-committed skill directory, a plain file, a symlink pointing
    elsewhere — belongs to the user. `.claude/skills/` is Claude Code's own convention and
    routinely holds third-party skills, so a collision there is expected, not exceptional.
    """
    if f".claude/skills/{dst.name}" in owned_targets:
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
