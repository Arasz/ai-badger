"""Tests for features/common/skills/mcp-index/scripts/context_enrichment_hook.py.

The Claude/Copilot side of issue #147: `context-enrichment` used to reach only Hermes
(`ai_badger_hooks.py`'s `pre_llm_call`). This is its stdin/stdout adapter, run as a
`UserPromptSubmit` (Claude) / `userPromptSubmitted` (Copilot) hook — same telemetry component
(`ai_badger_hooks/mcp_retrieval`) and event names (hit/gate/no_terms/absent/legacy) as the Hermes
path, asserted here the same way tests/test_mcp_retrieval_telemetry.py asserts them there, so an
audit record reads identically regardless of which agent produced it.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json
import sys

import pytest

HOOK_PATH = "features/common/skills/mcp-index/scripts/context_enrichment_hook.py"
COMPONENT = "ai_badger_hooks/mcp_retrieval"


def _write_index(project, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "mcp-tools.json").write_text(json.dumps(data), encoding="utf-8")


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


@pytest.fixture(autouse=True)
def _project_comes_from_the_payload(monkeypatch):
    """These tests hand the hook its project in the payload's `cwd`.

    `resolve_project_root` reads `$CLAUDE_PROJECT_DIR` first, and the suite now points that at
    a scratch directory so nothing writes into the real checkout (#222) — which would outrank
    the payload and leave the hook looking for an index that is not there.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


@pytest.fixture
def hook(load_script):
    return load_script(HOOK_PATH)


@pytest.fixture
def real_context_enrichment(hook, load_script, monkeypatch):
    """Inject the real shared module, as the retrieval adjustment would copy beside the hook."""
    module = load_script("features/common/retrieval/context_enrichment.py")
    monkeypatch.setitem(sys.modules, hook.CONTEXT_ENRICHMENT_MODULE_NAME, module)
    return module


def _run_main(module, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return module.main()


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


class TestNoPromptOrNoMatcher:
    def test_no_prompt_emits_nothing(self, hook, monkeypatch, capsys):
        rc = _run_main(hook, monkeypatch, {"cwd": "/repo"})
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_matcher_unavailable_emits_nothing(self, hook, monkeypatch, capsys, tmp_path):
        """context_enrichment stays None when the retrieval adjustment never ran."""
        project = tmp_path / "proj"
        _write_index(project, _sample_index())
        rc = _run_main(hook, monkeypatch, {"prompt": "build the solution", "cwd": str(project)})
        assert rc == 0
        assert capsys.readouterr().out == ""


class TestHitGateNoTermsAbsentAreDistinguishable:
    def test_a_matching_query_emits_additional_context_and_a_hit_record(
        self, hook, tmp_path, monkeypatch, capsys, real_context_enrichment
    ):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        rc = _run_main(hook, monkeypatch,
                        {"prompt": "build the solution", "cwd": str(project)})

        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        context = out["hookSpecificOutput"]["additionalContext"]
        assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert "rider:build_solution" in context

        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "hit"
        record = records[-1]
        assert record[dl.KEY_QUERY] == "build the solution"
        assert "rider:build_solution" in record[dl.KEY_RETURNED]

    def test_a_query_that_scores_below_the_bar_emits_no_context_and_a_gate_record(
        self, hook, tmp_path, monkeypatch, capsys, real_context_enrichment
    ):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        rc = _run_main(hook, monkeypatch,
                        {"prompt": "take a screenshot of the page", "cwd": str(project)})

        assert rc == 0
        assert capsys.readouterr().out == ""
        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "gate"

    def test_a_query_that_tokenizes_to_nothing_emits_no_terms_not_gate(
        self, hook, tmp_path, monkeypatch, capsys, real_context_enrichment
    ):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        rc = _run_main(hook, monkeypatch, {"prompt": "!!! ---", "cwd": str(project)})

        assert rc == 0
        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "no_terms"
        assert dl.KEY_THRESHOLD not in records[-1]

    def test_no_index_file_emits_an_absent_record(self, hook, tmp_path, monkeypatch,
                                                    real_context_enrichment):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        project.mkdir(parents=True, exist_ok=True)

        rc = _run_main(hook, monkeypatch,
                        {"prompt": "build the solution", "cwd": str(project)})

        assert rc == 0
        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "absent"

    def test_a_not_yet_migrated_legacy_index_emits_legacy_not_absent(
        self, hook, tmp_path, monkeypatch, real_context_enrichment
    ):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        aib = project / ".ai-badger"
        aib.mkdir(parents=True)
        (aib / "mcp-tools.yaml").write_text("sources: []\n", encoding="utf-8")

        rc = _run_main(hook, monkeypatch,
                        {"prompt": "build the solution", "cwd": str(project)})

        assert rc == 0
        records = _retrieval_records(dl)
        assert records and records[-1][dl.KEY_EVENT] == "legacy"


class TestRedactModeDropsOnlyTheQuery:
    def test_redaction_removes_the_query_but_keeps_the_rest(
        self, hook, tmp_path, monkeypatch, real_context_enrichment
    ):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        monkeypatch.setenv(dl.REDACT_ENV, "1")
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        _run_main(hook, monkeypatch, {"prompt": "build the solution", "cwd": str(project)})

        record = _retrieval_records(dl)[-1]
        assert dl.KEY_QUERY not in record
        assert record[dl.KEY_EVENT] == "hit"


class TestRecordCompleteness:
    def test_every_key_this_hook_writes_is_registered(
        self, hook, tmp_path, monkeypatch, real_context_enrichment
    ):
        dl = hook.debug_log
        _enable(dl, tmp_path, monkeypatch)
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        _run_main(hook, monkeypatch, {"prompt": "build the solution", "cwd": str(project)})
        _run_main(hook, monkeypatch,
                   {"prompt": "take a screenshot of the page", "cwd": str(project)})
        _run_main(hook, monkeypatch, {"prompt": "!!! ---", "cwd": str(project)})

        records = _retrieval_records(dl)
        assert len(records) == 3
        for record in records:
            assert set(record.keys()) <= set(dl.KEY_NAMES), record


class TestNeverBlocksAndNeverInterceptsTheTool:
    def test_malformed_stdin_never_raises(self, hook, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        rc = hook.guarded_main()
        assert rc == 0

    def test_emitted_json_is_advisory_only(self, hook, tmp_path, monkeypatch, capsys,
                                            real_context_enrichment):
        project = tmp_path / "proj"
        _write_index(project, _sample_index())

        _run_main(hook, monkeypatch, {"prompt": "build the solution", "cwd": str(project)})

        out = json.loads(capsys.readouterr().out)
        keys = set(out["hookSpecificOutput"].keys())
        assert keys == {"hookEventName", "additionalContext"}
