"""The store-backed plan service: canonical payload round-trip, atomic CAS, root precedence.

`task_plan_store.py` is the one adapter between the plan model and the `plans` row: it
serialises a `TaskPlan` to the canonical payload the row stores, gates the raw payload's
`schema_version` before pydantic ever sees it, and performs every mutation as one
read-validate-mutate-CAS write. Root resolution mirrors `tracker_lib.resolve_project_root`
(env -> cwd marker walk -> script-dir walk, linked worktrees collapsed) and pins
`AI_BADGER_TRACKING_ROOT` before opening the vendored store, per the frozen plan precedence.

Every test routes the store under `tmp_path` via `AI_BADGER_TRACKING_ROOT`; the autouse
tripwire makes any path that falls back to `_default_badger_root()` fail loudly instead of
writing the developer's real checkout.

Test map:
  1. round trip ................ test_save_load_round_trip_preserves_runtime_state_and_payload_bytes
  2. create / CAS .............. test_save_plan_create_refuses_a_second_create_and_a_stale_update,
                                 test_save_plan_with_an_expected_revision_on_an_absent_row_is_not_found,
                                 test_absent_plan_and_unknown_step_are_not_found
  3. atomic RMW ................ test_scheduled_interleave_leaves_one_winner_and_one_conflict,
                                 test_update_step_no_op_mutation_writes_nothing,
                                 test_held_write_lock_refuses_the_rmw_cleanly_then_lands_after_release
  4. version gate .............. test_newer_schema_version_refuses_before_pydantic_and_leaves_the_row,
                                 test_version_below_the_floor_with_no_upgrade_hook_refuses,
                                 test_mutation_on_a_newer_schema_row_refuses_and_leaves_it_untouched
  5. refusals .................. test_missing_plans_table_refuses_with_an_actionable_remediation,
                                 test_missing_store_refuses_with_an_actionable_remediation
  6. root precedence ........... test_root_precedence_pins_tracker_lib_on_a_scratch_worktree,
                                 test_explicit_tracking_root_wins_over_project_resolution,
                                 test_resolved_root_lands_the_store_under_the_resolved_project
  7. tripwire .................. test_the_default_root_tripwire_is_armed
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

STORE_RELPATH = "features/common/skills/task-decomposition/scripts/task_plan_store.py"
SIBLING_STORE = "features/common/skills/task-decomposition/scripts/badger_store.py"
SIBLING_MODEL = "features/common/skills/task-decomposition/scripts/task_plan_model.py"
TRACKER_RELPATH = "features/common/skills/task/scripts/tracker_lib.py"
TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"
TASK_ID = "aib-demo-task"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plan_store(load_script, tmp_path, monkeypatch):
    """The service module, with this test's store routed under `tmp_path`."""
    module = load_script(STORE_RELPATH)
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(tmp_path))
    return module


@pytest.fixture(autouse=True)
def _default_root_is_a_tripwire(plan_store, monkeypatch):
    """Any test path reaching the module's fallback root fails instead of writing the real
    checkout; a passing test is the assertion that it never took that path."""
    def tripwire():
        raise AssertionError(
            "test path reached _default_badger_root(); set AI_BADGER_TRACKING_ROOT instead")

    monkeypatch.setattr(plan_store.badger_store, "_default_badger_root", tripwire)
    yield


# --------------------------------------------------------------------------- fixtures


def _evidence(summary="pytest passed", *, kind="test", ref=None,
              recorded_at="2026-09-28T10:00:00Z"):
    return {"kind": kind, "summary": summary, "ref": ref, "recorded_at": recorded_at}


def _criterion(criterion_id="ac1", *, status="unchecked", evidence=None):
    return {"id": criterion_id, "statement": "the check proves it", "check": "pytest -q",
            "status": status, "evidence": evidence or []}


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
        "files": ["a.py"],
        "resources": [],
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "completion": None,
    }
    data.update(overrides)
    return data


def _plan_document(**overrides):
    data = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "task_description_ref": "docs/work/plan.md",
        "research_ref": None,
        "task_context": "a demo plan",
        "loop": "high",
        "source_refs": ["docs/work/plan.md"],
        "workflow": {"steps": {"s1": _step()}},
        "revision": 0,
        "created_at": "2026-09-28T10:00:00Z",
        "updated_at": "2026-09-28T10:00:00+00:00",
    }
    if "steps" in overrides:
        data["workflow"] = {"steps": overrides.pop("steps")}
    data.update(overrides)
    return data


def _validated(plan_store, **overrides):
    return plan_store.model.TaskPlan.model_validate(_plan_document(**overrides))


def _start_step(step):
    return step.model_copy(update={"status": "in_progress",
                                   "started_at": "2026-09-28T10:05:00Z"})


def _start_plan(model, plan):
    steps = dict(plan.workflow.steps)
    steps["s1"] = _start_step(steps["s1"])
    return plan.model_copy(
        update={"workflow": plan.workflow.model_copy(update={"steps": steps})})


def _row(plan_store, task_id=TASK_ID):
    store = plan_store.open_plan_store()
    try:
        return store.plan_row(task_id)
    finally:
        store.close()


# --------------------------------------------------------------------------- 1. round trip


def test_save_load_round_trip_preserves_runtime_state_and_payload_bytes(plan_store):
    """Statuses, evidence, revision and created_at survive save -> load unchanged, and the
    stored payload is the model's canonical JSON byte for byte."""
    model = plan_store.model
    summary = "caf\u00e9 \u2713 \u2014 pytest tests/test_x.py::test_y passed"
    plan = model.TaskPlan.model_validate(_plan_document(steps={
        "s1": _step(
            status="in_progress",
            started_at="2026-09-28T10:05:00Z",
            acceptance_criteria=[_criterion(
                status="passed", evidence=[_evidence(summary, ref="tests/test_x.py")])],
        ),
    }))

    saved = plan_store.save_plan(plan)

    assert saved.revision == 0, "a create lands at revision 0"
    assert saved.created_at == plan.created_at, "created_at belongs to the document"
    loaded = plan_store.load_plan(TASK_ID)
    assert loaded == saved, "save -> load must preserve the document exactly"
    step = loaded.workflow.steps["s1"]
    assert step.status is model.StepStatus.IN_PROGRESS
    assert step.started_at == "2026-09-28T10:05:00Z"
    criterion = step.acceptance_criteria[0]
    assert criterion.status is model.CriterionStatus.PASSED
    assert criterion.evidence[0].summary == summary
    assert criterion.evidence[0].ref == "tests/test_x.py"

    stored = _row(plan_store)["payload"]
    assert stored == plan_store.canonical_payload(loaded), \
        "the stored payload must be the model's canonical JSON, byte for byte"


# --------------------------------------------------------------------------- 2. create / CAS


def test_save_plan_create_refuses_a_second_create_and_a_stale_update(plan_store):
    plan = _validated(plan_store)
    plan_store.save_plan(plan)

    with pytest.raises(plan_store.PlanConflictError) as excinfo:
        plan_store.save_plan(plan)
    assert excinfo.value.code == "conflict"
    assert excinfo.value.current_revision == 0
    assert excinfo.value.as_error()["current_revision"] == 0

    replaced = plan_store.save_plan(plan, expected_revision=0)
    assert replaced.revision == 1

    with pytest.raises(plan_store.PlanConflictError) as stale:
        plan_store.save_plan(plan, expected_revision=0)
    assert stale.value.current_revision == 1
    assert _row(plan_store)["revision"] == 1, "a refused CAS must not touch the row"


def test_save_plan_with_an_expected_revision_on_an_absent_row_is_not_found(plan_store):
    """CAS on a row that is not there is a not-found, never a silent insert at 0."""
    with pytest.raises(plan_store.PlanNotFound) as excinfo:
        plan_store.save_plan(_validated(plan_store), expected_revision=3)
    assert excinfo.value.code == "not-found"
    assert _row(plan_store) is None


def test_absent_plan_and_unknown_step_are_not_found(plan_store):
    with pytest.raises(plan_store.PlanNotFound) as missing:
        plan_store.load_plan("never-written")
    assert missing.value.code == "not-found"

    plan_store.save_plan(_validated(plan_store))
    with pytest.raises(plan_store.PlanNotFound):
        plan_store.update_step(TASK_ID, "ghost", _start_step, expected_revision=0)


# --------------------------------------------------------------------------- 3. atomic RMW


def test_scheduled_interleave_leaves_one_winner_and_one_conflict(plan_store):
    """The scheduled interleave, never a timing race: both readers see revision 0, the
    second connection holds BEGIN IMMEDIATE across its read-modify-write and commits it,
    and the first connection's CAS is then refused against the winner's stamp."""
    model = plan_store.model
    plan_store.save_plan(_validated(plan_store))
    reader_a = plan_store.load_plan(TASK_ID)
    reader_b = plan_store.load_plan(TASK_ID)
    assert reader_a.revision == reader_b.revision == 0

    writer_b = plan_store.badger_store.open_tracking()
    try:
        writer_b.conn.execute("BEGIN IMMEDIATE")
        held = plan_store.load_plan(TASK_ID, store=writer_b)
        plan_store.save_plan(_start_plan(model, held), expected_revision=reader_b.revision,
                             store=writer_b)
        writer_b.conn.commit()
    finally:
        writer_b.close()

    with pytest.raises(plan_store.PlanConflictError) as excinfo:
        plan_store.update_step(TASK_ID, "s1", _start_step,
                               expected_revision=reader_a.revision)
    assert excinfo.value.code == "conflict"
    assert excinfo.value.current_revision == 1
    assert excinfo.value.as_error()["current_revision"] == 1

    winner = plan_store.load_plan(TASK_ID)
    assert winner.revision == 1
    assert winner.workflow.steps["s1"].status is model.StepStatus.IN_PROGRESS
    assert winner.workflow.steps["s1"].started_at == "2026-09-28T10:05:00Z"
    row = _row(plan_store)
    assert row["revision"] == 1, "no lost update: the winner's row survives the loser"
    assert row["payload"] == plan_store.canonical_payload(winner)


def test_update_step_no_op_mutation_writes_nothing(plan_store):
    """A mutation that reports no change returns the stored plan untouched: no revision
    bump, no updated_at rewrite — the seam S7's idempotent tools build on."""
    plan_store.save_plan(_validated(plan_store))
    before = _row(plan_store)

    unchanged = plan_store.update_step(TASK_ID, "s1", lambda step: None, expected_revision=0)

    assert unchanged.revision == 0
    assert unchanged.workflow.steps["s1"].status is plan_store.model.StepStatus.PENDING
    assert _row(plan_store) == before, "a no-op mutation must not write"


def test_held_write_lock_refuses_the_rmw_cleanly_then_lands_after_release(plan_store):
    """The blocker holds BEGIN IMMEDIATE uncommitted; the service's write fails with a
    clean retryable store-error and the row is untouched; releasing lets the same write
    land — the S3 lock contract lifted to the service."""
    plan_store.save_plan(_validated(plan_store))
    store = plan_store.open_plan_store()
    blocker = None
    try:
        store.conn.execute("PRAGMA busy_timeout = 0")
        blocker = plan_store.badger_store.open_tracking()
        blocker.conn.execute("BEGIN IMMEDIATE")
        blocker.conn.execute(
            "UPDATE plans SET revision = revision + 1 WHERE task_id = ?", (TASK_ID,))
        before = store.plan_row(TASK_ID)

        with pytest.raises(plan_store.PlanStoreError) as excinfo:
            plan_store.update_step(TASK_ID, "s1", _start_step, expected_revision=0,
                                   store=store)
        assert excinfo.value.code == "store-error"
        assert excinfo.value.retryable is True
        assert "database is locked" in str(excinfo.value).lower()
        assert store.plan_row(TASK_ID) == before, "a refused write must not touch the row"

        blocker.conn.rollback()
        blocker.close()
        blocker = None
        landed = plan_store.update_step(TASK_ID, "s1", _start_step, expected_revision=0,
                                        store=store)
        assert landed.revision == 1
    finally:
        if blocker is not None:
            blocker.close()
        store.close()


# --------------------------------------------------------------------------- 4. version gate


def test_newer_schema_version_refuses_before_pydantic_and_leaves_the_row(plan_store):
    """The raw `schema_version` is gated before any model validation: a v2 row that could
    not validate at all refuses with the pinned structured error, and neither load nor
    mutation touches the row."""
    store = plan_store.open_plan_store()
    try:
        store.plan_upsert("future-plan", json.dumps({"schema_version": 2,
                                                     "task_id": "future-plan"}))
        before = store.plan_row("future-plan")
    finally:
        store.close()

    with pytest.raises(plan_store.SchemaVersionUnsupported) as excinfo:
        plan_store.load_plan("future-plan")
    assert plan_store.SUPPORTED_SCHEMA_VERSION == 1
    assert excinfo.value.as_error() == {
        "code": "schema-version-unsupported",
        "found": 2,
        "supported": [1],
        "remediation": "upgrade ai-badger, or re-create the plan with this version",
    }

    with pytest.raises(plan_store.SchemaVersionUnsupported):
        plan_store.update_step("future-plan", "s1", _start_step, expected_revision=0)

    store = plan_store.open_plan_store()
    try:
        assert store.plan_row("future-plan") == before, \
            "a refused version must leave the row byte-identical"
    finally:
        store.close()


def test_version_below_the_floor_with_no_upgrade_hook_refuses(plan_store):
    """An older version is upgraded only through a PLAN_UPGRADES hook; with none
    registered today, it gets the same refusal instead of silent coercion."""
    assert plan_store.model.PLAN_UPGRADES == {}, "v1 is the first version; the seam is empty"
    store = plan_store.open_plan_store()
    try:
        store.plan_upsert("legacy-plan", json.dumps({"schema_version": 0,
                                                     "task_id": "legacy-plan"}))
        before = store.plan_row("legacy-plan")
    finally:
        store.close()

    with pytest.raises(plan_store.SchemaVersionUnsupported) as excinfo:
        plan_store.load_plan("legacy-plan")
    assert excinfo.value.as_error()["found"] == 0
    assert excinfo.value.as_error()["supported"] == [1]
    with pytest.raises(plan_store.SchemaVersionUnsupported):
        plan_store.decode_plan(json.dumps({"schema_version": 0, "task_id": TASK_ID}))

    store = plan_store.open_plan_store()
    try:
        assert store.plan_row("legacy-plan") == before
    finally:
        store.close()


def test_mutation_on_a_newer_schema_row_refuses_and_leaves_it_untouched(plan_store):
    """The gate is in the store adapter once, so the mutation path refuses identically."""
    store = plan_store.open_plan_store()
    try:
        store.plan_upsert("future-plan", json.dumps({"schema_version": 7,
                                                     "task_id": "future-plan"}))
        before = store.plan_row("future-plan")
    finally:
        store.close()

    with pytest.raises(plan_store.SchemaVersionUnsupported) as excinfo:
        plan_store.update_step("future-plan", "s1", _start_step, expected_revision=0)
    assert excinfo.value.as_error()["found"] == 7
    store = plan_store.open_plan_store()
    try:
        assert store.plan_row("future-plan") == before
    finally:
        store.close()


# --------------------------------------------------------------------------- 5. refusals


def test_missing_plans_table_refuses_with_an_actionable_remediation(plan_store):
    """A tracking.db that predates the plans table (or lost it) refuses with the
    remediation named, never a traceback."""
    store = plan_store.open_plan_store()
    try:
        store.conn.execute("DROP TABLE plans")
        store.conn.commit()
    finally:
        store.close()

    with pytest.raises(plan_store.PlanStoreError) as excinfo:
        plan_store.load_plan(TASK_ID)
    assert excinfo.value.code == "store-error"
    assert "den-refresh" in str(excinfo.value)
    assert "task pipeline" in str(excinfo.value)

    with pytest.raises(plan_store.PlanStoreError) as writing:
        plan_store.save_plan(_validated(plan_store))
    assert writing.value.code == "store-error"
    assert "den-refresh" in str(writing.value)


def test_missing_store_refuses_with_an_actionable_remediation(plan_store, tmp_path,
                                                              monkeypatch):
    """A tracking root that cannot host the DB (a file in the path) refuses with the
    remediation named, never a traceback."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(blocker / "task-tracking"))

    with pytest.raises(plan_store.PlanStoreError) as excinfo:
        plan_store.open_plan_store()
    assert excinfo.value.code == "store-error"
    assert "den-refresh" in str(excinfo.value)
    assert "task pipeline" in str(excinfo.value)


# --------------------------------------------------------------------------- 6. root precedence


def _run_git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _scratch_worktree(tmp_path):
    """A main checkout carrying the committed marker, plus a linked worktree of it —
    the exact shape `collapse_worktree` exists for."""
    main = tmp_path / "main checkout"
    (main / ".ai-badger").mkdir(parents=True)
    (main / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    _run_git(main, "init", "-q")
    _run_git(main, "config", "user.email", "t@example.com")
    _run_git(main, "config", "user.name", "Test")
    _run_git(main, "add", ".")
    _run_git(main, "commit", "-q", "-m", "init")
    linked = tmp_path / "linked worktree"
    _run_git(main, "worktree", "add", "-b", "feature", str(linked))
    return main.resolve(), linked.resolve()


def test_root_precedence_pins_tracker_lib_on_a_scratch_worktree(plan_store, load_script,
                                                                tmp_path):
    """The frozen precedence, pinned input-for-input against tracker_lib on a scratch
    worktree: CLAUDE_PROJECT_DIR, then the cwd marker walk (collapsed), then the script-dir
    walk stopping at $HOME, then the parents[3] fallback."""
    tracker = load_script(TRACKER_RELPATH)
    main, linked = _scratch_worktree(tmp_path)
    nested = linked / "src" / "deep"
    nested.mkdir(parents=True)
    env_project = tmp_path / "env-project"
    env_project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    cases = [
        ({"CLAUDE_PROJECT_DIR": str(env_project)}, nested, plan_store.SCRIPT_DIR),
        ({}, nested, plan_store.SCRIPT_DIR),
        ({}, outside, linked / "scripts"),
        ({}, outside, plan_store.SCRIPT_DIR),
    ]
    for env, cwd, script_dir in cases:
        assert plan_store.resolve_project_root(env, cwd, script_dir) == \
            tracker.resolve_project_root(env, cwd, script_dir), \
            f"precedence diverged for env={env} cwd={cwd} script_dir={script_dir}"

    assert plan_store.project_above(nested) == tracker.project_above(nested) == main
    assert plan_store.collapse_worktree(linked) == tracker.collapse_worktree(linked) == main

    explicit = tmp_path / "explicit-root"
    assert plan_store.tracking_root(env={
        TRACKING_ROOT_ENV: str(explicit),
        "CLAUDE_PROJECT_DIR": str(env_project),
    }) == explicit, "an explicit tracking root wins over every resolution step"


def test_explicit_tracking_root_wins_over_project_resolution(plan_store, tmp_path,
                                                             monkeypatch):
    explicit = tmp_path / "explicit-root"
    env_project = tmp_path / "env-project"
    env_project.mkdir()
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(explicit))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(env_project))

    assert plan_store.tracking_root() == explicit
    store = plan_store.open_plan_store()
    try:
        assert store.db_path == explicit / "tracking.db"
    finally:
        store.close()


def test_resolved_root_lands_the_store_under_the_resolved_project(plan_store, tmp_path,
                                                                  monkeypatch):
    """With no explicit env, the resolved project root's `.ai-badger/task-tracking` is
    pinned into AI_BADGER_TRACKING_ROOT before the store opens."""
    monkeypatch.delenv(TRACKING_ROOT_ENV, raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)
    (project / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    cwd = project / "src"
    cwd.mkdir()
    expected = project / ".ai-badger" / "task-tracking"

    assert plan_store.tracking_root(env={}, cwd=cwd) == expected
    store = plan_store.open_plan_store(env={}, cwd=cwd)
    try:
        assert store.db_path == expected / "tracking.db"
    finally:
        store.close()
    assert os.environ[TRACKING_ROOT_ENV] == str(expected), \
        "the resolved root must be pinned for later callers in the same process"


# --------------------------------------------------------------------------- 7. tripwire


def test_load_sibling_rejects_a_stale_module_under_the_bare_name(plan_store, tmp_path,
                                                                 monkeypatch):
    """A cached module from another tree must not be served as this file's sibling."""
    stale = types.ModuleType("task_plan_model")
    stale.__file__ = str(tmp_path / "elsewhere" / "task_plan_model.py")
    monkeypatch.setitem(sys.modules, "task_plan_model", stale)

    loaded = plan_store._load_sibling("task_plan_model")

    assert loaded is not stale
    assert Path(loaded.__file__).resolve() == (ROOT / SIBLING_MODEL).resolve()


def test_load_badger_store_rejects_a_stale_module_under_the_bare_name(
        plan_store, tmp_path, monkeypatch):
    """A stale bare-name store would silently serve another tree's schema (A11)."""
    stale = types.ModuleType("badger_store")
    stale.__file__ = str(tmp_path / "elsewhere" / "badger_store.py")
    monkeypatch.setitem(sys.modules, "badger_store", stale)

    loaded = plan_store._load_badger_store()

    assert loaded is not stale
    assert Path(loaded.__file__).resolve() == (ROOT / SIBLING_STORE).resolve()
    assert sys.modules["badger_store"] is stale, (
        "another module's bare-name binding must not be rebound under it")


def test_the_default_root_tripwire_is_armed(plan_store, monkeypatch):
    """The break-it witness every other test leans on: with the env unset, resolving the
    store path reaches the tripwire, so the guard can fail."""
    monkeypatch.delenv(TRACKING_ROOT_ENV, raising=False)
    with pytest.raises(AssertionError, match="_default_badger_root"):
        plan_store.badger_store.tracking_db_path()
