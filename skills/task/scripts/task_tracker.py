#!/usr/bin/env python3
"""CLI for the /task skill: task lifecycle + token-usage tracking.

Commands:
  start <taskId> [--title T] [--branch B] [--no-cron]   register task, start token checkpoint
  finish <taskId>                                        finish checkpoint + usage calc (requires .ai-badger/state.json updated)
  grade <taskId> <0-5>                                   save the user's quality grade
  subagent <taskId> <totalTokens> [--description D]      record a completed subagent's token cost
  reattach <taskId>                                      point task at the current session (after resume)
  status                                                 print all tasks (state, tokens, grade)
  install-cron / uninstall-cron                          manage the 30-min resume cron job

Exit codes: 0 ok, 2 bad input, 3 finish blocked (.ai-badger/state.json not updated since task start).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import tracker_lib as lib

CRON_MARKER = "# task-skill-resume"


def _session_or_die(args) -> dict:
    session = {
        "sessionId": getattr(args, "session_id", None),
        "transcriptPath": getattr(args, "transcript_path", None),
    }
    if not session["sessionId"]:
        resolved = lib.resolve_own_session()
        session["sessionId"] = resolved.get("sessionId")
        session["transcriptPath"] = session["transcriptPath"] or resolved.get("transcriptPath")
    if not session["sessionId"]:
        print(
            "No session reference. CLAUDE_CODE_SESSION_ID isn't set and no active session in "
            "current-session.json matches this process's PID ancestry or cwd; pass "
            "--session-id/--transcript-path explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)
    return session


def cmd_start(args) -> int:
    session = _session_or_die(args)
    checkpoint = lib.make_checkpoint(session["transcriptPath"] or "")
    with lib.locked_store():
        tasks = lib.load_tasks()
        conflict = lib.find_other_entry_with_session(tasks, session["sessionId"], args.task_id)
        if conflict is not None and conflict.get("state") != lib.STATE_FINISHED:
            print(
                f"Session {session['sessionId']} is already attached to task {conflict['taskId']!r} "
                f"(state={conflict.get('state')}), which isn't finished yet. Refusing to also attach "
                f"it to {args.task_id!r} — this usually means current-session.json is stale (a hook "
                "didn't fire yet for the real new session). Pass --session-id/--transcript-path "
                "explicitly if this attachment is genuinely intended.",
                file=sys.stderr,
            )
            return 2
        entry = lib.find_entry(tasks, args.task_id)
        if entry is None:
            entry = {"taskId": args.task_id}
            tasks["tasks"].append(entry)
        if entry.get("state") == lib.STATE_FINISHED:
            print(f"Task {args.task_id} is already FINISHED; refusing to restart it.", file=sys.stderr)
            return 2
        entry.update(
            {
                "title": args.title or entry.get("title", ""),
                "sessionId": session["sessionId"],
                "transcriptPath": session["transcriptPath"],
                "cwd": str(lib.PROJECT_ROOT),
                "branch": args.branch or entry.get("branch", ""),
                "startedAt": entry.get("startedAt") or lib.now_iso(),
                "finishedAt": None,
                "state": entry.get("state") or lib.STATE_STARTED,
                "resumeCommand": f"claude --resume {session['sessionId']}",
                "resumeAttempts": entry.get("resumeAttempts", []),
            }
        )
        lib.save_json(lib.EXECUTED_TASKS, tasks)

        usage = lib.load_usage()
        usage_entry = lib.find_entry(usage, args.task_id)
        if usage_entry is None:
            usage_entry = {"taskId": args.task_id, "subagents": [], "grade": None}
            usage["tasks"].append(usage_entry)
        usage_entry["sessionId"] = session["sessionId"]
        checkpoints = usage_entry.setdefault("checkpoints", {})
        checkpoints.setdefault("start", checkpoint)  # keep the original start on re-runs
        checkpoints["latest"] = checkpoint
        lib.save_json(lib.TOKEN_USAGE, usage)

    print(
        json.dumps(
            {
                "taskId": args.task_id,
                "state": entry["state"],
                "sessionId": session["sessionId"],
                "startContextTokens": checkpoint["contextTokens"],
            }
        )
    )
    print(
        f"REMINDER (SKILL.md Phase 1 step 3): ask the user to run `/rename {args.task_id}` now, "
        "so this session's label matches the task. Do not skip this silently.",
        file=sys.stderr,
    )
    if not args.no_cron:
        install_cron(quiet=True)
    return 0


def cmd_finish(args) -> int:
    with lib.locked_store():
        tasks = lib.load_tasks()
        entry = lib.find_entry(tasks, args.task_id)
        if entry is None:
            print(f"Unknown task {args.task_id}. Run start first.", file=sys.stderr)
            return 2
        if not args.force and not lib.state_json_updated_since(entry["startedAt"]):
            print(
                f".ai-badger/state.json has not been modified since task start ({entry['startedAt']}). "
                "Update it with what this task changed/learned, then re-run finish "
                "(or pass --force if the task genuinely produced no new knowledge).",
                file=sys.stderr,
            )
            return 3

        checkpoint = lib.make_checkpoint(entry.get("transcriptPath") or "")
        entry["state"] = lib.STATE_FINISHED
        entry["finishedAt"] = lib.now_iso()
        entry["stateJsonUpdated"] = lib.state_json_updated_since(entry["startedAt"])
        lib.save_json(lib.EXECUTED_TASKS, tasks)

        usage = lib.load_usage()
        usage_entry = lib.find_entry(usage, args.task_id)
        if usage_entry is None:
            usage_entry = {"taskId": args.task_id, "subagents": [], "grade": None, "checkpoints": {}}
            usage["tasks"].append(usage_entry)
        checkpoints = usage_entry.setdefault("checkpoints", {})
        checkpoints["finish"] = checkpoint
        checkpoints["latest"] = checkpoint
        start_cp = checkpoints.get("start", checkpoint)
        usage_entry["usage"] = lib.compute_usage(start_cp, checkpoint, usage_entry.get("subagents", []))
        lib.save_json(lib.TOKEN_USAGE, usage)

    stats = lib.claude_md_stats()
    print(
        json.dumps(
            {
                "taskId": args.task_id,
                "state": lib.STATE_FINISHED,
                "usage": usage_entry["usage"],
                "claudeMd": {"overBudget": stats["overBudget"], "chars": stats["chars"], "lines": stats["lines"]},
            },
            indent=2,
        )
    )
    if stats["overBudget"]:
        print(
            f"CLAUDE.md is over budget ({stats['chars']} chars / {stats['lines']} lines, "
            f"limits {stats['maxChars']}/{stats['maxLines']}). Compact it now per the skill's compaction rules.",
            file=sys.stderr,
        )
    return 0


def cmd_grade(args) -> int:
    if not 0 <= args.grade <= 5:
        print("Grade must be 0-5.", file=sys.stderr)
        return 2
    with lib.locked_store():
        usage = lib.load_usage()
        entry = lib.find_entry(usage, args.task_id)
        if entry is None:
            print(f"Unknown task {args.task_id}.", file=sys.stderr)
            return 2
        entry["grade"] = args.grade
        entry["gradedAt"] = lib.now_iso()
        lib.save_json(lib.TOKEN_USAGE, usage)
    print(f"Grade {args.grade}/5 saved for {args.task_id}.")
    return 0


def cmd_subagent(args) -> int:
    with lib.locked_store():
        usage = lib.load_usage()
        entry = lib.find_entry(usage, args.task_id)
        if entry is None:
            print(f"Unknown task {args.task_id}. Run start first.", file=sys.stderr)
            return 2
        entry.setdefault("subagents", []).append(
            {"description": args.description or "", "totalTokens": args.total_tokens, "at": lib.now_iso()}
        )
        # Recompute usage even if `finish` already ran — review-fix rounds and other subagent
        # work routinely land after the finish checkpoint, and usage must not go stale then.
        checkpoints = entry.get("checkpoints", {})
        start_cp = checkpoints.get("start")
        end_cp = checkpoints.get("finish") or checkpoints.get("latest")
        if start_cp and end_cp:
            entry["usage"] = lib.compute_usage(start_cp, end_cp, entry["subagents"])
        lib.save_json(lib.TOKEN_USAGE, usage)
    print(f"Recorded {args.total_tokens} subagent tokens for {args.task_id}.")
    return 0


def cmd_reattach(args) -> int:
    session = _session_or_die(args)
    with lib.locked_store():
        tasks = lib.load_tasks()
        conflict = lib.find_other_entry_with_session(tasks, session["sessionId"], args.task_id)
        if conflict is not None and conflict.get("state") != lib.STATE_FINISHED:
            print(
                f"Session {session['sessionId']} is already attached to task {conflict['taskId']!r} "
                f"(state={conflict.get('state')}), which isn't finished yet. Refusing to also reattach "
                f"{args.task_id!r} to it — this usually means current-session.json is stale. Pass "
                "--session-id/--transcript-path explicitly if this attachment is genuinely intended.",
                file=sys.stderr,
            )
            return 2
        entry = lib.find_entry(tasks, args.task_id)
        if entry is None:
            print(f"Unknown task {args.task_id}.", file=sys.stderr)
            return 2
        entry["sessionId"] = session["sessionId"]
        entry["transcriptPath"] = session["transcriptPath"]
        entry["resumeCommand"] = f"claude --resume {session['sessionId']}"
        if entry.get("state") != lib.STATE_FINISHED:
            entry["state"] = lib.STATE_IN_PROGRESS
        lib.save_json(lib.EXECUTED_TASKS, tasks)
    print(f"Task {args.task_id} reattached to session {session['sessionId']}.")
    return 0


def cmd_status(_args) -> int:
    tasks = lib.load_tasks()["tasks"]
    usage = lib.load_usage()
    if not tasks:
        print("No tracked tasks.")
        return 0
    for entry in tasks:
        usage_entry = lib.find_entry(usage, entry["taskId"]) or {}
        usage_stats = usage_entry.get("usage") or {}
        totals = usage_stats.get("grandTotal")
        cache_eff = usage_stats.get("cacheEfficiency")
        grade = usage_entry.get("grade")
        print(
            f"{entry['taskId']:<12} {entry.get('state', '?'):<12} "
            f"started={entry.get('startedAt', '-')} finished={entry.get('finishedAt') or '-'} "
            f"tokens={totals if totals is not None else '-'} "
            f"cacheEff={cache_eff if cache_eff is not None else '-'} "
            f"grade={grade if grade is not None else '-'}"
        )
    return 0


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def install_cron(quiet: bool = False) -> int:
    current = _current_crontab()
    if CRON_MARKER in current:
        if not quiet:
            print("Resume cron job already installed.")
        return 0
    script = lib.SCRIPT_DIR / "resume_cron.py"
    log = lib.DATA_DIR / "resume.log"
    lib.ensure_data_dir()
    line = f"*/30 * * * * /usr/bin/env python3 {script} run >> {log} 2>&1 {CRON_MARKER}\n"
    new_tab = current + ("" if current.endswith("\n") or not current else "\n") + line
    result = subprocess.run(["crontab", "-"], input=new_tab, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Failed to install cron job: {result.stderr}", file=sys.stderr)
        return 1
    if not quiet:
        print("Installed 30-min resume cron job.")
    return 0


def uninstall_cron() -> int:
    current = _current_crontab()
    kept = [line for line in current.splitlines() if CRON_MARKER not in line]
    result = subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Failed to update crontab: {result.stderr}", file=sys.stderr)
        return 1
    print("Resume cron job removed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_session_args(p):
        p.add_argument("--session-id")
        p.add_argument("--transcript-path")

    p_start = sub.add_parser("start")
    p_start.add_argument("task_id")
    p_start.add_argument("--title", default="")
    p_start.add_argument("--branch", default="")
    p_start.add_argument("--no-cron", action="store_true")
    add_session_args(p_start)

    p_finish = sub.add_parser("finish")
    p_finish.add_argument("task_id")
    p_finish.add_argument("--force", action="store_true")

    p_grade = sub.add_parser("grade")
    p_grade.add_argument("task_id")
    p_grade.add_argument("grade", type=int)

    p_sub = sub.add_parser("subagent")
    p_sub.add_argument("task_id")
    p_sub.add_argument("total_tokens", type=int)
    p_sub.add_argument("--description", default="")

    p_re = sub.add_parser("reattach")
    p_re.add_argument("task_id")
    add_session_args(p_re)

    sub.add_parser("status")
    sub.add_parser("install-cron")
    sub.add_parser("uninstall-cron")

    args = parser.parse_args()
    if args.command == "start":
        return cmd_start(args)
    if args.command == "finish":
        return cmd_finish(args)
    if args.command == "grade":
        return cmd_grade(args)
    if args.command == "subagent":
        return cmd_subagent(args)
    if args.command == "reattach":
        return cmd_reattach(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "install-cron":
        return install_cron()
    if args.command == "uninstall-cron":
        return uninstall_cron()
    return 2


if __name__ == "__main__":
    sys.exit(main())
