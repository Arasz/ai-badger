"""Adjustment: map ai-badger personas to Copilot custom agents.

Copilot discovers custom agents from .github/agents/*.agent.md with YAML
frontmatter. This adjustment converts the configured stacks' personas into
Copilot custom agent format (issue #210).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import frontmatter as fm


# Copilot's own documented custom-agent tool aliases; any other name is one its frontmatter
# parser will not recognise.
COPILOT_TOOL_ALIASES = frozenset({"read", "edit", "search", "execute", "agent", "web", "todo"})

# Deliberate Copilot-specific overrides; they win over a persona's own frontmatter. Reviewer and
# architect stay read-only; test-engineer is the one persona that also gets edit and execute (D7).
PERSONA_MAP = {
    "architect": {
        "description": "System architecture and design decisions. Reviews patterns, evaluates trade-offs, and proposes structural improvements.",
        "tools": ["read", "search"],
        "user-invocable": True,
    },
    "code-reviewer": {
        "description": "Code review with focus on quality, security, and maintainability. Reviews diffs, identifies issues, and suggests improvements.",
        "tools": ["read", "search"],
        "user-invocable": True,
    },
    "test-engineer": {
        "description": "Test strategy and implementation. Writes failing tests first, implements to pass, and ensures coverage.",
        "tools": ["read", "search", "edit", "execute"],
        "user-invocable": True,
    },
}

AGENTS_SUBDIR = Path(".github") / "agents"

MANAGED_HEADER = (
    "<!-- Managed by ai-badger. Source of truth: .ai-badger/agents/{name}. "
    "Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->"
)
# The stable leading text every delivered file carries (the part before the {name} slot).
_MANAGED_PREFIX = MANAGED_HEADER.split("{name}", 1)[0]


def _split_frontmatter(yaml_mod, text: str) -> Tuple[Dict[str, Any], str]:
    """Split a leading `---` YAML block off `text`; ({}, text) when there is none.

    The fence is the shared extractor's call; only the typed values are pyyaml's, because
    `tools` has to come back as a list rather than a string this module would re-split.
    """
    split = fm.split(text)
    if not split.present:
        return {}, text
    try:
        data = yaml_mod.safe_load(split.raw)
    except yaml_mod.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), split.body.lstrip("\n")


def _tool_list(value: Any) -> List[str]:
    """Normalize a frontmatter `tools` value — YAML often carries it as one comma string."""
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, list):
        return [str(t) for t in value]
    return []


def _merged_frontmatter(name: str, source_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Defaults < the persona's own frontmatter < the Copilot-specific PERSONA_MAP.

    An allowlist: `model` is deliberately dropped — Copilot picks its own model and would
    not recognise a Claude alias like `sonnet`.
    """
    merged: Dict[str, Any] = {
        "name": name,
        "description": f"AI agent persona: {name}",
        "tools": ["read", "search"],
        "user-invocable": True,
    }
    if isinstance(source_meta.get("name"), str):
        merged["name"] = source_meta["name"].strip()
    if isinstance(source_meta.get("description"), str):
        merged["description"] = source_meta["description"].strip()
    if _tool_list(source_meta.get("tools")):
        merged["tools"] = _tool_list(source_meta.get("tools"))
    merged.update(PERSONA_MAP.get(name, {}))
    return merged


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

    Everything else in `.github/agents/` belongs to the user — Copilot's own convention
    routinely holds hand-written and third-party custom agents, so a collision there is
    expected, not a fault (L7-6).
    """
    if rel in owned_targets:
        return True
    try:
        return _MANAGED_PREFIX in dst.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False


def _prune_stale(target: Path, target_dir: Path, keep: List[str]) -> List[str]:
    """Delete `.github/agents/` files the prior manifest attributes to this adjuster.

    `prune_superseded` never reaches these: their manifest entries carry feature
    `adjustments` under the still-configured `copilot` stack, so only the adjuster
    itself knows which of its own outputs this run no longer asks for (#210).
    """
    try:
        entries = json.loads((target_dir / "manifest.json")
                             .read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        return []
    removed = []
    for entry in entries:
        if entry.get("feature") != "adjustments" or entry.get("stack") != "copilot":
            continue
        rel = Path(entry.get("target", ""))
        if rel.parent != AGENTS_SUBDIR or rel.suffix != ".md" or rel.name in keep:
            continue
        path = target / rel
        if path.is_file():
            path.unlink()
            removed.append(rel.as_posix())
    return removed


def _notes(created: List[str], refused: List[str], removed: List[str]) -> str:
    """One line per outcome: what was delivered, what was pruned, what was left alone."""
    notes = []
    if created:
        notes.append(f"Created {len(created)} Copilot custom agent(s) from personas")
    if removed:
        notes.append(f"removed {len(removed)} stale agent file(s): {', '.join(sorted(removed))}")
    if refused:
        notes.append(
            f"left {', '.join(sorted(refused))} untouched — not placed by ai-badger, so it "
            f"shadows the managed persona and will not follow releases; remove by hand, or "
            f"decline the persona with config.exclude.personas"
        )
    return "; ".join(notes) or "No persona files found to convert"


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the configured stacks' personas to Copilot custom agents.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
            'personas': list,       # index items the configured stacks deliver
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    if "copilot" not in context.get("config", {}).get("agents", []):
        return {"applied": False, "files": [], "notes": "copilot not in config.agents"}

    try:
        import yaml  # pylint: disable=import-outside-toplevel
    except ImportError:
        return {"applied": False, "files": [],
                "notes": "PyYAML not available — Copilot custom agents not generated; "
                         "pip install pyyaml (engine/requirements.txt)"}

    framework_root = context["framework_root"]
    target = context["target"]

    # Already filtered by the scaffolder to the configured stacks minus config.exclude:
    # re-deriving a set here is how the two hosts came to disagree (#210).
    personas = context.get("personas") or []
    if not personas:
        return {"applied": False, "files": [], "notes": "No personas configured"}

    agents_dir = target / AGENTS_SUBDIR
    agents_dir.mkdir(parents=True, exist_ok=True)
    owned = _manifest_targets(context["target_dir"])

    created: List[str] = []
    refused: List[str] = []
    for persona in personas:
        name = persona.get("name", "")
        persona_path = framework_root / persona.get("path", "")
        if not persona_path.exists():
            continue

        rel = f"{AGENTS_SUBDIR.as_posix()}/{name}.agent.md"
        agent_file = agents_dir / f"{name}.agent.md"
        if agent_file.exists() and not _ours(agent_file, rel, owned):
            refused.append(rel)
            continue

        source_meta, body = _split_frontmatter(yaml, persona_path.read_text(encoding="utf-8"))
        frontmatter = _merged_frontmatter(name, source_meta)
        yaml_header = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip()
        agent_file.write_text(
            f"---\n{yaml_header}\n---\n\n{MANAGED_HEADER.format(name=name)}\n\n{body.strip()}\n",
            encoding="utf-8")
        created.append(name)

    removed = _prune_stale(target, context["target_dir"],
                           [f"{name}.agent.md" for name in created])
    if not created and not removed:
        return {"applied": False, "files": [], "notes": _notes([], refused, [])}

    return {
        "applied": True,
        "files": [f".github/agents/{name}.agent.md" for name in created],
        "notes": _notes(created, refused, removed),
    }
