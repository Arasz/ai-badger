#!/usr/bin/env python3
"""Rule 6B: reasoning-scaffold linter.

Scans .md and .json instruction files for chain-of-thought anti-patterns that
instruct the model to reason step-by-step rather than producing a direct answer.

Exit 0 — clean (no anti-patterns found).
Exit 1 — one or more anti-patterns found; each printed as file:line:match.

Usage:
    python3 reasoning_scaffold_lint.py <file-or-dir> [<file-or-dir> ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Sequence

# ── anti-patterns ────────────────────────────────────────────────────────────
# Each entry is (compiled_regex, human_readable_label).
# Patterns are case-insensitive and matched per-line.

_PATTERNS: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthink step by step\b", re.IGNORECASE), "think step by step"),
    (re.compile(r"\blet's think step by step\b", re.IGNORECASE), "let's think step by step"),
    (re.compile(r"\banalyze this carefully\b", re.IGNORECASE), "analyze this carefully"),
    (re.compile(r"\bproduce a plan before responding\b", re.IGNORECASE),
     "produce a plan before responding"),
    (re.compile(r"\bstep-by-step plan\b", re.IGNORECASE), "step-by-step plan"),
    # "chain of thought" as an instruction (imperative mood), not a neutral reference.
    # Matches "use chain of thought", "apply chain of thought", "with chain of thought",
    # or bare "chain of thought" at the start of a sentence (imperative).
    # Does NOT match "chain-of-thought" (hyphenated = adjective/reference form).
    (re.compile(
        r"(?:^|\b)(?:use|apply|employ|with|using)\s+chain of thought\b"
        r"|\bchain of thought\s+(?:reasoning|when|to|for)\b",
        re.IGNORECASE,
    ), "chain of thought (as instruction)"),
]

_EXTENSIONS = {".md", ".json"}


class Finding(NamedTuple):
    path: Path
    line: int
    match: str
    label: str


def _scan_file(path: Path) -> List[Finding]:
    """Scan a single file for anti-patterns. Returns a list of Finding."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: List[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, label in _PATTERNS:
            m = pattern.search(line)
            if m:
                findings.append(Finding(path=path, line=lineno, match=m.group(0), label=label))
    return findings


def _collect_files(paths: Sequence[str]) -> List[Path]:
    """Resolve arguments into scannable files (.md, .json)."""
    files: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix.lower() in _EXTENSIONS:
                files.append(p)
        elif p.is_dir():
            for ext in _EXTENSIONS:
                files.extend(sorted(p.rglob(f"*{ext}")))
    return files


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns 0 (clean) or 1 (findings)."""
    args = list(argv if argv is not None else sys.argv[1:])

    if not args:
        print("Usage: reasoning_scaffold_lint.py <file-or-dir> [<file-or-dir> ...]")
        return 0

    files = _collect_files(args)
    if not files:
        return 0

    all_findings: List[Finding] = []
    for f in files:
        all_findings.extend(_scan_file(f))

    if not all_findings:
        return 0

    for finding in all_findings:
        print(f"{finding.path}:{finding.line}:{finding.match}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
