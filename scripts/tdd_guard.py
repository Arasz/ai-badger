#!/usr/bin/env python3
"""Fail when shipped code changed since `--base` and no test file changed with it.

"TDD is mandatory" is a non-negotiable invariant whose siblings all have mechanical
backing (release_guard.py, version_sync.py --check, index_build.py --check); this one had
none (review F-41). The gate is deliberately a *signal*, not a proof: nothing here can tell
a real test from an empty one. It checks the one thing a machine can — that a change to
executable code touched tests at all.

Scope: .py and .mjs under scripts/ and features/. Catalog JSON is covered by
`validate.py --all`, and documentation by review, so neither counts as code here.

Escape hatch: put `[no-tests]` in a commit message in the range. It is printed, so an
unjustified one is visible in CI output rather than silent.

Usage: tdd_guard.py [--base <ref>] [--root <dir>]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl

CODE_ROOTS = ("scripts/", "features/")
CODE_SUFFIXES = (".py", ".mjs")
TEST_PREFIX = "tests/"
SKIP_MARKER = "[no-tests]"


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                           check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip() or 'failed'}")
    return proc.stdout


def is_code(path: str) -> bool:
    """True for an executable file this repo ships — not catalog data, not documentation."""
    return path.startswith(CODE_ROOTS) and path.endswith(CODE_SUFFIXES)


def changed_files(root: Path, base: str) -> List[str]:
    """Files differing between `base` and the working tree, including untracked ones.

    `git diff` never lists an untracked file, so without the second call a brand-new
    script — the most likely thing to lack a test — would read as no change at all.
    """
    tracked = _git(root, "diff", "--name-only", base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({p for p in tracked + untracked if p.strip()})


def skip_marker(root: Path, base: str) -> str:
    """The first commit subject in the range carrying the escape marker, or ""."""
    out = _git(root, "log", "--format=%s%n%b", f"{base}..HEAD")
    for line in out.splitlines():
        if SKIP_MARKER in line:
            return line.strip()
    return ""


def check(root: Path, base: str) -> int:
    """Run the gate; print its verdict; return 0 pass / 1 fail."""
    try:
        changed = changed_files(root, base)
    except RuntimeError as exc:
        print(f"TDD GUARD COULD NOT RUN: {exc}")
        return 1

    code = [p for p in changed if is_code(p)]
    if not code:
        print("no shipped code changed — PASS")
        return 0
    if any(p.startswith(TEST_PREFIX) for p in changed):
        print(f"{len(code)} code file(s) changed alongside tests/ — PASS")
        return 0

    marker = skip_marker(root, base)
    if marker:
        print(f"{len(code)} code file(s) changed with no test change, allowed by "
              f"{SKIP_MARKER}: {marker}")
        return 0

    print(f"{len(code)} code file(s) changed since {base} and nothing under {TEST_PREFIX} did:")
    for path in code:
        print(f"    - {path}")
    print("Write the failing test first. If this change genuinely cannot have one, say so in "
          f"a commit message with {SKIP_MARKER}.")
    return 1


def main(argv=None) -> int:
    """CLI entry point: compare the working tree against --base (default: origin/main)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="origin/main", help="Ref to compare against")
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()
    return check(root, args.base)


if __name__ == "__main__":
    raise SystemExit(main())
