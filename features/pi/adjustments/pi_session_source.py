"""pi session source for the /task tracker (installed by the pi adjustment).

pi has no session database (no state.db, no SQLite store). The session source
reads the PI_SESSION_ID env var for identification and provides a resume command.
All token tracking values are zeroed — pi does not expose per-session token usage
through an env var or file API.

The pi adjustment (features/pi/adjustments/adjust_task.py) copies this module into
the scaffolded .ai-badger/skills/task/scripts/pi_session_source.py, where
tracker_lib's discovery import finds and asks it to register(lib).
"""
from __future__ import annotations

import os

PI_SESSION_ENV = "PI_SESSION_ID"


def register(tracker_lib) -> None:
    """Register the pi session source with a tracker_lib module.

    Called by tracker_lib's guarded optional import. Wires the env var,
    checkpoint maker, resume command, and delegation reader.
    """
    tracker_lib.register_session_source(
        "pi",
        env_var=PI_SESSION_ENV,
        resolve=_resolve,
        checkpoint=lambda session: _zeroed_checkpoint(session["sessionId"]),
        resume=lambda session_id: f"pi -p --resume {session_id}",
        delegation_usage=lambda delegation_id: None,
    )


def _resolve() -> dict:
    """Identify the invoking pi session: PI_SESSION_ID env var."""
    sid = os.environ.get(PI_SESSION_ENV)
    if sid:
        return {"sessionId": sid, "transcriptPath": None}
    return {}


def _zeroed_checkpoint(session_id: str) -> dict:
    """Checkpoint shape with all zeros — pi provides no token data."""
    return {
        "timestamp": "",
        "contextTokens": 0,
        "assistantMessages": 0,
        "byModel": {},
        "cumulative": {
            "inputTokens": 0,
            "outputTokens": 0,
            "cacheReadTokens": 0,
            "cacheCreationTokens": 0,
        },
    }