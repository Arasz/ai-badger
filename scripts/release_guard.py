#!/usr/bin/env python3
"""Fail CI if the shipped surface changed since the last release without a VERSION bump.

Kept as its own script rather than a mode on version_sync.py: it is git-shaped (tags, diffs)
rather than JSON-shaped, has its own failure mode unrelated to the three version literals, and
this repo already keeps single-purpose scripts side by side (index_build.py vs. validate.py
both touch index.json for different reasons).

Logic (see docs/adr/0001-versioning-and-release-model.md, decision 2):
  1. Find the last release tag matching `ai-badger--v*`, by highest SEMVER — not latest by
     date, not lexicographic string order (`ai-badger--v0.10.0` must beat `ai-badger--v0.9.0`).
  2. No such tag -> PASS. A fresh clone or a repo before its first release is not blocked.
  3. Diff the working tree against that tag, limited to the shipped surface: skills/,
     features/, scripts/, schemas/, index.json.
  4. If anything there changed, VERSION must differ from the tag's version, or this fails.

Compared against the LAST RELEASE TAG, never the previous commit — load-bearing per the ADR,
so several PRs can land at one unreleased version without inflating it each time.

CI GOTCHA: `actions/checkout` defaults to fetch-depth: 1 and does not fetch tags. Under that
default, step 1 above finds no tags and this script takes the "no release tag" PASS path —
silently, making the guard a no-op that still looks green. The workflow MUST set
`fetch-depth: 0` (or explicitly fetch tags). To make a misconfigured CI visibly wrong rather
than silently permissive, the no-tag path always prints the literal string
"NO RELEASE TAG FOUND" — grep CI logs for it; if it appears on a repo that HAS releases, tags
were not fetched.

Usage: release_guard.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl

TAG_PATTERN = re.compile(r"^ai-badger--v(\d+)\.(\d+)\.(\d+)$")
SHIPPED_PATHS = ["skills", "features", "scripts", "schemas", "index.json"]


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                           check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _semver(tag: str) -> Optional[Tuple[int, int, int]]:
    m = TAG_PATTERN.match(tag)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def latest_release_tag(root: Path) -> Optional[str]:
    """Return the ai-badger--v* tag with the highest semver, or None if none exist."""
    out = _git(root, "tag", "-l", "ai-badger--v*")
    candidates = [(v, t) for t in out.splitlines() if t.strip()
                  for v in [_semver(t.strip())] if v is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda vt: vt[0])
    return candidates[-1][1]


def tag_version(tag: str) -> str:
    """Extract the "x.y.z" version encoded in an ai-badger--v* tag name."""
    m = TAG_PATTERN.match(tag)
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def changed_shipped_paths(root: Path, tag: str) -> List[str]:
    """Return sorted shipped-surface paths that differ between `tag` and the working tree."""
    out = _git(root, "diff", "--name-only", tag, "--", *SHIPPED_PATHS)
    return sorted(p for p in out.splitlines() if p.strip())


def check(root: Path) -> int:
    """Run the release guard; print its verdict; return 0 pass / 1 fail."""
    tag = latest_release_tag(root)
    if tag is None:
        print("NO RELEASE TAG FOUND (ai-badger--v*) — nothing to guard against; PASS. "
              "If this repo has releases and you did not expect this, actions/checkout needs "
              "fetch-depth: 0 (tags are not fetched by default).")
        return 0

    released_version = tag_version(tag)
    changed = changed_shipped_paths(root, tag)
    if not changed:
        print(f"no shipped-surface changes since {tag} — PASS")
        return 0

    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current_version != released_version:
        print(f"shipped surface changed since {tag} and VERSION was bumped "
              f"({released_version} -> {current_version}) — PASS")
        return 0

    print(f"shipped surface changed since {tag} but VERSION is still {current_version}:")
    for p in changed:
        print(f"    - {p}")
    print("bump VERSION")
    return 1


def main(argv=None) -> int:
    """CLI entry point: run the release guard against --root (default: auto-detected)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main())
