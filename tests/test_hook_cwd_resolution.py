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


@pytest.fixture
def real_mcp_matcher(hooks, load_script, monkeypatch):
    """Inject the real BM25 matcher, as scaffolding would copy beside the hook."""
    module = load_script("features/common/retrieval/mcp_matcher.py")
    monkeypatch.setitem(sys.modules, hooks.MCP_MATCHER_MODULE_NAME, module)
    return module


def _scaffolded_project(tmp_path: Path, framework_version: str = "0.0.1") -> Path:
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(
        json.dumps({"frameworkVersion": framework_version, "entries": []}), encoding="utf-8")
    return project


def _with_index(project: Path) -> Path:
    (project / ".ai-badger" / "mcp-tools.json").write_text(json.dumps({
        "version": "0.1.0",
        "sources": [{
            "name": "rider",
            "tools": {"build_solution": {"tags": ["dotnet", "build"],
                                         "intent": "Compile the solution"}},
        }],
    }), encoding="utf-8")
    return project


def test_drift_notice_fires_when_hermes_sends_no_cwd(tmp_path, monkeypatch, caplog, hooks):
    """on_session_start receives only session_id/model/platform — cwd must be resolved."""
    project = _scaffolded_project(tmp_path)
    monkeypatch.chdir(project)

    with caplog.at_level("INFO"):
        hooks.on_session_start_drift_notice(
            session_id="sess_1", model="claude-opus-5", platform="cli")

    assert any("ai-badger drift" in r.message for r in caplog.records)


def test_drift_notice_silent_on_patch_only_bump(tmp_path, root, monkeypatch, caplog, hooks):
    """Acceptance criterion (B10): a patch-only bump must not produce a drift notice."""
    fw_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    major, minor, patch = fw_version.split(".")
    scaffold_version = f"{major}.{minor}.{int(patch) + 1}"
    project = _scaffolded_project(tmp_path, framework_version=scaffold_version)
    monkeypatch.chdir(project)

    with caplog.at_level("INFO"):
        hooks.on_session_start_drift_notice(session_id="sess_1")

    assert not any("ai-badger drift" in r.message for r in caplog.records)


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


def test_pre_llm_silent_on_patch_only_bump(tmp_path, root, monkeypatch, hooks):
    """Same acceptance criterion (B10) for the per-turn context-injection path."""
    fw_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    major, minor, patch = fw_version.split(".")
    scaffold_version = f"{major}.{minor}.{int(patch) + 1}"
    project = _scaffolded_project(tmp_path, framework_version=scaffold_version)
    monkeypatch.chdir(project)

    result = hooks.pre_llm_inject_context(
        session_id="sess_1", user_message="hello", model="claude-opus-5", platform="cli")

    if result is not None:
        assert "Run den-refresh to update." not in result["context"]


def test_pre_llm_reads_the_user_message_kwarg_hermes_sends(
        tmp_path, monkeypatch, hooks, real_mcp_matcher):
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


def test_both_hosts_agree_on_versions_diverge(hooks, load_script):
    """ai_badger_hooks.py cannot import drift_notice.py cleanly (different Hermes/Claude
    directories), so `versions_diverge` is duplicated -- this pins both spellings agree,
    the pattern SPAWN_LOG_ENV/REAL_WRITE_LOG_ENV use in tests/conftest.py."""
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")

    cases = [
        ("0.89.0", "0.89.1", False),
        ("0.89.0", "0.90.0", True),
        ("0.89.0", "1.0.0", True),
        ("0.89.0", "0.89.0", False),
        ("not-a-version", "also-not-a-version", True),
        ("not-a-version", "not-a-version", False),
    ]
    for scaffolded, running, expected in cases:
        claude_result = dn.versions_diverge(scaffolded, running)
        hermes_result = hooks.versions_diverge(scaffolded, running)
        assert claude_result is expected, (scaffolded, running, "drift_notice.py")
        assert hermes_result is expected, (scaffolded, running, "ai_badger_hooks.py")
        assert claude_result == hermes_result, (scaffolded, running)
