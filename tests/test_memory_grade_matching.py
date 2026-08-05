"""The memory-grade matcher: only memory_search acts, in every naming spelling.

Hermes deferred-MCP names (`mcp__ai_raccoon__memory_search`), the colon form the
index partitions on (`ai-raccoon:memory_search`), and the bare name all identify
the same tool; every other memory-* tool and every non-memory tool never matches.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import pytest


@pytest.fixture
def memory_grade(load_script):
    return load_script("features/common/skills/ai-raccoon-memory/scripts/memory_grade.py")


def test_namespaced_mcp_name_matches(memory_grade):
    assert memory_grade.is_memory_search("mcp__ai_raccoon__memory_search")
    assert memory_grade.is_memory_search("mcp__ai-raccoon__memory_search")


def test_colon_form_matches(memory_grade):
    assert memory_grade.is_memory_search("ai-raccoon:memory_search")
    assert memory_grade.is_memory_search("ai_raccoon:memory_search")


def test_bare_name_matches(memory_grade):
    assert memory_grade.is_memory_search("memory_search")


def test_non_memory_tools_never_match(memory_grade):
    for name in ("memory_write", "memory_stats", "memory_embed_pending", "terminal",
                 "write_file", "mcp__code_review_graph__get_prompt",
                 "mcp__ai_raccoon__memory_write"):
        assert not memory_grade.is_memory_search(name), name


def test_non_string_never_matches(memory_grade):
    assert not memory_grade.is_memory_search(None)
    assert not memory_grade.is_memory_search(42)
