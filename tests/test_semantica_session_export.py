"""Semantica session-graph persistence: Hermes hook wiring (U2).

Pins the two hook arms of the feature:
- post_tool_observer auto-saves an export_graph MCP result to .semantica/<session>.json
  (dispatching through the lazy-loaded sibling export_semantica_graph.py module).
- pre_llm_inject_context surfaces a once-per-session Semantica nudge, gated on the
  MCP tool index naming a semantica source.

The write/parse logic itself lives in features/common/skills/semantica-knowledge-graph/
scripts/export_semantica_graph.py (covered by U1); this file only pins the wiring.
"""
# pylint: disable=redefined-outer-name,protected-access  # module-local fixtures; see pyproject.toml
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def hooks(load_script):
    """Load a fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def export_module(hooks, load_script, monkeypatch):
    """The real export module, injected under the hooks' module-name constant."""
    module = load_script(
        "features/common/skills/semantica-knowledge-graph/scripts/export_semantica_graph.py")
    monkeypatch.setitem(sys.modules, hooks.SEMANTICA_EXPORT_MODULE_NAME, module)
    return module


def _export_graph_result():
    """The double-encoded envelope Hermes' post_tool_call emits for an MCP text result."""
    return '{"result": "{\\"nodes\\":[{\\"id\\":\\"n1\\"}]}"}'


def test_post_tool_observer_saves_export_graph_result(
        hooks, export_module, tmp_path, monkeypatch):
    """The observer unwraps the envelope and writes one .semantica/<session>-*.json dump."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(
        function_name="mcp__semantica__export_graph",
        result=_export_graph_result(),
        session_id="sess-42",
    )

    files = list((tmp_path / ".semantica").glob("sess-42-*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["nodes"][0]["id"] == "n1"


def test_post_tool_observer_skips_non_export_tools(hooks, export_module, tmp_path, monkeypatch):
    """A non-export tool must not create the .semantica/ directory."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(
        function_name="memory_search",
        result='{"results": []}',
        session_id="sess-42",
    )

    assert not (tmp_path / ".semantica").exists()


def test_error_result_is_not_written(hooks, export_module, tmp_path, monkeypatch):
    """An isError payload must leave any existing dump untouched and write nothing new."""
    monkeypatch.chdir(tmp_path)
    semantica_dir = tmp_path / ".semantica"
    semantica_dir.mkdir(parents=True)
    good = semantica_dir / "sess-42-1.json"
    good.write_text('{"nodes": [{"id": "n1"}]}', encoding="utf-8")

    hooks.post_tool_observer(
        function_name="mcp__semantica__export_graph",
        result='{"isError": true, "result": "{\\"nodes\\":[]}"}',
        session_id="sess-42",
    )

    files = list(semantica_dir.glob("sess-42-*.json"))
    assert files == [good]
    assert good.read_text(encoding="utf-8") == '{"nodes": [{"id": "n1"}]}'


def test_missing_autosave_module_means_no_write(hooks, tmp_path, monkeypatch):
    """Fail open: with no sibling module beside the hook, an export_graph result writes nothing."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(
        function_name="mcp__semantica__export_graph",
        result=_export_graph_result(),
        session_id="sess-42",
    )

    assert not (tmp_path / ".semantica").exists()


def test_pre_llm_nudge_injected_once_and_reset(hooks, export_module, tmp_path, monkeypatch):
    """The Semantica nudge is once-per-session, gated on the index, and cleared by reset."""
    monkeypatch.setattr(hooks, "_load_mcp_index",
                        lambda cwd: {"sources": [{"name": "semantica"}]})
    hooks.reset_session_hints()

    first = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="")
    second = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="")

    assert "Semantica" in (first or {}).get("context", "")
    assert "Semantica" not in (second or {}).get("context", "")

    hooks.reset_session_hints()
    again = hooks.pre_llm_inject_context(cwd=str(tmp_path), message="")
    assert "Semantica" in (again or {}).get("context", "")


def test_pre_llm_nudge_gated_on_index(hooks, export_module, tmp_path, monkeypatch):
    """No semantica source in the index (or no index) -> no nudge."""
    monkeypatch.setattr(hooks, "_load_mcp_index",
                        lambda cwd: {"sources": [{"name": "other"}]})
    hooks.reset_session_hints()
    assert "Semantica" not in hooks.pre_llm_inject_context(cwd=str(tmp_path),
                                                            message="hello")["context"]

    monkeypatch.setattr(hooks, "_load_mcp_index", lambda cwd: None)
    hooks.reset_session_hints()
    assert "Semantica" not in hooks.pre_llm_inject_context(cwd=str(tmp_path),
                                                            message="hello")["context"]


def test_semantica_indexed_matches_only_the_semantica_last_token(export_module):
    """Bare 'semantica' and 'plugin:semantica:semantica' match; 'semantica-fork' does not."""
    assert export_module.semantica_indexed({"sources": [{"name": "semantica"}]})
    assert export_module.semantica_indexed({"sources": [{"name": "plugin:semantica:semantica"}]})
    assert not export_module.semantica_indexed({"sources": [{"name": "semantica-fork"}]})
    assert not export_module.semantica_indexed(None)
    assert not export_module.semantica_indexed({"sources": []})
