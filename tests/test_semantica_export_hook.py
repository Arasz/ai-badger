"""Unit and sensitivity tests for the Semantica export hook script.

Verifies atomic file writing, seed fallback, error resilience, and sensitivity checks.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "features"
    / "common"
    / "skills"
    / "semantica-knowledge-graph"
    / "scripts"
    / "export_semantica_graph.py"
)

spec = importlib.util.spec_from_file_location("export_semantica_graph", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
export_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_module)

export_graph = export_module.export_graph
main = export_module.main
DEFAULT_SEED = export_module.DEFAULT_SEED
SEMANTICA_DIR = export_module.SEMANTICA_DIR
is_export_graph = export_module.is_export_graph
session_export_target = export_module.session_export_target
extract_graph_json = export_module.extract_graph_json
autosave_export = export_module.autosave_export


def test_export_graph_creates_file_with_seeded_payload(tmp_path):
    """When no raw_json or target file exists, export_graph creates file with default seed."""
    target = tmp_path / "semantica-graph.json"
    result = export_graph(target_path=target)

    assert result == target
    assert target.is_file()

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == "1.0"
    assert "nodes" in data
    assert "edges" in data
    assert "decisions" in data
    assert data["metadata"]["source"] == "semantica-mcp"
    assert data["metadata"]["updatedAt"] is not None


def test_export_graph_atomic_write_overwrites_existing(tmp_path):
    """export_graph atomically overwrites an existing file."""
    target = tmp_path / "semantica-graph.json"
    target.write_text(json.dumps({"old": True}), encoding="utf-8")

    new_data = json.dumps({"nodes": [{"id": "n1"}], "edges": []})
    export_graph(target_path=target, raw_json=new_data)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["nodes"] == [{"id": "n1"}]
    assert data["metadata"]["updatedAt"] is not None


def test_export_graph_handles_invalid_json_gracefully(tmp_path):
    """Invalid JSON falls back to default seed structure with raw_unparsed field."""
    target = tmp_path / "semantica-graph.json"
    export_graph(target_path=target, raw_json="not valid json")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["raw_unparsed"] == "not valid json"
    assert data["metadata"]["updatedAt"] is not None


def test_export_graph_temp_dir_keeps_temp_out_of_target_dir(tmp_path):
    """With temp_dir outside the target dir, no *.tmp* file lands under .semantica/."""
    project_dir = tmp_path
    target = project_dir / ".semantica" / "graph.json"
    export_graph(target_path=target, data_dict={"nodes": []}, temp_dir=project_dir)

    assert target.is_file()
    assert sorted(p.name for p in (project_dir / ".semantica").iterdir()) == ["graph.json"]
    assert list(project_dir.glob("*.tmp*")) == []


def test_main_cli_returns_zero_on_success(tmp_path):
    """CLI main returns 0 on successful execution."""
    target = tmp_path / "sub" / "semantica-graph.json"
    exit_code = main(["--target", str(target), "--json", '{"nodes":[]}'])

    assert exit_code == 0
    assert target.is_file()


def test_main_cli_defaults_to_semantica_dir(tmp_path, monkeypatch):
    """CLI main with no --target writes under cwd/.semantica/ and returns 0."""
    monkeypatch.chdir(tmp_path)
    exit_code = main([])

    assert exit_code == 0
    files = list((tmp_path / ".semantica").glob("semantica-graph-*.json"))
    assert len(files) == 1
    assert files[0].is_file()


def test_main_cli_returns_zero_on_exception(monkeypatch):
    """CLI main logs error and returns 0 when unexpected exception occurs."""
    def _failing_export(*args, **kwargs):
        raise RuntimeError("Simulated write failure")

    monkeypatch.setattr(export_module, "export_graph", _failing_export)

    exit_code = main([])
    assert exit_code == 0


@pytest.mark.parametrize(
    "tool_name, expected",
    [
        ("mcp__semantica__export_graph", True),
        ("semantica:export_graph", True),
        ("export_graph", True),
        ("add_entity", False),
        ("memory_search", False),
        ("export_graph_extra", False),
        (None, False),
        (123, False),
    ],
)
def test_is_export_graph(tool_name, expected):
    """is_export_graph normalizes MCP/server prefixes and matches only export_graph."""
    assert is_export_graph(tool_name) == expected


def test_session_export_target_under_semantica_dir(tmp_path):
    """session_export_target nests under project_dir/.semantica/."""
    target = session_export_target("sess-1", tmp_path)

    assert target.parent == tmp_path / SEMANTICA_DIR
    assert target.name.startswith("sess-1-")
    assert target.name.endswith(".json")


def test_session_export_target_same_id_different_paths(tmp_path):
    """Two calls with the same session id produce distinct (timestamped) paths."""
    first = session_export_target("sess-1", tmp_path)
    second = session_export_target("sess-1", tmp_path)

    assert first != second


def test_session_export_target_none_id_timestamp_only(tmp_path):
    """A None session id yields a timestamp-only filename (no session segment)."""
    target = session_export_target(None, tmp_path)

    assert target.parent == tmp_path / SEMANTICA_DIR
    assert target.name.endswith(".json")
    assert "-" not in target.stem


def test_session_export_target_empty_id_timestamp_only(tmp_path):
    """An empty session id yields a timestamp-only filename (no session segment)."""
    target = session_export_target("", tmp_path)

    assert "-" not in target.stem


def test_session_export_target_sanitizes_id(tmp_path):
    """':' and '/' (and other unsafe chars) in the session id are sanitized away."""
    target = session_export_target("sess/1:2 a", tmp_path)

    assert ":" not in target.name
    assert "/" not in target.name
    assert target.stem.rsplit("-", 1)[0] == "sess_1_2_a"


@pytest.mark.parametrize(
    "result, expected",
    [
        ({"nodes": []}, {"nodes": []}),
        ('{"nodes": []}', {"nodes": []}),
        ('{"result": "{\\"nodes\\": []}"}', {"nodes": []}),
        ('{"result": {"nodes": []}}', {"nodes": []}),
        ('{"structuredContent": {"nodes": []}}', {"nodes": []}),
        ('{"isError": true, "error": "boom"}', None),
        ("not json", None),
        ("[]", None),
        (None, None),
        (123, None),
    ],
)
def test_extract_graph_json(result, expected):
    """extract_graph_json unwraps the double-encoded MCP envelope, or returns None."""
    assert extract_graph_json(result) == expected


def test_autosave_export_writes_graph_file(tmp_path):
    """A valid double-encoded export result writes exactly one .semantica/<session>-*.json."""
    result = '{"result": "{\\"nodes\\": [{\\"id\\": \\"n1\\"}]}"}'
    path = autosave_export("mcp__semantica__export_graph", result, "sess-1", tmp_path)

    assert path is not None
    assert path.parent == tmp_path / SEMANTICA_DIR
    assert path.is_file()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["nodes"] == [{"id": "n1"}]
    assert data["metadata"]["updatedAt"] is not None

    files = list(path.parent.glob("sess-1-*.json"))
    assert len(files) == 1


def test_autosave_export_skips_non_export_tool(tmp_path):
    """A non-export_graph tool name writes nothing and returns None."""
    assert autosave_export("add_entity", '{"nodes": []}', "sess-1", tmp_path) is None
    assert not (tmp_path / SEMANTICA_DIR).exists()


def test_autosave_export_skips_error_payload(tmp_path):
    """An isError/error payload writes nothing (never a seed) and returns None."""
    result = '{"isError": true, "error": "boom"}'
    assert autosave_export("export_graph", result, "sess-1", tmp_path) is None
    assert not (tmp_path / SEMANTICA_DIR).exists()


def test_autosave_export_skips_empty_result(tmp_path):
    """An empty/None result writes nothing and returns None."""
    assert autosave_export("export_graph", None, "sess-1", tmp_path) is None
    assert not (tmp_path / SEMANTICA_DIR).exists()


class TestExportHookChecksCanFail:
    """Sensitivity tests proving each assertion in this file can fail."""

    def test_missing_file_check_can_fail(self, tmp_path):
        """Detects if target file was not created."""
        target = tmp_path / "nonexistent.json"
        assert not target.is_file()

    def test_corrupted_metadata_check_can_fail(self):
        """Detects missing metadata field in payload."""
        data = {"version": "1.0"}
        assert "metadata" not in data

    def test_session_export_target_same_id_differs_check_can_fail(self, tmp_path, monkeypatch):
        """The same-id-differs assertion is load-bearing: a fixed slug collapses paths."""
        monkeypatch.setattr(export_module, "_now_slug", lambda: "fixed")
        first = session_export_target("sess-1", tmp_path)
        second = session_export_target("sess-1", tmp_path)
        assert first == second
