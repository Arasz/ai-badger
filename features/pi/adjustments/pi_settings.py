"""Shared read/merge/write helper for pi's user-global ~/.pi/agent/settings.json.

Used by adjust_skills.py (skills array) and adjust_mcp.py (mcp key). Both write user-global
state rather than a project-scope `.pi/settings.json` for a measured reason: on this machine
`~/.pi/agent/trust.json` does not exist and `defaultProjectTrust` is unset (default "ask"), and
pi's own docs state that `-p`, `--mode json` and `--mode rpc` — the headless modes ai-badger's
scaffold and away-mode run under — ignore project resources entirely without a saved trust
decision. A project-scope write would silently do nothing in exactly the runs this exists for.

Write contract, all load-bearing:
  * ATOMIC — temp file in the same directory, then os.replace. A crashed scaffold must never
    leave a truncated settings.json; it is the user's real config, not scaffold-owned state.
  * IDEMPOTENT — merge functions add an entry once, however many times they run.
  * UNKNOWN KEYS PRESERVED — the real file on this machine holds lastChangelogVersion and
    theme; anything not understood here is round-tripped, never dropped.
  * The file (and its parent directories) is created when absent, holding just the merged key.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

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
