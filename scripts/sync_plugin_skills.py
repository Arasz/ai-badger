#!/usr/bin/env python3
"""Sync framework skills into skills/ — the one directory Claude Code reads them from.

Claude Code scans <plugin-root>/skills/ for a plugin's skills and nowhere else (ADR-0008).
This script copies SKILL.md + essential files from features/common/skills/ and
features/claude/skills/ into skills/.

Run after changing skill content, before publishing the plugin.

Usage:
  python3 scripts/sync_plugin_skills.py [--dry-run | --check]
  --check : do not write; exit 1 if any shipped copy diverges from features/.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "skills"

# Which skills ship is declared once, in badger_lib.SKILL_SCOPES; each list is just that
# decision filtered to the stack whose directory holds the skill.
COMMON_SKILLS = bl.default_skills_in(ROOT / "features" / "common" / "skills")
CLAUDE_SKILLS = bl.default_skills_in(ROOT / "features" / "claude" / "skills")

# Files to skip when copying (test files, caches, evals). Shared with the hash used by
# --check so a file that is never copied can never be reported as divergence.
SKIP_PATTERNS = tuple(bl.SKILL_EXCLUDE_PATTERNS)

# Skills whose content another tool owns (code-review-graph): never written, never checked.
MANAGED_EXTERNALLY = {
    "debug-issue",
    "explore-codebase",
    "refactor-safely",
    "review-changes",
}


def _shipped_skills():
    """Yield (name, src, dest) for every skill the plugin ships, minus externally managed ones."""
    for base, names in (
        (ROOT / "features" / "common" / "skills", COMMON_SKILLS),
        (ROOT / "features" / "claude" / "skills", CLAUDE_SKILLS),
    ):
        for name in names:
            if name in MANAGED_EXTERNALLY:
                continue
            yield name, base / name, TARGET / name


def sync_skill(src: Path, dest: Path, dry_run: bool) -> int:
    """Sync one skill directory from src to dest. Returns count of files copied."""
    if not src.is_dir():
        return 0
    if dry_run:
        return 1
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*SKIP_PATTERNS))
    return 1


def check_skill(src: Path, dest: Path):
    """Return the divergence reason for one skill, or None when the shipped copy matches."""
    if not src.is_dir():
        return None
    if not dest.is_dir():
        return "missing"
    excluded = list(SKIP_PATTERNS)
    src_hash = bl.dir_content_hash(src, excluded)["content_hash"]
    dest_hash = bl.dir_content_hash(dest, excluded)["content_hash"]
    if src_hash != dest_hash:
        return "diverged"
    return None


def check_all() -> int:
    """Report every shipped skill whose .claude/ copy differs from features/. 1 if any."""
    checked = 0
    out_of_sync = 0
    for name, src, dest in _shipped_skills():
        if not src.is_dir():
            continue
        checked += 1
        reason = check_skill(src, dest)
        if reason:
            out_of_sync += 1
            print(f"  {reason}: {name}")

    if out_of_sync:
        print(f"\n{out_of_sync} of {checked} skill(s) out of sync — "
              f"run: python3 scripts/sync_plugin_skills.py")
        return 1
    print(f"\n{checked} skill(s) in sync")
    return 0


def sync_all(dry_run: bool) -> int:
    """Copy every shipped skill into TARGET. Returns 0."""
    TARGET.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name, src, dest in _shipped_skills():
        result = sync_skill(src, dest, dry_run)
        copied += result
        if result:
            print(f"  {'would sync' if dry_run else 'synced'}: {name}")

    print(f"\n{'Would sync' if dry_run else 'Synced'} {copied} skill(s) "
          f"into {TARGET.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Show what would be copied")
    mode.add_argument("--check", action="store_true",
                      help="Verify .claude/skills/ matches features/; exit 1 on divergence")
    args = parser.parse_args(argv)

    if args.check:
        return check_all()
    return sync_all(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
