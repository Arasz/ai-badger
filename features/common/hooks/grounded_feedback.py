"""Pending-context stashes for Hermes plugin.

Two stash-and-pop patterns that keep ai_badger_hooks.py under the 1000-line
pylint cap:
- Grounded feedback (Rule 3C): terminal failure output for next-turn evidence.
- Commit reminder: uncommitted-file nudge surfaced in pre_llm_inject_context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

# --- Grounded feedback (Rule 3C) ---

PENDING_FEEDBACK_FILE = Path.home() / ".ai-badger" / "pending-feedback.json"
MAX_FEEDBACK_LINES = 30
MAX_FEEDBACK_CHARS = 3000


def load_pending_feedback() -> Dict[str, str]:
    """Load the pending-feedback file; ``{}`` on missing file or bad JSON."""
    try:
        raw = PENDING_FEEDBACK_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_pending_feedback(pending: Dict[str, str]) -> None:
    """Persist the pending-feedback file."""
    PENDING_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FEEDBACK_FILE.write_text(json.dumps(pending), encoding="utf-8")


def set_pending_feedback(project: str, message: str) -> None:
    """Stash grounded feedback for *project*."""
    pending = load_pending_feedback()
    pending[str(Path(project).resolve())] = message
    save_pending_feedback(pending)


def pop_pending_feedback(project: str) -> Optional[str]:
    """Return and clear the pending grounded feedback for *project*, or None."""
    pending = load_pending_feedback()
    key = str(Path(project).resolve())
    message = pending.pop(key, None)
    if message is not None:
        save_pending_feedback(pending)
    return message


def stash_if_failure(tool_name: str, result: str, project: str,
                     debug_fn=None) -> None:
    """After a terminal/Bash command, stash failure output for the next turn.

    *debug_fn* is an optional ``_debug(event, **fields)`` callback.
    """
    normalized = tool_name.lower()
    if normalized not in ("terminal", "bash"):
        return
    if not result or not result.strip():
        return
    lines = result.strip().splitlines()
    if len(lines) > MAX_FEEDBACK_LINES:
        lines = lines[-MAX_FEEDBACK_LINES:]
    truncated = "\n".join(lines)
    if len(truncated) > MAX_FEEDBACK_CHARS:
        truncated = truncated[-MAX_FEEDBACK_CHARS:]
    message = (
        "GROUNDED FEEDBACK: The last terminal command produced failure output. "
        "Use it as evidence for your next correction:\n\n"
        f"```\n{truncated}\n```"
    )
    set_pending_feedback(project, message)
    if debug_fn:
        debug_fn("grounded_feedback", "stashed", project=project,
                 output_lines=len(lines))


# --- Commit reminder stash ---

PENDING_REMINDER_FILE = Path.home() / ".ai-badger" / "commit-reminder" / "pending.json"


def load_pending_reminders() -> Dict[str, str]:
    """Load the pending-reminder file; ``{}`` on missing file or bad JSON."""
    try:
        raw = PENDING_REMINDER_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_pending_reminders(pending: Dict[str, str]) -> None:
    """Persist the pending-reminder file."""
    PENDING_REMINDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_REMINDER_FILE.write_text(json.dumps(pending), encoding="utf-8")


def set_pending_reminder(project: str, message: str) -> None:
    """Stash *message* for *project*."""
    pending = load_pending_reminders()
    pending[str(Path(project).resolve())] = message
    save_pending_reminders(pending)


def pop_pending_reminder(project: str) -> Optional[str]:
    """Return and clear the pending reminder for *project*, or None."""
    pending = load_pending_reminders()
    key = str(Path(project).resolve())
    message = pending.pop(key, None)
    if message is not None:
        save_pending_reminders(pending)
    return message
