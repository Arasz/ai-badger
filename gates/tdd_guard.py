#!/usr/bin/env python3
"""Fail when shipped code changed since `--base` and no test file changed with it.

"TDD is mandatory" is a non-negotiable invariant whose siblings all have mechanical
backing (release_guard.py, version_sync.py --check, index_build.py --check); this one had
none (review F-41). The gate is deliberately a *signal*, not a proof: nothing here can tell
a real test from an empty one. It checks the one thing a machine can — that a change to
executable code touched tests at all.

Scope: .py and .mjs under engine/, tooling/, features/ and gates/, plus shipped pi
TypeScript under features/pi/adjustments/ (D6) — the pi adapter has no .py/.mjs source at
all, so excluding .ts left its 4 shipped files with no gate coverage. Catalog JSON is
covered by `validate.py --all`, and documentation by review, so neither counts as code here.

Diffed against `git merge-base <base> HEAD`, not `<base>` directly (L8-2): once `<base>`
(typically origin/main) has moved on, diffing straight against its tip shows main's own
later changes — including its own test files — as differences from the branch's working
tree, so a branch that changes code with no test of its own could read as covered.

Only `--diff-filter=AMR` counts as a test change (R43): a deleted test must not satisfy the
gate, while a renamed-and-edited test still does.

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

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

CODE_ROOTS = ("engine/", "tooling/", "features/", "gates/")
CODE_SUFFIXES = (".py", ".mjs")
PI_CODE_ROOT = "features/pi/adjustments/"
PI_TEST_ROOT = "features/pi/tests/"
PI_TEST_SUFFIX = ".test.ts"
TEST_PREFIX = "tests/"
SKIP_MARKER = "[no-tests]"


def _git(root: Path, *args: str) -> str:
    proc = bl.run_git(list(args), root)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip() or 'failed'}")
    return proc.stdout


def merge_base(root: Path, base: str) -> str:
    """The commit `base` and HEAD both descend from — the real branch point (L8-2)."""
    return _git(root, "merge-base", base, "HEAD").strip()


def is_code(path: str) -> bool:
    """True for an executable file this repo ships — not catalog data, not documentation."""
    if path.startswith(CODE_ROOTS) and path.endswith(CODE_SUFFIXES):
        return True
    return path.startswith(PI_CODE_ROOT) and path.endswith(".ts")


def is_test(path: str) -> bool:
    """True for a path this repo treats as a test, in either test tree."""
    if path.startswith(TEST_PREFIX):
        return True
    return path.startswith(PI_TEST_ROOT) and path.endswith(PI_TEST_SUFFIX)


def changed_files(root: Path, merge_point: str) -> List[str]:
    """Files differing between `merge_point` and the working tree, including untracked ones.

    `git diff` never lists an untracked file, so without the second call a brand-new
    script — the most likely thing to lack a test — would read as no change at all.
    """
    tracked = _git(root, "diff", "--name-only", merge_point).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({p for p in tracked + untracked if p.strip()})


def changed_test_files(root: Path, merge_point: str) -> List[str]:
    """Paths that count as a *test* change since `merge_point` (R43).

    Tracked changes are filtered to `--diff-filter=AMR` (with rename detection forced via
    `-M`): an add, a modify, or a rename count; a plain delete does not, so removing a test
    can never satisfy the gate. Untracked files are unfiltered — a brand-new test file has
    no status to filter on, and is trivially an addition.
    """
    tracked = _git(root, "diff", "--name-only", "-M", "--diff-filter=AMR",
                    merge_point).splitlines()
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
        merge_point = merge_base(root, base)
    except RuntimeError as exc:
        print(f"TDD GUARD COULD NOT RUN: {exc}")
        return 1

    try:
        changed = changed_files(root, merge_point)
        test_changed = changed_test_files(root, merge_point)
    except RuntimeError as exc:
        print(f"TDD GUARD COULD NOT RUN: {exc}")
        return 1

    code = [p for p in changed if is_code(p)]
    if not code:
        print("no shipped code changed — PASS")
        return 0
    if any(is_test(p) for p in test_changed):
        print(f"{len(code)} code file(s) changed alongside a test — PASS")
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
