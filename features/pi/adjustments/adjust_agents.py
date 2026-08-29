"""Adjustment: deliver ai-badger personas to `<project>/.pi/agents/*.md` for pi.

pi core has no custom-agent feature of its own; agent files are read by a subagent extension.
ai-badger ships its own (`features/pi/subagent/`, installed user-scope by this same arm),
which reads this directory itself through `fs` — so the personas load in headless `pi -p` runs even
with no project-trust decision saved. The filename is a plain `*.md` because that is what the
discovery test matches (`entry.name.endsWith(".md")`); `.agent.md` is copilot's convention and
would name the persona `architect.agent`.

The arm has two halves. The project half writes `.pi/agents/` and — unlike adjust_skills and
adjust_cron — is NOT a no-op under `--no-install`, because it is project state. The user half
installs the reader itself into `~/.pi/agent/extensions/ai-badger-subagent/`, which is
user-global state and therefore is the documented `--no-install` no-op. Persona files without
that reader would be inert: pi core has no custom-agent feature of its own.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter as fm

# The two keys a pi agent reader requires, in the order it documents them. An allowlist, and a
# deliberately narrow one: `model` and `tools` become `--model` / `--tools` arguments on the
# delegated `pi -p` process, and a persona's values for them are Claude's vocabulary (`opus`,
# `Read`) which pi would reject. Dropping them lets each delegation inherit the session's own
# model and tool set, which is the behaviour ai-badger's delegation map actually asks for.
PI_KEYS = ("name", "description")

AGENTS_SUBDIR = Path(".pi") / "agents"

SUBAGENT_DIR = "subagent"
USER_EXTENSIONS_DIR = Path.home() / ".pi" / "agent" / "extensions" / "ai-badger-subagent"

MANAGED_HEADER = (
    "<!-- Managed by ai-badger. Source of truth: .ai-badger/agents/{name}. "
    "Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->"
)
# The stable leading text every delivered file carries (the part before the {name} slot).
_MANAGED_PREFIX = MANAGED_HEADER.split("{name}", 1)[0]


def _install_subagent_extension(
        subagent_dir: Path, install: bool) -> Tuple[List[str], Optional[str]]:
    """Copy the subagent extension to ~/.pi/agent/extensions/ai-badger-subagent/.

    Returns (installed_filenames, error_note). install=False is a documented no-op — this is
    user-global state, deliberately left untouched — and returns ([], None), not an error. A
    missing subagent_dir under install=True is an ERROR note naming the path, the same rule
    adjust_hooks and adjust_cron follow: an uninstalled reader leaves every delivered persona
    file inert, and a silent `[]` return is exactly how that ships unnoticed.
    """
    if not install:
        return [], None

    if not subagent_dir.is_dir():
        return [], f"ERROR: pi subagent extension directory not found: {subagent_dir}"

    USER_EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    installed: List[str] = []
    for item in sorted(subagent_dir.iterdir()):
        if item.is_file():
            shutil.copy2(item, USER_EXTENSIONS_DIR / item.name)
            installed.append(item.name)
    return installed, None


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Write one pi agent file per scaffolded persona, and install the extension that reads them.

    Args:
        context: {
            'config': dict,
            'feature_dir': Path,    # features/pi/adjustments/
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
            'install': bool,        # False under --no-install
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "pi" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "pi not in config.agents"}

    target_dir, target = context["target_dir"], context["target"]
    source_dir = target_dir / "agents"
    if not source_dir.is_dir():
        return {"applied": False, "files": [],
                "notes": f"ERROR: persona source directory not found: {source_dir}"}

    sources = sorted(source_dir.glob("*.md"))
    if not sources:
        return {"applied": False, "files": [], "notes": f"no personas in {source_dir}"}

    owned = _manifest_targets(target_dir)
    dest_dir = target / AGENTS_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    written, refused, unparsed = [], [], []
    for src in sources:
        rel = f"{AGENTS_SUBDIR.as_posix()}/{src.name}"
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

    installed, install_error = _install_subagent_extension(
        context["feature_dir"].parent / SUBAGENT_DIR, context.get("install", True))

    return {
        "applied": bool(written or installed),
        "files": written,
        "notes": _notes(written, refused, unparsed, installed, install_error),
    }


def render(text: str, source_name: str) -> Optional[str]:
    """Turn one persona file into a pi agent definition, or None when it has no frontmatter.

    The persona's own `---` block is replaced rather than stacked under a second one, and the
    managed header goes on the first *body* line so the frontmatter still starts at line 1.
    The body below it is what the delegated process gets as its system prompt.
    """
    split = fm.split(text)
    if not split.present:
        return None
    keep = {entry.key: entry for entry in split.entries}
    if "name" not in keep or "description" not in keep:
        return None
    out = ["---\n"]
    for key in PI_KEYS:
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

    Everything else in `.pi/agents/` belongs to the user — the directory is pi's own convention
    and routinely holds hand-written agents, so a collision there is expected, not a fault.
    """
    if rel in owned_targets:
        return True
    try:
        return _MANAGED_PREFIX in dst.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False


def _notes(written: List[str], refused: List[str], unparsed: List[str],
           installed: List[str], install_error: Optional[str]) -> str:
    """One line per outcome: what was delivered, what was left alone, what could not be read."""
    notes = []
    if install_error:
        notes.append(install_error)
    if installed:
        notes.append(
            f"installed the subagent extension into {USER_EXTENSIONS_DIR}: "
            f"{', '.join(installed)}")
    if written:
        notes.append(f"Delivered {len(written)} persona(s) to {AGENTS_SUBDIR.as_posix()}/")
    if refused:
        notes.append(
            f"left {', '.join(sorted(refused))} untouched — not placed by ai-badger, so it "
            f"shadows the managed persona and will not follow releases; remove by hand, or "
            f"decline the persona with config.exclude.personas"
        )
    if unparsed:
        notes.append(
            f"skipped {', '.join(sorted(unparsed))} — no name/description frontmatter to "
            f"build a pi agent definition from"
        )
    return "; ".join(notes) or "no personas delivered"
