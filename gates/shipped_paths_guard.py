#!/usr/bin/env python3
"""Fail when a machine-specific absolute path ships inside a tracked file.

`.mcp.json` shipped tracked, carrying `cwd` and a hand-added server command that only resolved
on the maintainer's machine (issue #173): `.claude-plugin/plugin.json` carries no file
allowlist, so every tracked file is part of the plugin payload, and nothing inspected that
payload for content that only makes sense on one machine. Same shape as this repository's other
"correct locally, wrong once distributed" defects: the artifact was never examined after the
code that produces it passed review.

Scope: every path `git ls-files` reports — the same list the plugin payload has no allowlist to
narrow — minus:

  * `docs/` (any depth) and root-level `*.md` — a changelog entry or an ADR legitimately quotes a
    real leaked path as the record of an incident (`docs/changelog/0.22.0-portability-and-truth.md`
    does exactly that), the same reason `docs_guard.py`'s RECORD_DIRS exempts them from link
    freshness. Without this, this fix's own changelog entry would fail the gate it adds.
  * `tests/` — an existing policy exemption (`test_gates_layout.py`): a fixture fabricates a
    `/Users/<name>/...` path on purpose to exercise path-handling code, and nothing that installs
    the plugin ever loads a test file as configuration.
  * Anything listed in `.shipped-paths-guard-ignore`, one repo-relative path prefix per line —
    for a case the two rules above get wrong, without reopening either of them.

The pattern is the other half of staying quiet: it requires a real path-shaped segment after
`/Users/`, `/home/` or `<drive>:\\Users\\` (letters, digits, `_.-`), so a placeholder that is
NOT covered by an exempt directory — `/Users/…/.claude/projects/…` (an ellipsis, not a name) in
a shipped skill reference doc — does not match, while a real username does.

Usage: shipped_paths_guard.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, Sequence, Tuple

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

IGNORE_FILE = ".shipped-paths-guard-ignore"
EXEMPT_DIRS = ("docs/", "tests/")
# A generated page is not prose. `docs/` is exempt because a changelog may quote a real leaked
# path as the record of an incident; a review form's `CONFIG.expectedDir` is read by the page's
# own JavaScript and shown to a reviewer as where to save, so a machine path there is a live
# instruction pointing at someone else's home directory. #268 shipped two such files.
GENERATED_PAGE_SUFFIXES = (".html", ".htm")

_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9_.\-]*"
# 1-2 backslashes: a Windows path inside a JSON string value is stored double-escaped
# (`"C:\\Users\\<name>"`), and this guard reads raw text rather than JSON-decoding it.
_WIN_SEP = r"\\{1,2}"
ABS_PATH_RE = re.compile(
    r"(?:/Users/|/home/)" + _SEGMENT
    + r"|[A-Za-z]:" + _WIN_SEP + "Users" + _WIN_SEP + _SEGMENT
)


class Problem(NamedTuple):
    """One actionable finding: where it is, and what leaked."""

    path: str
    line: int
    message: str

    def location(self) -> str:
        """`file:line`, or just the file when the finding has no single line."""
        return f"{self.path}:{self.line}" if self.line else self.path


def exempt_prefixes(root: Path) -> Tuple[str, ...]:
    """Repo-relative path prefixes from `.shipped-paths-guard-ignore`, if it exists."""
    extra: List[str] = []
    ignore = root / IGNORE_FILE
    if ignore.is_file():
        for raw in ignore.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                extra.append(line)
    return tuple(extra)


def is_exempt(rel: str, prefixes: Sequence[str]) -> bool:
    """True when *rel* is documentation, a test, or explicitly listed."""
    if any(rel == p or rel.startswith(p) for p in prefixes):
        return True
    if rel.endswith(GENERATED_PAGE_SUFFIXES):
        return False
    if rel.startswith(EXEMPT_DIRS):
        return True
    if "/" not in rel and rel.endswith(".md"):
        return True
    return False


def tracked_files(root: Path) -> Tuple[List[str], bool]:
    """Every path `git ls-files` reports, and whether the command itself succeeded."""
    proc = subprocess.run(["git", "ls-files"], cwd=str(root), capture_output=True, text=True,
                          check=False)
    if proc.returncode != 0:
        return [], False
    return sorted(line for line in proc.stdout.splitlines() if line), True


def leaks_in_file(root: Path, rel: str) -> List[Problem]:
    """Machine-specific absolute paths found on any line of one tracked file."""
    raw = (root / rel).read_bytes()
    if b"\x00" in raw:
        return []  # binary: not prose, not config a matcher can usefully read
    text = raw.decode("utf-8", errors="replace")
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = ABS_PATH_RE.search(line)
        if match:
            problems.append(Problem(rel, number, f"machine-specific absolute path: {match.group(0)}"))
    return problems


def collect(root: Path) -> Tuple[List[Problem], int]:
    """All findings in the tree, and the number of tracked files scanned."""
    files, ok = tracked_files(root)
    if not ok:
        return ([Problem("git ls-files", 0, "GIT COMMAND FAILED")], 0)

    prefixes = exempt_prefixes(root)
    problems: List[Problem] = []
    scanned = 0
    for rel in files:
        if is_exempt(rel, prefixes):
            continue
        path = root / rel
        if not path.is_file():
            continue  # a tracked path git resolves to a symlink target that is gone locally
        scanned += 1
        problems += leaks_in_file(root, rel)
    return problems, scanned


def check(root: Path) -> int:
    """Run the shipped-paths guard; print its verdict; return 0 pass / 1 fail."""
    problems, scanned = collect(root)
    if not problems:
        print(f"{scanned} tracked file(s) scanned; no machine-specific absolute path found — "
              f"PASS")
        return 0

    print(f"SHIPPED PATH GUARD FAILED: {len(problems)} finding(s) in {scanned} tracked file(s):")
    for problem in problems:
        print(f"    {problem.location()}  {problem.message}")
    print(f"Untrack the file (ship a portable .example alongside it), or — only for a genuine "
          f"exception — list its path prefix in {IGNORE_FILE}.")
    return 1


def main(argv=None) -> int:
    """CLI entry point: run the shipped-paths guard against --root (default: auto-detected)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main())
