"""The status-report script: a mid-task snapshot a status request can answer from in seconds.

The skill's whole point is speed under interruption: the report degrades per source (missing,
corrupt) instead of failing, always exits 0, and answers four questions — current task,
progress as a checklist, what is next, sub-agent/delegation status.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import _test_write

SCRIPT = "features/common/skills/status-report/scripts/status_report.py"

TT = ".ai-badger/task-tracking"


def _write(target: Path, rel: str, payload) -> None:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        _test_write(path, payload, encoding="utf-8")
    else:
        _test_write(path, json.dumps(payload), encoding="utf-8")


def _task(task_id: str, state: str, started: str, title: str = "") -> dict:
    return {"taskId": task_id, "state": state, "startedAt": started,
            "title": title or task_id, "branch": f"task/{task_id}"}


def _seed(target: Path, tasks: list, *, usage=None, sessions=None, next_note=None) -> None:
    _write(target, f"{TT}/executed-tasks.json", {"tasks": tasks})
    if usage is not None:
        _write(target, f"{TT}/token-usage.json", {"tasks": usage})
    if sessions is not None:
        _write(target, f"{TT}/current-session.json", {"sessions": sessions})
    if next_note is not None:
        _write(target, ".ai-badger/state.json", {"next": next_note})


def _run(load_script, target, argv=None):
    module = load_script(SCRIPT)
    rc = module.main(["--target", str(target), *(argv or [])])
    return module, rc


# ---------------------------------------------------------------- degradation


class TestDegradesGracefully:
    def test_an_empty_project_answers_with_placeholders_and_exit_zero(self, load_script,
                                                                      tmp_path, capsys):
        _, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "CURRENT TASK" in out
        assert "(no task in progress)" in out
        assert "WHAT'S NEXT" in out
        assert "SUB-AGENTS" in out

    def test_corrupt_json_files_never_crash_the_report(self, load_script, tmp_path, capsys):
        _write(tmp_path, f"{TT}/executed-tasks.json", "{not json")
        _write(tmp_path, ".ai-badger/state.json", "][")

        module, rc = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert rc == 0
        assert data["current_task"] is None
        assert data["next"] is None


# ---------------------------------------------------------------- current task


class TestCurrentTask:
    def test_the_latest_started_in_progress_task_is_current(self, load_script, tmp_path,
                                                            capsys):
        _seed(tmp_path, [
            _task("old-one", "FINISHED", "2026-08-28T08:00:00+00:00"),
            _task("incident-guard", "IN_PROGRESS", "2026-08-28T08:29:00+00:00"),
            _task("newer-task", "IN_PROGRESS", "2026-08-28T10:04:00+00:00"),
        ])

        module, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert module.report(tmp_path)["current_task"]["taskId"] == "newer-task"
        assert "newer-task" in out
        assert "incident-guard" in out  # the other open task stays visible

    def test_no_in_progress_falls_back_to_the_last_finished_task(self, load_script, tmp_path):
        _seed(tmp_path, [_task("done-thing", "FINISHED", "2026-08-28T08:00:00+00:00")])

        module, _ = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert data["current_task"] is None
        assert data["last_finished"]["taskId"] == "done-thing"


# ---------------------------------------------------------------- progress checklist


class TestProgressChecklist:
    def test_checkboxes_and_package_headings_are_parsed_from_the_plan(self, load_script,
                                                                      tmp_path):
        _seed(tmp_path, [_task("aib-do-a-thing-now", "IN_PROGRESS",
                               "2026-08-29T08:00:00+00:00")])
        plan = ("# Plan — aib-do-a-thing-now\n\n## Packages\n\n"
                "**P1 one (RUNNING):** do it\n- [x] first point\n- [ ] second point\n\n"
                "**P2 two:** the rest\n- [ ] third point\n")
        _write(tmp_path, f"{TT}/plans/2026-08-29-aib-do-a-thing-now.md", plan)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["plan_file"].endswith("aib-do-a-thing-now.md")
        assert progress["checked"] == 1
        assert progress["total"] == 3
        assert progress["packages"] == ["P1 one (RUNNING):", "P2 two:"]

    def test_no_plan_file_and_a_plan_without_checkboxes_read_differently(self, load_script,
                                                                         tmp_path):
        _seed(tmp_path, [_task("aib-no-plan-task", "IN_PROGRESS",
                               "2026-08-29T08:00:00+00:00")])

        module, _ = _run(load_script, tmp_path)
        absent = module.report(tmp_path)["progress"]

        _write(tmp_path, f"{TT}/plans/2026-08-29-other.md", "**P1 one:** items only\n")
        no_checkboxes = module.report(tmp_path)["progress"]

        assert absent["plan_file"] is None
        assert no_checkboxes["plan_file"] is not None
        assert no_checkboxes["checked"] == 0 and no_checkboxes["total"] == 0
        assert no_checkboxes["packages"] == ["P1 one:"]


# ---------------------------------------------------------------- next


class TestNext:
    def test_state_json_next_is_surfaced_verbatim(self, load_script, tmp_path):
        note = "(1) ship the resolver; (2) pi stack parity; (3) stop passing projectId."
        _seed(tmp_path, [], next_note=note)

        module, _ = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert data["next"] == note
        assert note in _run(load_script, tmp_path)[0].report(tmp_path)["next"]


# ---------------------------------------------------------------- sub-agents & delegation


class TestSubagentsAndDelegation:
    def test_recorded_subagents_for_the_current_task_are_listed(self, load_script, tmp_path):
        _seed(tmp_path, [_task("aib-lane-task", "IN_PROGRESS", "2026-08-29T08:00:00+00:00")],
              usage=[{"taskId": "other", "subagents": [{"description": "not this task",
                                                        "totalTokens": 5, "at": "x"}]},
                     {"taskId": "aib-lane-task",
                      "subagents": [{"description": "research lane", "totalTokens": 12345,
                                     "at": "2026-08-29T09:00:00+00:00"}]}])

        module, _ = _run(load_script, tmp_path)
        subs = module.report(tmp_path)["subagents"]

        assert subs["recorded"][0]["description"] == "research lane"
        assert subs["recorded"][0]["totalTokens"] == 12345

    def test_live_lanes_list_open_task_worktrees_only(self, load_script, tmp_path):
        _seed(tmp_path, [_task("incident-guard", "IN_PROGRESS", "2026-08-28T08:29:00+00:00"),
                         _task("old-finished", "FINISHED", "2026-08-28T07:00:00+00:00")])
        for name in ("incident-guard", "incident-guard-lane-a", "old-finished",
                     "some-other-finished"):
            (tmp_path / ".ai-badger" / "worktrees" / name).mkdir(parents=True)

        module, _ = _run(load_script, tmp_path)
        lanes = module.report(tmp_path)["subagents"]["live_lanes"]

        assert sorted(lanes) == ["incident-guard", "incident-guard-lane-a"]

    def test_a_prefix_sibling_worktree_is_not_a_live_lane(self, load_script, tmp_path):
        """An open task 'a-b' must not claim a finished task's 'a-b-skill' worktree."""
        _seed(tmp_path, [_task("aib-do", "IN_PROGRESS", "2026-08-29T08:00:00+00:00")])
        for name in ("aib-do", "aib-do-skill", "aib-do-not-a-lane"):
            (tmp_path / ".ai-badger" / "worktrees" / name).mkdir(parents=True)

        module, _ = _run(load_script, tmp_path)

        assert module.report(tmp_path)["subagents"]["live_lanes"] == ["aib-do"]

    def test_no_live_lanes_states_it(self, load_script, tmp_path):
        _seed(tmp_path, [_task("aib-alone", "IN_PROGRESS", "2026-08-29T08:00:00+00:00")])

        module, _ = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert data["subagents"]["live_lanes"] == []
        assert "(no live lanes)" in module.render(data)

    def test_the_newest_file_fallback_is_marked_as_unmatched(self, load_script, tmp_path):
        """When no plan filename carries the task id, the report says so."""
        _seed(tmp_path, [_task("aib-unique-nomatch", "IN_PROGRESS",
                               "2026-08-29T08:00:00+00:00")])
        _write(tmp_path, f"{TT}/plans/2026-08-29-wholly-different.md",
               "**P1 one:** something\n- [x] done\n")

        module, _ = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert data["progress"]["matched"] is False
        assert "newest-file fallback" in module.render(data)


# ---------------------------------------------------------------- json mode


class TestJsonMode:
    def test_json_flag_emits_the_four_sections(self, load_script, tmp_path, capsys):
        _seed(tmp_path, [_task("aib-json-task", "IN_PROGRESS", "2026-08-29T08:00:00+00:00")],
              next_note="the next thing")

        module, rc = _run(load_script, tmp_path, argv=["--json"])
        data = json.loads(capsys.readouterr().out)

        assert rc == 0
        assert {"current_task", "progress", "next", "subagents"} <= set(data)
        assert data["current_task"]["taskId"] == "aib-json-task"
        assert data["next"] == "the next thing"


# ---------------------------------------------------------------- import bootstrap


class TestTrackerLibImportPath:
    def test_bootstrap_resolves_to_existing_tracker_lib(self):
        """parents[2]/task/scripts must hold tracker_lib.py (was parents[1], off-by-one)."""
        from conftest import ROOT

        script = (ROOT / SCRIPT).resolve()
        candidate = script.parents[2] / "task" / "scripts" / "tracker_lib.py"

        assert candidate.is_file(), f"tracker_lib not found via parents[2]: {candidate}"

    def test_bootstrap_does_not_use_parents1_for_tracker(self):
        from conftest import ROOT

        text = (ROOT / SCRIPT).read_text(encoding="utf-8")

        assert 'parents[2] / "task" / "scripts"' in text
