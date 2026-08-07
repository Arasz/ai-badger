#!/usr/bin/env python3
"""Sync framework skills into skills/ — the one directory Claude Code reads them from.

Claude Code scans <plugin-root>/skills/ for a plugin's skills and nowhere else (ADR-0008).
This script copies SKILL.md + essential files from features/common/skills/ and
features/claude/skills/ into skills/.

Run after changing skill content, before publishing the plugin.

Usage:
  python3 tooling/sync_plugin_skills.py [--dry-run | --check]
  --check : do not write; exit 1 if any shipped copy diverges from features/.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "skills"

# Which skills ship is declared once, in badger_lib.SKILL_SCOPES; each list is just that
# decision filtered to the stack whose directory holds the skill.
# skills_for_stack() is the single place this decision lives.
COMMON_SKILLS = bl.skills_for_stack(ROOT, "common")
CLAUDE_SKILLS = bl.skills_for_stack(ROOT, "claude")

# Files to skip when copying (test files, caches, evals). Shared with the hash used by
# --check so a file that is never copied can never be reported as divergence.
SKIP_PATTERNS = tuple(bl.SKILL_EXCLUDE_PATTERNS)

# Empty, and deliberately kept. It held the four skills `code-review-graph` auto-installs into
# `.claude/skills/`; each has since been rewritten into the catalog as an `optIn` skill this
# framework owns, so none is externally managed any more. The mechanism stays because the next
# tool that writes its own skills into a project will need it, and because it gates deletion in
# `_orphans()` as well as writing — an empty set there is a fact, not an oversight.
MANAGED_EXTERNALLY: set = set()


# These run before, or independently of, a scaffold, so their plugin copy carries the whole
# procedure. `welcome-ai-badger` creates `.ai-badger/`; pointing at it would be circular.
# `den-refresh` and `feed-badger` must run the *framework's* copy — ADR-0011 makes that
# load-bearing across a breaking version boundary, where the project's copy is the stale one.
BOOTSTRAP_SKILLS = {"welcome-ai-badger", "den-refresh", "feed-badger"}

FULL_BODY_NAME = "SKILL.full.md"

_POINTER_BODY = """
> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `{name}` skill: it is `.ai-badger/skills/{name}/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `{full}` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
"""


def render_pointer(name: str, source_text: str) -> str:
    """Frontmatter verbatim, body replaced by a pointer at the tailored copy.

    The frontmatter is untouched on purpose: `description` is the only text an agent reads
    before choosing a skill, so changing it here would change what the skill matches on to fix
    a problem about which of two matches to take.

    A source with no frontmatter is returned unchanged rather than rendered — a pointer with no
    name for the agent to match on is worse than the duplicate it replaces.
    """
    parts = source_text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        return source_text
    frontmatter = parts[1]
    return f"---{frontmatter}---\n{_POINTER_BODY.format(name=name, full=FULL_BODY_NAME)}"


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


def _orphans() -> list:
    """Names present in the plugin dir that the catalog no longer ships.

    Sync only ever wrote, so a skill dropped from the shipped list kept its directory —
    still discovered by Claude Code, and invisible to --check because both walked the
    shipped list. MANAGED_EXTERNALLY gates deletion as well as writing: those directories
    are never shipped, so subtracting the shipped set alone would delete them.
    """
    if not TARGET.is_dir():
        return []
    shipped = {name for name, _, _ in _shipped_skills()}
    return sorted(
        d.name for d in TARGET.iterdir()
        if d.is_dir() and d.name not in shipped and d.name not in MANAGED_EXTERNALLY
    )


def render_into(name: str, src: Path, dest: Path) -> None:
    """Write the shipped copy of one skill: a plain copy, then the pointer rendering.

    The single place a shipped copy is produced. `check_skill` renders into a temp directory
    and compares, rather than reimplementing the rule — two implementations of "what should be
    there" is how a check starts disagreeing with the thing it checks.
    """
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*SKIP_PATTERNS))
    _ship_extra_files(name, dest)
    if name in BOOTSTRAP_SKILLS:
        return
    skill_md = dest / "SKILL.md"
    if not skill_md.is_file():
        return
    source_text = skill_md.read_text(encoding="utf-8")
    pointer = render_pointer(name, source_text)
    if pointer == source_text:  # no frontmatter — left alone rather than rendered
        return
    (dest / FULL_BODY_NAME).write_text(source_text, encoding="utf-8")
    skill_md.write_text(pointer, encoding="utf-8")


# Files the plugin ships beside a skill's own content, from outside the skill directory.
# The plugin is Claude Code's distribution, so the task skill's plugin copy carries the
# claude session source (the transcript reader) — without it the shipped tracker would have
# no session source at all, since agent sources live in features/<agent>/adjustments/ and
# are installed by the scaffold, not by the plugin.
PLUGIN_EXTRA_FILES = {
    "task": [
        (ROOT / "features" / "claude" / "adjustments" / "claude_session_source.py",
         "scripts/claude_session_source.py"),
    ],
}


def _ship_extra_files(name: str, dest: Path) -> None:
    """Copy PLUGIN_EXTRA_FILES for *name* into the shipped copy, if the sources exist."""
    for src, rel in PLUGIN_EXTRA_FILES.get(name, ()):
        if src.is_file():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def sync_skill(src: Path, dest: Path, dry_run: bool, name: str = "") -> int:
    """Sync one skill directory from src to dest. Returns count of files copied."""
    if not src.is_dir():
        return 0
    if dry_run:
        return 1
    if dest.exists():
        shutil.rmtree(dest)
    render_into(name or src.name, src, dest)
    return 1


def shape_violations(src: Path, dest: Path, name: str = "") -> List[str]:
    """Report top-level entry-name differences between a shipped copy and a fresh render.

    The render is the contract: a shape the renderer itself would create (no
    `SKILL.full.md` for a bootstrap skill or a frontmatter-less source) is not a
    violation. Content equality stays `check_skill`'s job; this is names only.
    A missing destination directory is `check_skill`'s "missing" report, not ours.
    """
    if not dest.is_dir():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        expected = Path(tmp) / "expected"
        render_into(name or src.name, src, expected)
        rendered = {entry.name for entry in expected.iterdir()}
        actual = {entry.name for entry in dest.iterdir()}
    return sorted(f"missing {n}" for n in rendered - actual) + sorted(
        f"unexpected {n}" for n in actual - rendered
    )


def check_skill(src: Path, dest: Path, name: str = ""):
    """Return the divergence reason for one skill, or None when the shipped copy matches."""
    if not src.is_dir():
        return None
    if not dest.is_dir():
        return "missing"
    excluded = list(SKIP_PATTERNS)
    with tempfile.TemporaryDirectory() as tmp:
        expected = Path(tmp) / "expected"
        render_into(name or src.name, src, expected)
        expected_hash = bl.dir_content_hash(expected, excluded)["content_hash"]
    dest_hash = bl.dir_content_hash(dest, excluded)["content_hash"]
    if expected_hash != dest_hash:
        return "diverged"
    return None


def check_all() -> int:
    """Report every shipped skill whose skills/ copy differs from features/. 1 if any."""
    checked = 0
    out_of_sync = 0
    for name, src, dest in _shipped_skills():
        if not src.is_dir():
            continue
        checked += 1
        reason = check_skill(src, dest, name)
        if reason:
            out_of_sync += 1
            print(f"  {reason}: {name}")
        for violation in shape_violations(src, dest, name):
            out_of_sync += 1
            print(f"  shape {violation}: {name}")

    orphans = _orphans()
    for name in orphans:
        print(f"  orphaned: {name}")

    if out_of_sync or orphans:
        print(f"\n{out_of_sync} of {checked} skill(s) out of sync, "
              f"{len(orphans)} orphaned — run: python3 tooling/sync_plugin_skills.py")
        return 1
    print(f"\n{checked} skill(s) in sync")
    return 0


def sync_all(dry_run: bool) -> int:
    """Copy every shipped skill into TARGET. Returns 0."""
    TARGET.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name, src, dest in _shipped_skills():
        result = sync_skill(src, dest, dry_run, name)
        copied += result
        if result:
            print(f"  {'would sync' if dry_run else 'synced'}: {name}")

    for name in _orphans():
        if dry_run:
            print(f"  would remove: {name}")
            continue
        shutil.rmtree(TARGET / name)
        print(f"  removed: {name}")

    print(f"\n{'Would sync' if dry_run else 'Synced'} {copied} skill(s) "
          f"into {TARGET.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Show what would be copied")
    mode.add_argument("--check", action="store_true",
                      help="Verify skills/ matches features/; exit 1 on divergence or orphan")
    args = parser.parse_args(argv)

    if args.check:
        return check_all()
    return sync_all(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
