#!/usr/bin/env python3
"""Capture Claude Code statusLine JSON for task-skill automation, then delegate display.

The user's rich status line remains the renderer. This wrapper persists the raw
statusLine payload so poll_limit.py can use Claude Code's own rate-limit metadata
instead of spending a probe while a reset time is known.
"""
# pylint: disable=missing-function-docstring
# Ported verbatim from the originating job-search-ai-assistant repo's /task skill: kept in
# lockstep with that source rather than churned for local docstring style rules.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker_lib as lib

# No default: a path is personal to one machine, so there is nothing sensible to guess.
# Set CLAUDE_USER_STATUSLINE to chain your own statusline script after ai-badger's capture.
_USER_STATUSLINE_ENV = "CLAUDE_USER_STATUSLINE"
_configured = os.environ.get(_USER_STATUSLINE_ENV)
USER_STATUSLINE = Path(_configured) if _configured else None
STATUSLINE_STATE = lib.DATA_DIR / "statusline-state.json"


def capture_statusline(input_text: str) -> None:
    try:
        payload = json.loads(input_text)
    except json.JSONDecodeError:
        return
    lib.ensure_data_dir()
    state = {
        "capturedAt": lib.now_iso(),
        "sessionId": payload.get("session_id"),
        "transcriptPath": payload.get("transcript_path"),
        "cwd": payload.get("cwd") or payload.get("workspace", {}).get("current_dir"),
        "rateLimits": payload.get("rate_limits", {}),
        "contextWindow": payload.get("context_window", {}),
        "model": payload.get("model", {}),
    }
    lib.save_json(STATUSLINE_STATE, state)


def render_user_statusline(input_text: str) -> int:
    if USER_STATUSLINE is None or not USER_STATUSLINE.exists():
        return 0
    result = subprocess.run(
        [str(USER_STATUSLINE)],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    return 0


def main() -> int:
    input_text = sys.stdin.read()
    capture_statusline(input_text)
    return render_user_statusline(input_text)


if __name__ == "__main__":
    sys.exit(main())
