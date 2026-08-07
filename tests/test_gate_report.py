"""Tests for gates/gate_report.py: the one finding shape the path/line/message gates print.

Three gates hand-rolled `Problem` and its `location()`, and the copies had already drifted —
deps_guard dropped the line-less fallback and printed `engine/requirements.txt:0` for a file
that has no line 0. The other three gates report different things and are deliberately not
here (release_guard and tdd_guard print paths, scaffold_freshness_guard prints verdicts).
"""
from __future__ import annotations

import pytest

SHARED_SHAPE_GATES = ("deps_guard", "docs_guard", "shipped_paths_guard")
OTHER_GATES = ("release_guard", "tdd_guard", "scaffold_freshness_guard")


@pytest.fixture(name="gates")
def _gates(load_script):
    return {name: load_script(f"gates/{name}.py") for name in SHARED_SHAPE_GATES}


def test_the_three_path_line_message_gates_share_one_problem_type(gates):
    """Three copies is how the fallback went missing from one of them."""
    types = {gate.Problem for gate in gates.values()}

    assert len(types) == 1
    assert types.pop().__module__ == "gate_report"


@pytest.mark.parametrize("name", SHARED_SHAPE_GATES)
def test_a_finding_with_no_line_renders_as_just_the_path(gates, name):
    """`engine/requirements.txt:0` points at a line that cannot exist."""
    assert gates[name].Problem("engine/requirements.txt", 0, "gone").location() == \
           "engine/requirements.txt"


@pytest.mark.parametrize("name", SHARED_SHAPE_GATES)
def test_a_finding_with_a_line_renders_as_path_colon_line(gates, name):
    assert gates[name].Problem("engine/x.py", 12, "bad").location() == "engine/x.py:12"


def test_deps_guard_names_a_missing_requirements_file_without_a_line_number(
        load_script, tmp_path, capsys,
):
    """End-to-end: the drifted copy printed the bogus line to the operator, not just in a unit."""
    deps_guard = load_script("gates/deps_guard.py")
    (tmp_path / "engine").mkdir()

    rc = deps_guard.check(tmp_path)

    out = capsys.readouterr().out
    assert rc == 1
    assert "engine/requirements.txt:0" not in out
    assert "engine/requirements.txt" in out


def test_report_prints_the_headline_then_every_finding_then_the_remediation(load_script, capsys):
    gate_report = load_script("gates/gate_report.py")
    problems = [gate_report.Problem("a.py", 3, "first"), gate_report.Problem("b.txt", 0, "second")]

    rc = gate_report.report("TWO THINGS WRONG:", problems, "Fix them.")

    lines = capsys.readouterr().out.splitlines()
    assert rc == 1
    assert lines == ["TWO THINGS WRONG:", "    a.py:3  first", "    b.txt  second", "Fix them."]


@pytest.mark.parametrize("name", OTHER_GATES)
def test_the_other_gates_are_left_alone(load_script, name):
    """They do not report path/line/message; forcing them into it would serve nobody (D5)."""
    assert not hasattr(load_script(f"gates/{name}.py"), "Problem")