#!/usr/bin/env python3
"""Mid-task status snapshot for the status-report skill.

Answers four questions in one cheap read — what is the current task, progress as a
checklist, what is next, sub-agent/delegation status — from the tracking files the /task
pipeline already writes. The skill's defining behavior is speed under interruption: a
status request must never wait for the running task to finish, so every source degrades
independently (missing or corrupt reads render as "(not found)", never an error) and the
exit code is 0 on every reporting path. Usage errors still exit 2 via argparse.

Stdlib-only by design: the script ships into scaffolded consumer projects
(`.ai-badger/skills/status-report/scripts/`) where the framework's badger_lib does not
exist. All functions take the project root (`target`) as their first argument so tests can
run them against fixture directories.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

TRACKING = ".ai-badger/task-tracking"
TASKS_FILE = f"{TRACKING}/executed-tasks.json"
USAGE_FILE = f"{TRACKING}/token-usage.json"
SESSIONS_FILE = f"{TRACKING}/current-session.json"
PLANS_DIR = f"{TRACKING}/plans"
WORKTREES_DIR = ".ai-badger/worktrees"
STATE_FILE = ".ai-badger/state.json"

CHECKBOX_RE = re.compile(r"^[-*]\s+\[[ xX]\]\s+")
DONE_RE = re.compile(r"^[-*]\s+\[[xX]\]\s+")
PACKAGE_RE = re.compile(r"^\*\*(P\d+[^*]*)\*\*")

NO_TASK = "(no task in progress)"
NOT_FOUND = "(not found)"
NO_PLAN = "(no plan file)"
NO_LANES = "(no live lanes)"


# ---------------------------------------------------------------- file reads


def _read_json(path: Path) -> Optional[Any]:
    """The file's parsed JSON, or None when missing or corrupt — a report never fails."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- task state


def _load_tasks(target: Path) -> List[Dict[str, Any]]:
    """executed-tasks.json's task list, newest start first; [] when unreadable."""
    data = _read_json(target / TASKS_FILE)
    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    return sorted((t for t in tasks if isinstance(t, dict)),
                  key=lambda t: str(t.get("startedAt", "")), reverse=True)


def _in_progress(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The open tasks, latest-started first — the first of these is the current task."""
    return [t for t in tasks if t.get("state") == "IN_PROGRESS"]


def _last_finished(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The most recently started FINISHED task, for the nothing-in-progress fallback."""
    for task in tasks:
        if task.get("state") == "FINISHED":
            return task
    return None


# ---------------------------------------------------------------- plan checklist


def _plan_for(target: Path, task_id: str) -> Optional[Path]:
    """The plan file for a task: best filename-token match, else the newest plan, else None.

    Plan files are named `<date>-<slug>.md` and slugs drift from task ids, so a zero-score
    match still falls back to the newest file — reported with matched=False so the reader
    can sanity-check it instead of the report going silently wrong or silently empty.
    """
    plans_dir = target / PLANS_DIR
    try:
        files = sorted(p for p in plans_dir.iterdir() if p.is_file())
    except OSError:
        return None
    if not files:
        return None
    tokens = [t for t in task_id.split("-") if t]

    def score(path: Path) -> int:
        name = path.name.lower()
        return sum(1 for t in tokens if t in name)

    best = max(files, key=lambda p: (score(p), p.stat().st_mtime))
    return best


def plan_checklist(target: Path, task_id: str) -> Dict[str, Any]:
    """Progress evidence from the task's plan file: package headings + checkbox counts."""
    plan = _plan_for(target, task_id)
    if plan is None:
        return {"plan_file": None, "matched": False, "packages": [], "checked": 0, "total": 0}
    try:
        lines = plan.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"plan_file": str(plan), "matched": False, "packages": [],
                "checked": 0, "total": 0}
    packages = [m.group(1).strip() for line in lines if (m := PACKAGE_RE.match(line))]
    items = [line for line in lines if CHECKBOX_RE.match(line)]
    done = [line for line in items if DONE_RE.match(line)]
    return {"plan_file": str(plan), "matched": score_known(plan, task_id),
            "packages": packages, "checked": len(done), "total": len(items)}


def score_known(plan: Path, task_id: str) -> bool:
    """Whether the plan file actually matched the task id by tokens (vs newest-file fallback)."""
    return any(t in plan.name.lower() for t in task_id.split("-") if t)


# ---------------------------------------------------------------- delegation


def subagents_for(target: Path, task_id: str) -> List[Dict[str, Any]]:
    """token-usage.json's recorded subagent entries for one task ([] on anything missing)."""
    data = _read_json(target / USAGE_FILE)
    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    for task in tasks:
        if isinstance(task, dict) and task.get("taskId") == task_id:
            subs = task.get("subagents", [])
            return [s for s in subs if isinstance(s, dict)]
    return []


def live_lanes(target: Path, open_task_ids: List[str]) -> List[str]:
    """Worktrees belonging to open tasks, lane sub-worktrees included via taskId prefix.

    Worktrees of FINISHED tasks are stale leftovers, not live lanes, and are excluded —
    the main checkout routinely carries a dozen of them.
    """
    root = target / WORKTREES_DIR
    try:
        names = sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    lanes: List[str] = []
    for task_id in open_task_ids:
        lanes.extend(n for n in names if n == task_id or n.startswith(task_id + "-"))
    return sorted(set(lanes))


def live_sessions(target: Path) -> List[Dict[str, Any]]:
    """current-session.json's live sessions (pid/cwd/recordedAt), [] when unreadable."""
    data = _read_json(target / SESSIONS_FILE)
    sessions = data.get("sessions", {}) if isinstance(data, dict) else {}
    return [dict(v, session_id=k) for k, v in sessions.items() if isinstance(v, dict)]


def next_note(target: Path) -> Optional[str]:
    """state.json's `next` field — the cross-task queue — verbatim, None when absent."""
    data = _read_json(target / STATE_FILE)
    if isinstance(data, dict) and isinstance(data.get("next"), str) and data["next"].strip():
        return data["next"]
    return None


# ---------------------------------------------------------------- report


def report(target: Path) -> Dict[str, Any]:
    """The whole snapshot as data: current_task, progress, next, subagents, last_finished."""
    tasks = _load_tasks(target)
    open_tasks = _in_progress(tasks)
    current = open_tasks[0] if open_tasks else None
    task_id = str(current.get("taskId", "")) if current else ""
    return {
        "current_task": current,
        "other_open": [t.get("taskId") for t in open_tasks[1:]],
        "last_finished": _last_finished(tasks),
        "progress": plan_checklist(target, task_id) if task_id else
                    {"plan_file": None, "matched": False, "packages": [],
                     "checked": 0, "total": 0},
        "next": next_note(target),
        "subagents": {
            "recorded": subagents_for(target, task_id) if task_id else [],
            "live_lanes": live_lanes(target, [str(t.get("taskId", "")) for t in open_tasks]),
            "sessions": live_sessions(target),
        },
    }


def render(data: Dict[str, Any]) -> str:
    """The human-readable four-section report (plain text, one glance)."""
    out: List[str] = []
    out.append("== CURRENT TASK ==")
    current = data["current_task"]
    if current is None:
        out.append(NO_TASK)
        finished = data.get("last_finished")
        if finished:
            out.append(f"last finished: {finished.get('taskId')} — {finished.get('title')}")
    else:
        out.append(f"{current.get('taskId')} — {current.get('title')}")
        out.append(f"branch: {current.get('branch')}  started: {current.get('startedAt')}")
    for extra in data.get("other_open", []):
        out.append(f"(also open: {extra})")

    out.append("")
    out.append("== PROGRESS CHECKLIST ==")
    progress = data["progress"]
    if progress["plan_file"] is None:
        out.append(NO_PLAN)
    else:
        out.append(f"plan: {progress['plan_file']}")
        if not progress["matched"]:
            out.append("(plan matched by newest-file fallback — check it is this task's plan)")
        for package in progress["packages"]:
            out.append(f"  [package] {package}")
        if progress["total"]:
            out.append(f"checklist: {progress['checked']}/{progress['total']} done")
        else:
            out.append("no checkbox items in plan — read the plan file for point states")
    out.append("loop: prepare > analyze > plan > plan-review > implementation > review > "
               "fixes > pr > gates > close > reflect > merge")

    out.append("")
    out.append("== WHAT'S NEXT ==")
    out.append(data["next"] or NOT_FOUND)

    out.append("")
    out.append("== SUB-AGENTS & DELEGATION ==")
    recorded = data["subagents"]["recorded"]
    if recorded:
        for sub in recorded:
            out.append(f"recorded: {sub.get('description')} "
                       f"({sub.get('totalTokens')} tokens at {sub.get('at')})")
    else:
        out.append("recorded: none (empty here != no delegation running — records land on "
                   "completion only)")
    lanes = data["subagents"]["live_lanes"]
    out.append(f"live lanes: {', '.join(lanes) if lanes else NO_LANES}")
    sessions = data["subagents"]["sessions"]
    if sessions:
        for session in sessions:
            out.append(f"session: pid {session.get('pid')} cwd {session.get('cwd')} "
                       f"(recorded {session.get('recordedAt')})")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: print the report (or `--json`), exit 0 — a status report never fails hard."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default=".",
                        help="project root holding .ai-badger/ (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)
    data = report(Path(args.target))
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
