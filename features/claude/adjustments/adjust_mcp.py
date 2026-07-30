"""Adjustment: approve the MCP servers ai-badger declared, and deny the ones the project declined.

Project `.claude/settings.json` is the one MCP route besides `.mcp.json` that ai-badger owns
(ADR-0014 §0). `enabledMcpjsonServers` approves a declared server without a prompt;
`config.mcp.decline` is the project's decline route (#186) and lands as `disabledMcpjsonServers`
plus a `permissions.deny` rule, which beats allow whatever route the server arrived by.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List


def tool_pattern(server: str) -> str:
    """The permission rule matching every tool of *server* (documented: permissions.md, MCP)."""
    return f"mcp__{server}__*"


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Merge MCP approvals and denials into the project's `.claude/settings.json`.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target': Path,            # project root
            'mcp_servers': list[str],  # names ai-badger declares into this project's .mcp.json
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "claude" not in (config.get("agents") or []):
        return _unapplied("claude not in config.agents")

    declined = _declined(config)
    declared = [name for name in (context.get("mcp_servers") or []) if name not in declined]
    if not declared and not declined:
        return _unapplied("no MCP server declared and none declined — nothing to approve or deny")

    guard = _config_guard(Path(context["framework_root"]))
    path = Path(context["target"]) / ".claude" / "settings.json"
    settings, note = guard.read_json_mapping(path)
    if settings is None:
        return _unapplied(f"{note} (MCP servers not approved)")
    permissions = guard.mapping_section(settings, "permissions")
    if permissions is None:
        return _unapplied(
            f"{guard.refusal(path, 'permissions is not a mapping')} (MCP servers not approved)")

    refused: List[str] = []
    approved = declared if bool((config.get("mcp") or {}).get("approve", True)) else []
    added = _extend(settings, "enabledMcpjsonServers", approved, refused)
    added += _extend(permissions, "allow", [tool_pattern(n) for n in approved], refused,
                     label="permissions.allow")
    added += _extend(settings, "disabledMcpjsonServers", declined, refused)
    added += _extend(permissions, "deny", [tool_pattern(n) for n in declined], refused,
                     label="permissions.deny")

    if added:
        guard.write_json_with_backup(path, settings)
    return {
        "applied": bool(added),
        "files": [],  # settings.json is merged into, never owned — so never recorded
        "notes": _notes(added, approved, declined, refused),
    }


def _declined(config: Dict[str, Any]) -> List[str]:
    """Server names `config.mcp.decline` names, in order, blanks dropped."""
    return [name for name in ((config.get("mcp") or {}).get("decline") or []) if name]


def _extend(container: Dict[str, Any], key: str, values: List[str], refused: List[str],
            label: str = "") -> List[str]:
    """Append the missing *values* to the list at *key*; return what was added.

    A key already holding something that is not a list belongs to whoever wrote it: it is
    reported and left exactly as found, so one unusable key does not cost the others.
    """
    if not values:
        return []
    current = container.setdefault(key, [])
    if not isinstance(current, list):
        refused.append(f"left {label or key} untouched — it is not a list")
        return []
    added = [value for value in values if value not in current]
    current.extend(added)
    return added


def _notes(added: List[str], approved: List[str], declined: List[str],
           refused: List[str]) -> str:
    """One line saying what changed, what was already there, and what was refused."""
    parts: List[str] = []
    if approved:
        parts.append(f"approved {', '.join(approved)} in .claude/settings.json "
                     f"(enabledMcpjsonServers + permissions.allow)")
    if declined:
        parts.append(f"declined {', '.join(declined)} "
                     f"(disabledMcpjsonServers + permissions.deny)")
    if not added:
        parts.append("already recorded — nothing rewritten")
    parts.extend(refused)
    return "; ".join(parts)


def _unapplied(notes: str) -> Dict[str, Any]:
    return {"applied": False, "files": [], "notes": notes}


def _config_guard(framework_root: Path):
    """`config_guard` from the framework that ran this adjustment — the shared merge guard.

    An adjustment is loaded by path, so the scaffold's scripts directory is not necessarily on
    `sys.path` yet; nothing here may re-implement `write_with_backup` (#173).
    """
    scripts = (framework_root / "features" / "common" / "skills"
               / "welcome-ai-badger" / "scripts")
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import config_guard  # pylint: disable=import-outside-toplevel

    return config_guard
