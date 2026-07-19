#!/usr/bin/env python3
"""SessionStart hook: record the current session's id + transcript path.

task_tracker.py reads current-session.json so the model never has to know its
own session id. On resume, also surface any unfinished tracked tasks so the
model reattaches instead of starting from scratch. Also launches the
background usage-limit poller (poll_limit.py) so it is running for the
duration of the session.
"""
# pylint: disable=missing-function-docstring
# Ported from the originating job-search-ai-assistant repo's /task skill: kept in lockstep
# with that source rather than churned for local docstring style rules. One deliberate
# addition over the source: start_poll_limit_background() catches launch failures so a
# broken poller can never crash SessionStart itself.

import json
import subprocess
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import tracker_lib as lib


def start_poll_limit_background() -> None:
    script = lib.SCRIPT_DIR / "poll_limit.py"
    log = lib.DATA_DIR / "poll_limit.log"
    try:
        lib.ensure_data_dir()
        with open(log, "a", encoding="utf-8") as log_fh:
            subprocess.Popen(  # pylint: disable=consider-using-with
                ["python3", str(script)],
                cwd=str(lib.PROJECT_ROOT),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    session_id = payload.get("session_id", "")
    transcript = payload.get("transcript_path", "")
    if session_id:
        lib.save_current_session(session_id, transcript, payload.get("cwd", ""))
    start_poll_limit_background()

    if payload.get("source") == "resume":
        unfinished = [
            t["taskId"] for t in lib.load_tasks()["tasks"] if t.get("state") != lib.STATE_FINISHED
        ]
        if unfinished:
            context = (
                f"[task-skill] Unfinished tracked tasks: {', '.join(unfinished)}. "
                f"If you are continuing one of them, run "
                f"`python3 {lib.SCRIPT_DIR / 'task_tracker.py'} reattach <taskId>` "
                "so tracking follows this session, then resume the /task workflow."
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
