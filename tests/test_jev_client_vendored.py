"""Vendoring gate for the skill-side Jev client copy.

`features/common/skills/task-decomposition/scripts/openrouter_client.py` must be a byte copy of
`features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py` with exactly one changed
line: the test-base env name (`AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE` →
`AI_BADGER_JEV_TEST_OPENROUTER_BASE`). The comparison normalizes that one line and byte-compares
everything else; a mutation of any second line turns it red, and the mutation witness runs the
mutated copy through the same `comparison_result()` the primary test uses.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py"
VENDORED = ROOT / "features/common/skills/task-decomposition/scripts/openrouter_client.py"

SOURCE_LINE = 'TEST_BASE_ENV = "AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE"'
VENDORED_LINE = 'TEST_BASE_ENV = "AI_BADGER_JEV_TEST_OPENROUTER_BASE"'


def normalized_source() -> bytes:
    """The ai-raccoon source with the one sanctioned line changed, as raw bytes."""
    raw = SOURCE.read_bytes()
    assert raw.count(SOURCE_LINE.encode()) == 1, (
        f"the source's TEST_BASE_ENV line moved or was duplicated in {SOURCE}")
    return raw.replace(SOURCE_LINE.encode(), VENDORED_LINE.encode())


def comparison_result(vendored: bytes) -> bool:
    """The vendoring rule as one function, so the witness exercises the real comparison."""
    return vendored == normalized_source()


def test_vendored_copy_is_byte_identical_except_the_one_sanctioned_line():
    assert VENDORED.is_file(), f"{VENDORED} does not exist — the client was never vendored"
    assert comparison_result(VENDORED.read_bytes())


def test_the_sanctioned_line_is_the_jev_name_and_the_rule_is_kept():
    vendored = VENDORED.read_text(encoding="utf-8")
    assert vendored.count(VENDORED_LINE) == 1
    assert SOURCE_LINE not in vendored
    # The loopback-only rule the one-line change must not disturb.
    assert 'TEST_KEY_PREFIX = "sk-test-"' in vendored
    assert 'LOOPBACK = "127.0.0.1"' in vendored
    assert "never a silent switch to production" in vendored


def test_comparator_flags_a_second_changed_line():
    """Mutation proof for the comparator itself: any second line difference is caught.

    The mutated copy goes through the same `comparison_result()` the primary test uses, so a
    comparator that could only ever answer True fails here.
    """
    marker = b'LOOPBACK = "127.0.0.1"'
    mutated = VENDORED.read_bytes().replace(marker, b'LOOPBACK = "127.0.0.2"')
    assert marker in VENDORED.read_bytes()
    assert mutated != VENDORED.read_bytes()
    assert comparison_result(mutated) is False
