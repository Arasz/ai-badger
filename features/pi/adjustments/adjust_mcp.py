"""Adjustment: migration-only removal of this project's MCP entries from pi's settings.json.

The pi-mcp-tools fork reads the project's .mcp.json directly at session_start (claude→fork
conversion, ${HOME} expanded, project-over-global merge), so the 'mcp' key in
~/.pi/agent/settings.json is no longer scaffold-written — it is user-owned fallback state for
forks that cannot read .mcp.json yet. A re-scaffold therefore MIGRATES: it removes exactly the
entries this project's scaffold once wrote, and touches nothing else.

Removal is shape-aware (plan M5/R10): for each declared name the entry is regenerated exactly
as _server_entry would write it today; the global entry is removed only when it matches that
shape (deep-equal on enabled/toolPrefix/type/url/env/cwd; command compared shlex-split or
literal, tolerating the historical split→shlex drift c7d0d528). A same-named entry that does
not match is a user edit — warn-and-leave, never destroyed. Nothing new is ever written: a
removal pass with nothing matching leaves the file byte-identical, and no settings.json is
created where none exists.

Per-extension version gate (plan M5, R8+R9): removal runs only when the installed fork carries
the project-scope capability marker
~/.pi/agent/extensions/pi-mcp-tools/.ai-badger-capability-project-scope-mcp. A fork without it
still reads only the global 'mcp' key, so removing the entries would leave the machine with no
MCP at all — skip-with-warning instead. Under --no-install the removal proposal is printed and
nothing is written.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pi_settings  # pylint: disable=wrong-import-position

FORK_EXTENSION_DIR = Path.home() / ".pi" / "agent" / "extensions" / "pi-mcp-tools"
CAPABILITY_MARKER = FORK_EXTENSION_DIR / ".ai-badger-capability-project-scope-mcp"

REMOVED_HEADER = (
    "Removed {count} shape-matched MCP server(s) this project had merged into {path}'s "
    "'mcp' key: the installed pi-mcp-tools fork reads the project's .mcp.json directly, so "
    "the global entries are legacy scaffold state."
)
NOT_PRESENT_HEADER = (
    "{names}: not present in {path}'s 'mcp' key — nothing to remove."
)
DRIFTED_HEADER = (
    "{names}: left in place — the installed entry does not match what this scaffold would "
    "write today (a user edit or a drifted shape). Not removed."
)
GATE_WARNING = (
    "The installed pi-mcp-tools extension at {dir} predates project-scope .mcp.json reading "
    "(capability marker .ai-badger-capability-project-scope-mcp missing), so its global "
    "'mcp' entries are still its only configuration — they were left in place. Re-run after "
    "updating the extension to migrate this project's entries off the global key."
)
PROPOSAL_HEADER = (
    "{count} MCP server(s) are declared for this project. The pi-mcp-tools fork reads the "
    "project's .mcp.json directly; this scaffold no longer merges into ~/.pi/agent/settings.json. "
    "A subsequent install run would remove these shape-matched entries from the 'mcp' key "
    "(pi-mcp-tools extension only, not pi core):"
)
DECLINE_HEADER = (
    "config.mcp.decline names {names}. These servers are excluded from the proposal."
)


def _server_entry(name: str, server: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ai-badger MCP server declaration into pi-mcp-tools format.

    Also the shape-matcher's generator: a global entry is removable iff it equals what this
    function writes today (see module docstring). Raises ValueError on an unbalanced quote —
    a malformed declaration to report per-adjustment, not to mangle silently.
    """
    entry: Dict[str, Any] = {
        "enabled": True,
        "toolPrefix": f"mcp_{name}",
    }

    command = server.get("command", "")
    if command:
        parts = shlex.split(command)
        entry["type"] = "local"
        entry["command"] = parts
    else:
        entry["type"] = "remote"
        entry["url"] = server.get("url", "")

    env = server.get("env", {})
    if env:
        entry["env"] = env

    cwd = server.get("cwd", "")
    if cwd:
        entry["cwd"] = cwd

    return entry


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Remove (install=True) or print a removal proposal for (--no-install) this project's
    shape-matched entries in pi's settings.json 'mcp' key.

    Args:
        context: {
            'config': dict,
            'mcp_declarations': dict[str, dict],  # declared servers, resolved for pi
            'mcp_declined': list[str],            # config.mcp.decline
            'install': bool,                      # False under --no-install
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "pi" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "pi not in config.agents"}

    declined = [name for name in (context.get("mcp_declined") or []) if name]
    declared = {name: srv for name, srv in (context.get("mcp_declarations") or {}).items()
                if name not in declined}
    if not declared and not declined:
        return {"applied": False, "files": [],
                "notes": "no MCP server declared and none declined — nothing to propose"}

    sections: List[str] = []
    applied = True
    if declared:
        mcp_entries = {name: _server_entry(name, declared[name]) for name in sorted(declared)}
        if context.get("install", True):
            if not CAPABILITY_MARKER.exists():
                applied = False
                sections.append(GATE_WARNING.format(dir=FORK_EXTENSION_DIR))
            else:
                settings = pi_settings.load_settings(pi_settings.SETTINGS_PATH)
                settings, removed, warned = pi_settings.remove_mcp_servers(
                    settings, mcp_entries)
                if removed:
                    pi_settings.write_settings(pi_settings.SETTINGS_PATH, settings)
                    sections.append(REMOVED_HEADER.format(
                        count=len(removed), path=pi_settings.SETTINGS_PATH))
                    sections.append(f"removed: {', '.join(removed)}")
                if warned:
                    sections.append(DRIFTED_HEADER.format(names=", ".join(warned)))
                absent = [n for n in sorted(mcp_entries) if n not in removed + warned]
                if absent:
                    sections.append(NOT_PRESENT_HEADER.format(
                        names=", ".join(absent), path=pi_settings.SETTINGS_PATH))
        else:
            sections.append(PROPOSAL_HEADER.format(count=len(declared)))
            sections.append(json.dumps({"mcp": mcp_entries}, indent=2))
    if declined:
        sections.append(DECLINE_HEADER.format(names=", ".join(declined)))

    return {
        "applied": applied,
        "files": [],
        "notes": "\n".join(sections),
    }
