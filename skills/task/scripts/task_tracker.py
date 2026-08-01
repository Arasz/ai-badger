#!/usr/bin/env python3
"""CLI for the /task skill: task lifecycle + token-usage tracking.

Commands:
  start <taskId> [--title T] [--branch B] [--no-cron]
      register task, start token checkpoint
  finish <taskId>
      finish checkpoint + usage calc (requires .ai-badger/state.json updated)
  grade <taskId> <0-5>
      save the user's quality grade
  subagent <taskId> <totalTokens> [--description D]
      record a completed subagent's token cost
  reattach <taskId>
      point task at the current session (after resume)
  status
      print all tasks (state, tokens, grade)
  install-cron / uninstall-cron
      manage the 30-min resume cron job

Exit codes: 0 ok, 2 bad input, 3 finish blocked (.ai-badger/state.json not updated since
task start).
"""
# pylint: disable=missing-function-docstring
# Ported verbatim from the originating job-search-ai-assistant repo's /task skill: kept in
# lockstep with that source rather than churned for local docstring style rules.

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys

import tracker_lib as lib

CRON_MARKER = "# task-skill-resume"
_NO_CRONTAB_MARKER = "no crontab for"


class CrontabUnavailable(Exception):
    """The current crontab could not be read, or the `crontab` binary is missing.

    Never treat this as "the crontab is empty" — doing so is what turns a transient read
    failure into an overwrite of the user's real cron jobs.
    """


WORKTREE_DIR = ".claude/worktrees"


def _git(root, *args, check=True):
    """Run git in `root` and return stdout. Returns '' when check is False and git fails."""
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0 and check:
        raise subprocess.CalledProcessError(result.returncode, result.args,
                                            result.stdout, result.stderr)
    return result.stdout if result.returncode == 0 else ""


def worktree_path(root, task_id):
    """Where a task's worktree lives. One per task, named by the task id."""
    return lib.Path(root) / WORKTREE_DIR / str(task_id)


def ensure_worktree(root, task_id, branch):
    """Create (or adopt) the task's worktree on `branch`. Returns its path, or None.

    None when no branch was recorded: a task that did not ask for one does not get one
    invented for it. Idempotent, so a resumed task re-running `start` is not an error.
    """
    if not branch:
        return None
    path = worktree_path(root, task_id)
    if path.is_dir():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _git(root, "rev-parse", "--verify", "--quiet", branch, check=False).strip()
    args = ["worktree", "add"] + ([] if existing else ["-b", branch])
    args += [str(path)] + ([branch] if existing else [])
    _git(root, *args)
    return path


def worktree_blockers(path):
    """Reasons this worktree must not be removed: uncommitted files, then unmerged commits.

    Checked in that order because the first is what a person recognises. An empty list means
    every change in here also exists somewhere else, so removing it loses nothing.
    """
    if not path or not lib.Path(path).is_dir():
        return []
    blockers = []
    dirty = _git(path, "status", "--porcelain", check=False).strip()
    if dirty:
        names = ", ".join(line[3:] for line in dirty.splitlines()[:5])
        blockers.append(f"uncommitted changes: {names}")
    head = _git(path, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if head:
        # Commits reachable from HEAD and from nowhere else — not on a remote, and not on any
        # other local branch. Excluding both matters: `--not --remotes` alone calls every commit
        # unique in a repo with no remote, and omitting other locals would flag a branch whose
        # work is already merged. What is left is the set that disappears with this directory.
        others = [b for b in _git(path, "branch", "--format=%(refname:short)",
                                  check=False).split() if b != head]
        only_here = _git(path, "log", "HEAD", "--not", "--remotes", *others, "--oneline",
                         check=False).strip()
        if only_here:
            blockers.append(
                f"{len(only_here.splitlines())} commit(s) on {head} and nowhere else")
    return blockers


def release_worktree(root, task_id):
    """Remove the task's worktree. Returns (removed, reason-it-was-kept).

    Refuses rather than forcing: a worktree holding the only copy of a change is the one case
    where cleanup is indistinguishable from data loss. (False, "") means there was nothing to
    remove, which is not a failure — `finish` runs whether or not `start` made one.
    """
    path = worktree_path(root, task_id)
    if not path.is_dir():
        return False, ""
    blockers = worktree_blockers(path)
    if blockers:
        return False, "; ".join(blockers)
    _git(root, "worktree", "remove", str(path))
    return True, ""


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
                f"Session {session['sessionId']} is already attached to task "
                f"{conflict['taskId']!r} (state={conflict.get('state')}), which isn't finished "
                f"yet. Refusing to also attach it to {args.task_id!r} — this usually means "
                "current-session.json is stale (a hook didn't fire yet for the real new "
                "session). Pass --session-id/--transcript-path explicitly if this attachment "
                "is genuinely intended.",
                file=sys.stderr,
            )
            return 2
        entry = lib.find_entry(tasks, args.task_id)
        if entry is None:
            entry = {"taskId": args.task_id}
            tasks["tasks"].append(entry)
        if entry.get("state") == lib.STATE_FINISHED:
            print(
                f"Task {args.task_id} is already FINISHED; refusing to restart it.",
                file=sys.stderr,
            )
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

    # Outside the lock: this shells out to git, and holding the store lock across it would let a
    # slow checkout block every other tracker call.
    if not args.no_worktree:
        try:
            created = ensure_worktree(lib.PROJECT_ROOT, args.task_id, entry.get("branch", ""))
        except subprocess.CalledProcessError as exc:
            print(f"could not create the task worktree: {exc.stderr or exc}", file=sys.stderr)
            created = None
        if created is not None:
            print(f"worktree: {created}")

    if args.no_cron:
        print(
            "--no-cron is deprecated and is now a no-op: cron installation is opt-in via "
            "--cron.",
            file=sys.stderr,
        )
    if args.cron:
        install_cron(quiet=True)

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
                ".ai-badger/state.json has not been modified since task start "
                f"({entry['startedAt']}). Update it with what this task changed/learned, "
                "then re-run finish (or pass --force if the task genuinely produced no new "
                "knowledge).",
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
            usage_entry = {
                "taskId": args.task_id, "subagents": [], "grade": None, "checkpoints": {},
            }
            usage["tasks"].append(usage_entry)
        checkpoints = usage_entry.setdefault("checkpoints", {})
        checkpoints["finish"] = checkpoint
        checkpoints["latest"] = checkpoint
        start_cp = checkpoints.get("start", checkpoint)
        usage_entry["usage"] = lib.compute_usage(
            start_cp, checkpoint, usage_entry.get("subagents", [])
        )
        lib.save_json(lib.TOKEN_USAGE, usage)

    worktree = {"removed": False, "keptBecause": ""}
    if not args.keep_worktree:
        try:
            removed, reason = release_worktree(lib.PROJECT_ROOT, args.task_id)
        except subprocess.CalledProcessError as exc:
            removed, reason = False, str(exc.stderr or exc)
        worktree = {"removed": removed, "keptBecause": reason}
        if reason:
            print(f"kept the task worktree — {reason}", file=sys.stderr)

    stats = lib.claude_md_stats()
    print(
        json.dumps(
            {
                "taskId": args.task_id,
                "state": lib.STATE_FINISHED,
                "worktree": worktree,
                "usage": usage_entry["usage"],
                "claudeMd": {
                    "overBudget": stats["overBudget"],
                    "chars": stats["chars"],
                    "lines": stats["lines"],
                },
            },
            indent=2,
        )
    )
    if stats["overBudget"]:
        print(
            f"CLAUDE.md is over budget ({stats['chars']} chars / {stats['lines']} lines, "
            f"limits {stats['maxChars']}/{stats['maxLines']}). Compact it now per the "
            "skill's compaction rules.",
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
        entry.setdefault("subagents", []).append({
            "description": args.description or "",
            "totalTokens": args.total_tokens,
            "at": lib.now_iso(),
        })
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
                f"Session {session['sessionId']} is already attached to task "
                f"{conflict['taskId']!r} (state={conflict.get('state')}), which isn't finished "
                f"yet. Refusing to also reattach {args.task_id!r} to it — this usually means "
                "current-session.json is stale. Pass --session-id/--transcript-path explicitly "
                "if this attachment is genuinely intended.",
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


def _format_mix(model_mix) -> str:
    """Shortest honest rendering of the model mix: the biggest share and its model."""
    if not model_mix:
        return "-"
    model, share = max(model_mix.items(), key=lambda kv: kv[1])
    return f"{model.replace('claude-', '')}:{share:.0%}"


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
            f"mix={_format_mix(usage_stats.get('modelMix'))} "
            f"grade={grade if grade is not None else '-'}"
        )
    return 0


def _run_crontab(argv: list, **kwargs):
    """subprocess.run wrapper for crontab invocations: a missing binary is a reported
    condition (`CrontabUnavailable`), never a traceback.
    """
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=False, **kwargs)
    except FileNotFoundError as exc:
        raise CrontabUnavailable(f"crontab executable not found: {exc}") from exc


def _current_crontab() -> str:
    """Return the user's current crontab text, or "" if they genuinely have none yet.

    Raises `CrontabUnavailable` for every other failure — a read failure must never be
    conflated with an empty crontab, since the caller may go on to write an authoritative
    replacement computed from this value.
    """
    result = _run_crontab(["crontab", "-l"])
    if result.returncode == 0:
        return result.stdout
    stderr = (result.stderr or "").strip()
    if _NO_CRONTAB_MARKER in stderr.lower():
        return ""
    raise CrontabUnavailable(stderr or f"crontab -l exited with status {result.returncode}")


def _desired_cron_line() -> str:
    script = shlex.quote(_cron_escape(str(lib.SCRIPT_DIR / "resume_cron.py")))
    log = shlex.quote(_cron_escape(str(lib.DATA_DIR / "resume.log")))
    return f"*/30 * * * * /usr/bin/env python3 {script} run >> {log} 2>&1 {CRON_MARKER}"


def _cron_escape(value: str) -> str:
    """Escape `%` for a crontab command field.

    cron(5): an unescaped `%` in the command is turned into a newline, and everything after
    it is sent to the command as stdin — a `%` in an interpolated path would silently
    truncate the job.
    """
    return value.replace("%", r"\%")


def install_cron(quiet: bool = False) -> int:
    """Install the resume cron job, correcting a stale marker line rather than skipping it.

    A marker line whose generated command no longer matches the current script/log paths
    (e.g. the skill moved on disk) is replaced in place, since the marker check alone would
    otherwise leave a dead cron entry pointing at a script that no longer exists.
    """
    try:
        current = _current_crontab()
    except CrontabUnavailable as exc:
        print(f"Not installing resume cron job: {exc}", file=sys.stderr)
        return 1
    desired_line = _desired_cron_line()
    lines = current.splitlines()
    marker_indices = [i for i, line in enumerate(lines) if CRON_MARKER in line]

    if marker_indices and all(lines[i] == desired_line for i in marker_indices):
        if not quiet:
            print("Resume cron job already installed.")
        return 0

    lib.ensure_data_dir()
    if marker_indices:
        new_lines = list(lines)
        first = marker_indices[0]
        new_lines[first] = desired_line
        for i in reversed(marker_indices[1:]):
            del new_lines[i]
        verb = "Updated"
    else:
        new_lines = lines + [desired_line]
        verb = "Installed"
    new_tab = "\n".join(new_lines) + "\n"
    try:
        result = _run_crontab(["crontab", "-"], input=new_tab)
    except CrontabUnavailable as exc:
        print(f"Not installing resume cron job: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"Failed to install cron job: {result.stderr}", file=sys.stderr)
        return 1
    if not quiet:
        print(f"{verb} 30-min resume cron job.")
    return 0


def uninstall_cron() -> int:
    try:
        current = _current_crontab()
    except CrontabUnavailable as exc:
        print(f"Not modifying crontab: {exc}", file=sys.stderr)
        return 1
    kept = [line for line in current.splitlines() if CRON_MARKER not in line]
    try:
        result = _run_crontab(["crontab", "-"], input="\n".join(kept) + "\n")
    except CrontabUnavailable as exc:
        print(f"Not modifying crontab: {exc}", file=sys.stderr)
        return 1
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
    p_start.add_argument(
        "--cron", action="store_true",
        help="Install the 30-min resume cron job (opt-in).",
    )
    p_start.add_argument(
        "--no-cron", action="store_true",
        help="Deprecated no-op: cron installation is opt-in via --cron now.",
    )
    p_start.add_argument(
        "--no-worktree", action="store_true",
        help="Record the branch without creating a worktree for it.",
    )
    add_session_args(p_start)

    p_finish = sub.add_parser("finish")
    p_finish.add_argument("task_id")
    p_finish.add_argument("--force", action="store_true")
    p_finish.add_argument(
        "--keep-worktree", action="store_true",
        help="Leave the task's worktree on disk instead of removing it.",
    )

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
