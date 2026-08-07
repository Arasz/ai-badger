#!/usr/bin/env python3
"""Print the id of the task that put this branch into `--risk` mode, or nothing.

`task_tracker.py start --risk` records the switch on the task entry; verify.sh reads it back
through this script to decide whether to run the reduced lane list (skills/task/SKILL.md).

Fail safe in every direction: an absent, unreadable or unexpected tracker prints nothing, and
nothing means the full gate. Exit status is always 0 — this reports, it never gates.

Usage: risk_mode.py --root <project-root> --branch <name>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# engine/ is this repo, not a scaffolded tree, so `run_git` is importable here — and this is the
# one script that runs inside a git hook, where GIT_DIR is exported (docs/changelog/0.103.0-*).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import badger_lib as bl  # noqa: E402  # pylint: disable=wrong-import-position

# The tracker's own layout, repeated rather than imported: this runs before any lane and must
# not depend on a scaffolded tree. tests/test_risk_mode.py pins both spellings together.
TRACKING_DIR = (".ai-badger", "task-tracking")
EXECUTED_TASKS = "executed-tasks.json"
FINISHED = "FINISHED"


def executed_tasks_path(project_root: Path) -> Path:
    """Where the task tracker keeps its entries for `project_root`."""
    return project_root.joinpath(*TRACKING_DIR, EXECUTED_TASKS)


def collapse_worktree(project: Path) -> Path:
    """The checkout a linked worktree belongs to, or *project* unchanged (mirrors tracker_lib).

    A task worktree carries its own `.ai-badger/config.json`, so without this the query reads
    an empty store and every risk task silently reverts to the full gate.
    """
    try:
        common = bl.run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], project)
    except OSError:
        return project
    if common.returncode != 0 or not common.stdout.strip():
        return project
    checkout = Path(common.stdout.strip()).parent
    if checkout == project or not (checkout / ".ai-badger" / "config.json").is_file():
        return project
    return checkout


def load_entries(project_root: Path) -> list:
    """The tracker's task entries; empty for anything this script cannot read as such."""
    try:
        data = json.loads(executed_tasks_path(project_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    tasks = data.get("tasks")
    return tasks if isinstance(tasks, list) else []


def risk_task(project_root: Path, branch: str) -> Optional[str]:
    """The id of the unfinished risk-mode task on `branch`, or None."""
    if not branch:
        return None
    for entry in load_entries(project_root):
        if not isinstance(entry, dict):
            continue
        if entry.get("branch") != branch or not entry.get("risk"):
            continue
        if entry.get("state") == FINISHED:
            continue
        return str(entry.get("taskId") or "")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="project root to read the tracker from")
    parser.add_argument("--branch", default="", help="branch being pushed")
    args = parser.parse_args()

    task = risk_task(collapse_worktree(Path(args.root).resolve()), args.branch)
    if task:
        print(task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
