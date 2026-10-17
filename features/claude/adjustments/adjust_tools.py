"""Adjustment: merge each opted-in tool's marked PreToolUse Bash handler into .claude/settings.json.

ADR-0039. Handlers are recognised by their ``AI_BADGER_TOOL`` marker alone, so HookWiring's
framework hooks and the operator's own pass through untouched, and an opt-out removes exactly
what this added — down to the group, event and ``hooks`` key it created.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

EVENT = "PreToolUse"


def _modules(framework_root: Path):
    """`config_guard` and `tool_hooks` from the framework that ran this adjustment."""
    scripts = framework_root / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import config_guard  # pylint: disable=import-outside-toplevel
    import tool_hooks  # pylint: disable=import-outside-toplevel
    return config_guard, tool_hooks


def _entry(command: str) -> Dict[str, Any]:
    return {"matcher": "Bash", "hooks": [{"type": "command", "command": command, "timeout": 5}]}


def _shape_error(settings: Dict[str, Any]) -> Optional[str]:
    """Why the ``hooks`` section cannot be merged into, or None when it can."""
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return "hooks is not a mapping"
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            return f"hooks.{event} is not a list"
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                return f"hooks.{event} holds a group that is not a mapping with a hooks list"
            if any(not isinstance(h, dict) for h in group.get("hooks", [])):
                return f"hooks.{event} holds a handler that is not a mapping"
    return None


def _merge(settings: Dict[str, Any], wanted: List[Dict[str, Any]],
           is_ours: Callable[[object], bool]) -> None:
    """Keep wanted entries in place, drop every other marked handler, put what is missing first.

    A group, event or ``hooks`` key emptied by a removal goes with it; one that was already
    empty stays, because it was the operator's.
    """
    hooks = settings.get("hooks", {})
    was_empty = not hooks
    missing = list(wanted)
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            if event == EVENT and group in missing:
                missing.remove(group)
                kept.append(group)
                continue
            handlers = group.get("hooks", [])
            remaining = [h for h in handlers if not is_ours(h.get("command"))]
            if len(remaining) == len(handlers):
                kept.append(group)
            elif remaining:
                kept.append(dict(group, hooks=remaining))
        if kept or not hooks[event]:
            hooks[event] = kept
        else:
            del hooks[event]
    if missing:
        hooks.setdefault(EVENT, [])[:0] = missing
    if hooks or was_empty:
        settings["hooks"] = hooks
    else:
        del settings["hooks"]


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Wire one marked handler per tool with a Claude arm; remove marked handlers without one.

    Returns:
        {'applied': bool, 'files': [], 'notes': str} — settings.json is merged into, never owned.
    """
    guard, tool_hooks = _modules(Path(context["framework_root"]))
    commands = [arm["command"] for tool in (context.get("tools") or {}).values()
                if (arm := (tool.get("agents") or {}).get("claude"))
                and arm.get("mode") == "native"]
    path = Path(context["target"]) / ".claude" / "settings.json"
    if not path.exists() and not commands:
        return {"applied": False, "files": [], "notes": "no tool hooks for Claude"}

    settings, refusal = guard.read_json_mapping(path)
    if settings is None:
        return {"applied": False, "files": [], "notes": f"{refusal} (tool hooks not wired)"}
    problem = _shape_error(settings)
    if problem:
        return {"applied": False, "files": [],
                "notes": f"{guard.refusal(path, problem)} (tool hooks not wired)"}

    had_hooks = "hooks" in settings
    _merge(settings, [_entry(command) for command in commands], tool_hooks.is_ours)
    if not had_hooks and settings.get("hooks") == {}:
        del settings["hooks"]
    if not guard.write_json_with_backup(path, settings):
        return {"applied": bool(commands), "files": [],
                "notes": "tool hooks already wired" if commands else "no tool hooks for Claude"}
    return {"applied": True, "files": [],
            "notes": (f"{len(commands)} tool hook(s) wired into .claude/settings.json"
                      if commands else "tool hooks removed from .claude/settings.json")}
