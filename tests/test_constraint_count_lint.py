"""Tests for constraint_count_lint.py: counts invariants in instruction files.

Rule 8B: long negative instruction lists are brittle.  This script counts bullet
points under the 'Non-negotiable invariants' section and warns when the count
exceeds a configurable threshold (default 35).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _test_write

SCRIPT = Path(__file__).resolve().parents[1] / (
    "features/common/skills/maintain-agent-instructions/scripts/constraint_count_lint.py"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_instruction_file(tmp_path: Path, body: str, name: str = "CLAUDE.md") -> Path:
    path = tmp_path / name
    _test_write(path, body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Helpers loaded via load_script for unit-level assertions
# ---------------------------------------------------------------------------

@pytest.fixture(name="lint")
def _lint(load_script):
    return load_script(
        "features/common/skills/maintain-agent-instructions/scripts/constraint_count_lint.py"
    )


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

INVARIANTS_TEMPLATE = """\
# Project

Some preamble.

## Non-negotiable invariants

{bullets}

## Next section

More text.
"""


def _make_bullets(n: int) -> str:
    return "\n".join(f"- **Invariant {i}** — description {i}." for i in range(1, n + 1))


def test_count_returns_zero_for_empty_section(lint, tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=""),
    )

    assert lint.count_invariants(path) == 0


def test_count_returns_number_of_bullet_points(lint, tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(5)),
    )

    assert lint.count_invariants(path) == 5


def test_count_ignores_indented_continuation_lines(lint, tmp_path):
    """Lines like `  → .ai-badger/invariants/...` are not new invariants."""
    body = INVARIANTS_TEMPLATE.format(
        bullets="- **One** — first.\n  → .ai-badger/invariants/one.md\n- **Two** — second.\n  → .ai-badger/invariants/two.md"
    )
    path = _write_instruction_file(tmp_path, body)

    assert lint.count_invariants(path) == 2


def test_count_stops_at_next_heading(lint, tmp_path):
    """Only bullets under the invariants heading are counted."""
    body = """\
## Non-negotiable invariants

- **A** — alpha.

## Commands

- **B** — beta.
"""
    path = _write_instruction_file(tmp_path, body)

    assert lint.count_invariants(path) == 1


def test_count_handles_no_invariants_section(lint, tmp_path):
    """A file with no invariants section returns 0."""
    path = _write_instruction_file(tmp_path, "# Just a heading\n\nSome text.\n")

    assert lint.count_invariants(path) == 0


def test_count_handles_file_not_found(lint):
    with pytest.raises(FileNotFoundError):
        lint.count_invariants(Path("/nonexistent/CLAUDE.md"))


# ---------------------------------------------------------------------------
# Threshold / verdict
# ---------------------------------------------------------------------------

def test_under_threshold_passes(lint, tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(10)),
    )

    result = lint.check(path, threshold=30)

    assert result.passed is True
    assert result.count == 10
    assert result.threshold == 30


def test_at_threshold_passes(lint, tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(30)),
    )

    result = lint.check(path, threshold=30)

    assert result.passed is True
    assert result.count == 30


def test_over_threshold_fails(lint, tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(31)),
    )

    result = lint.check(path, threshold=30)

    assert result.passed is False
    assert result.count == 31
    assert result.threshold == 30


def test_custom_threshold_is_respected(lint, tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(5)),
    )

    result = lint.check(path, threshold=3)

    assert result.passed is False
    assert result.count == 5
    assert result.threshold == 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_exits_zero_when_under_threshold(tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(5)),
    )

    done = _run(str(path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "5" in done.stdout


def test_cli_exits_one_when_over_threshold(tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(36)),
    )

    done = _run(str(path))

    assert done.returncode == 1
    assert "36" in done.stdout
    assert "35" in done.stdout


def test_cli_accepts_custom_threshold(tmp_path):
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(5)),
    )

    done = _run(str(path), "--threshold", "3")

    assert done.returncode == 1
    assert "5" in done.stdout


def test_cli_exits_one_on_missing_file():
    done = _run("/nonexistent/CLAUDE.md")

    assert done.returncode == 1
    assert "not found" in done.stderr.lower() or "error" in done.stderr.lower()


def test_cli_works_with_copilot_instructions(tmp_path):
    """The script should also work with copilot-instructions.md files."""
    path = _write_instruction_file(
        tmp_path,
        INVARIANTS_TEMPLATE.format(bullets=_make_bullets(3)),
        name="copilot-instructions.md",
    )

    done = _run(str(path))

    assert done.returncode == 0, done.stdout + done.stderr


def test_this_repository_invariants_are_within_threshold(root):
    """The real CLAUDE.md should not exceed the default threshold."""
    claude = root / "CLAUDE.md"
    if not claude.exists():
        pytest.skip("CLAUDE.md not found at repo root")

    done = _run(str(claude))

    assert done.returncode == 0, (
        f"CLAUDE.md has too many invariants:\n{done.stdout}"
    )
