"""`--risk` has to reach the gate, or it is a flag that buys nothing (review finding A8).

`task_tracker.py start --risk` records the switch on the task; this script is the only thing
that reads it back, so every way it can answer wrong is a way the gate silently changes shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".lefthook" / "pre-push" / "risk_mode.py"


def _project(tmp_path, entries):
    tmp_path.mkdir(parents=True, exist_ok=True)
    """A scaffolded project whose tracker holds `entries`."""
    tracking = tmp_path / ".ai-badger" / "task-tracking"
    tracking.mkdir(parents=True)
    (tmp_path / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    (tracking / "executed-tasks.json").write_text(
        json.dumps({"tasks": entries}), encoding="utf-8")
    return tmp_path


def _ask(project, branch):
    done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(project),
                           "--branch", branch],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _task(**overrides):
    entry = {"taskId": "T-1", "branch": "feat/x", "risk": True, "state": "IN_PROGRESS"}
    entry.update(overrides)
    return entry


def test_it_names_the_task_when_the_branch_is_in_risk_mode(tmp_path):
    assert _ask(_project(tmp_path, [_task()]), "feat/x") == "T-1"


def test_it_is_silent_when_the_task_did_not_ask_for_risk(tmp_path):
    assert _ask(_project(tmp_path, [_task(risk=False)]), "feat/x") == ""


def test_it_is_silent_for_a_branch_with_no_task(tmp_path):
    assert _ask(_project(tmp_path, [_task()]), "feat/other") == ""


def test_it_is_silent_once_the_task_is_finished(tmp_path):
    """A finished task must not keep reducing the gate for whoever reuses its branch."""
    assert _ask(_project(tmp_path, [_task(state="FINISHED")]), "feat/x") == ""


def test_it_is_silent_when_the_project_tracks_nothing(tmp_path):
    (tmp_path / ".ai-badger").mkdir()
    assert _ask(tmp_path, "feat/x") == ""


@pytest.mark.parametrize("payload", ["{ not json", '{"tasks": "nope"}', '[]'])
def test_a_corrupt_tracker_reads_as_no_risk(tmp_path, payload):
    """Fail safe: an unreadable tracker runs the full gate, it does not reduce it."""
    tracking = tmp_path / ".ai-badger" / "task-tracking"
    tracking.mkdir(parents=True)
    (tracking / "executed-tasks.json").write_text(payload, encoding="utf-8")

    assert _ask(tmp_path, "feat/x") == ""


def test_an_empty_branch_name_is_never_a_match(tmp_path):
    """Detached HEAD reports no branch; an entry with `branch: ""` must not match it."""
    assert _ask(_project(tmp_path, [_task(branch="")]), "") == ""


def test_it_looks_where_the_tracker_actually_writes(load_script):
    """The layout is repeated, not imported; a silent divergence would read as `no risk`."""
    risk_mode = load_script(".lefthook/pre-push/risk_mode.py")
    tracker = load_script(".ai-badger/skills/task/scripts/tracker_lib.py")

    assert (risk_mode.executed_tasks_path(Path("/proj"))
            == tracker.compute_paths(Path("/proj"))["executed_tasks"])


def test_it_reads_the_checkout_tracker_from_inside_a_worktree(tmp_path):
    """0.88.6 collapsed a linked worktree onto its checkout; the query must land there too."""
    checkout = _project(tmp_path / "repo", [_task()])
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-qm", "root", "--allow-empty"], cwd=checkout, check=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH":
                            __import__("os").environ["PATH"], "HOME": str(tmp_path)})
    linked = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(linked)],
                   cwd=checkout, check=True)
    (linked / ".ai-badger").mkdir(exist_ok=True)
    (linked / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")

    assert _ask(linked, "feat/x") == "T-1"
