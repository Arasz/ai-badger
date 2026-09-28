"""The `task_graph_cli.py` transport: 12 verbs, one golden payload per tool, CLI == MCP.

The goldens are the oracle: each tool's payload is pinned as a full literal (server-stamped
timestamps normalised to `<ts>`), and the CLI is additionally compared against the same call
made over the MCP pipes — equality is an extra check on top, never the only one.

The module-scoped `pipeline` fixture drives one plan through all 12 tools exactly once, over
two separate tracking roots (one CLI, one MCP), so a golden failure names the tool and the
transport divergence is visible in the same run.

Test map:
  1. goldens ............ test_plan_create_golden, ..., test_progress_checklist_golden
  2. equality ........... test_cli_payloads_equal_the_mcp_payloads
  3. failures ........... test_cli_reports_a_tool_error_envelope_with_a_nonzero_exit,
                          test_cli_refuses_an_unknown_verb_or_non_object_json
"""
from __future__ import annotations

# pylint: disable=redefined-outer-name  # the pipeline fixture is requested by name

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI_RELPATH = "features/common/skills/task-decomposition/scripts/task_graph_cli.py"
SERVER_RELPATH = "features/common/skills/task-decomposition/scripts/task_graph_server.py"
TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"
TASK_ID = "aib-demo-task"
CLI = ROOT / CLI_RELPATH
SERVER = ROOT / SERVER_RELPATH

GOLDEN_CONTENT_HASH = "b47e37641b43586fc4a697ce627a4c538e9eb99ad5e0bf8db43311ec34893a90"
P2_CONTENT_HASH = "faf3a9a83ff7e83ef4dcdf1e3b3cd9aaeb178159b2a8eedab4c686e72b932b23"
SCHEMA_URL = "https://github.com/Arasz/ai-badger/schemas/task-plan.schema.json"
MEASURED_AT = "2026-09-28T10:00:00Z"
STAMPED = frozenset({"created_at", "updated_at", "started_at", "completed_at"})

#: The frozen PEP 723 block every launch path depends on; `uv run --script` reads it before
#: Python starts. Byte-pinned so a corrupted header cannot ship silently (R4-F1).
LAUNCH_HEADER = (
    "# /// script\n"
    '# requires-python = ">=3.10"\n'
    '# dependencies = ["pydantic>=2.12,<3"]\n'
    "# ///"
)


def freeze(value):
    """A payload with server-stamped timestamps replaced by a placeholder."""
    if isinstance(value, dict):
        return {key: ("<ts>" if key in STAMPED and isinstance(item, str) else freeze(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [freeze(item) for item in value]
    return value


# ------------------------------------------------------------------- fixture builders


def _ac(ac_id="ac1", *, statement="the check proves it", check=None):
    return {"id": ac_id, "statement": statement, "check": check}


def _step(step_id="s1", **overrides):
    data = {
        "id": step_id, "goal": "do the thing", "instructions": "follow the plan",
        "effort": "medium", "depends_on": [], "acceptance_criteria": [_ac()],
        "files": ["a.py"], "resources": [],
    }
    data.update(overrides)
    return data


def _two_step_steps():
    return [
        _step(),
        _step("s2", goal="verify it", instructions="run the gate", effort="low",
              depends_on=["s1"], acceptance_criteria=[
                  _ac("ac2", statement="the gate passes", check="pytest -q")],
              files=["b.py"]),
    ]


def _create_args():
    return {
        "task_id": TASK_ID, "task_description_ref": "docs/work/plan.md",
        "task_context": "a demo plan", "loop": "high",
        "source_refs": ["docs/work/plan.md"], "steps": [_step()],
    }


def _replace_args(expected_revision, steps):
    return {
        "task_id": TASK_ID, "expected_revision": expected_revision,
        "task_description_ref": "docs/work/plan.md", "task_context": "a demo plan",
        "loop": "high", "source_refs": ["docs/work/plan.md"], "steps": steps,
    }


def _evidence(summary="suite green", *, kind="test", ref=None):
    payload = {"kind": kind, "summary": summary, "recorded_at": MEASURED_AT}
    if ref is not None:
        payload["ref"] = ref
    return payload


S1_REF = {"id": "s1", "goal": "do the thing", "effort": "medium", "files": ["a.py"],
          "resources": [], "blocked_by": [], "skipped_deps": [],
          "criteria": {"passed": 0, "total": 1}}
S2_REF = {"id": "s2", "goal": "verify it", "effort": "low", "files": ["b.py"],
          "resources": [], "blocked_by": [], "skipped_deps": [],
          "criteria": {"passed": 0, "total": 1}}

S1_IN_PROGRESS = {
    "id": "s1", "goal": "do the thing", "instructions": "follow the plan", "effort": "medium",
    "depends_on": [], "acceptance_criteria": [
        {"id": "ac1", "statement": "the check proves it", "status": "unchecked", "evidence": []}],
    "files": ["a.py"], "resources": [], "status": "in_progress", "started_at": "<ts>",
}
S1_COMPLETE = {
    "id": "s1", "goal": "do the thing", "instructions": "follow the plan", "effort": "medium",
    "depends_on": [], "acceptance_criteria": [
        {"id": "ac1", "statement": "the check proves it", "status": "passed",
         "evidence": [{"kind": "test", "summary": "pytest passed",
                       "recorded_at": MEASURED_AT}]}],
    "files": ["a.py"], "resources": [], "status": "complete", "started_at": "<ts>",
    "completed_at": "<ts>",
    "completion": {"forced": False,
                   "evidence": [{"kind": "test", "summary": "suite green", "ref": "log.txt",
                                 "recorded_at": MEASURED_AT}]},
}
S2_FAILED = {
    "id": "s2", "goal": "verify it", "instructions": "run the gate", "effort": "low",
    "depends_on": ["s1"], "acceptance_criteria": [
        {"id": "ac2", "statement": "the gate passes", "check": "pytest -q",
         "status": "unchecked", "evidence": []}],
    "files": ["b.py"], "resources": [], "status": "failed", "started_at": "<ts>",
    "completion": {"forced": False, "note": "the gate is red",
                   "evidence": [{"kind": "command", "summary": "gate failed",
                                 "recorded_at": MEASURED_AT}]},
}
S2_SKIPPED = {
    "id": "s2", "goal": "verify it", "instructions": "run the gate", "effort": "low",
    "depends_on": ["s1"], "acceptance_criteria": [
        {"id": "ac2", "statement": "the gate passes", "check": "pytest -q",
         "status": "unchecked", "evidence": []}],
    "files": ["b.py"], "resources": [], "status": "skipped", "started_at": "<ts>",
    "completion": {"forced": False, "note": "deferred to a follow-up", "evidence": []},
}

GOLDEN: Dict[str, dict] = {
    "plan_create": {
        "task_id": TASK_ID, "revision": 0, "schema_version": 1,
        "content_hash": GOLDEN_CONTENT_HASH, "created": True, "steps": 1,
        "ready": [S1_REF], "waves": [["s1"]], "findings": [],
    },
    "plan_replace": {
        "task_id": TASK_ID, "revision": 1, "schema_version": 1,
        "content_hash": P2_CONTENT_HASH, "created": False, "replaced": True, "steps": 2,
        "ready": [S1_REF], "waves": [["s1"], ["s2"]], "findings": [],
    },
    "steps_ready": {
        "revision": 1, "ready": [S1_REF], "waves": [["s1"], ["s2"]], "blocked": [],
    },
    "step_start": {
        "revision": 2, "changed": True, "step": S1_IN_PROGRESS,
    },
    "ac_check": {
        "revision": 3, "changed": True, "step_id": "s1",
        "criterion": {"id": "ac1", "statement": "the check proves it", "status": "passed",
                      "evidence": [{"kind": "test", "summary": "pytest passed",
                                    "recorded_at": MEASURED_AT}]},
        "criteria": {"passed": 1, "total": 1},
    },
    "step_complete": {
        "revision": 4, "changed": True, "step": S1_COMPLETE, "ready": [S2_REF],
    },
    "step_fail": {
        "revision": 6, "changed": True, "step": S2_FAILED, "blocked": [],
    },
    "step_skip": {
        "revision": 7, "changed": True, "step": S2_SKIPPED, "ready": [],
    },
    "step_get": {
        "revision": 7, "step": S2_SKIPPED, "blocked_by": [], "blocks": [], "ready": False,
    },
    "plan_get": {
        "task_id": TASK_ID, "revision": 7,
        "counts": {"total": 2, "pending": 0, "in_progress": 0, "complete": 1, "failed": 0,
                   "skipped": 1},
        "criteria": {"passed": 1, "total": 2}, "integration_ok": True,
        "integration_sink": "s2", "findings": [],
    },
    "plan_export": {
        "task_id": TASK_ID, "revision": 7, "content_hash": P2_CONTENT_HASH,
        "schema_url": SCHEMA_URL,
        "document": {
            "schema_version": 1, "task_id": TASK_ID,
            "task_description_ref": "docs/work/plan.md", "task_context": "a demo plan",
            "loop": "high", "source_refs": ["docs/work/plan.md"],
            "workflow": {"steps": {"s1": S1_COMPLETE, "s2": S2_SKIPPED}},
            "revision": 7, "created_at": "<ts>", "updated_at": "<ts>",
        },
    },
    "progress_checklist": {
        "task_id": TASK_ID, "revision": 7, "complete": 1, "total": 2,
        "steps": [
            {"id": "s1", "goal": "do the thing", "status": "complete", "marker": "x",
             "criteria": {"passed": 1, "total": 1}},
            {"id": "s2", "goal": "verify it", "status": "skipped", "marker": "-",
             "criteria": {"passed": 0, "total": 1}},
        ],
        "next": [], "blocked": [],
        "integration_ok": True, "integration_finding": None,
    },
}


# ----------------------------------------------------------------------------- runners


class CliRunner:
    """`python task_graph_cli.py <verb> --json <args>`, one process per call."""

    def __init__(self, root: Path):
        self.root = root

    def run(self, tool: str, args: dict) -> dict:
        env = dict(os.environ)
        env[TRACKING_ROOT_ENV] = str(self.root)
        proc = subprocess.run(
            [sys.executable, str(CLI), tool, "--json",
             json.dumps(args, ensure_ascii=False)],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False)
        assert proc.returncode == 0, (
            f"cli {tool} exited {proc.returncode}\nstdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}")
        return json.loads(proc.stdout)


class McpRunner:
    """One spawned server process, addressed over real pipes."""

    def __init__(self, root: Path):
        env = dict(os.environ)
        env[TRACKING_ROOT_ENV] = str(root)
        self._proc = subprocess.Popen(
            [sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self._next_id = 0

    def tool(self, tool: str, args: dict) -> dict:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": "tools/call",
                   "params": {"name": tool, "arguments": args}}
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        assert line, f"server died:\n{self._proc.stderr.read()}"
        result = json.loads(line)["result"]
        assert result.get("isError") is False, result
        return result["structuredContent"]

    def close(self) -> None:
        if not self._proc.stdin.closed:
            self._proc.stdin.close()
        self._proc.wait(timeout=10)


@dataclass
class Outcome:
    """One tool invoked over both transports, for golden and equality assertions."""

    tool: str
    cli: dict
    mcp: dict
    args: dict


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Drive one plan through all 12 tools over both transports, recording every payload."""
    outcomes: List[Outcome] = []
    by_tool: Dict[str, Outcome] = {}
    cli = CliRunner(tmp_path_factory.mktemp("cli-store"))
    mcp = McpRunner(tmp_path_factory.mktemp("mcp-store"))

    def both(tool: str, args: dict) -> dict:
        cli_payload = cli.run(tool, args)
        mcp_payload = mcp.tool(tool, args)
        outcome = Outcome(tool, cli_payload, mcp_payload, args)
        outcomes.append(outcome)
        by_tool.setdefault(tool, outcome)
        return cli_payload

    try:
        both("plan_create", _create_args())
        both("plan_replace", _replace_args(0, _two_step_steps()))
        both("steps_ready", {"task_id": TASK_ID})
        both("step_start", {"task_id": TASK_ID, "step_id": "s1", "expected_revision": 1})
        both("ac_check", {"task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1",
                          "expected_revision": 2, "status": "passed",
                          "evidence": [{"kind": "test", "summary": "pytest passed",
                                        "recorded_at": MEASURED_AT}]})
        both("step_complete", {"task_id": TASK_ID, "step_id": "s1", "expected_revision": 3,
                               "evidence": [_evidence(ref="log.txt")],
                               "criterion_results": {}})
        both("step_start", {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 4})
        both("step_fail", {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 5,
                           "reason": "the gate is red",
                           "evidence": [{"kind": "command", "summary": "gate failed",
                                         "recorded_at": MEASURED_AT}]})
        both("step_skip", {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 6,
                           "reason": "deferred to a follow-up", "evidence": []})
        both("step_get", {"task_id": TASK_ID, "step_id": "s2"})
        both("plan_get", {"task_id": TASK_ID, "include": "state"})
        both("plan_export", {"task_id": TASK_ID})
        both("progress_checklist", {"task_id": TASK_ID})
    finally:
        mcp.close()

    yield {"outcomes": outcomes, "by_tool": by_tool, "root": cli.root}


# ------------------------------------------------------------------------------- goldens


def _assert_golden(pipeline, tool: str) -> None:
    outcome = pipeline["by_tool"][tool]
    assert freeze(outcome.cli) == GOLDEN[tool]


def test_plan_create_golden(pipeline):
    _assert_golden(pipeline, "plan_create")


def test_plan_replace_golden(pipeline):
    _assert_golden(pipeline, "plan_replace")


def test_steps_ready_golden(pipeline):
    _assert_golden(pipeline, "steps_ready")


def test_step_start_golden(pipeline):
    _assert_golden(pipeline, "step_start")


def test_ac_check_golden(pipeline):
    _assert_golden(pipeline, "ac_check")


def test_step_complete_golden(pipeline):
    _assert_golden(pipeline, "step_complete")


def test_step_fail_golden(pipeline):
    _assert_golden(pipeline, "step_fail")


def test_step_skip_golden(pipeline):
    _assert_golden(pipeline, "step_skip")


def test_step_get_golden(pipeline):
    _assert_golden(pipeline, "step_get")


def test_plan_get_golden(pipeline):
    _assert_golden(pipeline, "plan_get")


def test_plan_export_golden(pipeline):
    _assert_golden(pipeline, "plan_export")


def test_progress_checklist_golden(pipeline):
    _assert_golden(pipeline, "progress_checklist")


def test_cli_payloads_equal_the_mcp_payloads(pipeline):
    seen = {outcome.tool for outcome in pipeline["outcomes"]}
    assert seen == set(GOLDEN)

    for outcome in pipeline["outcomes"]:
        assert freeze(outcome.cli) == freeze(outcome.mcp), (
            f"{outcome.tool} diverged between CLI and MCP on {outcome.args}")


# ------------------------------------------------------------------------------ failures


def _cli(root: Path, *argv: str):
    env = dict(os.environ)
    env[TRACKING_ROOT_ENV] = str(root)
    return subprocess.run([sys.executable, str(CLI), *argv], capture_output=True, text=True,
                          encoding="utf-8", env=env, check=False)


@pytest.mark.parametrize("script", [CLI, SERVER], ids=["cli", "server"])
def test_both_scripts_carry_the_pinned_pep723_launch_header(script):
    """`uv run --script` reads these exact lines; a deleted or edited header ships broken."""
    lines = script.read_text(encoding="utf-8").splitlines()

    assert lines[0].startswith("#!")
    assert "\n".join(lines[1:5]) == LAUNCH_HEADER


def test_cli_exits_three_when_the_tool_cannot_start(load_script, tmp_path, monkeypatch,
                                                    capsys):
    """A launch failure is its own exit code (3), distinct from tool error (1) and usage (2)."""
    cli = load_script(CLI_RELPATH)
    broken = tmp_path / "task_graph_server.py"
    broken.write_text("raise RuntimeError('cannot start')\n", encoding="utf-8")
    monkeypatch.setattr(cli, "SERVER_PATH", broken)
    sys.modules.pop("task_graph_server", None)

    rc = cli.main(["plan_get", "--json", "{}"])

    assert rc == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.strip().splitlines()
    assert len(lines) == 1, captured.err
    assert "cannot start" in lines[0]


def test_cli_survives_non_utf8_argv_bytes(tmp_path):
    """Raw bytes in `--json` may not decode cleanly; the CLI refuses, never tracebacks."""
    env = dict(os.environ)
    env[TRACKING_ROOT_ENV] = str(tmp_path)
    proc = subprocess.run(
        [os.fsencode(sys.executable), os.fsencode(CLI), b"plan_get", b"--json",
         b'{"task_id": "a\xffb"}'], capture_output=True, env=env, check=False)

    assert proc.returncode in (1, 2), proc.stderr.decode("utf-8", "replace")
    assert b"Traceback" not in proc.stderr, proc.stderr.decode("utf-8", "replace")


def test_cli_reports_a_tool_error_envelope_with_a_nonzero_exit(tmp_path):
    proc = _cli(tmp_path, "plan_get", "--json", json.dumps({"task_id": "no-such-plan"}))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "not-found"


def test_cli_refuses_an_unknown_verb_or_non_object_json(tmp_path):
    unknown = _cli(tmp_path, "plan_build", "--json", "{}")
    assert unknown.returncode == 2
    assert "plan_build" in unknown.stderr

    bad_json = _cli(tmp_path, "plan_get", "--json", "{not json")
    assert bad_json.returncode == 2
    assert "json" in bad_json.stderr.lower()

    not_object = _cli(tmp_path, "plan_get", "--json", "[1, 2, 3]")
    assert not_object.returncode == 2
    assert "object" in not_object.stderr.lower()
