"""Tests for features/copilot/adjustments/adjust_retrieval.py.

The Copilot twin of features/claude/adjustments/adjust_retrieval.py (issue #147): delivers the
BM25 retrieval modules beside `context_enrichment_hook.py` in the scaffolded mcp-index skill,
the same destination Claude's copy lands in — Copilot's own hook wiring
(features/copilot/adjustments/adjust_hooks.py) points at that same `.ai-badger/skills/
mcp-index/scripts/` path, unprefixed.
"""
from __future__ import annotations

from pathlib import Path


def _context(root: Path, target: Path, agents=("copilot",), skills=("mcp-index",)) -> dict:
    return {
        "framework_root": root,
        "config": {"agents": list(agents)},
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": list(skills),
    }


def _scaffold_mcp_index_scripts(target: Path) -> Path:
    dest = target / ".ai-badger" / "skills" / "mcp-index" / "scripts"
    dest.mkdir(parents=True)
    return dest


def test_copies_all_four_modules_beside_the_hook(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/copilot/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    dest = _scaffold_mcp_index_scripts(target)

    result = adjust_retrieval.adjust(_context(root, target))

    assert result["applied"]
    for filename in ("tokenizer.py", "bm25.py", "mcp_matcher.py", "context_enrichment.py"):
        assert (dest / filename).is_file(), f"{filename} missing"


def test_not_applied_when_copilot_is_not_configured(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/copilot/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    _scaffold_mcp_index_scripts(target)

    result = adjust_retrieval.adjust(_context(root, target, agents=("claude",)))

    assert not result["applied"]
    assert result["files"] == []


def test_not_applied_when_mcp_index_skill_was_declined(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/copilot/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    _scaffold_mcp_index_scripts(target)

    result = adjust_retrieval.adjust(_context(root, target, skills=()))

    assert not result["applied"]
    assert result["files"] == []


def test_not_applied_when_mcp_index_scripts_dir_does_not_exist(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/copilot/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    result = adjust_retrieval.adjust(_context(root, target))

    assert not result["applied"]
    assert not (target / ".ai-badger" / "skills" / "mcp-index").exists()
