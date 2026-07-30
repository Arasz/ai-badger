"""Adjustment: propose the Copilot coding agent's MCP configuration; write nothing.

The Copilot **CLI** reads `.github/mcp.json`, which ai-badger writes (`mcp_tools.py`, #189).
The Copilot **coding agent** reads its MCP configuration from the repository settings UI and
from no repo file at all, so this adjustment can only print what an admin pastes there. Two
documented constraints shape the snippet: the per-server `tools` array is required, and a
secret must be referenced by a `COPILOT_MCP_*`-prefixed name.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

# `${VAR}` / `$VAR` — the whole value, so a literal that merely mentions a `$` is left alone.
ENV_REF = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")
SECRET_PREFIX = "COPILOT_MCP_"

PROPOSAL_HEADER = (
    "{count} MCP server(s) are declared for this project. The Copilot CLI reads them from "
    ".github/mcp.json, which ai-badger just wrote; the Copilot coding agent takes MCP "
    "configuration only from the repository settings UI (Settings, Copilot, Coding agent, MCP "
    "configuration) and from no repo file, so ai-badger can only propose it. Paste this there, "
    "and add each COPILOT_MCP_-prefixed value as a Copilot secret:")
DECLINE_NOTE = (
    "config.mcp.decline names {names}: declined servers are left out of .github/mcp.json and "
    "out of the snippet above, which is the whole of Copilot's committable decline route. A "
    "server that arrives from ~/.copilot/mcp-config.json or a plugin is blocked only at "
    "runtime, with copilot --deny-tool '{first}(<tool>)'.")


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Print the coding agent's MCP snippet for this project; write nothing.

    Args:
        context: {
            'config': dict,
            'mcp_declarations': dict[str, dict],  # declared servers, resolved for copilot
            'mcp_declined': list[str],            # config.mcp.decline
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "copilot" not in (config.get("agents") or []):
        return _unapplied("copilot not in config.agents")

    declined = [name for name in (context.get("mcp_declined") or []) if name]
    servers = _repository_scoped(context.get("mcp_declarations") or {}, declined)
    if not servers and not declined:
        return _unapplied("no MCP server declared and none declined — nothing to propose")

    sections: List[str] = []
    if servers:
        sections.append(PROPOSAL_HEADER.format(count=len(servers)))
        sections.append(json.dumps({"mcpServers": servers}, ensure_ascii=False, sort_keys=True))
    if declined:
        sections.append(DECLINE_NOTE.format(names=", ".join(declined), first=declined[0]))
    return {"applied": True, "files": [], "notes": " ".join(sections)}


def _repository_scoped(declarations: Dict[str, Any],
                       declined: List[str]) -> Dict[str, Dict[str, Any]]:
    """Every declared server the settings UI may carry, rendered as one `mcpServers` entry each.

    A `scope: user` declaration names a user-global file (`~/.copilot/mcp-config.json`); the
    settings UI is a repository surface and is not where it belongs.
    """
    return {name: _entry(srv) for name, srv in sorted(declarations.items())
            if name not in declined and srv.get("scope", "project") == "project"}


def _entry(server: Dict[str, Any]) -> Dict[str, Any]:
    """One coding-agent server entry: launch config, secret-safe env, and the required `tools`."""
    command, args = _split_command(server)
    entry = {"command": command}  # type: Dict[str, Any]
    if args:
        entry["args"] = args
    env = server.get("env") or {}
    if env:
        entry["env"] = {key: copilot_secret_ref(str(value)) for key, value in env.items()}
    entry["tools"] = ["*"]
    return entry


def copilot_secret_ref(value: str) -> str:
    """An env-var reference renamed to the `COPILOT_MCP_*` name the coding agent can resolve.

    A literal value is returned untouched: only a reference needs a secret to exist.
    """
    match = ENV_REF.match(value)
    if not match:
        return value
    name = match.group(1)
    return "$" + (name if name.startswith(SECRET_PREFIX) else SECRET_PREFIX + name)


def _split_command(server: Dict[str, Any]) -> Tuple[str, List[str]]:
    """`(executable, args)` — an explicit `args` wins, otherwise the command splits on spaces."""
    command = server.get("command", "")
    if "args" in server:
        return command, list(server["args"])
    parts = command.split()
    return (parts[0], parts[1:]) if parts else (command, [])


def _unapplied(notes: str) -> Dict[str, Any]:
    return {"applied": False, "files": [], "notes": notes}
