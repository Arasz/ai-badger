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
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import tracker_lib as lib


def scaffold_drift_notice(project_root: Path, plugin_root: Optional[str]) -> Optional[str]:
    """Return a one-line notice when the scaffold and the running plugin are different versions.

    Two local file reads, no network (ADR-0001 decision 5). Silent on match, on an
    unscaffolded project, and on any read error — a hook must never break session start,
    and a noisy hook gets ignored.
    """
    if not plugin_root:
        return None
    try:
        manifest = json.loads(
            (project_root / ".ai-badger" / "manifest.json").read_text(encoding="utf-8")
        )
        scaffold_version = manifest.get("frameworkVersion")
        plugin_version = (Path(plugin_root) / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not scaffold_version or not plugin_version or scaffold_version == plugin_version:
        return None
    return (
        f"[ai-badger] .ai-badger/ was scaffolded by {scaffold_version} but the running "
        f"plugin is {plugin_version}. Re-scaffold with welcome-ai-badger to realign, "
        f"then review the diff."
    )


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

    notices = []
    drift = scaffold_drift_notice(lib.PROJECT_ROOT, os.environ.get("CLAUDE_PLUGIN_ROOT"))
    if drift:
        notices.append(drift)

    if payload.get("source") == "resume":
        unfinished = [
            t["taskId"] for t in lib.load_tasks()["tasks"] if t.get("state") != lib.STATE_FINISHED
        ]
        if unfinished:
            notices.append(
                f"[task-skill] Unfinished tracked tasks: {', '.join(unfinished)}. "
                f"If you are continuing one of them, run "
                f"`python3 {lib.SCRIPT_DIR / 'task_tracker.py'} reattach <taskId>` "
                "so tracking follows this session, then resume the /task workflow."
            )

    if notices:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n".join(notices),
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
