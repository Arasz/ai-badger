"""The finding shape and failure report shared by the gates that report `path:line: message`.

deps_guard, docs_guard and shipped_paths_guard only. The other three gates report something
else and keep their own output (see tests/test_gate_report.py).
"""
from __future__ import annotations

from typing import Iterable, NamedTuple


class Problem(NamedTuple):
    """One actionable finding: where it is, and what about it fails the gate."""

    path: str
    line: int
    message: str

    def location(self) -> str:
        """`file:line`, or just the file when the finding has no single line."""
        return f"{self.path}:{self.line}" if self.line else self.path


def report(headline: str, problems: Iterable[Problem], remediation: str) -> int:
    """Print the failure verdict — headline, one row per finding, then what to do. Returns 1."""
    print(headline)
    for problem in problems:
        print(f"    {problem.location()}  {problem.message}")
    print(remediation)
    return 1
