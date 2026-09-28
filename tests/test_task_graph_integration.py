"""Cross-step integration: the assembled task-decomposition pipeline over the real modules.

This is the S13 join proof. One fixture brief is decomposed with the domain model, created
over the MCP transport's real pipes, dispatched through the deferral waves (start, AC check,
fail + retry, skip, complete), rendered by the server, and read back through
`status_report`'s independent parser. The degraded path (DR12) reports a hand-written plan
with no server row. Every seam S1-S12 built is exercised as the interface it exposes:
model -> store -> server -> renderer -> status-report, with the schema artifact and the
content hash as the cross-module contracts.

Every store path is routed under `tmp_path` via `AI_BADGER_TRACKING_ROOT`; the in-process
store copy the tripwire test loads is armed so any fallback to `_default_badger_root()`
fails loudly instead of writing the developer's real checkout.

Test map:
  1. create ........ test_scenario_1_decompose_and_create_match_the_model_hash
  2. dispatch ...... test_scenario_2_waves_deferral_retry_and_skip_advance_the_frontier
  3. progress ...... test_scenario_3_text_and_rendered_file_agree_with_status_report
  4. refusal ....... test_scenario_4_replace_refuses_mid_execution_then_bumps_pending
  5. export ........ test_scenario_5_export_validates_under_both_validators
  6. degraded ...... test_scenario_6_handwritten_plan_reports_without_a_server_row
  7. tripwire ...... test_the_default_root_tripwire_is_armed
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import jsonschema
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SERVER_RELPATH = "features/common/skills/task-decomposition/scripts/task_graph_server.py"
MODEL_RELPATH = "features/common/skills/task-decomposition/scripts/task_plan_model.py"
STORE_RELPATH = "features/common/skills/task-decomposition/scripts/task_plan_store.py"
STATUS_RELPATH = "features/common/skills/status-report/scripts/status_report.py"
SCHEMA_PATH = ROOT / "schemas" / "task-plan.schema.json"
SERVER = ROOT / SERVER_RELPATH
TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"
TRACKING = Path(".ai-badger") / "task-tracking"
TASK_ID = "aib-integration-demo"
PENDING_TASK_ID = "aib-integration-pending"

# The fixture brief: a small realistic slice with five work steps plus a join step. Its
# geometry is deliberate — s1 and s2 are both dependency-ready but share `src/reminder.py`,
# so the deferral rule must split them across waves; s6 is the integration sink the join
# rule and the cross-step acceptance criteria hang off.
FIXTURE_BRIEF = (
    "Ship the reminder slice end to end: model a reminder, wire the CLI, dispatch due "
    "reminders, cover the CLI with tests, document the guide, and join with an integration "
    "step that proves every other step's acceptance criteria passed."
)

STEPS = [
    {
        "id": "s1", "goal": "model the reminder",
        "instructions": "A Reminder value object with a due date; invalid dates are refused.",
        "effort": "high", "level": "high", "persona": "api-engineer",
        "depends_on": [],
        "acceptance_criteria": [
            {"id": "s1-ac1", "statement": "the model round-trips a reminder",
             "check": "pytest tests/test_reminder_model.py -q"},
            {"id": "s1-ac2", "statement": "an invalid due date is refused",
             "check": "pytest tests/test_reminder_model.py -q -k invalid"},
        ],
        "files": ["src/reminder.py"], "resources": [],
    },
    {
        "id": "s2", "goal": "wire the reminder CLI",
        "instructions": "Add `reminder add`; it prints one line and uses the model.",
        "effort": "medium", "depends_on": [],
        "acceptance_criteria": [
            {"id": "s2-ac1", "statement": "the CLI prints a reminder",
             "check": "pytest tests/test_reminder_cli.py -q -k add"},
        ],
        "files": ["src/reminder.py", "src/cli.py"], "resources": [],
    },
    {
        "id": "s3", "goal": "dispatch reminders",
        "instructions": "Dispatch due reminders through the model.",
        "effort": "medium", "depends_on": ["s1"],
        "acceptance_criteria": [
            {"id": "s3-ac1", "statement": "dispatch reads the model",
             "check": "pytest tests/test_dispatch.py -q"},
        ],
        "files": ["src/dispatch.py"], "resources": [],
    },
    {
        "id": "s4", "goal": "cover the CLI with tests",
        "instructions": "Add the CLI suite; it must be green.",
        "effort": "low", "depends_on": ["s2", "s3"],
        "acceptance_criteria": [
            {"id": "s4-ac1", "statement": "the CLI suite is green",
             "check": "pytest tests/test_reminder_cli.py -q"},
        ],
        "files": ["tests/test_reminder_cli.py"], "resources": [],
    },
    {
        "id": "s5", "goal": "document the reminders",
        "instructions": "Write the guide and link it from the README.",
        "effort": "low", "depends_on": ["s1"],
        "acceptance_criteria": [
            {"id": "s5-ac1", "statement": "README links the reminder guide",
             "check": "pytest tests/test_docs_links.py -q"},
        ],
        "files": ["docs/reminders.md"], "resources": [],
    },
    {
        "id": "s6", "goal": "join: prove the pipeline",
        "instructions": "Exercise every step's output together and record the evidence.",
        "effort": "high", "level": "high", "persona": "code-reviewer",
        "depends_on": ["s2", "s3", "s4", "s5"],
        "acceptance_criteria": [
            {"id": "s6-ac1",
             "statement": "every step's acceptance criteria passed and the plan is complete",
             "check": "progress_checklist reports 6/6 steps complete"},
            {"id": "s6-ac2",
             "statement": "the rendered plan file agrees with the graph state",
             "check": "status_report.plan_checklist agrees with progress_checklist"},
        ],
        "files": ["src/integration.py"], "resources": [],
    },
]

# The fixture's expected wave geometry, asserted in scenario 2. s1/s2 share a file; the
# join is the only step depending on every other sink.
EXPECTED_WAVES = [["s1"], ["s2", "s3", "s5"], ["s4"], ["s6"]]


def _spec(step_id: str) -> dict:
    return next(spec for spec in STEPS if spec["id"] == step_id)


def _model_step(spec: dict) -> dict:
    """One authored step with the runtime fields the model requires at rest."""
    return {
        "id": spec["id"], "goal": spec["goal"], "instructions": spec["instructions"],
        "effort": spec["effort"], "level": spec.get("level"), "model": spec.get("model"),
        "persona": spec.get("persona"), "depends_on": list(spec["depends_on"]),
        "acceptance_criteria": [
            {"id": ac["id"], "statement": ac["statement"], "check": ac["check"],
             "status": "unchecked", "evidence": []}
            for ac in spec["acceptance_criteria"]],
        "files": list(spec["files"]), "resources": list(spec["resources"]),
        "status": "pending", "started_at": None, "completed_at": None, "completion": None,
    }


def _decompose(plan_model):
    """The fixture brief as a validated `TaskPlan` — the pre-transport half of the seam."""
    document = {
        "schema_version": plan_model.SUPPORTED_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "task_description_ref": "docs/work/2026-09-28-task-decomposition-plan.md",
        "research_ref": "docs/work/2026-09-28-task-decomposition-brief.md",
        "task_context": FIXTURE_BRIEF,
        "loop": "high",
        "source_refs": ["docs/work/2026-09-28-task-decomposition-plan.md"],
        "workflow": {"steps": {spec["id"]: _model_step(spec) for spec in STEPS}},
        "revision": 0,
        "created_at": "2026-09-28T10:00:00Z",
        "updated_at": "2026-09-28T10:00:00Z",
    }
    return plan_model.TaskPlan.model_validate(document)


def _create_args(plan, **overrides) -> dict:
    """The model's authored content projected onto `plan_create`'s wire arguments."""
    steps = [
        {
            "id": step.id, "goal": step.goal, "instructions": step.instructions,
            "effort": step.effort.value,
            "level": step.level.value if step.level is not None else None,
            "model": step.model, "persona": step.persona,
            "depends_on": list(step.depends_on),
            "acceptance_criteria": [
                {"id": ac.id, "statement": ac.statement, "check": ac.check}
                for ac in step.acceptance_criteria],
            "files": list(step.files), "resources": list(step.resources),
        }
        for step in (plan.workflow.steps[step_id]
                     for step_id in sorted(plan.workflow.steps))
    ]
    args = {
        "task_id": plan.task_id,
        "task_description_ref": plan.task_description_ref,
        "task_context": plan.task_context,
        "research_ref": plan.research_ref,
        "loop": plan.loop.value,
        "source_refs": list(plan.source_refs),
        "steps": steps,
    }
    args.update(overrides)
    return args


def _replace_args(plan, expected_revision: int, **overrides) -> dict:
    return _create_args(plan, expected_revision=expected_revision, **overrides)


# ------------------------------------------------------------------------------- the pipe


class McpServer:
    """One spawned server process, addressed in NDJSON over its real stdin/stdout pipes."""

    def __init__(self, root: Path):
        env = dict(os.environ)
        env[TRACKING_ROOT_ENV] = str(root / TRACKING)
        self._proc = subprocess.Popen(
            [sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self._next_id = 0

    def send(self, payload) -> None:
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def call(self, method: str, params=None) -> dict:
        """One request/response round trip; returns the full JSON-RPC envelope."""
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        return self.read()

    def read(self) -> dict:
        line = self._proc.stdout.readline()
        if not line:
            raise AssertionError(
                f"task-graph server exited (rc={self._proc.poll()}):\n"
                f"{self._proc.stderr.read()}")
        return json.loads(line)

    def finished(self) -> bool:
        return self._proc.poll() is not None

    def close(self) -> None:
        if not self._proc.stdin.closed:
            self._proc.stdin.close()
        rc = self._proc.wait(timeout=10)
        assert rc == 0, f"server exited {rc}:\n{self._proc.stderr.read()}"


@pytest.fixture
def plan_model(load_script):
    """The domain model loaded by repo-relative path (the emitter both halves share)."""
    return load_script(MODEL_RELPATH)


@pytest.fixture(autouse=True)
def _isolated_tracking_root(load_script, monkeypatch, tmp_path):
    """Every in-process store read is routed under `tmp_path`; the fallback is a tripwire."""
    store = load_script(STORE_RELPATH)
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(tmp_path / TRACKING))

    def tripwire():
        raise AssertionError(
            "test path reached _default_badger_root(); set AI_BADGER_TRACKING_ROOT instead")

    monkeypatch.setattr(store.badger_store, "_default_badger_root", tripwire)
    yield store


@pytest.fixture
def mcp(tmp_path):
    """A factory of live server processes, all closed at test end."""
    started = []

    def start(root: Optional[Path] = None) -> McpServer:
        server = McpServer(Path(root) if root is not None else tmp_path)
        started.append(server)
        return server

    yield start
    for server in started:
        if not server.finished():
            try:
                server.close()
            except AssertionError:
                pass


# ------------------------------------------------------------------ tool-call shorthands


def _tool(server: McpServer, name: str, arguments: dict) -> dict:
    response = server.call("tools/call", {"name": name, "arguments": arguments})
    assert "result" in response, response
    return response["result"]


def _payload(server: McpServer, name: str, arguments: dict) -> dict:
    result = _tool(server, name, arguments)
    assert result.get("isError") is False, result
    return result["structuredContent"]


def _refusal(server: McpServer, name: str, arguments: dict, code: str) -> dict:
    result = _tool(server, name, arguments)
    assert result.get("isError") is True, result
    envelope = result["structuredContent"]
    assert envelope["ok"] is False, envelope
    assert envelope["error"]["code"] == code, envelope["error"]
    return envelope["error"]


def _evidence(summary: str, *, kind: str = "test") -> dict:
    return {"kind": kind, "summary": summary, "ref": None,
            "recorded_at": "2026-09-28T10:00:00Z"}


def _create(server: McpServer, plan, **overrides) -> dict:
    return _payload(server, "plan_create", _create_args(plan, **overrides))


def _complete_step(server: McpServer, step_id: str, revision: int, ac_ids: list):
    """start -> one ac_check per criterion -> complete, returning (revision, payload)."""
    started = _payload(server, "step_start", {
        "task_id": TASK_ID, "step_id": step_id, "expected_revision": revision})
    if started["changed"]:
        revision = started["revision"]
    else:  # an already in_progress step replays as a no-op; keep its revision
        assert started["step"]["status"] == "in_progress", started
    for ac_id in ac_ids:
        checked = _payload(server, "ac_check", {
            "task_id": TASK_ID, "step_id": step_id, "ac_id": ac_id,
            "expected_revision": revision, "status": "passed",
            "evidence": [_evidence(f"{ac_id} recorded by the integration harness")]})
        assert checked["changed"] is True, checked
        revision = checked["revision"]
    done = _payload(server, "step_complete", {
        "task_id": TASK_ID, "step_id": step_id, "expected_revision": revision,
        "evidence": [_evidence(f"{step_id} completed by the integration harness")],
        "criterion_results": {}})
    assert done["changed"] is True, done
    return done["revision"], done


def _rendered_plan_path(project: Path) -> Path:
    files = sorted((project / TRACKING / "plans").glob(f"*-{TASK_ID}.md"))
    assert len(files) == 1, files
    return files[0]


# ------------------------------------------------------------------- 1. decompose + create


def test_scenario_1_decompose_and_create_match_the_model_hash(mcp, plan_model):
    server = mcp()
    plan = _decompose(plan_model)
    payload = _create(server, plan)

    assert set(payload) == {
        "task_id", "revision", "schema_version", "content_hash", "created", "steps",
        "ready", "waves"}
    assert payload["task_id"] == TASK_ID
    assert payload["created"] is True
    assert payload["revision"] == 0
    assert payload["schema_version"] == 1
    assert payload["steps"] == len(plan.workflow.steps) == 6

    # The cross-module contract: the server hashes the same authored content the model built.
    assert payload["content_hash"] == plan_model.content_hash(plan)

    assert payload["waves"] == EXPECTED_WAVES
    assert [ref["id"] for ref in payload["ready"]] == ["s1", "s2"]
    assert all(ref["blocked_by"] == [] and ref["skipped_deps"] == []
               for ref in payload["ready"])

    state = _payload(server, "plan_get", {"task_id": TASK_ID, "include": "state"})
    assert state["integration_ok"] is True
    assert state["integration_sink"] == "s6"


# ------------------------------------------------------------------------ 2. dispatch waves


def test_scenario_2_waves_deferral_retry_and_skip_advance_the_frontier(mcp, plan_model):
    server = mcp()
    plan = _decompose(plan_model)
    revision = _create(server, plan)["revision"]

    frontier = _payload(server, "steps_ready", {"task_id": TASK_ID})
    assert [ref["id"] for ref in frontier["ready"]] == ["s1", "s2"]
    assert frontier["waves"] == EXPECTED_WAVES

    # The deferral proof: both are dependency-ready, share a file, and never share a wave.
    assert set(_spec("s1")["files"]) & set(_spec("s2")["files"])
    wave_of = {step_id: index
               for index, wave in enumerate(frontier["waves"]) for step_id in wave}
    assert wave_of["s1"] != wave_of["s2"]

    # Wave 0 (s1) completes: the frontier and waves advance to the next admitted prefix.
    revision, completed = _complete_step(server, "s1", revision, ["s1-ac1", "s1-ac2"])
    assert [ref["id"] for ref in completed["ready"]] == ["s2", "s3", "s5"]
    advanced = _payload(server, "steps_ready", {"task_id": TASK_ID})
    assert advanced["waves"] == [["s2", "s3", "s5"], ["s4"], ["s6"]]

    revision, _ = _complete_step(server, "s2", revision, ["s2-ac1"])

    # Failure propagates to descendants, and a failed step re-enters the frontier for retry.
    started = _payload(server, "step_start", {
        "task_id": TASK_ID, "step_id": "s3", "expected_revision": revision})
    revision = started["revision"]
    failed = _payload(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s3", "expected_revision": revision,
        "reason": "the dispatch suite is red", "evidence": [_evidence("gate failed")]})
    revision = failed["revision"]
    assert failed["step"]["status"] == "failed"
    assert failed["blocked"] == [
        {"id": "s4", "blocked_by": ["s3"]},
        {"id": "s6", "blocked_by": ["s3"]},
    ]
    retry_frontier = _payload(server, "steps_ready", {"task_id": TASK_ID})
    assert [ref["id"] for ref in retry_frontier["ready"]] == ["s3", "s5"]

    retried = _payload(server, "step_start", {
        "task_id": TASK_ID, "step_id": "s3", "expected_revision": revision})
    revision = retried["revision"]
    assert retried["step"]["status"] == "in_progress"
    checked = _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s3", "ac_id": "s3-ac1",
        "expected_revision": revision, "status": "passed",
        "evidence": [_evidence("retry run passed")]})
    revision = checked["revision"]
    done = _payload(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s3", "expected_revision": revision,
        "evidence": [_evidence("dispatch green after the retry")], "criterion_results": {}})
    revision = done["revision"]
    assert done["step"]["status"] == "complete"

    # DR7 amendment: a never-started step is retired directly, without a forced start.
    skipped = _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s5", "expected_revision": revision,
        "reason": "docs deferred to the follow-up slice"})
    revision = skipped["revision"]
    assert skipped["step"]["status"] == "skipped"
    after_skip = _payload(server, "steps_ready", {"task_id": TASK_ID})
    assert [ref["id"] for ref in after_skip["ready"]] == ["s4"]
    # A skipped dep satisfies readiness but stays surfaced as a blocked ancestor (DR7).
    assert after_skip["blocked"] == [{"id": "s6", "blocked_by": ["s5"]}]

    revision, _ = _complete_step(server, "s4", revision, ["s4-ac1"])
    join_frontier = _payload(server, "steps_ready", {"task_id": TASK_ID})
    assert [ref["id"] for ref in join_frontier["ready"]] == ["s6"]
    assert join_frontier["ready"][0]["skipped_deps"] == ["s5"]
    assert join_frontier["waves"] == [["s6"]]
    assert join_frontier["blocked"] == [{"id": "s6", "blocked_by": ["s5"]}]

    revision, joined = _complete_step(server, "s6", revision, ["s6-ac1", "s6-ac2"])
    assert joined["ready"] == []
    final = _payload(server, "progress_checklist", {"task_id": TASK_ID})
    # s5 was retired, so five steps are complete and the skipped one still counts as remaining.
    assert final["complete"] == 5
    assert final["total"] == 6
    assert final["next"] == []
    assert [row["marker"] for row in final["steps"]] == ["x", "x", "x", "x", "-", "x"]


# ------------------------------------------------------------ 3. progress + render + parse


def test_scenario_3_text_and_rendered_file_agree_with_status_report(mcp, plan_model,
                                                                    tmp_path, load_script):
    server = mcp()
    plan = _decompose(plan_model)
    revision = _create(server, plan)["revision"]

    # A mixed state: complete, in_progress, failed, pending, skipped, pending.
    revision, _ = _complete_step(server, "s1", revision, ["s1-ac1", "s1-ac2"])
    started = _payload(server, "step_start", {
        "task_id": TASK_ID, "step_id": "s2", "expected_revision": revision})
    revision = started["revision"]
    started = _payload(server, "step_start", {
        "task_id": TASK_ID, "step_id": "s3", "expected_revision": revision})
    revision = started["revision"]
    failed = _payload(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s3", "expected_revision": revision,
        "reason": "the dispatch suite is red", "evidence": []})
    revision = failed["revision"]
    skipped = _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s5", "expected_revision": revision,
        "reason": "docs deferred"})
    assert skipped["changed"] is True

    payload = _payload(server, "progress_checklist",
                       {"task_id": TASK_ID, "format": "text"})
    assert payload["complete"] == 1
    assert payload["total"] == 6
    assert payload["blocked"] == [
        {"id": "s4", "blocked_by": ["s3"]},
        {"id": "s6", "blocked_by": ["s3", "s5"]},
    ]
    assert payload["text"] == "\n".join([
        f"# {TASK_ID} — 1/6 steps complete",
        "- [x] S1 model the reminder (2/2 criteria)",
        "- [~] S2 wire the reminder CLI (0/1 criteria)",
        "- [!] S3 dispatch reminders (0/1 criteria)",
        "- [ ] S4 cover the CLI with tests (0/1 criteria)",
        "- [-] S5 document the reminders (0/1 criteria)",
        "- [ ] S6 join: prove the pipeline (0/2 criteria)",
    ])

    # The server-rendered file is the graph state's projection: `S` headings, one box per AC.
    plan_file = _rendered_plan_path(tmp_path)
    text = plan_file.read_text(encoding="utf-8")
    assert text.startswith("<!-- generated by task-graph")
    headings = re.findall(r"^\*\*S(\d+) — (.*?) \(([a-z_]+)\)\*\*$", text, re.M)
    assert [(int(number), goal, status) for number, goal, status in headings] == [
        (index, row["goal"], row["status"])
        for index, row in enumerate(payload["steps"], start=1)]
    boxes = re.findall(r"^- \[([ x])\] ", text, re.M)
    assert len(boxes) == sum(row["criteria"]["total"] for row in payload["steps"]) == 8
    assert boxes.count("x") == sum(row["criteria"]["passed"] for row in payload["steps"]) == 2

    # An independent parser (S11's dual-read) sees the same plan the graph holds.
    status = load_script(STATUS_RELPATH)
    checklist = status.plan_checklist(tmp_path, TASK_ID)
    assert checklist["matched"] is True
    assert checklist["plan_file"] == str(plan_file)
    assert checklist["packages"] == [
        f"S{index} — {row['goal']} ({row['status']})"
        for index, row in enumerate(payload["steps"], start=1)]
    assert checklist["checked"] == sum(
        row["criteria"]["passed"] for row in payload["steps"]) == 2
    assert checklist["total"] == sum(
        row["criteria"]["total"] for row in payload["steps"]) == 8
    assert len(checklist["packages"]) == payload["total"] == 6


# --------------------------------------------------------------- 4. mid-execution refusal


def test_scenario_4_replace_refuses_mid_execution_then_bumps_pending(mcp, plan_model):
    server = mcp()
    plan = _decompose(plan_model)
    _create(server, plan)

    started = _payload(server, "step_start", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 0})
    revision = started["revision"]
    in_progress = _refusal(server, "plan_replace", _replace_args(
        plan, revision, task_context="re-authored mid-flight"), "plan-in-progress")
    assert in_progress["details"]["blocking_steps"] == ["s1"]

    # A completed step blocks a re-plan exactly as an in-flight one does.
    revision, _ = _complete_step(server, "s1", revision, ["s1-ac1", "s1-ac2"])
    completed = _refusal(server, "plan_replace", _replace_args(
        plan, revision, task_context="re-authored after completion"), "plan-in-progress")
    assert completed["details"]["blocking_steps"] == ["s1"]

    # A pending-only plan re-authors freely and bumps the revision.
    pending = _create(server, plan, task_id=PENDING_TASK_ID)
    assert pending["revision"] == 0
    replaced = _payload(server, "plan_replace", _replace_args(
        plan, 0, task_id=PENDING_TASK_ID,
        task_context="re-authored while every step is still pending"))
    assert replaced["replaced"] is True
    assert replaced["created"] is False
    assert replaced["revision"] == 1
    assert replaced["steps"] == 6
    assert replaced["waves"] == EXPECTED_WAVES
    assert replaced["content_hash"] != pending["content_hash"]


# ---------------------------------------------------------------- 5. export validity


def test_scenario_5_export_validates_under_both_validators(mcp, plan_model):
    server = mcp()
    plan = _decompose(plan_model)
    revision = _create(server, plan)["revision"]
    _complete_step(server, "s1", revision, ["s1-ac1", "s1-ac2"])

    export = _payload(server, "plan_export", {"task_id": TASK_ID})
    document = export["document"]
    assert document["revision"] == 4
    assert document["workflow"]["steps"]["s1"]["status"] == "complete"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    # Both validators accept the exported document, and the hash survives the round trip.
    assert list(validator.iter_errors(document)) == []
    parsed = plan_model.TaskPlan.model_validate(document)
    assert plan_model.content_hash(parsed) == export["content_hash"]
    assert plan_model.content_hash(parsed) == plan_model.content_hash(plan)

    # Verdicts are identical in the refusing direction too — a broken export cannot pass both.
    for label, mutate in (
            ("unknown status", lambda doc: doc["workflow"]["steps"]["s1"].__setitem__(
                "status", "sideways")),
            ("missing identity", lambda doc: doc.pop("task_id")),
            ("unknown criterion status",
             lambda doc: doc["workflow"]["steps"]["s1"]["acceptance_criteria"][0].__setitem__(
                 "status", "maybe")),
    ):
        corrupted = copy.deepcopy(document)
        mutate(corrupted)
        assert list(validator.iter_errors(corrupted)) != [], label
        with pytest.raises(ValidationError):
            plan_model.TaskPlan.model_validate(corrupted)


# --------------------------------------------------------------------- 6. degraded path


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


def test_scenario_6_handwritten_plan_reports_without_a_server_row(tmp_path, load_script):
    plans = tmp_path / TRACKING / "plans"
    plans.mkdir(parents=True)
    (plans / "2026-09-28-aib-graph-off.md").write_text(HANDWRITTEN_PLAN, encoding="utf-8")

    # No server ever ran: no `plans` row, no tracking database at all.
    assert not (tmp_path / TRACKING / "tracking.db").exists()

    status = load_script(STATUS_RELPATH)
    checklist = status.plan_checklist(tmp_path, "aib-graph-off")
    assert checklist["matched"] is True
    assert checklist["plan_file"] == str(plans / "2026-09-28-aib-graph-off.md")
    assert checklist["packages"] == ["S1 — do the thing (pending)",
                                     "S2 — finish (pending)"]
    assert checklist["checked"] == 1
    assert checklist["total"] == 3


# ------------------------------------------------------------------------------ tripwire


def test_the_default_root_tripwire_is_armed(load_script, monkeypatch):
    """With the env unset, the loaded store reaches the tripwire instead of the real checkout."""
    module = load_script(STORE_RELPATH)

    def tripwire():
        raise AssertionError(
            "test path reached _default_badger_root(); set AI_BADGER_TRACKING_ROOT instead")

    monkeypatch.setattr(module.badger_store, "_default_badger_root", tripwire)
    monkeypatch.delenv(TRACKING_ROOT_ENV, raising=False)
    with pytest.raises(AssertionError, match="_default_badger_root"):
        module.badger_store.tracking_db_path()
