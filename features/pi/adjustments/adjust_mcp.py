"""Adjustment: migration-only removal of this project's legacy MCP entries from pi's settings.json.

pi's native MCP support reads ~/.pi/agent/mcp.json (global) and .pi/mcp.json (project,
trust-gated) — never the 'mcp' key in ~/.pi/agent/settings.json. That key holds legacy state
this scaffold once merged this project's servers into, and it may still be a machine's only
configuration while a legacy reader that depends on it is installed. A re-scaffold therefore
MIGRATES: it removes exactly the entries this project's scaffold once wrote, and touches
nothing else.

Removal is shape-aware (plan M5/R10): for each declared name the entry is regenerated exactly
as _server_entry would write it today; the global entry is removed only when it matches that
shape (deep-equal on enabled/toolPrefix/type/url/env/cwd; command compared shlex-split or
literal, tolerating the historical split→shlex drift c7d0d528). A same-named entry that does
not match is a user edit — warn-and-leave, never destroyed. Nothing new is ever written: a
removal pass with nothing matching leaves the file byte-identical, and no settings.json is
created where none exists.

Native-config gate: removal runs only when the project's .pi/mcp.json exists. Without it a
machine still running a legacy reader may depend on the global 'mcp' key, so removing the
entries could leave it with no MCP configuration at all — skip-with-warning instead. The gate
is conservative: a missing 'target', an absent file, or a file whose contents are malformed or
parse to something other than a JSON object all count as absent. Under --no-install the
removal proposal is printed and nothing is written.

Residual worlds this file does not resolve:
  * With a native .pi/mcp.json present and a stale legacy reader still installed, removal
    proceeds. Cleaning up that reader belongs to the consumer's extension cleanup and is NOT
    performed by this file.
  * An existing but malformed .pi/mcp.json counts as absent, so the gate stays closed.
  * An existing but empty object ({}) opens the gate while declaring no servers: presence
    plus parseable shape IS the capability check — what servers to migrate comes from this
    project's own declarations, not from the file.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pi_settings  # pylint: disable=wrong-import-position

NATIVE_MCP_RELPATH = Path(".pi") / "mcp.json"

REMOVED_HEADER = (
    "Removed {count} shape-matched MCP server(s) this project had merged into {path}'s "
    "'mcp' key: pi reads MCP servers from .pi/mcp.json (project, trust-gated) and "
    "~/.pi/agent/mcp.json (global), never the settings 'mcp' key, so those global entries "
    "are legacy scaffold state."
)
NOT_PRESENT_HEADER = (
    "{names}: not present in {path}'s 'mcp' key — nothing to remove."
)
DRIFTED_HEADER = (
    "{names}: left in place — the installed entry does not match what this scaffold would "
    "write today (a user edit or a drifted shape). Not removed."
)
GATE_WARNING = (
    "native pi reads {config} for MCP servers (trust-gated), and this project does not carry "
    "it yet, so the global 'mcp' entries were left in place. A legacy reader that still "
    "depends on the global 'mcp' key may be installed and must be updated or removed first. "
    "Add {config} and re-run to migrate this project's entries off the global key."
)
PROPOSAL_HEADER = (
    "{count} MCP server(s) are declared for this project. pi reads MCP servers from "
    ".pi/mcp.json (project, trust-gated) and ~/.pi/agent/mcp.json (global) and reads no "
    "settings 'mcp' key; this scaffold no longer merges into ~/.pi/agent/settings.json. A "
    "later install run would remove these shape-matched entries from the global 'mcp' key "
    "only once this project carries .pi/mcp.json:"
)
DECLINE_HEADER = (
    "config.mcp.decline names {names}. These servers are excluded from the proposal."
)


def _native_project_mcp_config(context: Dict[str, Any]) -> Optional[Path]:
    """The project's native .pi/mcp.json, or None when it is not a usable config file.

    That file's presence is what opens the removal gate. Conservative on purpose: a missing
    'target', an absent file, or a file whose contents are malformed or parse to something
    other than a JSON object all count as absent — the gate stays closed rather than raising
    out of the adjustment.
    """
    target = context.get("target")
    if not target:
        return None
    candidate = Path(target) / NATIVE_MCP_RELPATH
    if not candidate.is_file():
        return None
    try:
        content = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return candidate if isinstance(content, dict) else None


def _server_entry(name: str, server: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ai-badger MCP server declaration into the legacy global settings mcp entry
    shape this scaffold once wrote — retained as the shape-matcher's generator.

    A global entry is removable iff it equals what this function writes today (see module
    docstring). Raises ValueError on an unbalanced quote — a malformed declaration to report
    per-adjustment, not to mangle silently.
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
            native_config = _native_project_mcp_config(context)
            if native_config is None:
                target = context.get("target")
                project_config = NATIVE_MCP_RELPATH
                if target:
                    project_config = Path(target) / NATIVE_MCP_RELPATH
                applied = False
                sections.append(GATE_WARNING.format(config=project_config))
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
