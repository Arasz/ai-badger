"""Tests for features/claude/adjustments/adjust_retrieval.py.

Delivers the BM25 retrieval modules beside `context_enrichment_hook.py` in the scaffolded
mcp-index skill — the Claude equivalent of the copy `features/hermes/adjustments/adjust_hooks.py`
already does for Hermes (issue #147). Without this, a Claude-only project's hook wiring is
correct but the hook itself has nothing to import: exactly the state a real scaffold of a
Claude-only project showed before this adjustment existed.
"""
from __future__ import annotations

from pathlib import Path


def _context(root: Path, target: Path, agents=("claude",), skills=("mcp-index",)) -> dict:
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
    adjust_retrieval = load_script("features/claude/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    dest = _scaffold_mcp_index_scripts(target)

    result = adjust_retrieval.adjust(_context(root, target))

    assert result["applied"]
    for filename in ("tokenizer.py", "bm25.py", "mcp_matcher.py", "context_enrichment.py"):
        assert (dest / filename).is_file(), f"{filename} missing"
    assert sorted(result["files"]) == sorted(
        f".ai-badger/skills/mcp-index/scripts/{f}"
        for f in ("tokenizer.py", "bm25.py", "mcp_matcher.py", "context_enrichment.py")
    )


def test_not_applied_when_claude_is_not_configured(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/claude/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    _scaffold_mcp_index_scripts(target)

    result = adjust_retrieval.adjust(_context(root, target, agents=("hermes",)))

    assert not result["applied"]
    assert result["files"] == []


def test_not_applied_when_mcp_index_skill_was_declined(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/claude/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    _scaffold_mcp_index_scripts(target)

    result = adjust_retrieval.adjust(_context(root, target, skills=()))

    assert not result["applied"]
    assert result["files"] == []


def test_not_applied_when_mcp_index_scripts_dir_does_not_exist(tmp_path, root, load_script):
    """`mcp-index` in skills but its scripts/ directory never scaffolded: refuse, don't create."""
    adjust_retrieval = load_script("features/claude/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    result = adjust_retrieval.adjust(_context(root, target))

    assert not result["applied"]
    assert result["files"] == []
    assert not (target / ".ai-badger" / "skills" / "mcp-index").exists()


def test_copied_content_matches_the_framework_source_byte_for_byte(tmp_path, root, load_script):
    adjust_retrieval = load_script("features/claude/adjustments/adjust_retrieval.py")
    target = tmp_path / "proj"
    dest = _scaffold_mcp_index_scripts(target)

    adjust_retrieval.adjust(_context(root, target))

    src = root / "features" / "common" / "retrieval" / "mcp_matcher.py"
    assert (dest / "mcp_matcher.py").read_text(encoding="utf-8") == src.read_text(
        encoding="utf-8")
