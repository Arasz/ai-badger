"""Every shipped module must import on Python 3.10, the floor engine/requirements.txt implies.

`from __future__ import annotations` defers annotations, so `dict[str, Any]` is safe *there* —
but an executed expression like a module-level alias `X = dict[str, ...]` subscripts the builtin
at import time and raises TypeError below 3.9 (PEP 585). The floor has been 3.9+ since it moved
to 3.10, so this specific pattern can no longer trip the check — it stays as a tripwire in case
the floor is ever lowered again, and pairs with the call-time check below for methods that
*can* still land after today's floor. Local dev runs 3.14 and never notices a floor violation of
either kind on its own; CI's oldest lane does (issue #183's third axis).
"""
import ast
from pathlib import Path

import pytest
from conftest import _test_write

ROOT = Path(__file__).resolve().parent.parent

BUILTIN_GENERICS = {"dict", "list", "set", "tuple", "frozenset", "type"}


def _shipped_sources():
    """Every tracked-shape shipped *.py: engine, tooling, gates, features (not tests/mirrors)."""
    for top in ("engine", "tooling", "gates", "features"):
        yield from sorted((ROOT / top).rglob("*.py"))


class _RuntimeSubscripts(ast.NodeVisitor):
    """Collect builtin-generic subscripts in executed positions, skipping all annotations."""

    def __init__(self):
        self.findings = []

    def visit_AnnAssign(self, node):
        if node.value is not None:  # the annotation itself is deferred; the value executes
            self.visit(node.value)

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)

    def _visit_function(self, node):
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(default)
        for stmt in node.body:
            self.visit(stmt)

    def visit_Subscript(self, node):
        if isinstance(node.value, ast.Name) and node.value.id in BUILTIN_GENERICS:
            self.findings.append(node.lineno)
        self.generic_visit(node)


def _runtime_builtin_generic_lines(path: Path):
    visitor = _RuntimeSubscripts()
    visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
    return visitor.findings


@pytest.mark.parametrize("path", _shipped_sources(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_builtin_generic_subscript_executes_at_import(path):
    lines = _runtime_builtin_generic_lines(path)
    assert not lines, (
        f"{path.relative_to(ROOT)} subscripts a builtin generic at runtime on line(s) {lines}; "
        f"that raises TypeError below Python 3.9 — use typing.Dict/List or defer the expression"
    )


def test_the_checker_itself_can_fail(tmp_path):
    probe = tmp_path / "probe.py"
    _test_write(probe, "from __future__ import annotations\nAlias = dict[str, int]\n", encoding="utf-8")
    assert _runtime_builtin_generic_lines(probe) == [2]


# ── methods that did not exist on the floor ─────────────────────────────────────
#
# The subscript check above catches a TypeError at *import*. A too-new method call fails at
# *call* time instead, so it passes import, passes a local 3.14 run, and fails only in CI's
# oldest lane — which is exactly how `str.removesuffix` (3.9+, and 3.9 was still newer than the
# floor at the time) reached a pull request from this repo on 2026-08-01. Same floor, different
# failure mode, so it needs its own check. The floor moved to 3.10 on 2026-08-15, which is why
# `removesuffix`/`removeprefix` (3.9+) are no longer listed below — they are within the floor now.

# name -> the version that introduced it. Only methods newer than today's 3.10 floor belong
# here. Method calls only: a same-named method on someone else's class would be a false
# positive (e.g. `ast.walk` is a module function, not `pathlib.Path.walk` (3.12+), and has
# existed since 3.4 — do not add "walk" here without checking for collisions first), which is
# why the message says "if this is not the type that added it". Empty for now: nothing in this
# codebase currently calls a method introduced after the floor.
METHODS_ADDED_AFTER_3_10 = {}


def _late_method_calls(path: Path, banned=METHODS_ADDED_AFTER_3_10):
    """(line, name) for every attribute call naming a method in *banned*.

    *banned* defaults to the production floor list but is injectable so the mechanism test
    below does not need a real post-floor stdlib method to exercise the detector.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in banned:
                found.append((node.lineno, node.func.attr))
    return found


@pytest.mark.parametrize("path", _shipped_sources(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_method_newer_than_the_floor_is_called(path):
    calls = _late_method_calls(path)
    assert not calls, (
        f"{path.relative_to(ROOT)} calls "
        + ", ".join(f"`.{name}()` (Python {METHODS_ADDED_AFTER_3_10[name]}+) on line {line}"
                    for line, name in calls)
        + ". The floor is 3.10, and this fails at call time rather than import, so a local run "
          "on a newer interpreter will not notice. Use an alternative instead. "
          "(If this is not the type that added it, rename the local or add it to an allowlist here.)"
    )


def test_the_method_checker_can_fail(tmp_path):
    """Without this, the check above passes on a repo that simply never calls one.

    Uses a synthetic banned-method name rather than a real post-3.10 stdlib method: the
    production list is empty today (nothing in this codebase is known to violate the current
    floor), and inventing a real one here would make this test's correctness depend on
    guessing right about a future Python release instead of on the detector's own logic.
    """
    probe = tmp_path / "probe.py"
    _test_write(probe, "x.frobnicate()\n", encoding="utf-8")

    assert _late_method_calls(probe, banned={"frobnicate": "9999.9"}) == [(1, "frobnicate")]
