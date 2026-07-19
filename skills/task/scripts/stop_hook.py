#!/usr/bin/env python3
"""Stop hook: continuous token checkpoints + end-of-task enforcement.

Every time the main agent stops:
1. Update the `latest` token checkpoint for any unfinished task tied to this
   session (so token-usage.json stays fresh even if the session dies abruptly).
2. Promote STARTED -> IN_PROGRESS (first stop means real work happened).
3. Enforcement net: if a task tied to this session was FINISHED but
   .ai-badger/state.json was never touched during the task, or CLAUDE.md is over
   its size budget, block the stop once and tell the model what to do.
   `stop_hook_active` and a per-task reminder flag prevent infinite loops.
"""
# pylint: disable=missing-function-docstring
# Ported verbatim from the originating job-search-ai-assistant repo's /task skill: kept in
# lockstep with that source rather than churned for local docstring style rules.

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker_lib as lib


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    session_id = payload.get("session_id", "")
    transcript = payload.get("transcript_path", "")
    if not session_id:
        return 0

    block_reasons = []
    with lib.locked_store():
        tasks = lib.load_tasks()
        usage = lib.load_usage()
        tasks_dirty = usage_dirty = False

        for entry in tasks["tasks"]:
            if entry.get("sessionId") != session_id:
                continue

            if entry.get("state") in (lib.STATE_STARTED, lib.STATE_IN_PROGRESS):
                checkpoint = lib.make_checkpoint(transcript)
                usage_entry = lib.find_entry(usage, entry["taskId"])
                if usage_entry is not None:
                    usage_entry.setdefault("checkpoints", {})["latest"] = checkpoint
                    usage_dirty = True
                if entry["state"] == lib.STATE_STARTED:
                    entry["state"] = lib.STATE_IN_PROGRESS
                    tasks_dirty = True

            elif entry.get("state") == lib.STATE_FINISHED and not payload.get("stop_hook_active"):
                if not entry.get("stateJsonUpdated") and not entry.get("stateJsonReminderSent"):
                    if lib.state_json_updated_since(entry["startedAt"]):
                        entry["stateJsonUpdated"] = True
                    else:
                        entry["stateJsonReminderSent"] = True
                        block_reasons.append(
                            f"Task {entry['taskId']} finished but .ai-badger/state.json was not "
                            "updated. Add what this task changed/learned to it now."
                        )
                    tasks_dirty = True
                stats = lib.claude_md_stats()
                if stats["overBudget"] and not entry.get("compactionReminderSent"):
                    entry["compactionReminderSent"] = True
                    tasks_dirty = True
                    block_reasons.append(
                        f"CLAUDE.md is over its size budget ({stats['chars']} chars / "
                        f"{stats['lines']} lines; limits {stats['maxChars']} chars / "
                        f"{stats['maxLines']} lines). Compact it: drop anything derivable from "
                        "code/git/docs — per-task state belongs in .ai-badger/state.json, not here."
                    )

        if tasks_dirty:
            lib.save_json(lib.EXECUTED_TASKS, tasks)
        if usage_dirty:
            lib.save_json(lib.TOKEN_USAGE, usage)

    if block_reasons:
        print(json.dumps({"decision": "block", "reason": " ".join(block_reasons)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
