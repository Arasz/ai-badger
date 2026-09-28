"""The task-plan domain model, its checked-in JSON Schema, and the drift gate between them.

One fixture corpus drives three claims: the model round-trips (unicode, timestamps, the
``$schema`` editor hint), the checked-in Draft 2020-12 artifact agrees with the runtime model
on every shape invariant JSON Schema can express, and the three graph invariants it cannot
express (map key == step id, unknown dependency, cycle) are pinned as schema-passes /
model-fails. ``content_hash`` carries one known-answer golden vector (DR5) plus a pair of
tests proving what it does and does not cover.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
MODEL_RELPATH = "features/common/skills/task-decomposition/scripts/task_plan_model.py"
SCHEMA_RELPATH = "schemas/task-plan.schema.json"
GENERATOR_RELPATH = "tooling/task_plan_schema.py"
SCHEMA_ID = "https://github.com/Arasz/ai-badger/schemas/task-plan.schema.json"
DIALECT = "https://json-schema.org/draft/2020-12/schema"

UNICODE = "Größe — naïve café 日本語 ✓ 🐍"

# One pinned known-answer vector (DR5): a literal a refactor cannot quietly change. Produced
# once from the fixture below and recorded here.
GOLDEN_CONTENT_HASH = "b47e37641b43586fc4a697ce627a4c538e9eb99ad5e0bf8db43311ec34893a90"


# ------------------------------------------------------------------------------- fixtures


def _criterion(criterion_id="ac1", *, statement="the check proves it", check=None,
               status="unchecked", evidence=None):
    return {"id": criterion_id, "statement": statement, "check": check, "status": status,
            "evidence": evidence or []}


def _evidence(kind="test", *, summary="pytest passed", ref=None,
              recorded_at="2026-09-28T10:00:00Z"):
    return {"kind": kind, "summary": summary, "ref": ref, "recorded_at": recorded_at}


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


def _plan(**overrides):
    data = {
        "schema_version": 1,
        "task_id": "aib-demo-task",
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


def _step_plan(**step_overrides):
    return _plan(steps={"s1": _step(**step_overrides)})


def _without(payload, *keys):
    data = copy.deepcopy(payload)
    for key in keys:
        data.pop(key, None)
    return data


def _validates(model, payload):
    """True when the runtime model accepts `payload`."""
    try:
        model.TaskPlan.model_validate(payload)
        return True
    except ValidationError:
        return False


def _invalid(model, payload, needle=""):
    """Validate a known-bad fixture; return the human-readable error, asserting it failed."""
    with pytest.raises(ValidationError) as excinfo:
        model.TaskPlan.model_validate(payload)
    text = str(excinfo.value)
    if needle:
        assert needle in text, f"expected {needle!r} in validation error:\n{text}"
    return text


def _error_locs(excinfo):
    return [tuple(error["loc"]) for error in excinfo.value.errors()]


def _schema():
    return json.loads((ROOT / SCHEMA_RELPATH).read_text(encoding="utf-8"))


def _write_tree_with_model(root: Path) -> Path:
    """A hermetic `--root` tree: the model script the generator loads, nothing else."""
    target = root / MODEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / MODEL_RELPATH, target)
    return root


# --------------------------------------------------------------------------- round trip


def test_plan_round_trips_unicode_and_timestamps(load_script):
    model = load_script(MODEL_RELPATH)
    payload = _plan(task_context=UNICODE)
    payload["workflow"]["steps"]["s1"]["goal"] = f"{UNICODE} goal"
    payload["workflow"]["steps"]["s1"]["acceptance_criteria"][0]["statement"] = UNICODE

    plan = model.TaskPlan.model_validate(payload)
    text = plan.model_dump_json(by_alias=True, exclude_none=True)

    assert UNICODE in text, "model_dump_json escaped unicode the fixture wrote literally"
    assert model.TaskPlan.model_validate_json(text) == plan

    dumped = plan.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped["created_at"] == "2026-09-28T10:00:00Z"
    assert dumped["updated_at"] == "2026-09-28T10:00:00+00:00"
    assert dumped["workflow"]["steps"]["s1"]["goal"] == f"{UNICODE} goal"
    assert model.TaskPlan.model_validate(dumped) == plan


def test_schema_hint_is_accepted_and_excluded_from_hashing(load_script):
    model = load_script(MODEL_RELPATH)
    hinted = model.TaskPlan.model_validate(_plan(**{"$schema": "./task-plan.schema.json"}))

    assert hinted.schema_ == "./task-plan.schema.json"
    assert hinted.model_dump(by_alias=True)["$schema"] == "./task-plan.schema.json"
    assert model.content_hash(hinted) == model.content_hash(
        model.TaskPlan.model_validate(_plan()))


# ------------------------------------------------------------------------- V1 .. V12


def test_v1_steps_must_not_be_empty(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _plan(steps={}), "at least 1")


def test_v2_map_key_must_equal_step_id(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _plan(steps={"s1": _step("s2")}), "must equal step.id")


def test_v3_id_patterns(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _plan(task_id="Bad Task"), "String should match pattern")
    _invalid(model, _plan(steps={"S1": _step("S1")}), "String should match pattern")


def test_v4_dependencies_must_be_known_and_not_self(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _plan(steps={"s1": _step("s1", depends_on=["ghost"])}), "unknown step")
    _invalid(model, _plan(steps={"s1": _step("s1", depends_on=["s1"])}), "lists itself")


def test_v5_cycle_is_rejected_and_named(load_script):
    model = load_script(MODEL_RELPATH)
    payload = _plan(steps={
        "a": _step("a", depends_on=["b"]),
        "b": _step("b", depends_on=["a"]),
    })
    text = _invalid(model, payload, "cycle")
    assert "a -> b -> a" in text


def test_v6_duplicate_criterion_ids_are_rejected(load_script):
    model = load_script(MODEL_RELPATH)
    payload = _step_plan(acceptance_criteria=[_criterion("ac1"), _criterion("ac1")])
    _invalid(model, payload, "duplicate acceptance-criterion id")


def test_v6_empty_criterion_list_is_legal_but_a_finding(load_script):
    model = load_script(MODEL_RELPATH)
    plan = model.TaskPlan.model_validate(_step_plan(acceptance_criteria=[]))

    findings = model.plan_quality_findings(plan)
    assert [finding.kind for finding in findings] == ["step_without_acs"]
    assert findings[0].step_id == "s1"
    assert model.plan_quality_findings(
        model.TaskPlan.model_validate(_plan())) == []


def test_v7_unknown_keys_are_rejected_at_every_level(load_script):
    model = load_script(MODEL_RELPATH)
    complete = _step_plan(
        status="complete",
        started_at="2026-09-28T10:00:00Z",
        completed_at="2026-09-28T11:00:00Z",
        acceptance_criteria=[_criterion(status="passed")],
        completion={"completed_by": "tester", "forced": False, "note": None, "evidence": []},
    )
    complete["workflow"]["steps"]["s1"]["completion"]["approved_by"] = "nobody"

    cases = [
        ("top level", _plan(plan_id="x"), ("plan_id",)),
        ("step", _step_plan(package="p1"), ("workflow", "steps", "s1", "package")),
        ("criterion", _step_plan(acceptance_criteria=[
            {"id": "ac1", "statement": "s", "status": "unchecked", "evidence": [],
             "criterion": "x"}]),
         ("workflow", "steps", "s1", "acceptance_criteria", 0, "criterion")),
        ("evidence", _step_plan(acceptance_criteria=[
            _criterion(status="passed", evidence=[_evidence(), {
                "kind": "note", "summary": "s",
                "recorded_at": "2026-09-28T10:00:00Z", "url": "x"}])]),
         ("workflow", "steps", "s1", "acceptance_criteria", 0, "evidence", 1, "url")),
        ("completion", complete, ("workflow", "steps", "s1", "completion", "approved_by")),
    ]
    for label, payload, loc in cases:
        with pytest.raises(ValidationError) as excinfo:
            model.TaskPlan.model_validate(payload)
        locs = _error_locs(excinfo)
        assert loc in locs, f"{label}: expected a failure at {loc}, got {locs}"
        assert "Extra inputs are not permitted" in str(excinfo.value), label


def test_v8_enums_are_closed(load_script):
    model = load_script(MODEL_RELPATH)
    cases = [
        ("loop", _plan(loop="medium"), ("loop",)),
        ("effort", _step_plan(effort="extreme"),
         ("workflow", "steps", "s1", "effort")),
        ("level", _step_plan(level="urgent"),
         ("workflow", "steps", "s1", "level")),
        ("status", _step_plan(status="done"),
         ("workflow", "steps", "s1", "status")),
        ("criterion status", _step_plan(acceptance_criteria=[_criterion(status="skipped")]),
         ("workflow", "steps", "s1", "acceptance_criteria", 0, "status")),
        ("evidence kind", _step_plan(acceptance_criteria=[
            _criterion(status="passed", evidence=[_evidence(kind="screenshot")])]),
         ("workflow", "steps", "s1", "acceptance_criteria", 0, "evidence", 0, "kind")),
    ]
    for label, payload, loc in cases:
        with pytest.raises(ValidationError) as excinfo:
            model.TaskPlan.model_validate(payload)
        assert loc in _error_locs(excinfo), label


def test_v9_schema_version_is_one_and_revision_non_negative(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _plan(schema_version=2), "Input should be 1")
    _invalid(model, _plan(revision=-1), "greater than or equal to 0")


def test_v10_timestamps_are_iso8601_utc(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _plan(created_at="yesterday"), "ISO-8601")
    _invalid(model, _plan(updated_at="2026-01-01T00:00:00"), "not UTC")
    _invalid(model, _step_plan(started_at="2026-09-28T10:00:00+05:00"), "not UTC")
    _invalid(model, _step_plan(status="complete",
                              started_at="2026-09-28T10:00:00Z",
                              completed_at="2026-09-28T11:00:00Z",
                              acceptance_criteria=[_criterion(
                                  status="passed",
                                  evidence=[_evidence(recorded_at="not a time")])]),
              "ISO-8601")


def test_v11_completion_consistency(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _step_plan(status="complete",
                               acceptance_criteria=[_criterion(status="passed")]),
              "completed_at is missing")
    _invalid(model, _step_plan(status="complete",
                               completed_at="2026-09-28T11:00:00Z"), "completion.forced")
    _invalid(model, _step_plan(
        status="complete", completed_at="2026-09-28T11:00:00Z",
        completion={"completed_by": None, "forced": False, "note": "nope", "evidence": []}),
        "completion.forced")
    _invalid(model, _step_plan(
        status="complete", completed_at="2026-09-28T11:00:00Z",
        completion={"completed_by": "tester", "forced": True, "note": "  ", "evidence": []}),
        "note must say why")
    _invalid(model, _step_plan(status="in_progress"), "started_at is missing")

    forced = model.TaskPlan.model_validate(_step_plan(
        status="complete", started_at="2026-09-28T10:00:00Z",
        completed_at="2026-09-28T11:00:00Z",
        acceptance_criteria=[_criterion(status="failed")],
        completion={"completed_by": "tester", "forced": True, "note": "owner waived",
                    "evidence": [_evidence(kind="review")]}))
    assert forced.workflow.steps["s1"].completion.forced is True


def test_v12_completed_at_must_not_precede_started_at(load_script):
    model = load_script(MODEL_RELPATH)
    _invalid(model, _step_plan(
        status="complete", started_at="2026-09-28T11:00:00Z",
        completed_at="2026-09-28T10:00:00Z",
        acceptance_criteria=[_criterion(status="passed")]),
        "precedes started_at")


def test_versioning_hooks_are_declared(load_script):
    model = load_script(MODEL_RELPATH)
    assert model.SUPPORTED_SCHEMA_VERSION == 1
    assert model.PLAN_UPGRADES == {}
    assert _schema()["properties"]["schema_version"]["const"] == 1


# ------------------------------------------------------------------------ content hash


def test_content_hash_golden_vector(load_script):
    model = load_script(MODEL_RELPATH)
    plan = model.TaskPlan.model_validate(_plan())
    assert model.content_hash(plan) == GOLDEN_CONTENT_HASH


def test_content_hash_ignores_runtime_state_and_schema_hint(load_script):
    model = load_script(MODEL_RELPATH)
    variant = copy.deepcopy(_plan())
    variant["revision"] = 7
    variant["created_at"] = "2026-09-29T00:00:00Z"
    variant["updated_at"] = "2026-09-29T01:00:00Z"
    variant["$schema"] = "./task-plan.schema.json"
    step = variant["workflow"]["steps"]["s1"]
    step["status"] = "complete"
    step["started_at"] = "2026-09-28T10:00:00Z"
    step["completed_at"] = "2026-09-28T11:00:00Z"
    step["completion"] = {"completed_by": "tester", "forced": False, "note": None,
                          "evidence": [_evidence()]}
    criterion = step["acceptance_criteria"][0]
    criterion["status"] = "passed"
    criterion["evidence"] = [_evidence()]

    assert model.content_hash(model.TaskPlan.model_validate(variant)) == \
        model.content_hash(model.TaskPlan.model_validate(_plan()))


def test_content_hash_tracks_authored_content(load_script):
    model = load_script(MODEL_RELPATH)
    base = model.content_hash(model.TaskPlan.model_validate(_plan()))

    def _add_dependency(payload):
        payload["workflow"]["steps"]["s2"] = _step("s2")
        payload["workflow"]["steps"]["s1"].update(depends_on=["s2"])

    mutations = {
        "research_ref": lambda p: p.update(research_ref="docs/work/research.md"),
        "task_context": lambda p: p.update(task_context="different"),
        "loop": lambda p: p.update(loop="low"),
        "source_refs": lambda p: p.update(source_refs=["docs/work/other.md"]),
        "step goal": lambda p: p["workflow"]["steps"]["s1"].update(goal="different"),
        "step instructions": lambda p: p["workflow"]["steps"]["s1"].update(instructions="x"),
        "step effort": lambda p: p["workflow"]["steps"]["s1"].update(effort="high"),
        "step level": lambda p: p["workflow"]["steps"]["s1"].update(level="high"),
        "step model": lambda p: p["workflow"]["steps"]["s1"].update(model="claude-sonnet"),
        "step persona": lambda p: p["workflow"]["steps"]["s1"].update(persona="architect"),
        "step depends_on": _add_dependency,
        "step files": lambda p: p["workflow"]["steps"]["s1"].update(files=["b.py"]),
        "step resources": lambda p: p["workflow"]["steps"]["s1"].update(resources=["gpu"]),
        "criterion statement": lambda p: p["workflow"]["steps"]["s1"]["acceptance_criteria"][0]
        .update(statement="different"),
        "criterion check": lambda p: p["workflow"]["steps"]["s1"]["acceptance_criteria"][0]
        .update(check="pytest -q"),
    }
    for label, mutate in mutations.items():
        payload = copy.deepcopy(_plan())
        mutate(payload)
        assert model.content_hash(model.TaskPlan.model_validate(payload)) != base, label


def test_content_hash_is_order_independent_for_the_step_map(load_script):
    model = load_script(MODEL_RELPATH)
    s2 = _step("s2", depends_on=["s1"])
    ordered = _plan(steps={"s1": _step(), "s2": s2})
    reordered = _plan(steps={"s2": copy.deepcopy(s2), "s1": _step()})
    assert model.content_hash(model.TaskPlan.model_validate(ordered)) == \
        model.content_hash(model.TaskPlan.model_validate(reordered))


# --------------------------------------------------------------- artifact and generator


def test_checked_in_schema_is_the_generated_one(load_script):
    generator = load_script(GENERATOR_RELPATH)
    generated = generator.build_schema(generator.load_model(ROOT))
    assert _schema() == generated


def test_schema_artifact_shape(load_script):
    model = load_script(MODEL_RELPATH)
    generator = load_script(GENERATOR_RELPATH)
    schema = _schema()

    assert schema["$schema"] == DIALECT
    assert schema["$id"] == SCHEMA_ID
    assert schema["title"] == "TaskPlan"
    assert schema["additionalProperties"] is False
    assert "$schema" in schema["properties"]
    assert generator.steps_schema(schema)["propertyNames"] == {
        "pattern": model.STEP_ID_PATTERN}
    assert "JSON Schema cannot express" in schema["description"]
    assert "cycle" in schema["description"]


def test_generator_writes_and_checks_canonically(load_script, tmp_path, capsys):
    generator = load_script(GENERATOR_RELPATH)
    root = _write_tree_with_model(tmp_path / "tree")

    assert generator.main(["--root", str(root)]) == 0
    expected = generator.canonical_text(generator.build_schema(generator.load_model(root)))
    written = (root / SCHEMA_RELPATH).read_text(encoding="utf-8")
    assert written == expected
    assert written.endswith("\n")

    capsys.readouterr()
    assert generator.main(["--check", "--root", str(root)]) == 0

    stale = json.loads(written)
    stale["required"].remove("task_id")
    (root / SCHEMA_RELPATH).write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")
    assert generator.main(["--check", "--root", str(root)]) == 1
    assert "/required/9" in capsys.readouterr().out


def test_generator_check_rejects_a_missing_artifact(load_script, tmp_path):
    generator = load_script(GENERATOR_RELPATH)
    root = _write_tree_with_model(tmp_path / "tree")
    assert generator.main(["--check", "--root", str(root)]) == 1


# ------------------------------------------------------------------ dual validator


def _schema_expressible_corpus():
    """Cases both validators can judge; the pydantic-only DAG cases live separately."""
    complete_step = dict(
        status="complete", started_at="2026-09-28T10:00:00Z",
        completed_at="2026-09-28T11:00:00Z",
        acceptance_criteria=[_criterion(status="passed", evidence=[_evidence()])],
        completion={"completed_by": "tester", "forced": False, "note": None,
                    "evidence": [_evidence()]})
    valid_multi = _plan(steps={"s1": _step(), "s2": _step("s2", depends_on=["s1"])})

    return [
        ("valid", _plan()),
        ("valid-runtime-state", _step_plan(**complete_step)),
        ("valid-unicode", _plan(
            task_context=UNICODE,
            steps={"s1": _step(goal=UNICODE, acceptance_criteria=[
                _criterion(statement=UNICODE)])})),
        ("valid-multi-step", valid_multi),
        ("valid-empty-ac-list", _step_plan(acceptance_criteria=[])),
        ("valid-schema-hint", _plan(**{"$schema": "./task-plan.schema.json"})),
        ("missing-task-id", _without(_plan(), "task_id")),
        ("missing-revision", _without(_plan(), "revision")),
        ("missing-created-at", _without(_plan(), "created_at")),
        ("missing-workflow", _without(_plan(), "workflow")),
        ("missing-step-goal", _plan(steps={"s1": _without(_step(), "goal")})),
        ("unknown-top-level", _plan(plan_id="x")),
        ("unknown-step-key", _step_plan(package="p1")),
        ("unknown-criterion-key", _step_plan(acceptance_criteria=[
            {"id": "ac1", "statement": "s", "status": "unchecked", "evidence": [],
             "criterion": "x"}])),
        ("unknown-evidence-key", _step_plan(acceptance_criteria=[
            _criterion(evidence=[{"kind": "note", "summary": "s",
                                  "recorded_at": "2026-09-28T10:00:00Z", "url": "x"}])])),
        ("empty-steps", _plan(steps={})),
        ("steps-not-object", _plan(steps=["s1"])),
        ("step-not-object", _plan(steps={"s1": "s1"})),
        ("bad-loop", _plan(loop="medium")),
        ("bad-effort", _step_plan(effort="extreme")),
        ("bad-step-status", _step_plan(status="done")),
        ("bad-criterion-status", _step_plan(acceptance_criteria=[
            _criterion(status="skipped")])),
        ("bad-evidence-kind", _step_plan(acceptance_criteria=[
            _criterion(evidence=[_evidence(kind="screenshot")])])),
        ("bad-task-id-pattern", _plan(task_id="Bad Task")),
        ("bad-step-id-pattern", _plan(steps={"S1": _step("S1")})),
        ("schema-version-2", _plan(schema_version=2)),
        ("negative-revision", _plan(revision=-1)),
        ("created-at-not-string", _plan(created_at=20260928)),
        ("source-refs-not-array", _plan(source_refs="docs/work/plan.md")),
        ("depends-on-not-array", _step_plan(depends_on="s1")),
        ("criteria-not-array", _step_plan(acceptance_criteria={"ac1": _criterion()})),
        ("step-id-not-string", _plan(steps={"s1": _step(1)})),
    ]


def test_dual_validator_verdicts_agree_over_the_corpus(load_script):
    model = load_script(MODEL_RELPATH)
    validator = Draft202012Validator(_schema())
    corpus = _schema_expressible_corpus()
    verdicts = []
    for name, payload in corpus:
        schema_ok = not list(validator.iter_errors(payload))
        verdicts.append((name, schema_ok, _validates(model, payload)))

    disagreements = [(name, schema_ok, model_ok) for name, schema_ok, model_ok in verdicts
                     if schema_ok != model_ok]
    assert not disagreements, f"schema and model disagree: {disagreements}"
    outcomes = {ok for _, ok, _ in verdicts}
    assert outcomes == {True, False}, "the corpus proves only one verdict"


def test_pydantic_only_dag_invariants_pass_schema_fail_model(load_script):
    """The boundary B2 documents: the three DAG rules no JSON Schema can state."""
    model = load_script(MODEL_RELPATH)
    validator = Draft202012Validator(_schema())
    cases = {
        "cycle": _plan(steps={
            "a": _step("a", depends_on=["b"]), "b": _step("b", depends_on=["a"])}),
        "unknown-dependency": _plan(steps={"a": _step("a", depends_on=["ghost"])}),
        "key-not-id": _plan(steps={"a": _step("b")}),
    }
    for name, payload in cases.items():
        assert not list(validator.iter_errors(payload)), \
            f"{name}: the schema was expected to pass this fixture"
        with pytest.raises(ValidationError):
            model.TaskPlan.model_validate(payload)
