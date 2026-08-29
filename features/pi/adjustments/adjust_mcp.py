"""Adjustment: apply (or propose) the MCP server block for pi's settings.json.

pi core reads no MCP configuration at all; the 'mcp' key in ~/.pi/agent/settings.json is
consumed solely by the third-party pi-mcp-tools extension — zero occurrences across pi's own
docs and dist. ai-badger generates .mcp.json for the project, but pi has no project-level MCP
config, so this adjustment maps the declared servers into the pi-mcp-tools format and, when
install=True, merges them into settings.json via the shared pi_settings helper (atomic,
idempotent, unknown-key-preserving). Under --no-install the merge is skipped and the snippet is
printed instead, for the user to apply by hand.

Config format (pi-mcp-tools):
  {
    "mcp": {
      "<serverName>": {
        "type": "local" | "remote",
        "command": ["npx", "-y", "<package>", ...],
        "env": { ... },
        "cwd": "...",
        "enabled": true,
        "toolPrefix": "mcp_<server>"
      }
    }
  }
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pi_settings  # pylint: disable=wrong-import-position

MERGED_HEADER = (
    "{count} MCP server(s) declared for this project were merged into {path}'s 'mcp' key. "
    "That key has no consumer in pi core — it is read solely by the pi-mcp-tools extension."
)
PROPOSAL_HEADER = (
    "{count} MCP server(s) are declared for this project. pi reads MCP configuration "
    "from ~/.pi/agent/settings.json under the 'mcp' key (pi-mcp-tools extension only, "
    "not pi core). Merge this into your settings.json:"
)
DECLINE_HEADER = (
    "config.mcp.decline names {names}. These servers are excluded from the proposal."
)


def _server_entry(name: str, server: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ai-badger MCP server declaration into pi-mcp-tools format.

    Raises ValueError on an unbalanced quote — a malformed declaration to report per-adjustment,
    not to mangle silently.
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
    """Merge (install=True) or print (--no-install) the pi-mcp-tools settings.json block.

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
    if declared:
        mcp_entries = {name: _server_entry(name, declared[name]) for name in sorted(declared)}
        if context.get("install", True):
            settings = pi_settings.load_settings(pi_settings.SETTINGS_PATH)
            settings = pi_settings.merge_mcp_servers(settings, mcp_entries)
            pi_settings.write_settings(pi_settings.SETTINGS_PATH, settings)
            sections.append(MERGED_HEADER.format(
                count=len(declared), path=pi_settings.SETTINGS_PATH))
        else:
            sections.append(PROPOSAL_HEADER.format(count=len(declared)))
            sections.append(json.dumps({"mcp": mcp_entries}, indent=2))
    if declined:
        sections.append(DECLINE_HEADER.format(names=", ".join(declined)))

    return {
        "applied": True,
        "files": [],
        "notes": "\n".join(sections),
    }