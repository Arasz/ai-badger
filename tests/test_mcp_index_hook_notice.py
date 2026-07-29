"""Tests for features/common/hooks/mcp_index_hook.py's missing-index notice.

`_has_mcp_index` must accept either the current JSON index or a not-yet-migrated legacy
YAML one (issue #145) — a curated project mid-migration must never be told to run `init`.
"""
from __future__ import annotations

import logging

import pytest


@pytest.fixture
def hook(load_script):
    return load_script("features/common/hooks/mcp_index_hook.py")


def _project(tmp_path):
    aib = tmp_path / ".ai-badger"
    aib.mkdir(parents=True)
    return tmp_path


def test_has_mcp_index_true_for_current_json(hook, tmp_path):
    project = _project(tmp_path)
    (project / ".ai-badger" / "mcp-tools.json").write_text("{}", encoding="utf-8")
    assert hook._has_mcp_index(project) is True


def test_has_mcp_index_true_for_legacy_yaml(hook, tmp_path):
    project = _project(tmp_path)
    (project / ".ai-badger" / "mcp-tools.yaml").write_text("sources: []\n", encoding="utf-8")
    assert hook._has_mcp_index(project) is True


def test_has_mcp_index_false_when_neither_exists(hook, tmp_path):
    project = _project(tmp_path)
    assert hook._has_mcp_index(project) is False


def test_notice_names_the_json_path(hook, tmp_path, caplog):
    project = _project(tmp_path)
    with caplog.at_level(logging.INFO):
        hook.on_session_start(type("Ctx", (), {"cwd": str(project)})())
    assert any("mcp-tools.json" in r.message for r in caplog.records)
