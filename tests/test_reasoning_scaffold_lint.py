"""Rule 6B: reasoning-scaffold linter — scans instruction files for CoT anti-patterns.

Anti-patterns detected:
- "think step by step"
- "let's think step by step"
- "analyze this carefully"
- "produce a plan before responding"
- "step-by-step plan"
- "chain of thought" (when used as an instruction, not a reference)
"""
from __future__ import annotations

import json

from conftest import _test_write

SCRIPT = "features/common/skills/maintain-agent-instructions/scripts/reasoning_scaffold_lint.py"


# ── helpers ──────────────────────────────────────────────────────────────────

def _run(load_script, args: list[str]):
    """Run the linter's main() with the given argv, returning (exit_code, stdout, stderr)."""
    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    mod = load_script(SCRIPT)
    old_argv = sys.argv[:]
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        sys.argv = ["reasoning_scaffold_lint", *args]
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            code = mod.main()
    finally:
        sys.argv = old_argv
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


# ── exit-code behaviour ─────────────────────────────────────────────────────

def test_clean_file_exits_zero(tmp_path, load_script):
    """A file with no anti-patterns should exit 0."""
    f = tmp_path / "clean.md"
    _test_write(f, "# Project\n\nUse guard clauses.\n")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 0


def test_file_with_anti_pattern_exits_one(tmp_path, load_script):
    """A file containing an anti-pattern should exit 1."""
    f = tmp_path / "bad.md"
    _test_write(f, "# Instructions\n\nThink step by step before answering.\n")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 1


def test_directory_scanning_exits_one_when_any_file_has_match(tmp_path, load_script):
    """Scanning a directory should exit 1 if any file in it has an anti-pattern."""
    good = tmp_path / "good.md"
    bad = tmp_path / "bad.md"
    _test_write(good, "# Clean\n")
    _test_write(bad, "Let's think step by step.\n")

    code, _, _ = _run(load_script, [str(tmp_path)])
    assert code == 1


def test_directory_scanning_exits_zero_when_all_clean(tmp_path, load_script):
    """Scanning a directory of clean files should exit 0."""
    _test_write(tmp_path / "a.md", "# A\n")
    _test_write(tmp_path / "b.json", '{"prompt": "be helpful"}\n')

    code, _, _ = _run(load_script, [str(tmp_path)])
    assert code == 0


# ── individual anti-patterns ────────────────────────────────────────────────

def test_detects_think_step_by_step(tmp_path, load_script):
    f = tmp_path / "x.md"
    _test_write(f, "Please think step by step.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    assert "think step by step" in stdout.lower()


def test_detects_lets_think_step_by_step(tmp_path, load_script):
    f = tmp_path / "x.md"
    _test_write(f, "Let's think step by step about this.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    assert "let's think step by step" in stdout.lower()


def test_detects_analyze_this_carefully(tmp_path, load_script):
    f = tmp_path / "x.md"
    _test_write(f, "Analyze this carefully before proceeding.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    assert "analyze this carefully" in stdout.lower()


def test_detects_produce_a_plan_before_responding(tmp_path, load_script):
    f = tmp_path / "x.md"
    _test_write(f, "You should produce a plan before responding.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    assert "produce a plan before responding" in stdout.lower()


def test_detects_step_by_step_plan(tmp_path, load_script):
    f = tmp_path / "x.md"
    _test_write(f, "Create a step-by-step plan for the task.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    assert "step-by-step plan" in stdout.lower()


def test_detects_chain_of_thought_as_instruction(tmp_path, load_script):
    """'chain of thought' used as an instruction directive should be flagged."""
    f = tmp_path / "x.md"
    _test_write(f, "Use chain of thought reasoning when answering.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    assert "chain of thought" in stdout.lower()


def test_chain_of_thought_reference_not_flagged(tmp_path, load_script):
    """A neutral reference to 'chain of thought' (e.g. discussing the concept) should pass."""
    f = tmp_path / "x.md"
    _test_write(f, "Chain-of-thought prompting was introduced in Wei et al. (2022).\n")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 0


# ── output format ────────────────────────────────────────────────────────────

def test_output_format_is_file_line_match(tmp_path, load_script):
    """Each finding should be printed as file:line:match."""
    f = tmp_path / "bad.md"
    _test_write(f, "Line 1 ok.\nThink step by step here.\nLine 3 ok.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    # Should contain the file path, line number, and the matched text
    assert str(f) in stdout
    assert ":2:" in stdout


def test_multiple_matches_in_one_file(tmp_path, load_script):
    """Multiple anti-patterns in one file should all be reported."""
    f = tmp_path / "bad.md"
    _test_write(f, "Think step by step.\nAnalyze this carefully.\n")

    code, stdout, _ = _run(load_script, [str(f)])
    assert code == 1
    lines = [l for l in stdout.strip().splitlines() if l.strip()]
    assert len(lines) >= 2


# ── file-type filtering ─────────────────────────────────────────────────────

def test_scans_md_files(tmp_path, load_script):
    f = tmp_path / "instructions.md"
    _test_write(f, "Think step by step.\n")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 1


def test_scans_json_files(tmp_path, load_script):
    f = tmp_path / "prompt.json"
    _test_write(f, '{"system": "Think step by step."}\n')

    code, _, _ = _run(load_script, [str(f)])
    assert code == 1


def test_ignores_non_md_json_files(tmp_path, load_script):
    """Files that are not .md or .json should be skipped."""
    f = tmp_path / "notes.txt"
    _test_write(f, "Think step by step.\n")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 0


def test_directory_scan_skips_non_md_json(tmp_path, load_script):
    """When scanning a directory, only .md and .json files should be checked."""
    _test_write(tmp_path / "readme.txt", "Think step by step.\n")
    _test_write(tmp_path / "clean.md", "# Clean\n")

    code, _, _ = _run(load_script, [str(tmp_path)])
    assert code == 0


# ── case sensitivity ─────────────────────────────────────────────────────────

def test_case_insensitive_detection(tmp_path, load_script):
    """Anti-patterns should be detected regardless of case."""
    f = tmp_path / "x.md"
    _test_write(f, "THINK STEP BY STEP.\n")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 1


# ── edge cases ───────────────────────────────────────────────────────────────

def test_empty_file_exits_zero(tmp_path, load_script):
    f = tmp_path / "empty.md"
    _test_write(f, "")

    code, _, _ = _run(load_script, [str(f)])
    assert code == 0


def test_nonexistent_path_exits_zero(tmp_path, load_script):
    """A path that doesn't exist should be skipped gracefully."""
    code, _, _ = _run(load_script, [str(tmp_path / "nope.md")])
    assert code == 0


def test_no_arguments_exits_zero(load_script):
    """No arguments should print usage and exit 0."""
    code, stdout, _ = _run(load_script, [])
    assert code == 0
    assert "usage" in stdout.lower() or "usage" in (stdout + "").lower()


def test_multiple_file_arguments(load_script, tmp_path):
    """Passing multiple file paths should check all of them."""
    good = tmp_path / "good.md"
    bad = tmp_path / "bad.md"
    _test_write(good, "# Clean\n")
    _test_write(bad, "Think step by step.\n")

    code, stdout, _ = _run(load_script, [str(good), str(bad)])
    assert code == 1
    assert str(bad) in stdout
