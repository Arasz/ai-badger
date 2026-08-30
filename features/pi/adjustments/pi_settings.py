"""Shared read/merge/remove/write helper for pi's user-global ~/.pi/agent/settings.json.

Used by adjust_skills.py (skills array) and adjust_mcp.py (mcp key). Both touch user-global
state rather than a project-scope `.pi/settings.json` for a measured reason: on this machine
`~/.pi/agent/trust.json` does not exist and `defaultProjectTrust` is unset (default "ask"), and
pi's own docs state that `-p`, `--mode json` and `--mode rpc` — the headless modes ai-badger's
scaffold and away-mode run under — ignore project resources entirely without a saved trust
decision. A project-scope write would silently do nothing in exactly the runs this exists for.

Since the pi stack gained project-scope reading (the pi-mcp-tools fork reads the project's
.mcp.json; the adapter contributes project skills via resources_discover), the global entries
are user-owned fallback, and the adjustments' job on re-scaffold is MIGRATION: remove what this
project's scaffold once wrote (shape-aware, marker-gated — see the adjusters). The removal
helpers below follow the same write contract as the merge helpers.

Write contract, all load-bearing:
  * ATOMIC — temp file in the same directory, then os.replace. A crashed scaffold must never
    leave a truncated settings.json; it is the user's real config, not scaffold-owned state.
  * IDEMPOTENT — merge functions add an entry once, removal functions remove an entry once,
    however many times they run.
  * UNKNOWN KEYS PRESERVED — the real file on this machine holds lastChangelogVersion and
    theme; anything not understood here is round-tripped, never dropped.
  * The file (and its parent directories) is created when absent, holding just the merged key.
"""
from __future__ import annotations

import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

SETTINGS_PATH = Path.home() / ".pi" / "agent" / "settings.json"


def load_settings(path: Path) -> Dict[str, Any]:
    """Read pi's settings.json, or {} when it does not exist yet."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_settings(path: Path, settings: Dict[str, Any]) -> None:
    """Write settings atomically: temp file in the same directory, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def merge_skills_path(settings: Dict[str, Any], skills_path: str) -> Dict[str, Any]:
    """Return settings with skills_path appended to the 'skills' array once."""
    merged = dict(settings)
    skills = list(merged.get("skills") or [])
    if skills_path not in skills:
        skills.append(skills_path)
    merged["skills"] = skills
    return merged


def merge_mcp_servers(settings: Dict[str, Any], servers: Dict[str, Any]) -> Dict[str, Any]:
    """Return settings with servers merged into the 'mcp' key, same-named entries overwritten."""
    merged = dict(settings)
    mcp = dict(merged.get("mcp") or {})
    mcp.update(servers)
    merged["mcp"] = mcp
    return merged


# --- removal (migration) ------------------------------------------------------------------

# The fields whose equality decides removability (plan M5/R10): the entry is regenerated from
# the declaration and compared field-for-field on exactly this set. A same-named entry that
# differs here is a user edit — warn-and-leave.
_MCP_SHAPE_FIELDS = ("enabled", "toolPrefix", "type", "url", "env", "cwd")


def _commands_match(existing: Any, generated: Any) -> bool:
    """True when `existing`'s command is the same command the scaffold would write today.

    Accepted shapes (plan M5/R10, tolerating the historical split→shlex drift c7d0d528):
      * literal equality — both the same list or the same string;
      * the existing entry stored the command as one string — shlex-split it (the shape
        _server_entry generates is already tokenized);
      * the historical drift: the entry was tokenized with str.split(), so a quoted argument
        landed as several tokens — re-joined with single spaces and re-split with shlex it is
        the same command. A user-changed argument list never reconstructs to the generated
        shape, so real edits still warn-and-leave.
    """
    if existing == generated:
        return True
    if not isinstance(generated, list):
        return False
    if isinstance(existing, str):
        try:
            return shlex.split(existing) == generated
        except ValueError:
            return False
    if isinstance(existing, list):
        try:
            return shlex.split(" ".join(existing)) == generated
        except ValueError:
            return False
    return False


def _mcp_entry_matches(existing: Any, generated: Dict[str, Any]) -> bool:
    """The concrete shape matcher: deep-equal on the shape fields, command shlex-or-literal."""
    if not isinstance(existing, dict):
        return False
    if any(existing.get(field) != generated.get(field) for field in _MCP_SHAPE_FIELDS):
        return False
    return _commands_match(existing.get("command"), generated.get("command"))


def remove_mcp_servers(settings: Dict[str, Any], removals: Dict[str, Any]
                       ) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Remove shape-matched entries from the 'mcp' key; report what was left alone.

    removals maps name → the entry the scaffold would generate today. A same-named global
    entry is removed only when it matches that shape (plan M5/R10); a drifted entry is a user
    edit and stays, reported as warned. Names absent from settings are ignored. Unknown keys
    are preserved; an 'mcp' key left empty by the removal is dropped entirely. The input dict
    is never mutated. Returns (new_settings, removed_names, warned_names).
    """
    merged = dict(settings)
    mcp = dict(merged.get("mcp") or {})
    removed: List[str] = []
    warned: List[str] = []
    for name in sorted(removals):
        if name not in mcp:
            continue
        if _mcp_entry_matches(mcp[name], removals[name]):
            del mcp[name]
            removed.append(name)
        else:
            warned.append(name)
    if removed:
        if mcp:
            merged["mcp"] = mcp
        else:
            merged.pop("mcp", None)
    return merged, removed, warned


def remove_skills_path(settings: Dict[str, Any], skills_path: str) -> Tuple[Dict[str, Any], bool]:
    """Return (settings, removed) with skills_path dropped from the 'skills' array once.

    Exactly this path — the one this project's scaffold wrote — and nothing else: other
    projects' paths, user entries and unknown keys survive. Idempotent: a second call finds
    nothing to remove. The input dict is never mutated.
    """
    merged = dict(settings)
    skills = list(merged.get("skills") or [])
    if skills_path not in skills:
        return merged, False
    merged["skills"] = [p for p in skills if p != skills_path]
    return merged, True
