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

    def test_a_started_task_is_open_not_absent(self, load_script, tmp_path, capsys):
        """STARTED is registered work awaiting its first Stop-hook promotion (or a
        harness with no Stop hook) — it must never read as '(no task in progress)'."""
        _seed(tmp_path, [_task("aib-fresh-start", "STARTED",
                               "2026-08-28T11:00:00+00:00")])

        module, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out
        data = module.report(tmp_path)

        assert rc == 0
        assert data["current_task"]["taskId"] == "aib-fresh-start"
        assert "aib-fresh-start" in out
        assert "STARTED" in out

    def test_latest_started_wins_across_started_and_in_progress(self, load_script,
                                                                tmp_path):
        _seed(tmp_path, [
            _task("aib-older-running", "IN_PROGRESS", "2026-08-28T08:00:00+00:00"),
            _task("aib-newer-started", "STARTED", "2026-08-28T10:00:00+00:00"),
        ])

        module, _ = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert data["current_task"]["taskId"] == "aib-newer-started"
        assert data["other_open"] == ["aib-older-running"]


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


class TestDualReadPlanHeadings:
    """DR10/DR12: graph-rendered `**S<N> …**` plans report beside legacy `**P<N>**` plans.

    The server renders one heading per step and one checkbox per acceptance criterion; the
    script must read that shape with the same frozen keys the legacy shape reports."""

    GRAPH_PLAN = (
        "<!-- generated by task-graph from .ai-badger/task-tracking/tracking.db — "
        "do not edit; task_id=aib-graph-task revision=3 -->\n"
        "# aib-graph-task — task plan\n"
        "\n"
        "**S1 — wire the resolver (pending)**\n"
        "- [ ] ac-1: resolve a plan\n"
        "- [ ] ac-2: refuse a bad ref\n"
        "\n"
        "**S2 — ship the CLI (in_progress)**\n"
        "- [x] ac-1: verbs dispatch\n"
        "- [ ] ac-2: exit codes\n"
    )
    MIXED_PLAN = (
        "# Plan — mixed prefixes\n"
        "\n"
        "**P1 legacy package (RUNNING):** the old way\n"
        "- [x] p-done\n"
        "- [ ] p-open\n"
        "\n"
        "**S2 — new step (pending)**\n"
        "- [ ] s-open\n"
    )
    HANDWRITTEN_PLAN = (
        "<!-- hand-written — graph off; task_id=aib-graph-off revision=0 -->\n"
        "# aib-graph-off — task plan (hand-written)\n"
        "\n"
        "**S1 — do the thing (pending)**\n"
        "- [ ] ac-1: first\n"
        "- [x] ac-2: second\n"
        "\n"
        "**S2 — finish (pending)**\n"
        "- [ ] ac-1: third\n"
    )

    @staticmethod
    def _seed_plan(tmp_path, task_id, plan):
        _seed(tmp_path, [_task(task_id, "IN_PROGRESS", "2026-09-28T08:00:00+00:00")])
        _write(tmp_path, f"{TT}/plans/2026-09-28-{task_id}.md", plan)

    def test_s_headings_are_counted_like_package_headings(self, load_script, tmp_path):
        self._seed_plan(tmp_path, "aib-graph-task", self.GRAPH_PLAN)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["matched"] is True
        assert progress["packages"] == ["S1 — wire the resolver (pending)",
                                        "S2 — ship the CLI (in_progress)"]
        assert progress["checked"] == 1
        assert progress["total"] == 4

    def test_a_mixed_p_and_s_plan_reports_both_prefixes(self, load_script, tmp_path):
        self._seed_plan(tmp_path, "aib-graph-task", self.MIXED_PLAN)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["packages"] == ["P1 legacy package (RUNNING):",
                                        "S2 — new step (pending)"]
        assert progress["checked"] == 1
        assert progress["total"] == 3

    def test_render_labels_steps_and_packages_by_heading_prefix(self, load_script, tmp_path,
                                                                capsys):
        self._seed_plan(tmp_path, "aib-graph-task", self.MIXED_PLAN)

        _, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "  [package] P1 legacy package (RUNNING):" in out
        assert "  [step] S2 — new step (pending)" in out
        assert "[package] S2" not in out

    def test_a_hand_written_graph_off_plan_parses_and_renders(self, load_script, tmp_path,
                                                              capsys):
        """The degraded path (DR12): no server, a hand-written file in the same shape."""
        self._seed_plan(tmp_path, "aib-graph-off", self.HANDWRITTEN_PLAN)

        module, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out
        progress = module.report(tmp_path)["progress"]

        assert rc == 0
        assert progress["matched"] is True
        assert progress["packages"] == ["S1 — do the thing (pending)",
                                        "S2 — finish (pending)"]
        assert progress["checked"] == 1
        assert progress["total"] == 3
        assert "  [step] S1 — do the thing (pending)" in out
        assert "checklist: 1/3 done" in out

    def test_the_progress_keys_and_exit_zero_are_frozen(self, load_script, tmp_path, capsys):
        """`packages`/`checked`/`total` and their shapes stay frozen for --json consumers."""
        module = load_script(SCRIPT)
        absent = module.plan_checklist(tmp_path, "aib-graph-task")

        assert absent == {"plan_file": None, "matched": False, "packages": [],
                          "checked": 0, "total": 0}

        self._seed_plan(tmp_path, "aib-graph-task", self.GRAPH_PLAN)
        _, rc = _run(load_script, tmp_path, argv=["--json"])
        data = json.loads(capsys.readouterr().out)

        assert rc == 0
        assert set(data) >= {"current_task", "progress", "next", "subagents"}
        assert set(data["progress"]) == {"plan_file", "matched", "packages",
                                          "checked", "total"}
        assert data["progress"]["packages"][0] == "S1 — wire the resolver (pending)"

    def test_no_plan_still_prints_the_placeholder_and_exits_zero(self, load_script, tmp_path,
                                                                 capsys):
        _seed(tmp_path, [_task("aib-graph-task", "IN_PROGRESS",
                               "2026-09-28T08:00:00+00:00")])

        _, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "(no plan file)" in out
        assert "checklist:" not in out


class TestPlanMatching:
    """A plan counts as the task's own only on a whole-token match of the full task id.

    Substring token overlap once reported another task's review document as this task's
    plan with matched=True: the shared repo alias always matched, `review` hit `reviewer`,
    and a numeric key hit every dated filename."""

    JSAA_TASK = "jsaa-claude-code-review-github-workflow"
    JSAA_OTHER_REVIEW = ("2026-09-16-jsaa-study-topic-workflow-shadow-wiring"
                         ".plan-review-3-code-reviewer.md")

    @staticmethod
    def _plan(target: Path, name: str, body: str, mtime: int) -> None:
        import os

        _write(target, f"{TT}/plans/{name}", body)
        os.utime(target / TT / "plans" / name, (mtime, mtime))

    def test_the_tasks_own_older_plan_beats_a_newer_colliding_review(self, load_script,
                                                                      tmp_path):
        _seed(tmp_path, [_task(self.JSAA_TASK, "IN_PROGRESS", "2026-09-10T08:00:00+00:00")])
        self._plan(tmp_path, f"2026-09-10-{self.JSAA_TASK}.md",
                   "**P1 one:** go\n- [x] a\n- [ ] b\n", 1_000)
        self._plan(tmp_path, self.JSAA_OTHER_REVIEW, "# review\nno checkboxes\n", 2_000)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["plan_file"].endswith(f"2026-09-10-{self.JSAA_TASK}.md")
        assert progress["matched"] is True
        assert progress["total"] == 2

    def test_a_task_with_no_plan_never_reports_another_tasks_file_as_matched(
            self, load_script, tmp_path):
        """The consumer case: the shared alias plus `code`/`review`/`workflow` overlap."""
        _seed(tmp_path, [_task(self.JSAA_TASK, "IN_PROGRESS", "2026-09-20T08:00:00+00:00")])
        self._plan(tmp_path, "2026-09-01-jsaa-review-inbox-triage.md", "- [ ] x\n", 1_000)
        self._plan(tmp_path, self.JSAA_OTHER_REVIEW, "# review\n", 2_000)

        module, _ = _run(load_script, tmp_path)
        data = module.report(tmp_path)

        assert data["progress"]["matched"] is False
        assert "newest-file fallback" in module.render(data)

    def test_a_numeric_key_matches_as_a_whole_token_not_a_substring(self, load_script,
                                                                    tmp_path):
        """`aib-2` must not match every `2026-...` filename, nor `aib-22`."""
        _seed(tmp_path, [_task("aib-2", "IN_PROGRESS", "2026-09-01T08:00:00+00:00")])
        self._plan(tmp_path, "2026-08-20-aib-2.md", "- [x] own\n", 1_000)
        self._plan(tmp_path, "2026-08-29-aib-22-other-thing.md", "- [ ] not own\n", 2_000)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["plan_file"].endswith("2026-08-20-aib-2.md")
        assert progress["matched"] is True

    def test_a_numeric_key_with_no_own_plan_is_a_fallback(self, load_script, tmp_path):
        _seed(tmp_path, [_task("aib-2", "IN_PROGRESS", "2026-09-01T08:00:00+00:00")])
        self._plan(tmp_path, "2026-08-29-aib-other-thing.md", "- [ ] not own\n", 1_000)

        module, _ = _run(load_script, tmp_path)

        assert module.report(tmp_path)["progress"]["matched"] is False

    def test_review_documents_of_the_task_are_not_its_plan(self, load_script, tmp_path):
        task = "aib-widget-sync"
        _seed(tmp_path, [_task(task, "IN_PROGRESS", "2026-09-10T08:00:00+00:00")])
        self._plan(tmp_path, f"2026-09-10-{task}.md", "- [x] a\n- [ ] b\n", 1_000)
        self._plan(tmp_path, f"2026-09-12-{task}.plan-review-1-code-reviewer.md",
                   "# review\n", 2_000)
        self._plan(tmp_path, f"2026-09-13-{task}.review.md", "# review\n", 3_000)
        self._plan(tmp_path, f"2026-09-14-{task}-impl-review.md", "# review\n", 4_000)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["plan_file"].endswith(f"2026-09-10-{task}.md")
        assert progress["matched"] is True

    def test_a_review_document_alone_is_only_a_fallback(self, load_script, tmp_path):
        task = "aib-widget-sync"
        _seed(tmp_path, [_task(task, "IN_PROGRESS", "2026-09-10T08:00:00+00:00")])
        self._plan(tmp_path, f"2026-09-12-{task}.plan-review-1-code-reviewer.md",
                   "# review\n", 2_000)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["plan_file"] is not None
        assert progress["matched"] is False

    def test_a_task_named_for_reviews_still_matches_its_own_plan(self, load_script,
                                                                 tmp_path):
        """`review` inside the task id is not a review-document marker."""
        task = "aib-code-review-skill"
        _seed(tmp_path, [_task(task, "IN_PROGRESS", "2026-09-10T08:00:00+00:00")])
        self._plan(tmp_path, f"2026-09-10-{task}.md", "- [ ] a\n", 1_000)

        module, _ = _run(load_script, tmp_path)
        progress = module.report(tmp_path)["progress"]

        assert progress["plan_file"].endswith(f"2026-09-10-{task}.md")
        assert progress["matched"] is True


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

    def test_a_started_task_claims_its_worktree_as_a_live_lane(self, load_script,
                                                                tmp_path):
        _seed(tmp_path, [_task("aib-fresh-start", "STARTED",
                               "2026-08-29T08:00:00+00:00")])
        (tmp_path / ".ai-badger" / "worktrees" / "aib-fresh-start").mkdir(parents=True)

        module, _ = _run(load_script, tmp_path)

        assert module.report(tmp_path)["subagents"]["live_lanes"] == ["aib-fresh-start"]

    def test_a_worktree_with_no_tracker_row_is_untracked_not_live(self, load_script,
                                                                   tmp_path, capsys):
        """Never-registered work (branch+PR, no tracker row) must surface as
        untracked — otherwise the report reads '(no task in progress)' while real
        work sits in the worktree. FINISHED leftovers stay hidden."""
        _seed(tmp_path, [_task("aib-live-task", "IN_PROGRESS",
                               "2026-08-29T08:00:00+00:00"),
                         _task("old-finished", "FINISHED", "2026-08-28T07:00:00+00:00")])
        for name in ("aib-live-task", "mystery-work", "old-finished"):
            (tmp_path / ".ai-badger" / "worktrees" / name).mkdir(parents=True)

        module, rc = _run(load_script, tmp_path)
        out = capsys.readouterr().out
        subs = module.report(tmp_path)["subagents"]

        assert rc == 0
        assert subs["live_lanes"] == ["aib-live-task"]
        assert subs["untracked"] == ["mystery-work"]
        assert "mystery-work" in out
        assert "old-finished" not in out

    def test_dead_pid_sessions_are_marked_stale(self, load_script, tmp_path, capsys):
        """The sessions table prunes dead pids only on write, so ghost rows linger;
        the report marks them instead of presenting them as live."""
        import os

        _seed(tmp_path, [_task("aib-lane-task", "IN_PROGRESS",
                               "2026-08-29T08:00:00+00:00")],
              sessions={"dead-beef": {"pid": 2 ** 30, "cwd": "/nowhere",
                                        "recordedAt": "2026-08-20T00:00:00+00:00"},
                        "live-one": {"pid": os.getpid(), "cwd": "/here",
                                     "recordedAt": "2026-08-29T00:00:00+00:00"}})

        module, _ = _run(load_script, tmp_path, )
        out = capsys.readouterr().out
        sessions = {s["session_id"]: s
                    for s in module.report(tmp_path)["subagents"]["sessions"]}

        assert sessions["dead-beef"]["alive"] is False
        assert sessions["live-one"]["alive"] is True
        assert "STALE" in out


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


# ---------------------------------------------------------------- progress source contract

SKILL_MD = "features/common/skills/status-report/SKILL.md"
TRACKING_VISIBILITY_MD = "features/common/skills/task/references/tracking-visibility.md"

# The frozen mapping sentence (DR10) the graph tool and the fallback bind on:
# `progress_checklist` with format:"text" IS the section verbatim; the script is the fallback.
GRAPH_IS_PRIMARY = ('`progress_checklist` with `format:"text"` **IS** the "Progress checklist" '
                    'section verbatim (primary); the status script\'s plan-file output is the '
                    'fallback when no graph plan or CLI is reachable.')


def _doc_text(rel: str) -> str:
    from conftest import ROOT

    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


class TestProgressSourceContract:
    """DR10: the graph's text IS the section; the script's parse is the fallback."""

    def test_the_skill_binds_format_text_to_the_section_verbatim(self):
        text = _doc_text(SKILL_MD)

        assert GRAPH_IS_PRIMARY in text
        assert ("uv run --script .ai-badger/skills/task-decomposition/scripts/"
                "task_graph_cli.py progress_checklist --json") in text

    def test_the_skill_keeps_never_delegate_never_wait_and_the_four_sections(self):
        text = _doc_text(SKILL_MD)

        assert "Do not delegate the report anywhere." in text
        assert "Do not poll or wait on running subagents" in text
        for section in ("Current task", "Progress checklist", "What's next",
                        "Sub-agents & delegation"):
            assert section in text

    def test_tracking_visibility_carries_the_two_path_plan_contract(self):
        text = _doc_text(TRACKING_VISIBILITY_MD)

        assert "**S<N> …**" in text
        assert "hand-written — graph off" in text
        assert "A plan living only in a delegation brief never counts" in text
        assert "whole taskId" in text


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
