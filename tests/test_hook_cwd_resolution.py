"""Plugin hooks must work with the kwargs Hermes actually sends (#76).

Hermes passes no `cwd` to any plugin hook, and names the prompt kwarg `user_message`.
Every test here invokes a hook with the *real* call shape, not a convenient one.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOKS_PATH = ROOT / "features" / "common" / "hooks" / "ai_badger_hooks.py"


@pytest.fixture
def hooks():
    """Load ai_badger_hooks.py fresh so module-level state never leaks between tests."""
    spec = importlib.util.spec_from_file_location("aib_hooks_cwd", HOOKS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["aib_hooks_cwd"] = module
    spec.loader.exec_module(module)
    return module


def _scaffolded_project(tmp_path: Path, framework_version: str = "0.0.1") -> Path:
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(
        json.dumps({"frameworkVersion": framework_version, "entries": []}), encoding="utf-8")
    return project


def _with_index(project: Path) -> Path:
    (project / ".ai-badger" / "mcp-tools.yaml").write_text(yaml.dump({
        "version": "0.1.0",
        "sources": [{
            "name": "rider",
            "tools": {"build_solution": {"tags": ["dotnet", "build"],
                                         "intent": "Compile the solution"}},
        }],
    }, sort_keys=False), encoding="utf-8")
    return project


def test_drift_notice_fires_when_hermes_sends_no_cwd(tmp_path, monkeypatch, caplog, hooks):
    """on_session_start receives only session_id/model/platform — cwd must be resolved."""
    project = _scaffolded_project(tmp_path)
    monkeypatch.chdir(project)

    with caplog.at_level("INFO"):
        hooks.on_session_start_drift_notice(
            session_id="sess_1", model="claude-opus-5", platform="cli")

    assert any("ai-badger drift" in r.message for r in caplog.records)


def test_drift_notice_silent_outside_a_project(tmp_path, monkeypatch, caplog, hooks):
    """Resolving cwd must not make the hook nag from an unscaffolded directory."""
    monkeypatch.chdir(tmp_path)

    with caplog.at_level("INFO"):
        hooks.on_session_start_drift_notice(session_id="sess_1")

    assert not any("ai-badger drift" in r.message for r in caplog.records)


def test_pre_llm_injects_drift_when_hermes_sends_no_cwd(tmp_path, monkeypatch, hooks):
    project = _scaffolded_project(tmp_path)
    monkeypatch.chdir(project)

    result = hooks.pre_llm_inject_context(
        session_id="sess_1", user_message="hello", model="claude-opus-5", platform="cli")

    assert result is not None
    assert "Run den-refresh to update." in result["context"]


def test_pre_llm_reads_the_user_message_kwarg_hermes_sends(tmp_path, monkeypatch, hooks):
    """Hermes names the prompt `user_message`; `message` is never sent."""
    project = _with_index(_scaffolded_project(tmp_path))
    monkeypatch.chdir(project)

    result = hooks.pre_llm_inject_context(
        session_id="sess_1", user_message="build the dotnet solution", platform="cli")

    assert result is not None
    assert "Relevant MCP tools" in result["context"]


def test_post_tool_observer_finds_the_index_when_hermes_sends_no_cwd(
        tmp_path, monkeypatch, hooks):
    """Was asserted via `caplog` against a bare logger with no configured handler anywhere —
    that assertion passed while nobody could ever have read the line it checked for. Rewritten
    to assert through `debug_log`, the mechanism that actually reaches a record now (#137)."""
    project = _with_index(_scaffolded_project(tmp_path))
    monkeypatch.chdir(project)
    dl = hooks.debug_log
    for attr, name in (("DEBUG_DIR", "debug"), ("STATE_FILE", "debug/state.json"),
                       ("AUDIT_FILE", "debug/audit.jsonl")):
        monkeypatch.setattr(dl, attr, tmp_path / name)
    dl.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    dl.STATE_FILE.write_text(json.dumps({
        "enabled": True, "scope": "user", "project": None,
        "expires_at": dl.iso(dl.now() + dl.timedelta(seconds=3600)),
    }), encoding="utf-8")
    monkeypatch.delenv(dl.DEBUG_ENV, raising=False)

    hooks.post_tool_observer(tool_name="rider:build_solution", result="ok", duration_ms=3)

    records = [json.loads(line) for line in dl.AUDIT_FILE.read_text(encoding="utf-8").splitlines()]
    assert any(r[dl.KEY_COMPONENT] == "ai_badger_hooks/mcp_retrieval" and r[dl.KEY_EVENT] == "known"
               for r in records)
