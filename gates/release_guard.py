#!/usr/bin/env python3
"""Fail CI if a release went out untagged, or the shipped surface changed without a bump.

Kept as its own script rather than a mode on version_sync.py: it is git-shaped (tags, diffs)
rather than JSON-shaped, has its own failure mode unrelated to the three version literals, and
this repo already keeps single-purpose scripts side by side (index_build.py vs. validate.py
both touch index.json for different reasons).

Logic (see docs/adr/0001-versioning-and-release-model.md, decision 2):
  1. Find the last release tag matching `ai-badger--v*`, by highest SEMVER — not latest by
     date, not lexicographic string order (`ai-badger--v0.10.0` must beat `ai-badger--v0.9.0`).
  2. No such tag -> PASS. A fresh clone or a repo before its first release is not blocked.
  3. Every version with a changelog entry strictly between that tag and VERSION must itself be
     tagged, or this fails. Checked before the diff, and independently of it: a release that
     shipped untagged stays wrong on every later push, including docs-only ones. The version in
     VERSION is exempt — one release in flight is the model (RELEASING.md).
  4. Diff the working tree against that tag, limited to the shipped surface: skills/,
     features/, engine/, tooling/, schemas/, index.json. `gates/` is deliberately absent —
     the repo gates are internal tooling no consumer runs, so a gate-only change needs no bump.
  5. If anything there changed, VERSION must differ from the tag's version, or this fails.

Compared against the LAST RELEASE TAG, never the previous commit — load-bearing per the ADR,
so several PRs can land at one unreleased version without inflating it each time.

CI GOTCHA: `actions/checkout` defaults to fetch-depth: 1 and does not fetch tags. Under that
default, step 1 above finds no tags and this script takes the "no release tag" PASS path —
silently, making the guard a no-op that still looks green. The workflow MUST set
`fetch-depth: 0` (or explicitly fetch tags). To make a misconfigured CI visibly wrong rather
than silently permissive, the no-tag path always prints the literal string
"NO RELEASE TAG FOUND" — grep CI logs for it; if it appears on a repo that HAS releases, tags
were not fetched.

A git command that FAILS is a third outcome, distinct from both "no tags" and "no changes": it
prints "GIT COMMAND FAILED" and exits 1, because empty output from a failed command proves
nothing about the shipped surface (F-10).

Usage: release_guard.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

TAG_PATTERN = re.compile(r"^ai-badger--v(\d+)\.(\d+)\.(\d+)$")
SHIPPED_PATHS = ["skills", "features", "engine", "tooling", "schemas", "index.json"]


class GitCommandFailed(RuntimeError):
    """A git command the guard depends on exited non-zero; its output proves nothing."""

    def __init__(self, args: Tuple[str, ...], stderr: str) -> None:
        self.command = "git " + " ".join(args)
        self.stderr = stderr.strip()
        super().__init__(f"{self.command}: {self.stderr or 'no stderr'}")


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                           check=False)
    if proc.returncode != 0:
        raise GitCommandFailed(args, proc.stderr)
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


def skipped_versions(root: Path, released: str, current: str) -> List[str]:
    """Changelog versions strictly between the last tag and VERSION — documented, never cut.

    The version in VERSION is excluded: one unreleased version in flight is the model
    (RELEASING.md, "Several PRs, one release"). Anything below it never got a tag at all.
    """
    low, high = _semver(f"ai-badger--v{released}"), _semver(f"ai-badger--v{current}")
    if low is None or high is None:
        return []
    found = []
    for entry in (root / "docs" / "changelog").glob("*.md"):
        version = _semver(f"ai-badger--v{entry.name.split('-')[0]}")
        if version is not None and low < version < high:
            found.append(".".join(str(part) for part in version))
    return sorted(found, key=lambda v: _semver(f"ai-badger--v{v}"))


def changed_shipped_paths(root: Path, tag: str) -> List[str]:
    """Return sorted shipped-surface paths that differ between `tag` and the working tree."""
    out = _git(root, "diff", "--name-only", tag, "--", *SHIPPED_PATHS)
    return sorted(p for p in out.splitlines() if p.strip())


def check(root: Path) -> int:
    """Run the release guard; print its verdict; return 0 pass / 1 fail."""
    try:
        return _check(root)
    except GitCommandFailed as exc:
        print(f"GIT COMMAND FAILED ({exc.command}): {exc.stderr or 'no stderr'}")
        print("the guard cannot prove the shipped surface is unchanged — FAIL. A shallow or "
              "partial clone is the usual cause; CI needs fetch-depth: 0.")
        return 1


def _report_skipped(root: Path, released_version: str, current_version: str) -> bool:
    """Print any documented-but-untagged versions; True when at least one exists."""
    skipped = skipped_versions(root, released_version, current_version)
    if not skipped:
        return False
    print(f"UNTAGGED RELEASES: {len(skipped)} version(s) have a changelog entry but no "
          f"ai-badger--v* tag: {', '.join(skipped)}")
    print("each denotes no commit, so no bug report can be pinned to it "
          "(see docs/incidents/2026-07-27-untagged-releases.md)")
    print("tag them at the commit that carried each VERSION, then push the tags:")
    for version in skipped:
        print(f"    git tag -a ai-badger--v{version} <commit> -m 'ai-badger {version}'")
    return True


def _check(root: Path) -> int:
    """The guard proper, assuming every git command it runs succeeds."""
    tag = latest_release_tag(root)
    if tag is None:
        print("NO RELEASE TAG FOUND (ai-badger--v*) — nothing to guard against; PASS. "
              "If this repo has releases and you did not expect this, actions/checkout needs "
              "fetch-depth: 0 (tags are not fetched by default).")
        return 0

    released_version = tag_version(tag)
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    # Checked before the diff: an untagged release is a fact about the repo, not about
    # whether this particular push touched the shipped surface.
    if _report_skipped(root, released_version, current_version):
        return 1

    changed = changed_shipped_paths(root, tag)
    if not changed:
        print(f"no shipped-surface changes since {tag} — PASS")
        return 0

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
