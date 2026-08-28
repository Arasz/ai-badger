"""Adjustment: propose the MCP server block for pi's settings.json.

pi reads MCP servers from ~/.pi/agent/settings.json under an 'mcp' key (via the
pi-mcp-tools extension). ai-badger generates .mcp.json for the project, but pi
has no project-level MCP config — it reads from user-global settings.json only.
This adjustment maps the declared servers into the pi-native format and prints
the snippet for the user to merge.

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
from typing import Any, Dict, List

PROPOSAL_HEADER = (
    "{count} MCP server(s) are declared for this project. pi reads MCP configuration "
    "from ~/.pi/agent/settings.json under the 'mcp' key. Merge this into your settings.json:"
)
DECLINE_HEADER = (
    "config.mcp.decline names {names}. These servers are excluded from the proposal."
)


def _server_entry(name: str, server: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ai-badger MCP server declaration into pi-mcp-tools format."""
    entry: Dict[str, Any] = {
        "enabled": True,
        "toolPrefix": f"mcp_{name}",
    }

    command = server.get("command", "")
    if command:
        parts = command.split()
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


def _yaml_block(entries: List[str]) -> str:
    """Render a JSON snippet for the settings.json 'mcp' key."""
    return "\n" + "\n".join(entries)


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Print the ~/.pi/agent/settings.json MCP snippet for this project.

    Args:
        context: {
            'config': dict,
            'mcp_declarations': dict[str, dict],  # declared servers, resolved for pi
            'mcp_declined': list[str],            # config.mcp.decline
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
        sections.append(PROPOSAL_HEADER.format(count=len(declared)))
        mcp_entries = {name: _server_entry(name, declared[name]) for name in sorted(declared)}
        sections.append(json.dumps({"mcp": mcp_entries}, indent=2))
    if declined:
        sections.append(DECLINE_HEADER.format(names=", ".join(declined)))

    return {
        "applied": True,
        "files": [],
        "notes": "\n".join(sections),
    }