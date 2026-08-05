#!/usr/bin/env python3
"""PostToolUse hook: log each memory_search call and return the grade ask as context.

Advisory only, never blocking: emits `additionalContext` alone, exit 0, never
`decision`/`permissionDecision`/`continue` — same discipline as commit_reminder_hook.py
(docs/changelog/0.33.0). All logic lives in memory_grade.py; this entry only transports.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_grade  # pylint: disable=wrong-import-position


def main() -> int:
    """Read the hook payload from stdin; print additionalContext iff a search was logged."""
    try:
        payload: Dict[str, Any] = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    if not memory_grade.is_memory_search(tool_name):
        return 0
    ask = memory_grade.log_search(
        payload.get("tool_input") or {},
        payload.get("tool_response") or "",
        payload.get("cwd") or "",
    )
    if ask is None:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": ask,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
