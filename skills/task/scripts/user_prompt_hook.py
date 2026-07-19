#!/usr/bin/env python3
"""UserPromptSubmit hook: auto-register a task when the user types `/task <id>`.

This guarantees a tracked entry exists with a start checkpoint the moment a task begins, even if
the model forgets to run `task_tracker.py start`. `task_tracker.py start` is idempotent, so both
paths can run safely without clobbering each other. Also refreshes `current-session.json` on
every prompt so `resolve_own_session()` stays accurate for the rest of the skill's scripts.

This hook does registration only — it has no opinion on prompt markers or any other
UserPromptSubmit concern. If your project also uses the `prompt-markers` skill, register both
hooks as separate entries under the same `UserPromptSubmit` event; Claude Code runs every
registered hook for an event.

Failure handling: a broken hook must never block the user's prompt. Malformed stdin JSON is a
silent no-op, and a failure while registering the task (e.g. a corrupt tracking file) is swallowed
so the prompt always goes through — worst case, the model falls back to running
`task_tracker.py start` itself.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker_lib as lib

# Matches `/task <id>` (optionally `/task:something <id>`, or namespaced as a plugin skill —
# `/<plugin>:task <id>` — the form Claude Code uses once this skill is installed via a
# marketplace plugin) at the very start of the prompt. Kept local to this hook, rather than in
# tracker_lib, so prompt parsing stays colocated with its only caller.
TASK_ID_RE = re.compile(r"^/(?:[\w-]+:)?task(?::\S+)?\s+([A-Za-z0-9._-]+)")


def task_id_from_prompt(prompt: str) -> str | None:
    """Return the task id in a leading `/task <id>` invocation, or None if there isn't one."""
    match = TASK_ID_RE.match(prompt.strip())
    return match.group(1) if match else None


def _register_task(task_id: str, session_id: str, transcript: str) -> None:
    checkpoint = lib.make_checkpoint(transcript)
    with lib.locked_store():
        tasks = lib.load_tasks()
        entry = lib.find_entry(tasks, task_id)
        if entry is not None and entry.get("state") == lib.STATE_FINISHED:
            return  # user referenced a finished task; nothing to register
        conflict = lib.find_other_entry_with_session(tasks, session_id, task_id)
        if conflict is not None and conflict.get("state") != lib.STATE_FINISHED:
            # current-session.json is a single global pointer shared by every concurrently
            # running session; it can be stale by the time this prompt is processed (another
            # session's hook may have overwritten it since). Don't silently steal session_id
            # from whatever task legitimately owns it — leave this entry untouched.
            return
        if entry is None:
            entry = {"taskId": task_id, "title": "", "branch": "", "resumeAttempts": []}
            tasks["tasks"].append(entry)
        entry.update(
            {
                "sessionId": session_id,
                "transcriptPath": transcript,
                "cwd": str(lib.PROJECT_ROOT),
                "startedAt": entry.get("startedAt") or lib.now_iso(),
                "finishedAt": None,
                "state": entry.get("state") or lib.STATE_STARTED,
                "resumeCommand": f"claude --resume {session_id}",
            }
        )
        lib.save_json(lib.EXECUTED_TASKS, tasks)

        usage = lib.load_usage()
        usage_entry = lib.find_entry(usage, task_id)
        if usage_entry is None:
            usage_entry = {"taskId": task_id, "subagents": [], "grade": None}
            usage["tasks"].append(usage_entry)
        usage_entry["sessionId"] = session_id
        checkpoints = usage_entry.setdefault("checkpoints", {})
        checkpoints.setdefault("start", checkpoint)
        checkpoints["latest"] = checkpoint
        lib.save_json(lib.TOKEN_USAGE, usage)


def main() -> int:
    """Read the hook payload from stdin, refresh the session, and register a `/task` invocation."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    session_id = payload.get("session_id", "")
    transcript = payload.get("transcript_path", "")
    if session_id:
        lib.save_current_session(session_id, transcript, payload.get("cwd", ""))

    task_id = task_id_from_prompt(payload.get("prompt", ""))
    if not task_id or not session_id:
        return 0

    try:
        _register_task(task_id, session_id, transcript)
    except Exception:  # pylint: disable=broad-exception-caught
        # Registration is a convenience net, not the source of truth: task_tracker.py's own
        # `start` command is idempotent and can register the task later. A hook must never
        # block the user's prompt over a tracking-file problem.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
