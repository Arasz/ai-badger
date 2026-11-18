"""Diff hunk map and lint ingest for review-flow (stdlib only).

`parse_diff` maps each changed path to the RIGHT-side line ranges GitHub accepts
for inline comments; `parse_lint` turns generic `path:line[:col]: message` output
into repo-relative findings.
"""
from __future__ import annotations

import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_LINT = re.compile(
    r"^(?P<path>(?:[A-Za-z]:)?[^:]+?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<message>.*)$")
_KIND_BY_TOKEN = (
    ("unused-", "dead_code"),
    ("unused ", "dead_code"),
    ("docstring", "docs"),
)


def _strip_side(path: str) -> str:
    path = path.strip().strip('"')
    return path[2:] if path[:2] in ("a/", "b/") else path


def _header_path(line: str) -> str | None:
    """Return the new-side path of a `diff --git a/x b/y` line."""
    _, sep, tail = line.rpartition(" b/")
    return tail.strip('"') if sep else None


def parse_diff(text: str) -> dict[str, list[tuple[int, int]]]:
    """Map path to the RIGHT-side (new file) line ranges that accept inline comments.

    Added and context lines inside hunks count; deleted, binary, mode-only and
    pure-rename files have no entry.
    """
    hunks: dict[str, list[tuple[int, int]]] = {}
    path: str | None = None
    old_left = new_left = 0
    for line in text.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("\\"):
                continue
            if line.startswith("+"):
                new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            else:
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("diff --git "):
            path = _header_path(line)
        elif line.startswith("+++ "):
            target = line[4:].strip()
            if target != "/dev/null":
                path = _strip_side(target)
        elif (match := _HUNK.match(line)) and path is not None:
            old_left = int(match.group(2) or 1) if match.group(2) != "0" else 0
            new_count = int(match.group(4)) if match.group(4) is not None else 1
            new_left = new_count
            if new_count > 0:
                start = int(match.group(3))
                hunks.setdefault(path, []).append((start, start + new_count - 1))
    return hunks


def in_diff(hunks: dict[str, list[tuple[int, int]]], path: str, line: int) -> bool:
    """True when `path:line` lies on the RIGHT side of some hunk."""
    return any(start <= line <= end for start, end in hunks.get(path, ()))


def _relative(path: str, root: str) -> str:
    path = path.replace("\\", "/")
    base = root.replace("\\", "/").rstrip("/")
    if base and path.lower().startswith(base.lower() + "/"):
        path = path[len(base) + 1:]
    while path.startswith("./"):
        path = path[2:]
    return path


def _kind(message: str) -> str:
    lowered = message.lower()
    for token, kind in _KIND_BY_TOKEN:
        if token in lowered:
            return kind
    return "style"


def parse_lint_counted(text: str, root: str) -> tuple[list[dict], int]:
    """Parse lint output into findings; also return how many non-blank lines did not match."""
    findings: list[dict] = []
    skipped = 0
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        match = _LINT.match(stripped)
        if not match:
            skipped += 1
            continue
        message = match.group("message").strip()
        col = match.group("col")
        findings.append({
            "path": _relative(match.group("path"), root),
            "line": int(match.group("line")),
            "col": int(col) if col is not None else None,
            "message": message,
            "kind": _kind(message),
        })
    return findings, skipped


def parse_lint(text: str, root: str) -> list[dict]:
    """Findings from lint output: {path (repo-relative, '/'), line, col|None, message, kind}."""
    return parse_lint_counted(text, root)[0]
