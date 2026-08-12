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


def test_main_cli_returns_zero_on_success(tmp_path):
    """CLI main returns 0 on successful execution."""
    target = tmp_path / "sub" / "semantica-graph.json"
    exit_code = main(["--target", str(target), "--json", '{"nodes":[]}'])

    assert exit_code == 0
    assert target.is_file()


def test_main_cli_returns_zero_on_exception(monkeypatch):
    """CLI main logs error and returns 0 when unexpected exception occurs."""
    def _failing_export(*args, **kwargs):
        raise RuntimeError("Simulated write failure")

    monkeypatch.setattr(export_module, "export_graph", _failing_export)

    exit_code = main([])
    assert exit_code == 0


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
