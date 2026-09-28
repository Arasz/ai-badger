"""Graph operations over the S2 plan model: ready sets, deferral waves, guards, checklist.

TDD matrix for `task_graph.py` (DR7/DR8 + plan §2). Every guard gets a test that can fail:
each refusal code has its own witness, the two structural invariants (ready pairs are
dependency-unordered; no wave packs a conflicting pair) have checkers shown able to fail
(`test_conflict_predicate_is_what_defers_a_pair`), and the no-subprocess property has both a
source guard and a mutated-copy witness. Fixtures are built through `graph.task_plan_model` —
the exact S2 model object the module imported — so the plan classes and the ops agree on one
module copy per process instead of loading the model twice.
"""
# pylint: disable=redefined-outer-name  # `graph`/`model` are pytest fixture names
from __future__ import annotations

import ast
import contextlib
import json
import random
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GRAPH_RELPATH = "features/common/skills/task-decomposition/scripts/task_graph.py"
GRAPH_SOURCE = ROOT / GRAPH_RELPATH

STARTED = "2026-09-28T11:00:00Z"
DONE = "2026-09-28T12:00:00Z"
NOW = datetime(2026, 9, 28, 13, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-09-28T13:00:00Z"

REMAINING = ("pending", "in_progress", "failed")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def graph(load_script):
    return load_script(GRAPH_RELPATH)


@pytest.fixture
def model(graph):
    return graph.task_plan_model


def _criterion(criterion_id="ac1", *, status="unchecked", check=None, evidence=None):
    return {"id": criterion_id, "statement": f"{criterion_id} holds", "check": check,
            "status": status, "evidence": evidence or []}


def _completion(*, forced=False, note=None):
    return {"completed_by": None, "forced": forced, "note": note, "evidence": []}


def _step(step_id="s1", **overrides):
    data = {
        "id": step_id,
        "goal": "do the thing",
        "instructions": "follow the plan",
        "effort": "medium",
        "level": None,
        "model": None,
        "persona": None,
        "depends_on": [],
        "acceptance_criteria": [_criterion()],
        "files": [],
        "resources": [],
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "completion": None,
    }
    data.update(overrides)
    return data


def _running(step_id="s1", **overrides):
    data = {"status": "in_progress", "started_at": STARTED}
    data.update(overrides)
    return _step(step_id, **data)


def _done(step_id="s1", **overrides):
    data = {"status": "complete", "started_at": STARTED, "completed_at": DONE,
            "acceptance_criteria": [_criterion(status="passed")],
            "completion": _completion()}
    data.update(overrides)
    return _step(step_id, **data)


def _plan(model, steps, **overrides):
    data = {
        "schema_version": 1,
        "task_id": "aib-s5-ops",
        "task_description_ref": "docs/work/2026-09-28-task-decomposition-plan.md",
        "research_ref": None,
        "task_context": "S5 graph-ops fixture",
        "loop": "high",
        "source_refs": ["docs/work/2026-09-28-task-decomposition-plan.md"],
        "workflow": {"steps": steps},
        "revision": 0,
        "created_at": "2026-09-28T10:00:00Z",
        "updated_at": "2026-09-28T10:00:00Z",
    }
    data.update(overrides)
    return model.TaskPlan.model_validate(data)


def _generated_plan(model, seed, count=7):
    """A deterministic random DAG with guard-reachable statuses; every load-valid (V11).

    A step that is not pending only ever depends on complete/skipped steps: `start` required
    satisfied dependencies, so no guard-reachable plan leaves a started/completed/skipped step
    hanging off an unsatisfied one. Pending steps may depend on anything.
    """
    rng = random.Random(seed)
    ids = [f"s{index}" for index in range(count)]
    steps = {}
    for index, step_id in enumerate(ids):
        status = rng.choice(["pending", "pending", "failed", "in_progress", "complete",
                             "skipped"])
        if status == "pending":
            pool = ids[:index]
        else:
            pool = [other for other in ids[:index]
                    if steps[other]["status"] in ("complete", "skipped")]
        data = {"depends_on": [other for other in pool if rng.random() < 0.3],
                "status": status}
        if status == "in_progress":
            data["started_at"] = STARTED
        elif status == "complete":
            data["started_at"] = STARTED
            data["completed_at"] = DONE
            data["acceptance_criteria"] = [_criterion(status="passed")]
            data["completion"] = _completion()
        steps[step_id] = _step(step_id, **data)
    return _plan(model, steps)


def _conflict_plan(model):
    """Two file-conflicting pairs and one resource-conflicting pair, all ready."""
    return _plan(model, {
        "a": _step("a", files=["src/shared.py"]),
        "b": _step("b", files=["src/shared.py"]),
        "c": _step("c", files=["src/other.py"]),
        "d": _step("d", resources=["shared-db"]),
        "e": _step("e", resources=["shared-db"]),
    })


def _refused(graph, code):
    """`pytest.raises` on a `TransitionRefused` carrying `code`; yields the exception."""
    return _Refusal(graph, code)


class _Refusal:
    def __init__(self, graph, code):
        self.context = pytest.raises(graph.TransitionRefused)
        self.code = code
        self.info = None
        self.details = None

    def __enter__(self):
        self.info = self.context.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        result = self.context.__exit__(exc_type, exc, tb)
        refused = self.info.value
        assert refused.code == self.code, (
            f"expected refusal code {self.code!r}, got {refused.code!r}: {refused}")
        self.details = refused.details
        return result


def _snapshot(graph, plan):
    return {
        "ready": [list(entry) for entry in graph.ready(plan)],
        "waves": graph.waves(plan),
        "blocked": [list(entry) for entry in graph.blocked(plan)],
        "checklist": graph.progress_checklist_data(plan),
        "integration_ok": graph.integration_ok(plan),
        "integration_sink": graph.integration_sink(plan),
        "findings": [list(finding) for finding in graph.plan_quality_findings(plan)],
    }


# --------------------------------------------------------------------------- ready


def test_ready_picks_pending_and_failed_with_satisfied_deps(graph, model):
    plan = _plan(model, {
        "a": _done("a"),
        "b": _step("b", status="skipped"),
        "c": _step("c", depends_on=["a"]),
        "d": _step("d", status="failed", started_at=STARTED, depends_on=["b"]),
        "e": _step("e", depends_on=["c"]),
        "f": _running("f", depends_on=["a"]),
        "g": _step("g", depends_on=["a", "b"]),
    })

    entries = graph.ready(plan)

    assert [(entry.step_id, entry.status) for entry in entries] == [
        ("c", "pending"), ("d", "failed"), ("g", "pending")]
    assert entries[0].skipped_deps == []
    assert entries[1].skipped_deps == ["b"]
    assert entries[2].skipped_deps == ["b"]


def test_ready_surfaces_skipped_deps_and_blocked_by(graph, model):
    plan = _plan(model, {
        "retired": _step("retired", status="skipped"),
        "next": _step("next", depends_on=["retired"]),
    })

    entry, = graph.ready(plan)

    assert entry.step_id == "next"
    assert entry.skipped_deps == ["retired"]
    assert entry.blocked_by == ["retired"]


def test_ready_is_topological_with_id_tiebreak(graph, model):
    # Inserted bottom-up; `a` and `b` tie on dependencies and must sort by id, while `tail`
    # follows its dependency despite sorting before both of them.
    plan = _plan(model, {
        "tail": _step("tail", depends_on=["done"]),
        "b": _step("b"),
        "a": _step("a"),
        "done": _done("done"),
    })

    assert [entry.step_id for entry in graph.ready(plan)] == ["a", "b", "tail"]


def test_ready_pairs_are_mutually_unordered_by_dependency(graph, model):
    checked = 0
    for seed in range(30):
        plan = _generated_plan(model, seed)
        entries = graph.ready(plan)
        for left, right in combinations(entries, 2):
            assert left.step_id not in graph.ancestors(plan, right.step_id), (
                f"seed {seed}: ready pair {left.step_id}/{right.step_id} is ordered")
            assert right.step_id not in graph.ancestors(plan, left.step_id), (
                f"seed {seed}: ready pair {left.step_id}/{right.step_id} is ordered")
            checked += 1
    assert checked > 20, "the generated corpus did not exercise any ready pair"


def test_ancestors_are_transitive_and_ordered(graph, model):
    plan = _plan(model, {
        "a": _done("a"),
        "b": _step("b", status="skipped", depends_on=["a"]),
        "c": _step("c", depends_on=["b"]),
        "d": _step("d", depends_on=["c"]),
    })

    assert graph.ancestors(plan, "d") == ["a", "b", "c"]
    assert graph.ancestors(plan, "a") == []


# --------------------------------------------------------------------------- waves


def test_waves_pack_greedy_by_topological_id_order(graph, model):
    plan = _plan(model, {
        "b": _step("b"),
        "a": _step("a"),
        "d": _step("d", depends_on=["a", "b"]),
        "c": _step("c", depends_on=["a"]),
    })

    assert graph.waves(plan) == [["a", "b"], ["c", "d"]]


def test_conflicting_pair_defers_the_later_member(graph, model):
    plan = _conflict_plan(model)

    assert graph.waves(plan) == [["a", "c", "d"], ["b", "e"]]


def test_deferred_ready_member_still_appears_in_a_later_wave(graph, model):
    plan = _plan(model, {"a": _step("a", files=["x"]),
                         "b": _step("b", files=["x"]),
                         "c": _step("c", files=["y"])})

    waves = graph.waves(plan)

    assert waves == [["a", "c"], ["b"]]
    assert set(graph.ready(plan)[i].step_id for i in range(len(graph.ready(plan)))) \
        <= {step_id for wave in waves for step_id in wave}


def test_waves_defer_dependents_to_strictly_later_waves(graph, model):
    plan = _plan(model, {
        "c": _step("c", depends_on=["a", "b"]),
        "a": _step("a"),
        "b": _step("b", depends_on=["a"]),
    })

    assert graph.waves(plan) == [["a"], ["b"], ["c"]]


def test_waves_cover_only_remaining_steps_and_respect_dependencies(graph, model):
    plan = _plan(model, {
        "done": _done("done", files=["x"]),
        "skip": _step("skip", status="skipped"),
        "failed": _step("failed", status="failed", started_at=STARTED),
        "live": _running("live"),
        "next": _step("next", depends_on=["live"]),
    })

    waves = graph.waves(plan)
    flat = [step_id for wave in waves for step_id in wave]
    positions = {step_id: index for index, step_id in enumerate(flat)}

    assert "done" not in flat and "skip" not in flat
    assert all(plan.workflow.steps[step_id].status.value in REMAINING for step_id in flat)
    for step_id in flat:
        for dependency in plan.workflow.steps[step_id].depends_on:
            assert positions[dependency] < positions[step_id], (
                f"{dependency!r} is not in an earlier wave than {step_id!r}")


def test_wave_zero_is_a_ready_subset_and_ready_is_covered(graph, model):
    plan = _generated_plan(model, 3)

    waves = graph.waves(plan)
    ready_ids = {entry.step_id for entry in graph.ready(plan)}
    flat = {step_id for wave in waves for step_id in wave}

    assert set(waves[0]) <= ready_ids
    assert ready_ids <= flat


def _assert_waves_have_no_conflicting_pair(graph, plan):
    # The invariant is spelled out here instead of calling `graph._conflicts`, so flipping the
    # module's predicate cannot make this checker pass vacuously (see the witness below).
    for wave in graph.waves(plan):
        members = [plan.workflow.steps[step_id] for step_id in wave]
        for left, right in combinations(members, 2):
            assert not set(left.files) & set(right.files), (
                f"wave {wave} packs {left.id!r} and {right.id!r} onto a shared file")
            assert not set(left.resources) & set(right.resources), (
                f"wave {wave} packs {left.id!r} and {right.id!r} onto a shared resource")


def test_no_wave_contains_a_conflicting_pair(graph, model):
    _assert_waves_have_no_conflicting_pair(graph, _conflict_plan(model))


def test_no_wave_contains_a_conflicting_pair_in_generated_corpus(graph, model):
    for seed in range(15):
        plan = _generated_plan(model, seed)
        _assert_waves_have_no_conflicting_pair(graph, plan)


def test_conflict_predicate_is_what_defers_a_pair(graph, model, monkeypatch):
    """Witness: flip the conflict predicate and the invariant checker above must fail."""
    plan = _conflict_plan(model)
    monkeypatch.setattr(graph, "_conflicts", lambda left, right: None)

    with pytest.raises(AssertionError):
        _assert_waves_have_no_conflicting_pair(graph, plan)


def test_waves_and_ops_are_deterministic_across_runs_and_copies(graph, model, load_script):
    plan = _generated_plan(model, 11)

    first = json.dumps(_snapshot(graph, plan), sort_keys=True)
    second = json.dumps(_snapshot(graph, plan), sort_keys=True)
    other = load_script(GRAPH_RELPATH)
    across = json.dumps(_snapshot(other, plan), sort_keys=True)

    assert first == second
    assert first == across


def test_determinism_bytes_change_when_the_order_drift(graph, model, monkeypatch):
    """Witness: the byte comparison above is sensitive to a drifting order."""
    plan = _generated_plan(model, 11)
    before = json.dumps(_snapshot(graph, plan), sort_keys=True)
    real = graph.topological_order
    monkeypatch.setattr(graph, "topological_order",
                        lambda candidate: list(reversed(real(candidate))))

    after = json.dumps(_snapshot(graph, plan), sort_keys=True)

    assert before != after


# --------------------------------------------------------------------------- start guard


def test_start_pending_sets_in_progress_and_started_at(graph, model):
    plan = _plan(model, {"s1": _step("s1")})

    started = graph.start(plan, "s1", now=NOW)

    assert started.status.value == "in_progress"
    assert started.started_at == NOW_ISO
    assert started.completed_at is None
    assert plan.workflow.steps["s1"].status.value == "pending"
    model.Step.model_validate(started.model_dump())


def test_start_failed_retry_clears_the_previous_attempt(graph, model):
    plan = _plan(model, {"s1": _step(
        "s1", status="failed", started_at=STARTED, completed_at=STARTED,
        completion=_completion(forced=True, note="earlier attempt"))})

    retried = graph.start(plan, "s1", now=NOW)

    assert retried.status.value == "in_progress"
    assert retried.started_at == NOW_ISO
    assert retried.completed_at is None
    assert retried.completion is None
    model.Step.model_validate(retried.model_dump())


def test_start_refuses_incomplete_dependencies(graph, model):
    plan = _plan(model, {
        "a": _step("a"),
        "b": _step("b", depends_on=["a"]),
    })

    with _refused(graph, "dependencies-incomplete") as refused:
        graph.start(plan, "b")

    assert refused.details["step_id"] == "b"
    assert refused.details["waiting_on"] == ["a"]
    assert plan.workflow.steps["b"].status.value == "pending"


@pytest.mark.parametrize("status,allowed", [
    ("complete", []),
    ("skipped", []),
    ("in_progress", ["complete", "failed", "skipped"]),
])
def test_start_refuses_non_startable_statuses_with_allowed_transitions(
        graph, model, status, allowed):
    step = {"complete": _done, "skipped": lambda sid: _step(sid, status="skipped"),
            "in_progress": _running}[status]("s1")
    plan = _plan(model, {"s1": step})

    with _refused(graph, "invalid-transition") as refused:
        graph.start(plan, "s1")

    assert refused.details["status"] == status
    assert refused.details["allowed_transitions"] == allowed


def test_start_refuses_unknown_step(graph, model):
    plan = _plan(model, {"s1": _step("s1")})

    with _refused(graph, "not-found") as refused:
        graph.start(plan, "ghost")

    assert refused.details["step_id"] == "ghost"


# --------------------------------------------------------------------------- complete guard


def _complete_plan(model):
    return _plan(model, {
        "done": _done("done"),
        "run": _running("run", depends_on=["done"], acceptance_criteria=[
            _criterion("ac1"),
            _criterion("ac2", status="failed"),
            _criterion("ac3", status="passed"),
        ]),
    })


def test_complete_refuses_unmet_criteria_and_lists_them(graph, model):
    plan = _complete_plan(model)

    with _refused(graph, "criteria-unmet") as refused:
        graph.complete(plan, "run", now=NOW)

    assert refused.details["unresolved"] == ["ac1"]
    assert refused.details["failed"] == ["ac2"]
    assert plan.workflow.steps["run"].status.value == "in_progress"


def test_complete_force_without_a_note_is_still_criteria_unmet(graph, model):
    plan = _complete_plan(model)

    for note in ("", "   ", None):
        with _refused(graph, "criteria-unmet"):
            graph.complete(plan, "run", now=NOW, force=True, note=note)


def test_complete_force_bypass_records_forced_note_and_leaves_acs(graph, model):
    plan = _complete_plan(model)
    note = "shipping with ac2 failed: tracked as a follow-up"

    completed = graph.complete(plan, "run", now=NOW, force=True, note=note)

    assert completed.status.value == "complete"
    assert completed.completed_at == NOW_ISO
    assert completed.completion.forced is True
    assert completed.completion.note == note
    assert [(ac.id, ac.status.value) for ac in completed.acceptance_criteria] == [
        ("ac1", "unchecked"), ("ac2", "failed"), ("ac3", "passed")]
    assert [(ac.id, ac.status.value) for ac in plan.workflow.steps["run"].acceptance_criteria] \
        == [("ac1", "unchecked"), ("ac2", "failed"), ("ac3", "passed")]
    model.Step.model_validate(completed.model_dump())


def test_complete_with_all_criteria_passed_records_unforced_completion(graph, model):
    plan = _plan(model, {"run": _running("run", acceptance_criteria=[
        _criterion(status="passed")])})

    completed = graph.complete(plan, "run", now=NOW)

    assert completed.status.value == "complete"
    assert completed.completed_at == NOW_ISO
    assert completed.completion.forced is False
    assert completed.completion.note is None
    model.Step.model_validate(completed.model_dump())


def test_complete_refuses_incomplete_dependencies_first(graph, model):
    plan = _plan(model, {
        "a": _step("a"),
        "run": _running("run", depends_on=["a"]),
    })

    with _refused(graph, "dependencies-incomplete") as refused:
        graph.complete(plan, "run", now=NOW)

    assert refused.details["waiting_on"] == ["a"]


def test_complete_already_complete_is_its_own_code(graph, model):
    plan = _plan(model, {"done": _done("done")})

    with _refused(graph, "already_complete") as refused:
        graph.complete(plan, "done")

    assert refused.details["status"] == "complete"


@pytest.mark.parametrize("status,allowed", [
    ("pending", ["in_progress"]),
    ("failed", ["in_progress"]),
    ("skipped", []),
])
def test_complete_refuses_non_in_progress_statuses(graph, model, status, allowed):
    step = {"pending": _step, "failed": _step, "skipped": _step}.get(status)("s1")
    overrides = {"status": status}
    if status == "failed":
        overrides["started_at"] = STARTED
    plan = _plan(model, {"s1": _step("s1", **overrides)})
    assert step is not None

    with _refused(graph, "invalid-transition") as refused:
        graph.complete(plan, "s1")

    assert refused.details["allowed_transitions"] == allowed


def test_complete_refuses_unknown_step(graph, model):
    plan = _plan(model, {"s1": _step("s1")})

    with _refused(graph, "not-found"):
        graph.complete(plan, "ghost")


# --------------------------------------------------------------------------- fail / skip guards


def test_fail_moves_in_progress_to_failed(graph, model):
    plan = _plan(model, {"run": _running("run")})

    failed = graph.fail(plan, "run")

    assert failed.status.value == "failed"
    assert plan.workflow.steps["run"].status.value == "in_progress"
    model.Step.model_validate(failed.model_dump())


@pytest.mark.parametrize("status,allowed", [
    ("pending", ["in_progress"]),
    ("complete", []),
    ("skipped", []),
])
def test_fail_refuses_non_in_progress_statuses(graph, model, status, allowed):
    step = _done("s1") if status == "complete" else _step("s1", status=status)
    plan = _plan(model, {"s1": step})

    with _refused(graph, "invalid-transition") as refused:
        graph.fail(plan, "s1")

    assert refused.details["status"] == status
    assert refused.details["allowed_transitions"] == allowed


def test_skip_moves_in_progress_to_skipped(graph, model):
    plan = _plan(model, {"run": _running("run")})

    skipped = graph.skip(plan, "run")

    assert skipped.status.value == "skipped"
    assert plan.workflow.steps["run"].status.value == "in_progress"
    model.Step.model_validate(skipped.model_dump())


@pytest.mark.parametrize("status,allowed", [
    ("pending", ["in_progress"]),
    ("complete", []),
    ("skipped", []),
])
def test_skip_refuses_non_in_progress_statuses(graph, model, status, allowed):
    # DR7 keeps skipped reachable from in_progress only; a pending step must start first.
    step = _done("s1") if status == "complete" else _step("s1", status=status)
    plan = _plan(model, {"s1": step})

    with _refused(graph, "invalid-transition") as refused:
        graph.skip(plan, "s1")

    assert refused.details["allowed_transitions"] == allowed


def test_guards_never_mutate_the_plan(graph, model):
    plan = _plan(model, {
        "done": _done("done"),
        "run": _running("run", depends_on=["done"]),
        "waiting": _step("waiting", depends_on=["run"]),
    })
    before = plan.model_dump_json()

    with contextlib.suppress(graph.TransitionRefused):
        graph.start(plan, "done")
        graph.start(plan, "waiting")
        graph.complete(plan, "run", now=NOW)
        graph.fail(plan, "run")
        graph.skip(plan, "run")
        graph.start(plan, "ghost")

    assert plan.model_dump_json() == before


# --------------------------------------------------------------------------- blocked


def test_blocked_lists_failed_or_skipped_ancestors_of_remaining_steps(graph, model):
    plan = _plan(model, {
        "a": _step("a", status="failed", started_at=STARTED),
        "b": _step("b", status="skipped"),
        "c": _done("c", depends_on=["a"]),
        "d": _step("d", depends_on=["a"]),
        "e": _step("e", depends_on=["b"]),
        "f": _step("f", depends_on=["c"]),
        "g": _step("g", depends_on=["d"]),
    })

    blocked = graph.blocked(plan)

    assert [(entry.step_id, entry.blocked_by) for entry in blocked] == [
        ("d", ["a"]), ("e", ["b"]), ("f", ["a"]), ("g", ["a"])]
    assert "c" not in [entry.step_id for entry in blocked]


def test_blocked_is_empty_when_no_ancestor_failed_or_skipped(graph, model):
    plan = _generated_plan(model, 21)

    for entry in graph.blocked(plan):
        assert entry.blocked_by
        assert all(plan.workflow.steps[ancestor].status.value in ("failed", "skipped")
                   for ancestor in entry.blocked_by)


# --------------------------------------------------------------------------- integration


def test_integration_sink_of_a_single_step_plan_is_that_step(graph, model):
    plan = _plan(model, {"s1": _step("s1")})

    assert graph.integration_sink(plan) == "s1"
    assert graph.integration_ok(plan) is True
    assert graph.integration_finding(plan) is None


def test_integration_sink_of_a_chain_is_its_tail(graph, model):
    plan = _plan(model, {
        "a": _step("a"),
        "b": _step("b", depends_on=["a"]),
        "c": _step("c", depends_on=["b"]),
    })

    assert graph.integration_sink(plan) == "c"
    assert graph.integration_ok(plan) is True


def test_integration_sink_is_none_for_parallel_sinks(graph, model):
    plan = _plan(model, {"a": _step("a"), "b": _step("b")})

    assert graph.integration_sink(plan) is None
    assert graph.integration_ok(plan) is False


def test_integration_sink_of_a_diamond_is_the_join(graph, model):
    plan = _plan(model, {
        "a": _step("a"),
        "left": _step("left", depends_on=["a"]),
        "right": _step("right", depends_on=["a"]),
        "join": _step("join", depends_on=["left", "right"]),
    })

    assert graph.integration_sink(plan) == "join"
    assert graph.integration_ok(plan) is True


def test_integration_ok_true_for_parallel_branches_joined_by_one_step(graph, model):
    plan = _plan(model, {
        "a": _step("a"),
        "b": _step("b"),
        "ja": _step("ja", depends_on=["a"]),
        "jb": _step("jb", depends_on=["b"]),
        "join": _step("join", depends_on=["ja", "jb"]),
    })

    assert graph.integration_sink(plan) == "join"
    assert graph.integration_ok(plan) is True


def test_integration_finding_appears_alongside_step_without_acs(graph, model):
    plan = _plan(model, {
        "x": _step("x", acceptance_criteria=[]),
        "y": _step("y"),
    })

    findings = graph.plan_quality_findings(plan)

    assert [finding.kind for finding in findings] == ["step_without_acs",
                                                      "integration_missing"]
    finding = findings[-1]
    assert finding.step_id == "x"
    assert "join" in finding.message
    assert graph.integration_finding(plan) == finding


# --------------------------------------------------------------------------- checklist


def _checklist_plan(model):
    return _plan(model, {
        "m": _step("m", status="failed", started_at=STARTED, acceptance_criteria=[
            _criterion("ac1", status="failed"), _criterion("ac2")]),
        "z": _step("z", status="complete", started_at=STARTED, completed_at=DONE,
                   acceptance_criteria=[_criterion("ac1", status="passed"),
                                         _criterion("ac2")],
                   completion=_completion(forced=True, note="ac2 waived")),
        "b": _step("b"),
        "t": _done("t"),
        "s": _step("s", status="skipped"),
        "a": _running("a", acceptance_criteria=[_criterion(status="passed")]),
        "aa": _step("aa", depends_on=["b"]),
    })


def test_checklist_orders_topologically_not_by_insertion_or_id(graph, model):
    plan = _checklist_plan(model)

    data = graph.progress_checklist_data(plan)

    assert [step["id"] for step in data["steps"]] == ["a", "b", "aa", "m", "s", "t", "z"]


def test_checklist_glyphs_and_header(graph, model):
    plan = _checklist_plan(model)

    data = graph.progress_checklist_data(plan)

    markers = {step["id"]: step["marker"] for step in data["steps"]}
    assert markers == {"a": "~", "b": " ", "aa": " ", "m": "!", "s": "-", "t": "x", "z": "x"}
    assert data["complete"] == 2
    assert data["total"] == 7
    assert data["task_id"] == "aib-s5-ops"
    assert data["revision"] == 0


def test_checklist_exposes_acs_tallies_and_forced_steps(graph, model):
    plan = _checklist_plan(model)

    tallies = {step["id"]: (step["acs_passed"], step["acs_total"])
               for step in graph.progress_checklist_data(plan)["steps"]}

    assert tallies == {"a": (1, 1), "b": (0, 1), "aa": (0, 1), "m": (0, 2),
                       "s": (0, 1), "t": (1, 1), "z": (1, 2)}


# --------------------------------------------------------------------------- no subprocess


def _source_offences(source):
    """Every `subprocess` / `os.system` / `Popen` use in `source`, as dotted strings."""
    offences = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                    offences.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "subprocess" or module.startswith("subprocess."):
                offences.append(f"from {module} import ...")
            if module == "os":
                for alias in node.names:
                    if alias.name in ("system", "popen") or alias.name.startswith(
                            ("spawn", "exec")):
                        offences.append(f"from os import {alias.name}")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted_name(node)
            if dotted.startswith("subprocess."):
                offences.append(f"reference to {dotted}")
            elif dotted.startswith(("os.system", "os.popen", "os.spawn", "os.exec")):
                offences.append(f"reference to {dotted}")
        elif isinstance(node, ast.Name) and node.id == "Popen":
            offences.append("reference to Popen")
    return sorted(set(offences))


def _dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def test_task_graph_source_never_reaches_a_subprocess(graph):
    assert _source_offences(GRAPH_SOURCE.read_text(encoding="utf-8")) == []


def test_source_guard_catches_a_mutated_copy(graph):
    """Witness: the guard above is a comparison that can come back non-empty."""
    mutated = GRAPH_SOURCE.read_text(encoding="utf-8") + (
        "\nimport subprocess\nsubprocess.run(['true'])\n")

    offences = _source_offences(mutated)

    assert "import subprocess" in offences
    assert "reference to subprocess.run" in offences


def test_check_strings_are_recorded_never_executed(graph, model, tmp_path):
    sentinel = tmp_path / "check-ran.marker"
    check = f"touch {sentinel}"
    pending = _plan(model, {"s1": _step("s1", acceptance_criteria=[
        _criterion("ac1", check=check)])})
    running = _plan(model, {"s1": _running("s1", acceptance_criteria=[
        _criterion("ac1", check=check, status="passed")])})

    for plan in (pending, running):
        graph.ready(plan)
        graph.waves(plan)
        graph.blocked(plan)
        graph.integration_ok(plan)
        graph.plan_quality_findings(plan)
        graph.progress_checklist_data(plan)
    graph.start(pending, "s1", now=NOW)
    graph.complete(running, "s1", now=NOW)
    graph.fail(running, "s1")
    graph.skip(running, "s1")
    with contextlib.suppress(graph.TransitionRefused):
        graph.start(running, "s1")

    assert not sentinel.exists(), "an acceptance-criterion `check` string was executed"
