"""The task-graph MCP server: protocol conformance, the 12-tool surface, and its guards.

The server is exercised the way a host exercises it — a real subprocess over pipes, NDJSON in
and out, `sys.executable` running the script at its repo path. The protocol matrix pins
`initialize` negotiation, `tools/list`'s frozen contract (12 names, no `plan_id`, no
`advisory`, `openWorldHint` false), JSON-RPC errors for protocol failures only, parse-error
survival and stdout purity. The tool matrix pins each of the 12 tools' happy path and every
error code in the closed set; mutations are pinned against the frozen store (CAS conflict,
idempotent replays, `plan-in-progress`, `schema-version-unsupported` passthrough).

Every test points `AI_BADGER_TRACKING_ROOT` at `tmp_path`; the in-process tests additionally
arm the S3/S6 tripwire on the loaded store so a forgotten redirect fails loudly instead of
writing the real checkout.

Test map:
  1. protocol ............ initialize negotiation, frozen tools/list, parse survival, stdout
                           purity, method/tool errors, notification no-ops
  2. plan_create ......... create shape, golden content_hash, idempotency, already-exists,
                           structured DAG findings
  3. plan_replace ........ replace, stale-revision idempotency, conflict, plan-in-progress
  4. reads ............... plan_get includes, plan_export stored bytes, step_get relations,
                           steps_ready waves, progress_checklist json/text
  5. transitions ......... start/complete/fail/skip/ac_check guards, replays, force
  6. store failures ...... schema-version-unsupported passthrough, store-error
  7. --check ............. clean schema 0, mutation and missing 1
  8. render .............. the plan file round-trips through an independent parser
  9. tripwire ............ the default-root fallback is armed
"""
from __future__ import annotations

# pylint: disable=redefined-outer-name  # the mcp server fixture is requested by name

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_RELPATH = "features/common/skills/task-decomposition/scripts/task_graph_server.py"
TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"
TASK_ID = "aib-demo-task"
SERVER = ROOT / SERVER_RELPATH

# The frozen surface (§2 interface freeze): exact order, exact names, closed error codes.
FROZEN_TOOLS = (
    "plan_create", "plan_replace", "plan_get", "plan_export", "step_get", "step_start",
    "step_complete", "step_fail", "step_skip", "ac_check", "steps_ready",
    "progress_checklist",
)
READ_ONLY_TOOLS = frozenset(
    {"plan_get", "plan_export", "step_get", "steps_ready", "progress_checklist"})
FROZEN_ERROR_CODES = frozenset({
    "invalid-arguments", "not-found", "already-exists", "conflict", "invalid-transition",
    "dependencies-incomplete", "criteria-unmet", "plan-in-progress",
    "schema-version-unsupported", "prerequisite-missing", "config-error", "store-error",
})
ERROR_STATUS = {
    "invalid-arguments": 422, "not-found": 404, "already-exists": 409, "conflict": 409,
    "invalid-transition": 409, "dependencies-incomplete": 409, "criteria-unmet": 422,
    "plan-in-progress": 409, "schema-version-unsupported": 422, "prerequisite-missing": 500,
    "config-error": 500, "store-error": 500,
}
GOLDEN_CONTENT_HASH = "b47e37641b43586fc4a697ce627a4c538e9eb99ad5e0bf8db43311ec34893a90"
P2_CONTENT_HASH = "faf3a9a83ff7e83ef4dcdf1e3b3cd9aaeb178159b2a8eedab4c686e72b932b23"

# Fields the server stamps from the clock; a golden comparison normalises them.
STAMPED = frozenset({"created_at", "updated_at", "started_at", "completed_at"})


def freeze(value):
    """A payload with server-stamped timestamps replaced by a placeholder."""
    if isinstance(value, dict):
        return {key: ("<ts>" if key in STAMPED and isinstance(item, str) else freeze(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [freeze(item) for item in value]
    return value


# ------------------------------------------------------------------------------- the pipe


class McpServer:
    """One spawned server process, addressed in NDJSON over its real stdin/stdout pipes."""

    def __init__(self, root: Path, script: Path = SERVER):
        env = dict(os.environ)
        env[TRACKING_ROOT_ENV] = str(root)
        self._proc = subprocess.Popen(
            [sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self._next_id = 0

    def send(self, payload) -> None:
        """Write one NDJSON message, flushed."""
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def notify(self, method: str, params=None) -> None:
        """Send a notification (no `id`): the server must not answer it."""
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)

    def raw(self, line: str) -> dict:
        """Send one raw line (malformed included) and read one response line."""
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        return self.read()

    def call(self, method: str, params=None) -> dict:
        """One request/response round trip; returns the full JSON-RPC envelope."""
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        return self.read()

    def read(self) -> dict:
        """The next stdout line, parsed; fails with the stderr tail when the server dies."""
        line = self._proc.stdout.readline()
        if not line:
            raise AssertionError(
                f"task-graph server exited (rc={self._proc.poll()}):\n"
                f"{self._proc.stderr.read()}")
        return json.loads(line)

    def stderr(self) -> str:
        """Everything the server wrote to stderr so far (read after closing stdin)."""
        return self._proc.stderr.read()

    def finished(self) -> bool:
        """True once the process has exited."""
        return self._proc.poll() is not None

    def close_stdin(self) -> None:
        """Close the input pipe, letting the server drain and exit."""
        if not self._proc.stdin.closed:
            self._proc.stdin.close()

    def wait(self, timeout: float = 10) -> int:
        """Wait for exit and return the status code."""
        return self._proc.wait(timeout=timeout)

    def read_remainder(self) -> str:
        """Everything still buffered on stdout, after stdin is closed."""
        return self._proc.stdout.read()

    def close(self) -> None:
        """Close stdin, wait for exit, and fail loudly on a non-zero return."""
        self.close_stdin()
        rc = self.wait()
        assert rc == 0, f"server exited {rc}:\n{self._proc.stderr.read()}"


@pytest.fixture(autouse=True)
def _tracking_root(tmp_path, monkeypatch):
    """Every test's store lands under tmp_path (the child inherits the env too)."""
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(tmp_path))
    yield tmp_path


@pytest.fixture
def mcp(tmp_path):
    """A factory of live server processes, all cleaned up at test end."""
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


# ----------------------------------------------------------------------- fixture builders


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


def _create_args(**overrides):
    """The S2 golden fixture's authored content, in `plan_create` argument shape."""
    data = {
        "task_id": TASK_ID, "task_description_ref": "docs/work/plan.md",
        "task_context": "a demo plan", "loop": "high",
        "source_refs": ["docs/work/plan.md"], "steps": [_step()],
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


def _evidence(summary="pytest passed", *, kind="test", ref=None,
              recorded_at="2026-09-28T10:00:00Z"):
    return {"kind": kind, "summary": summary, "ref": ref, "recorded_at": recorded_at}


def _tool(server: McpServer, name: str, arguments: dict) -> dict:
    """The raw `tools/call` result for one tool invocation."""
    response = server.call("tools/call", {"name": name, "arguments": arguments})
    assert "result" in response, response
    return response["result"]


def _payload(server: McpServer, name: str, arguments: dict) -> dict:
    """The structured payload of a successful tool call."""
    result = _tool(server, name, arguments)
    assert result.get("isError") is False, result
    return result["structuredContent"]


def _error(server: McpServer, name: str, arguments: dict, code: str) -> dict:
    """Assert a tool-domain refusal: closed code set, matching status, no raise."""
    result = _tool(server, name, arguments)
    assert result.get("isError") is True, result
    envelope = result["structuredContent"]
    assert envelope["ok"] is False, envelope
    error = envelope["error"]
    assert error["code"] in FROZEN_ERROR_CODES, error
    assert error["code"] == code, error
    assert error["status"] == ERROR_STATUS[code], error
    assert isinstance(error["title"], str) and error["title"]
    assert isinstance(error["detail"], str) and error["detail"]
    assert isinstance(error["instance"], str) and error["instance"]
    assert error["retryable"] is False or error["code"] == "store-error", error
    return error


def _create(server: McpServer, **overrides) -> dict:
    return _payload(server, "plan_create", _create_args(**overrides))


def _start(server: McpServer, step_id="s1", revision=0, **extra) -> dict:
    arguments = {"task_id": TASK_ID, "step_id": step_id, "expected_revision": revision}
    arguments.update(extra)
    return _payload(server, "step_start", arguments)


def _complete(server: McpServer, step_id="s1", revision=0, **extra) -> dict:
    arguments = {"task_id": TASK_ID, "step_id": step_id, "expected_revision": revision,
                 "evidence": [], "criterion_results": {}}
    arguments.update(extra)
    return _payload(server, "step_complete", arguments)


# ----------------------------------------------------------------------------- protocol


def test_initialize_negotiates_protocol_versions(mcp):
    server = mcp()
    for version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        result = server.call("initialize", {"protocolVersion": version})["result"]
        assert result["protocolVersion"] == version
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert result["serverInfo"]["name"] == "task-graph"
        assert result["serverInfo"]["version"] == (ROOT / "VERSION").read_text(
            encoding="utf-8").strip()

    assert server.call("initialize", {"protocolVersion": "1999-01-01"})["result"][
        "protocolVersion"] == "2025-06-18"
    assert server.call("initialize", {})["result"]["protocolVersion"] == "2025-06-18"


def test_tools_list_publishes_the_frozen_contract(mcp):
    server = mcp()
    response = server.call("tools/list", {})
    tools = response["result"]["tools"]

    assert [tool["name"] for tool in tools] == list(FROZEN_TOOLS)
    blob = json.dumps(tools)
    assert "plan_id" not in blob
    assert "advisory" not in blob

    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object", tool["name"]
        assert schema["additionalProperties"] is False, tool["name"]
        assert "task_id" in schema["properties"], tool["name"]
        assert isinstance(tool["description"], str) and tool["description"]
        annotations = tool["annotations"]
        assert set(annotations) == {"readOnlyHint", "idempotentHint", "openWorldHint"}
        assert annotations["openWorldHint"] is False, tool["name"]
        expected_read_only = tool["name"] in READ_ONLY_TOOLS
        assert annotations["readOnlyHint"] is expected_read_only, tool["name"]
        assert isinstance(annotations["idempotentHint"], bool), tool["name"]

    # Every write replays as a no-op except step_start: after a failure the same call is a
    # new attempt by design (P2-B1), so a client must not auto-retry it.
    not_idempotent = {tool["name"] for tool in tools
                      if tool["annotations"]["idempotentHint"] is False}
    assert not_idempotent == {"step_start"}


def test_malformed_line_gets_a_parse_error_and_the_server_survives(mcp):
    server = mcp()
    response = server.raw("{not json at all")
    assert response["error"]["code"] == -32700
    assert response["id"] is None

    pong = server.call("ping", {})
    assert pong["result"] == {}
    server.close_stdin()
    assert "parse error" in server.stderr()
    assert server.wait() == 0


def test_unknown_method_is_method_not_found_and_unknown_tool_is_invalid_params(mcp):
    server = mcp()
    response = server.call("tools/nowhere", {})
    assert response["error"]["code"] == -32601

    response = server.call("tools/call", {"name": "plan_nope", "arguments": {}})
    assert response["error"]["code"] == -32602

    response = server.call("tools/call", {"name": "plan_get", "arguments": "nope"})
    assert response["error"]["code"] == -32600


def test_invalid_request_shapes_are_refused_without_raising(mcp):
    server = mcp()
    assert server.raw("[]")["error"]["code"] == -32600
    assert server.raw('"a string"')["error"]["code"] == -32600
    assert server.raw('{"jsonrpc": "1.0", "id": 9, "method": "ping"}')["error"][
        "code"] == -32600
    assert server.call("ping", {})["result"] == {}


def test_notifications_are_noops(mcp):
    server = mcp()
    server.notify("notifications/initialized")
    server.notify("notifications/cancelled", {"requestId": 1, "reason": "user"})
    server.notify("notifications/unknown")
    pong = server.call("ping", {})
    assert pong["id"] == 1
    assert pong["result"] == {}


def test_stdout_carries_protocol_json_only(mcp):
    server = mcp()
    server.call("ping", {})
    server.raw("{not json")
    server.call("tools/list", {})
    server.close_stdin()
    remaining = server.read_remainder()
    for line in remaining.splitlines():
        message = json.loads(line)
        assert message["jsonrpc"] == "2.0"
    assert "parse error" in server.stderr()
    assert server.wait() == 0


# --------------------------------------------------------------------------- plan_create


def test_plan_create_returns_the_create_shape_and_the_golden_content_hash(mcp):
    server = mcp()
    payload = _create(server)

    assert payload == {
        "task_id": TASK_ID, "revision": 0, "schema_version": 1,
        "content_hash": GOLDEN_CONTENT_HASH, "created": True, "steps": 1,
        "ready": [{"id": "s1", "goal": "do the thing", "effort": "medium",
                   "files": ["a.py"], "resources": [], "blocked_by": [], "skipped_deps": [],
                   "criteria": {"passed": 0, "total": 1}}],
        "waves": [["s1"]],
    }


def test_plan_create_is_idempotent_on_identical_content(mcp):
    server = mcp()
    first = _create(server)
    second = _create(server)

    assert first["created"] is True
    assert second["created"] is False
    assert second["revision"] == 0
    assert second["content_hash"] == GOLDEN_CONTENT_HASH


def test_plan_create_refuses_existing_different_content(mcp):
    server = mcp()
    _create(server)
    error = _error(server, "plan_create", _create_args(task_context="different now"),
                   "already-exists")
    assert error["details"]["current_revision"] == 0


def test_plan_create_rejects_dag_findings_as_structured_invalid_arguments(mcp):
    server = mcp()
    cycle = _create_args(steps=[
        _step("s1", depends_on=["s2"]), _step("s2", depends_on=["s1"])])
    error = _error(server, "plan_create", cycle, "invalid-arguments")
    assert "cycle" in json.dumps(error["details"]["findings"])

    unknown = _create_args(steps=[_step("s1", depends_on=["ghost"])])
    error = _error(server, "plan_create", unknown, "invalid-arguments")
    assert "ghost" in json.dumps(error["details"]["findings"])

    duplicate = _create_args(steps=[_step("s1"), _step("s1", goal="again")])
    error = _error(server, "plan_create", duplicate, "invalid-arguments")
    assert "duplicate" in json.dumps(error["details"]["findings"])

    schema = _create_args(loop="turbo")
    error = _error(server, "plan_create", schema, "invalid-arguments")
    assert error["details"]["findings"]

    empty = _create_args(steps=[])
    _error(server, "plan_create", empty, "invalid-arguments")


# -------------------------------------------------------------------------- plan_replace


def test_plan_replace_writes_a_new_revision_and_reports_replaced(mcp):
    server = mcp()
    _create(server)
    payload = _payload(server, "plan_replace", {
        "task_id": TASK_ID, "expected_revision": 0,
        "task_description_ref": "docs/work/plan.md", "task_context": "a demo plan",
        "loop": "high", "source_refs": ["docs/work/plan.md"], "steps": _two_step_steps(),
    })

    assert payload["replaced"] is True
    assert payload["created"] is False
    assert payload["revision"] == 1
    assert payload["content_hash"] == P2_CONTENT_HASH
    assert payload["steps"] == 2
    assert payload["waves"] == [["s1"], ["s2"]]


def test_plan_replace_same_content_wins_even_with_a_stale_revision(mcp):
    server = mcp()
    _create(server)
    payload = _payload(server, "plan_replace", {
        "task_id": TASK_ID, "expected_revision": 99,
        "task_description_ref": "docs/work/plan.md", "task_context": "a demo plan",
        "loop": "high", "source_refs": ["docs/work/plan.md"], "steps": [_step()],
    })

    assert payload["replaced"] is False
    assert payload["revision"] == 0
    assert payload["content_hash"] == GOLDEN_CONTENT_HASH


def test_plan_replace_conflicts_on_a_stale_revision_with_new_content(mcp):
    server = mcp()
    _create(server)
    error = _error(server, "plan_replace", {
        "task_id": TASK_ID, "expected_revision": 7,
        "task_description_ref": "docs/work/plan.md", "task_context": "changed",
        "loop": "high", "source_refs": [], "steps": _two_step_steps(),
    }, "conflict")
    assert error["details"]["current_revision"] == 0


def test_plan_replace_refuses_while_any_step_has_left_pending_skipped(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    _start(server, "s1", 0)  # in_progress
    replace = {
        "task_id": TASK_ID, "expected_revision": 1,
        "task_description_ref": "docs/work/plan.md", "task_context": "changed",
        "loop": "high", "source_refs": [], "steps": _two_step_steps(),
    }
    error = _error(server, "plan_replace", replace, "plan-in-progress")
    assert error["details"]["blocking_steps"] == ["s1"]

    # complete is left pending/skipped too
    _payload(server, "ac_check", {"task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1",
                                  "expected_revision": 1, "status": "passed",
                                  "evidence": []})
    _complete(server, "s1", 2)
    _error(server, "plan_replace", {**replace, "expected_revision": 3},
           "plan-in-progress")

    # failed blocks as well
    _start(server, "s2", 3)
    _payload(server, "step_fail", {"task_id": TASK_ID, "step_id": "s2",
                                   "expected_revision": 4, "reason": "red",
                                   "evidence": []})
    _error(server, "plan_replace", {**replace, "expected_revision": 5},
           "plan-in-progress")

    # skipped-only (s2 fails -> skip) but s1 is complete: still refused
    _payload(server, "step_skip", {"task_id": TASK_ID, "step_id": "s2",
                                   "expected_revision": 5, "reason": "later"})
    _error(server, "plan_replace", {**replace, "expected_revision": 6},
           "plan-in-progress")


def test_plan_replace_allows_a_plan_whose_steps_are_only_pending_or_skipped(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    for step_id, revision in (("s1", 0), ("s2", 1)):
        _payload(server, "step_skip", {"task_id": TASK_ID, "step_id": step_id,
                                       "expected_revision": revision, "reason": "retired"})
    payload = _payload(server, "plan_replace", {
        "task_id": TASK_ID, "expected_revision": 2,
        "task_description_ref": "docs/work/plan.md", "task_context": "changed",
        "loop": "high", "source_refs": [], "steps": _two_step_steps(),
    })
    assert payload["replaced"] is True
    assert payload["revision"] == 3


# ---------------------------------------------------------------------------------- reads


def test_plan_get_offers_summary_full_steps_and_state(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    summary = _payload(server, "plan_get", {"task_id": TASK_ID})
    assert summary["task_id"] == TASK_ID
    assert summary["revision"] == 0
    assert summary["schema_version"] == 1
    assert summary["content_hash"] == P2_CONTENT_HASH
    assert summary["counts"] == {"total": 2, "pending": 2, "in_progress": 0,
                                 "complete": 0, "failed": 0, "skipped": 0}
    assert [ref["id"] for ref in summary["ready"]] == ["s1"]

    full = _payload(server, "plan_get", {"task_id": TASK_ID, "include": "full"})
    assert full["document"]["workflow"]["steps"]["s2"]["goal"] == "verify it"

    steps = _payload(server, "plan_get", {"task_id": TASK_ID, "include": "steps"})
    assert list(steps["steps"]) == ["s1", "s2"]
    assert steps["steps"]["s1"]["status"] == "pending"

    state = _payload(server, "plan_get", {"task_id": TASK_ID, "include": "state"})
    assert state["counts"] == summary["counts"]
    assert state["criteria"] == {"passed": 0, "total": 2}
    assert state["integration_ok"] is True
    assert state["integration_sink"] == "s2"

    _error(server, "plan_get", {"task_id": TASK_ID, "include": "everything"},
           "invalid-arguments")
    _error(server, "plan_get", {"task_id": "nope-nope"}, "not-found")


def test_plan_export_returns_the_stored_document_verbatim(mcp, _tracking_root):
    server = mcp()
    _create(server, steps=_two_step_steps())
    payload = _payload(server, "plan_export", {"task_id": TASK_ID})

    connection = sqlite3.connect(_tracking_root / "tracking.db")
    try:
        stored = connection.execute(
            "SELECT payload FROM plans WHERE task_id = ?", (TASK_ID,)).fetchone()[0]
    finally:
        connection.close()

    assert payload["revision"] == 0
    assert payload["content_hash"] == P2_CONTENT_HASH
    assert payload["schema_url"].endswith("/schemas/task-plan.schema.json")
    assert payload["document"] == json.loads(stored)


def test_step_get_reports_relations_and_readiness(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    payload = _payload(server, "step_get", {"task_id": TASK_ID, "step_id": "s2"})
    assert payload["revision"] == 0
    assert payload["step"]["id"] == "s2"
    assert payload["blocked_by"] == []
    assert payload["blocks"] == []
    assert payload["ready"] is False  # s1 is incomplete

    first = _payload(server, "step_get", {"task_id": TASK_ID, "step_id": "s1"})
    assert first["blocks"] == ["s2"]
    assert first["ready"] is True

    _error(server, "step_get", {"task_id": TASK_ID, "step_id": "ghost"}, "not-found")


def test_steps_ready_waves_and_blocked(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    payload = _payload(server, "steps_ready", {"task_id": TASK_ID})
    assert payload["revision"] == 0
    assert [ref["id"] for ref in payload["ready"]] == ["s1"]
    assert payload["waves"] == [["s1"], ["s2"]]
    assert payload["blocked"] == []

    without = _payload(server, "steps_ready", {"task_id": TASK_ID, "waves": False})
    assert without["waves"] == []


def test_progress_checklist_json_and_text(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    payload = _payload(server, "progress_checklist", {"task_id": TASK_ID})
    assert payload["task_id"] == TASK_ID
    assert payload["revision"] == 0
    assert payload["complete"] == 0
    assert payload["total"] == 2
    assert [row["id"] for row in payload["steps"]] == ["s1", "s2"]
    assert payload["steps"][0]["marker"] == " "
    assert payload["steps"][0]["criteria"] == {"passed": 0, "total": 1}
    assert payload["next"] == ["s1"]
    assert payload["blocked"] == []
    assert "text" not in payload

    text = _payload(server, "progress_checklist", {"task_id": TASK_ID, "format": "text"})
    assert "aib-demo-task" in text["text"]
    assert "0/2" in text["text"]


# ---------------------------------------------------------------------------- transitions


def test_step_start_guards_and_records_a_forced_override(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())

    refused = _error(server, "step_start",
                     {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 0},
                     "dependencies-incomplete")
    assert refused["details"]["blocking"] == ["s1"]

    _error(server, "step_start",
           {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 0,
            "force": True, "reason": "  "}, "invalid-arguments")

    forced = _payload(server, "step_start",
                      {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 0,
                       "force": True, "reason": "owner waived the ordering"})
    assert forced["changed"] is True
    assert forced["revision"] == 1
    assert forced["step"]["status"] == "in_progress"
    note = forced["step"]["completion"]["evidence"][0]
    assert note["kind"] == "note"
    assert note["summary"] == "owner waived the ordering"

    replay = _payload(server, "step_start",
                      {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 1})
    assert replay["changed"] is False
    assert replay["revision"] == 1

    _error(server, "step_start",
           {"task_id": TASK_ID, "step_id": "s2", "expected_revision": 0}, "conflict")
    _error(server, "step_start",
           {"task_id": TASK_ID, "step_id": "ghost", "expected_revision": 1}, "not-found")


def test_step_start_refuses_terminal_steps(mcp):
    server = mcp()
    _create(server)
    _payload(server, "step_skip", {"task_id": TASK_ID, "step_id": "s1",
                                   "expected_revision": 0, "reason": "retired"})
    error = _error(server, "step_start",
                   {"task_id": TASK_ID, "step_id": "s1", "expected_revision": 1},
                   "invalid-transition")
    assert error["details"]["allowed_transitions"] == []


def test_step_complete_requires_the_criteria_and_can_be_forced(mcp):
    server = mcp()
    _create(server)
    _start(server, "s1", 0)

    unmet = _error(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 1,
        "evidence": [], "criterion_results": {}}, "criteria-unmet")
    assert unmet["details"]["unresolved"] == ["ac1"]
    assert unmet["details"]["failed"] == []

    _error(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 1,
        "evidence": [], "criterion_results": {}, "force": True}, "invalid-arguments")

    _error(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 1,
        "evidence": [], "criterion_results": {"ghost": "passed"}}, "invalid-arguments")

    forced = _payload(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 1,
        "evidence": [_evidence("forced through", kind="review")],
        "criterion_results": {}, "force": True, "reason": "owner waived ac1"})
    assert forced["changed"] is True
    assert forced["revision"] == 2
    assert forced["step"]["status"] == "complete"
    assert forced["step"]["completion"]["forced"] is True
    assert forced["step"]["completion"]["note"] == "owner waived ac1"
    assert forced["step"]["completion"]["evidence"][0]["summary"] == "forced through"
    assert forced["step"]["acceptance_criteria"][0]["status"] == "unchecked"


def test_step_complete_replays_and_refuses_a_different_completion(mcp):
    server = mcp()
    _create(server)
    _start(server, "s1", 0)
    _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 1,
        "status": "passed", "evidence": [_evidence()]})
    first = _complete(server, "s1", 2, evidence=[_evidence("suite green")])
    assert first["changed"] is True
    assert first["revision"] == 3

    replay = _complete(server, "s1", 3, evidence=[_evidence("suite green")])
    assert replay["changed"] is False
    assert replay["revision"] == 3

    error = _error(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 3,
        "evidence": [_evidence("different evidence")], "criterion_results": {}},
        "invalid-transition")
    assert error["details"]["allowed_transitions"] == []


def test_step_complete_refuses_a_pending_step(mcp):
    server = mcp()
    _create(server)
    error = _error(server, "step_complete", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 0,
        "evidence": [], "criterion_results": {}}, "invalid-transition")
    assert error["details"]["allowed_transitions"] == ["in_progress", "skipped"]


def test_step_complete_reports_the_new_ready_frontier(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())
    _start(server, "s1", 0)
    _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 1,
        "status": "passed", "evidence": []})
    payload = _complete(server, "s1", 2)
    assert [ref["id"] for ref in payload["ready"]] == ["s2"]


def test_step_fail_records_its_reason_and_replays(mcp):
    server = mcp()
    _create(server)
    _error(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 0,
        "reason": "not started", "evidence": []}, "invalid-transition")

    _start(server, "s1", 0)
    failed = _payload(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 1,
        "reason": "the gate is red", "evidence": [_evidence("gate failed")]})
    assert failed["changed"] is True
    assert failed["revision"] == 2
    assert failed["step"]["status"] == "failed"
    assert failed["step"]["completion"]["note"] == "the gate is red"
    assert failed["blocked"] == []

    replay = _payload(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 2,
        "reason": "the gate is red", "evidence": [_evidence("gate failed")]})
    assert replay["changed"] is False
    assert replay["revision"] == 2

    _error(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 2,
        "reason": "something else", "evidence": []}, "invalid-transition")


def test_step_skip_is_valid_from_pending_in_progress_and_failed(mcp):
    server = mcp()
    _create(server, steps=_two_step_steps())

    from_pending = _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 0, "reason": "retired"})
    assert from_pending["step"]["status"] == "skipped"
    assert [ref["id"] for ref in from_pending["ready"]] == ["s2"]

    _start(server, "s2", 1)
    from_in_progress = _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s2", "expected_revision": 2,
        "reason": "dropped mid-flight"})
    assert from_in_progress["step"]["status"] == "skipped"
    assert from_in_progress["ready"] == []

    replay = _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s2", "expected_revision": 3,
        "reason": "dropped mid-flight"})
    assert replay["changed"] is False
    assert replay["revision"] == 3


def test_step_skip_after_failure_and_from_complete(mcp):
    server = mcp()
    _create(server)
    _start(server, "s1", 0)
    _payload(server, "step_fail", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 1,
        "reason": "red", "evidence": []})
    skipped = _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 2,
        "reason": "retired after failure"})
    assert skipped["step"]["status"] == "skipped"
    assert skipped["step"]["completion"]["note"] == "retired after failure"

    _error(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s1", "expected_revision": 3,
        "reason": "again"}, "invalid-transition")


def test_ac_check_updates_a_criterion_and_replays(mcp):
    server = mcp()
    _create(server)
    first = _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 0,
        "status": "passed", "evidence": [_evidence()], "note": "reviewed"})
    assert first["changed"] is True
    assert first["revision"] == 1
    assert first["step_id"] == "s1"
    assert first["criterion"]["status"] == "passed"
    assert [item["kind"] for item in first["criterion"]["evidence"]] == ["test", "note"]
    assert first["criteria"] == {"passed": 1, "total": 1}

    replay = _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 1,
        "status": "passed", "evidence": [_evidence()], "note": "reviewed"})
    assert replay["changed"] is False
    assert replay["revision"] == 1

    _error(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 0,
        "status": "failed", "evidence": []}, "conflict")
    _error(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ghost", "expected_revision": 1,
        "status": "failed", "evidence": []}, "invalid-arguments")


def test_ac_check_is_frozen_after_the_step_completes(mcp):
    server = mcp()
    _create(server)
    _start(server, "s1", 0)
    _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 1,
        "status": "passed", "evidence": []})
    _complete(server, "s1", 2)
    error = _error(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 3,
        "status": "failed", "evidence": []}, "invalid-transition")
    assert error["details"]["allowed_transitions"] == []


# ------------------------------------------------------------------------- store failures


def test_schema_version_unsupported_surfaces_and_leaves_the_row_alone(mcp, _tracking_root):
    server = mcp()
    _create(server)
    connection = sqlite3.connect(_tracking_root / "tracking.db")
    try:
        payload = json.loads(connection.execute(
            "SELECT payload FROM plans WHERE task_id = ?", (TASK_ID,)).fetchone()[0])
        payload["schema_version"] = 999
        mutated = json.dumps(payload)
        connection.execute("UPDATE plans SET payload = ? WHERE task_id = ?",
                           (mutated, TASK_ID))
        connection.commit()
    finally:
        connection.close()

    error = _error(server, "plan_get", {"task_id": TASK_ID},
                   "schema-version-unsupported")
    assert error["details"]["found"] == 999
    assert error["details"]["supported"] == [1]

    connection = sqlite3.connect(_tracking_root / "tracking.db")
    try:
        after = connection.execute(
            "SELECT payload FROM plans WHERE task_id = ?", (TASK_ID,)).fetchone()[0]
    finally:
        connection.close()
    assert after == mutated


def test_store_error_when_the_database_file_is_not_a_database(mcp, _tracking_root):
    (_tracking_root / "tracking.db").write_bytes(b"this is not a sqlite database")
    server = mcp()
    error = _error(server, "plan_get", {"task_id": TASK_ID}, "store-error")
    assert error["retryable"] is False


# ------------------------------------------------------------------------------- --check


def _run_check(root: Optional[Path] = None):
    argv = [sys.executable, str(SERVER), "--check"]
    if root is not None:
        argv += ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _schema_tree(work: Path, *, mutate: bool) -> Path:
    root = work / "tree"
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    schema = json.loads((ROOT / "schemas" / "task-plan.schema.json").read_text(
        encoding="utf-8"))
    if mutate:
        schema["required"].remove("task_id")
    (root / "schemas" / "task-plan.schema.json").write_text(
        json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return root


def test_check_verb_accepts_the_checked_in_schema_and_refuses_drift(tmp_path):
    clean = _run_check()
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "ok" in clean.stdout

    tree = _schema_tree(tmp_path / "clean", mutate=False)
    accepted = _run_check(tree)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    drifted = _run_check(_schema_tree(tmp_path / "drifted", mutate=True))
    assert drifted.returncode == 1
    assert "STALE" in drifted.stdout

    missing = _run_check(tmp_path / "empty")
    assert missing.returncode == 1
    assert "missing" in missing.stdout


# ------------------------------------------------------------------------------ rendering


HEADING_RE = re.compile(r"^\*\*S(\d+) — (.*?) \(([a-z_]+)\)\*\*$")
CHECKBOX_RE = re.compile(r"^- \[([ x])\] ([a-z0-9._-]+): (.*)$")


def parse_plan_file(text: str):
    """An independent parser of the renderer's format: headings -> (goal, status), boxes."""
    steps = []
    current = None
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            current = {"number": int(heading.group(1)), "goal": heading.group(2),
                       "status": heading.group(3), "boxes": []}
            steps.append(current)
            continue
        box = CHECKBOX_RE.match(line)
        if box and current is not None:
            current["boxes"].append({"checked": box.group(1) == "x", "id": box.group(2)})
    return steps


def test_rendered_plan_file_round_trips_through_an_independent_parser(mcp, _tracking_root):
    server = mcp()
    _create(server, steps=_two_step_steps())
    _start(server, "s1", 0)
    _payload(server, "ac_check", {
        "task_id": TASK_ID, "step_id": "s1", "ac_id": "ac1", "expected_revision": 1,
        "status": "passed", "evidence": []})
    _complete(server, "s1", 2)
    _payload(server, "step_skip", {
        "task_id": TASK_ID, "step_id": "s2", "expected_revision": 3, "reason": "later"})

    files = sorted((_tracking_root / "plans").glob(f"*-{TASK_ID}.md"))
    assert len(files) == 1, files
    assert re.match(r"\d{4}-\d{2}-\d{2}-aib-demo-task\.md", files[0].name)
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("<!-- generated by task-graph")
    assert TASK_ID in text

    steps = parse_plan_file(text)
    assert [(step["number"], step["goal"], step["status"]) for step in steps] == [
        (1, "do the thing", "complete"), (2, "verify it", "skipped")]
    assert [box["id"] for step in steps for box in step["boxes"]] == ["ac1", "ac2"]
    assert [box["checked"] for step in steps for box in step["boxes"]] == [True, False]


# ------------------------------------------------------------------------------- tripwire


def test_default_root_tripwire_is_armed(load_script, monkeypatch):
    """The break-it witness: with the env unset, the loaded store reaches the tripwire."""
    module = load_script(SERVER_RELPATH)

    def tripwire():
        raise AssertionError(
            "test path reached _default_badger_root(); set AI_BADGER_TRACKING_ROOT instead")

    monkeypatch.setattr(module.task_plan_store.badger_store, "_default_badger_root", tripwire)
    monkeypatch.delenv(TRACKING_ROOT_ENV, raising=False)
    with pytest.raises(AssertionError, match="_default_badger_root"):
        module.task_plan_store.badger_store.tracking_db_path()
