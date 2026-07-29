"""Telemetry for the MCP retrieval path: hit/gate/absent, and the tool-index defect fix.

Before this, the only observation point was a bare `logger.debug(...)` with no configured
handler in any shipped deployment shape — nobody ever read one. These tests assert a record
is actually produced, and that a "no match" is distinguishable from "no index".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

COMPONENT = "ai_badger_hooks/mcp_retrieval"


def _write_index(project: Path, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "mcp-tools.yaml").write_text(yaml.dump(data), encoding="utf-8")


def _sample_index() -> dict:
    return {
        "sources": [
            {
                "name": "rider",
                "tools": {
                    "build_solution": {
                        "tags": ["build", "dotnet"],
                        "intent": "Compile the solution and return build errors",
                    },
                    "execute_sql_query": {
                        "tags": ["database", "sql"],
                        "intent": "Run a SQL query against a database connection",
                    },
                },
            }
        ]
    }


@pytest.fixture
def hooks(load_script):
    return load_script("features/common/hooks/ai_badger_hooks.py")


def _enable(dl, tmp_path, monkeypatch):
    for attr, name in (("DEBUG_DIR", "debug"), ("STATE_FILE", "debug/state.json"),
                       ("AUDIT_FILE", "debug/audit.jsonl")):
        monkeypatch.setattr(dl, attr, tmp_path / name)
    dl.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    state = {"enabled": True, "scope": "user", "project": None,
              "expires_at": dl.iso(dl.now() + dl.timedelta(seconds=3600))}
    dl.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.delenv(dl.DEBUG_ENV, raising=False)
    monkeypatch.delenv(dl.REDACT_ENV, raising=False)


def _records(dl):
    if not dl.AUDIT_FILE.exists():
        return []
    return [json.loads(line) for line in dl.AUDIT_FILE.read_text(encoding="utf-8").splitlines()]


def _retrieval_records(dl):
    return [r for r in _records(dl) if r[dl.KEY_COMPONENT] == COMPONENT]


class TestHitGateAbsentAreDistinguishable:
    """A "no match" that reads identically to "no index" is a bug that hides itself."""

    def test_a_matching_query_emits_a_hit_record(self, hooks, tmp_path, monkeypatch):
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.pre_llm_inject_context(cwd=str(project), message="build the solution")

        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "hit"
        record = records[-1]
        assert record[dl.KEY_QUERY] == "build the solution"
        assert "build" in record[dl.KEY_TERMS]
        assert record[dl.KEY_CANDIDATES] == "2"
        assert "rider:build_solution" in record[dl.KEY_TOP]
        assert "rider:build_solution" in record[dl.KEY_RETURNED]
        assert record[dl.KEY_THRESHOLD]

    def test_a_query_that_scores_below_the_bar_emits_a_gate_record(self, hooks, tmp_path,
                                                                  monkeypatch):
        """`gate` means scored-and-rejected, so the query must actually reach the scorer."""
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.pre_llm_inject_context(cwd=str(project), message="csharp")

        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "gate"
        record = records[-1]
        assert record[dl.KEY_TERMS] == "csharp", "a gate record must name the terms it scored"
        assert record[dl.KEY_CANDIDATES] == "2"
        assert record[dl.KEY_RETURNED] == ""
        assert dl.KEY_THRESHOLD in record, "gate claims a threshold comparison; record it"

    def test_a_query_the_keyword_map_cannot_read_emits_no_terms_not_gate(self, hooks, tmp_path,
                                                                        monkeypatch):
        """8 of 11 realistic purposes produce zero tags. That is not a threshold miss.

        `_find_relevant_tools` returns early when no term is extracted, so nothing is ever
        compared to the bar — and the top scorer is often a correct match the map suppressed.
        Filing it as `gate` would misattribute the failure this telemetry exists to count.
        """
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.pre_llm_inject_context(cwd=str(project), message="take a screenshot of the page")

        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "no_terms"
        record = records[-1]
        assert record[dl.KEY_RETURNED] == ""
        assert dl.KEY_THRESHOLD not in record, (
            "no candidate was compared to the threshold, so the record must not claim one"
        )
        assert record[dl.KEY_TOP], (
            "the suppressed candidates are the point of this record — keep them"
        )

    def test_no_index_file_emits_an_absent_record(self, hooks, tmp_path, monkeypatch):
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        project.mkdir(parents=True, exist_ok=True)

        hooks.pre_llm_inject_context(cwd=str(project), message="build the solution")

        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "absent"
        record = records[-1]
        assert record[dl.KEY_QUERY] == "build the solution"
        assert dl.KEY_CANDIDATES not in record, "absent means there was nothing to count"


class TestRedactModeDropsOnlyTheQuery:
    def test_redaction_removes_the_query_but_keeps_the_rest(self, hooks, tmp_path, monkeypatch):
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        monkeypatch.setenv(dl.REDACT_ENV, "1")
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.pre_llm_inject_context(cwd=str(project), message="build the solution")

        record = _retrieval_records(dl)[-1]
        assert dl.KEY_QUERY not in record
        assert record[dl.KEY_EVENT] == "hit"
        assert "rider:build_solution" in record[dl.KEY_RETURNED]
        assert record[dl.KEY_CANDIDATES] == "2"


class TestTheToolIndexHitCheckIsNoLongerSilent:
    """The original `logger.debug("mcp_index_hit=...")` had no configured handler anywhere."""

    def test_a_known_tool_call_produces_a_record(self, hooks, tmp_path, monkeypatch):
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.post_tool_observer(tool_name="rider:build_solution", result="{}",
                                  duration_ms=1, cwd=str(project))

        records = _retrieval_records(dl)
        assert records, "no record was produced for a checked tool call"
        assert records[-1][dl.KEY_EVENT] == "known"

    def test_an_unknown_tool_call_is_distinguishable(self, hooks, tmp_path, monkeypatch):
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.post_tool_observer(tool_name="rider:no_such_tool", result="{}",
                                  duration_ms=1, cwd=str(project))

        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "unknown"


class TestRecordCompleteness:
    """A field added to a record without a matching legend entry renders as a raw letter."""

    def test_every_key_this_component_writes_is_registered(self, hooks, tmp_path, monkeypatch):
        dl = hooks.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        hooks.pre_llm_inject_context(cwd=str(project), message="build the solution")
        hooks.pre_llm_inject_context(cwd=str(project), message="philosophical question about life")
        hooks.post_tool_observer(tool_name="rider:build_solution", result="{}", cwd=str(project))
        (project / ".ai-badger" / "mcp-tools.yaml").unlink()
        hooks.pre_llm_inject_context(cwd=str(project), message="build the solution")

        records = _retrieval_records(dl)
        assert len(records) == 4
        for record in records:
            assert set(record.keys()) <= set(dl.KEY_NAMES), record
