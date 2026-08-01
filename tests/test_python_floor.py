"""Every shipped module must import on Python 3.8, the floor engine/requirements.txt implies.

`from __future__ import annotations` defers annotations, so `dict[str, Any]` is safe *there* —
but an executed expression like a module-level alias `X = dict[str, ...]` subscripts the builtin
at import time and raises TypeError on 3.8. Local dev runs 3.14 and never notices; CI's 3.8 lane
does (issue #183's third axis). This test is the local tripwire.
"""
import ast
from pathlib import Path

import pytest

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
        f"that raises TypeError on Python 3.8 — use typing.Dict/List or defer the expression"
    )


def test_the_checker_itself_can_fail(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("from __future__ import annotations\nAlias = dict[str, int]\n",
                     encoding="utf-8")
    assert _runtime_builtin_generic_lines(probe) == [2]


# ── methods that did not exist on 3.8 ───────────────────────────────────────────
#
# The subscript check above catches a TypeError at *import*. A 3.9-only method call fails at
# *call* time instead, so it passes import, passes a local 3.14 run, and fails only in CI's 3.8
# lane — which is exactly how `str.removesuffix` reached a pull request from this repo on
# 2026-08-01. Same floor, different failure mode, so it needs its own check.

# name -> the version that introduced it. Method calls only: a same-named method on someone
# else's class would be a false positive, which is why the message says "if this is not str".
METHODS_ADDED_AFTER_3_8 = {
    "removesuffix": "3.9",
    "removeprefix": "3.9",
}


def _late_method_calls(path: Path):
    """(line, name) for every attribute call naming a method added after the floor."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in METHODS_ADDED_AFTER_3_8:
                found.append((node.lineno, node.func.attr))
    return found


@pytest.mark.parametrize("path", _shipped_sources(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_method_newer_than_the_floor_is_called(path):
    calls = _late_method_calls(path)
    assert not calls, (
        f"{path.relative_to(ROOT)} calls "
        + ", ".join(f"`.{name}()` (Python {METHODS_ADDED_AFTER_3_8[name]}+) on line {line}"
                    for line, name in calls)
        + ". The floor is 3.8, and this fails at call time rather than import, so a local run "
          "on a newer interpreter will not notice. Use slicing or a conditional instead. "
          "(If this is not a str, rename the local or add it to an allowlist here.)"
    )


def test_the_method_checker_can_fail(tmp_path):
    """Without this, the check above passes on a repo that simply never calls one."""
    probe = tmp_path / "probe.py"
    probe.write_text('x = "ab^{}".removesuffix("^{}")\n', encoding="utf-8")

    assert _late_method_calls(probe) == [(1, "removesuffix")]
