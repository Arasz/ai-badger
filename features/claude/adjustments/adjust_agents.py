"""Adjustment: deliver ai-badger personas to .claude/agents/ as Claude Code subagents.

Claude Code loads subagents from `.claude/agents/*.md`, whose frontmatter must start at line
1. Each scaffolded persona is re-emitted with only the keys Claude documents (ADR-0014, #190).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter as fm

# The keys Claude Code reads from a subagent file, in its own documented order. An allowlist:
# a persona key Claude does not understand must not leak into a file it parses.
CLAUDE_KEYS = ("name", "description", "tools", "disallowedTools", "model")

MANAGED_HEADER = (
    "<!-- Managed by ai-badger. Source of truth: .ai-badger/agents/{name}. "
    "Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->"
)
# The stable leading text every delivered file carries (the part before the {name} slot).
_MANAGED_PREFIX = MANAGED_HEADER.split("{name}", 1)[0]


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Write one Claude subagent file per scaffolded persona.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    if "claude" not in context.get("config", {}).get("agents", []):
        return {"applied": False, "files": [], "notes": "claude not in config.agents"}

    target_dir, target = context["target_dir"], context["target"]
    sources = sorted((target_dir / "agents").glob("*.md"))
    if not sources:
        return {"applied": False, "files": [], "notes": "no personas in .ai-badger/agents/"}

    owned = _manifest_targets(target_dir)
    dest_dir = target / ".claude" / "agents"
    dest_dir.mkdir(parents=True, exist_ok=True)

    written, refused, unparsed = [], [], []
    for src in sources:
        rel = f".claude/agents/{src.name}"
        dst = dest_dir / src.name
        if dst.exists() and not _ours(dst, rel, owned):
            refused.append(rel)
            continue
        rendered = render(src.read_text(encoding="utf-8"), src.name)
        if rendered is None:
            unparsed.append(src.name)
            continue
        dst.write_text(rendered, encoding="utf-8")
        written.append(rel)

    return {
        "applied": bool(written),
        "files": written,
        "notes": _notes(written, refused, unparsed),
    }


def render(text: str, source_name: str) -> Optional[str]:
    """Turn one persona file into a Claude subagent definition, or None if it has no frontmatter.

    The persona's own `---` block is stripped and replaced, never stacked under a second one;
    the managed header goes on the first *body* line, because frontmatter must start at line 1.
    """
    split = fm.split(text)
    if not split.present:
        return None
    keep = {entry.key: entry for entry in split.entries}
    if "name" not in keep or "description" not in keep:
        return None
    out = ["---\n"]
    for key in CLAUDE_KEYS:
        if key in keep:
            out.extend(keep[key].lines)
    out += ["---\n", "\n", MANAGED_HEADER.format(name=source_name) + "\n", "\n"]
    return "".join(out) + split.body.lstrip("\n")


def _manifest_targets(target_dir: Path) -> set:
    """Targets recorded in .ai-badger/manifest.json — paths ai-badger placed.

    Adjustments run before the manifest is rewritten, so this is the previous run's record.
    """
    manifest = target_dir / "manifest.json"
    if not manifest.is_file():
        return set()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(entry.get("target", "")) for entry in data.get("entries", [])}


def _ours(dst: Path, rel: str, owned_targets: set) -> bool:
    """True only for a file ai-badger placed: recorded in the manifest, or carrying its header.

    Everything else in `.claude/agents/` belongs to the user — Claude Code's own convention
    routinely holds hand-written and third-party subagents, so a collision there is expected.
    """
    if rel in owned_targets:
        return True
    try:
        return _MANAGED_PREFIX in dst.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False


def _notes(written: List[str], refused: List[str], unparsed: List[str]) -> str:
    """One line per outcome: what was delivered, what was left alone, what could not be read."""
    notes = []
    if written:
        notes.append(f"Delivered {len(written)} persona(s) to .claude/agents/")
    if refused:
        notes.append(
            f"left {', '.join(sorted(refused))} untouched — not placed by ai-badger, so it "
            f"shadows the managed persona and will not follow releases; remove by hand, or "
            f"decline the persona with config.exclude.personas"
        )
    if unparsed:
        notes.append(
            f"skipped {', '.join(sorted(unparsed))} — no name/description frontmatter to "
            f"build a subagent definition from"
        )
    return "; ".join(notes) or "no personas delivered"
