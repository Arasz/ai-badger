"""Vendoring gate for the skill-side Jev client copy.

`features/common/skills/task-decomposition/scripts/openrouter_client.py` must be a byte copy of
`features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py` with exactly one changed
line: the test-base env name (`AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE` →
`AI_BADGER_JEV_TEST_OPENROUTER_BASE`). The comparison normalizes that one line and byte-compares
everything else; a mutation of any second line turns it red (witnessed by
`test_comparator_flags_a_second_changed_line`).
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


def test_vendored_copy_is_byte_identical_except_the_one_sanctioned_line():
    assert VENDORED.is_file(), f"{VENDORED} does not exist — the client was never vendored"
    assert VENDORED.read_bytes() == normalized_source()


def test_the_sanctioned_line_is_the_jev_name_and_the_rule_is_kept():
    vendored = VENDORED.read_text(encoding="utf-8")
    assert vendored.count(VENDORED_LINE) == 1
    assert SOURCE_LINE not in vendored
    # The loopback-only rule the one-line change must not disturb.
    assert 'TEST_KEY_PREFIX = "sk-test-"' in vendored
    assert 'LOOPBACK = "127.0.0.1"' in vendored
    assert "never a silent switch to production" in vendored


def test_comparator_flags_a_second_changed_line(tmp_path):
    """Mutation proof for the comparator itself: any second line difference is caught."""
    mutated = bytearray(VENDORED.read_bytes())
    marker = b'LOOPBACK = "127.0.0.1"'
    assert marker in mutated
    mutated = bytes(mutated).replace(marker, b'LOOPBACK = "127.0.0.2"')
    assert mutated != VENDORED.read_bytes()
    target = tmp_path / "openrouter_client.py"
    target.write_bytes(mutated)
    assert target.read_bytes() != normalized_source()
