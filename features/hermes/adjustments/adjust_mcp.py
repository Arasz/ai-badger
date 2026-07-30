"""Adjustment: propose the `mcp_servers:` block for `~/.hermes/config.yaml`; never write it.

Hermes reads MCP servers from `~/.hermes/config.yaml` alone — it has no project route, so
ADR-0014 decision 6 leaves a project scaffolder nothing here to own. Per-server `tools`
include/exclude globs are applied at registration, which is how `config.mcp.decline` reaches
this host (#186): a filtered tool never reaches the model.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

PROPOSAL_HEADER = (
    "{count} MCP server(s) are declared for this project, and hermes reads MCP configuration "
    "only from ~/.hermes/config.yaml — ai-badger never writes user-global agent configuration "
    "(ADR-0014 decision 6). Merge this into ~/.hermes/config.yaml yourself:")
DECLINE_HEADER = (
    "config.mcp.decline names {names}. Hermes filters tools per server at registration, so "
    "exclude their tools rather than deleting an entry you may not own — an excluded tool never "
    "reaches the model. Merge this into the same ~/.hermes/config.yaml entries:")


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Print the `~/.hermes/config.yaml` MCP snippet for this project; write nothing.

    Args:
        context: {
            'config': dict,
            'mcp_declarations': dict[str, dict],  # declared servers, resolved for hermes
            'mcp_declined': list[str],            # config.mcp.decline
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "hermes" not in (config.get("agents") or []):
        return _unapplied("hermes not in config.agents")

    declined = [name for name in (context.get("mcp_declined") or []) if name]
    declared = {name: srv for name, srv in (context.get("mcp_declarations") or {}).items()
                if name not in declined}
    if not declared and not declined:
        return _unapplied("no MCP server declared and none declined — nothing to propose")

    sections: List[str] = []
    if declared:
        sections.append(PROPOSAL_HEADER.format(count=len(declared)))
        sections.append(_yaml_block(_launch_lines(name, declared[name])
                                    for name in sorted(declared)))
    if declined:
        sections.append(DECLINE_HEADER.format(names=", ".join(declined)))
        sections.append(_yaml_block(_exclude_lines(name) for name in declined))
    return {"applied": True, "files": [], "notes": "\n\n".join(sections)}


def _yaml_block(per_server) -> str:
    """One `mcp_servers:` mapping built as text — pyyaml is optional and must not be needed."""
    lines = ["mcp_servers:"]
    for server_lines in per_server:
        lines.extend(server_lines)
    return "\n".join(lines)


def _launch_lines(name: str, server: Dict[str, Any]) -> List[str]:
    """The launch entry for one declared server: command, args, env, `enabled: true`."""
    command, args = _split_command(server)
    lines = [f"  {name}:", f"    command: {_scalar(command)}"]
    if args:
        lines.append(f"    args: [{', '.join(_scalar(arg) for arg in args)}]")
    env = server.get("env") or {}
    if env:
        lines.append("    env:")
        lines.extend(f"      {key}: {_scalar(env[key])}" for key in sorted(env))
    lines.append("    enabled: true")
    return lines


def _exclude_lines(name: str) -> List[str]:
    """The decline entry for one server: every tool excluded, no launch config asserted."""
    return [f"  {name}:", "    tools:", '      exclude: ["*"]']


def _split_command(server: Dict[str, Any]) -> Tuple[str, List[str]]:
    """`(executable, args)` — an explicit `args` wins, otherwise the command splits on spaces."""
    command = server.get("command", "")
    if "args" in server:
        return command, list(server["args"])
    parts = command.split()
    return (parts[0], parts[1:]) if parts else (command, [])


def _scalar(value: Any) -> str:
    """A YAML scalar: JSON is a YAML subset, so `json.dumps` quotes and escapes correctly."""
    return json.dumps(str(value), ensure_ascii=False)


def _unapplied(notes: str) -> Dict[str, Any]:
    return {"applied": False, "files": [], "notes": notes}
