#!/usr/bin/env python3
"""Sync framework skills into .claude/skills/ for plugin discovery.

Claude Code discovers plugin-provided skills from .claude/skills/ (or skills/)
in the plugin directory. This script copies SKILL.md + essential files from
features/common/skills/ and features/claude/skills/ into .claude/skills/.

Run after changing skill content, before publishing the plugin.

Usage:
  python3 scripts/sync_plugin_skills.py [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".claude" / "skills"

# Skills from features/common/skills/ to expose in the plugin
COMMON_SKILLS = [
    "task",
    "welcome-ai-badger",
    "feed-badger",
    "den-refresh",
    "maintain-agent-instructions",
    "prompt-markers",
    "mcp-index",
]

# Skills from features/claude/skills/ to expose in the plugin
CLAUDE_SKILLS = [
    "auto-wm",
]

# Files to skip when copying (test files, caches, evals)
SKIP_PATTERNS = {
    "__pycache__",
    "*.pyc",
    "test_*.py",
    "*_test.py",
    "tests",
    "evals",
}

# Skills already in .claude/skills/ that should NOT be overwritten
# (e.g. code-review-graph skills managed externally)
MANAGED_EXTERNALLY = {
    "debug-issue",
    "explore-codebase",
    "refactor-safely",
    "review-changes",
}


def _should_skip(path: Path) -> bool:
    """Return True if path matches a skip pattern."""
    name = path.name
    for pat in SKIP_PATTERNS:
        if pat.startswith("*"):
            if name.endswith(pat[1:]):
                return True
        elif name == pat:
            return True
    return False


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied")
    args = parser.parse_args(argv)

    TARGET.mkdir(parents=True, exist_ok=True)
    copied = 0

    # Sync common skills
    common_base = ROOT / "features" / "common" / "skills"
    for name in COMMON_SKILLS:
        if name in MANAGED_EXTERNALLY:
            continue
        src = common_base / name
        dest = TARGET / name
        result = sync_skill(src, dest, args.dry_run)
        copied += result
        if result:
            print(f"  {'would sync' if args.dry_run else 'synced'}: {name}")

    # Sync claude-specific skills
    claude_base = ROOT / "features" / "claude" / "skills"
    for name in CLAUDE_SKILLS:
        if name in MANAGED_EXTERNALLY:
            continue
        src = claude_base / name
        dest = TARGET / name
        result = sync_skill(src, dest, args.dry_run)
        copied += result
        if result:
            print(f"  {'would sync' if args.dry_run else 'synced'}: {name}")

    print(f"\n{'Would sync' if args.dry_run else 'Synced'} {copied} skill(s) into {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
