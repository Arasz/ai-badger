#!/usr/bin/env python3
"""Regenerate the release table in docs/changelog/README.md from the entry files.

The per-file changelog convention exists to avoid merge conflicts, and the entry files
deliver that — but the index row did not: every PR riding one unreleased version edited the
same table line, so N concurrent PRs cost N-1 hand-resolved conflicts, and a careless
resolution silently dropped an entry (issue #160). Every fact the table needs is already on
disk, so the table is generated and a stale one fails `--check` like index.json does.

What is generated, and from what:

  version   the `{version}` half of the `{version}-{slug}.md` filename
  title     the entry's first `# ` heading, with a leading `{version} —` stripped: the
            Version column already carries it. An H1 that does not repeat its version is
            used whole.
  order     versions semver-descending (0.10.0 above 0.9.4, which a text sort inverts);
            several entries at one version join with ` · ` in FILENAME order. Filename,
            not commit date: the row must be a function of the tree alone, so two branches
            that both add an entry regenerate the same row whichever lands first.
  note      an optional `<!-- index-note: … -->` line in an entry, rendered after its link
            as ` — *…*`. It is how 0.7.1's row records that its mechanism was reverted.

Only the region between the two markers is written; the README's prose documents the
convention and is left alone. A misnamed entry or one with no H1 is REPORTED, never skipped
— skipping is the silent omission this script exists to end. `gates/docs_guard.py` also
asserts every entry has a row; that assertion is now redundant with `--check` and kept as
defence in depth, since docs_guard runs on trees this generator is not pointed at.

Usage: changelog_index.py [--root <dir>] [--check]
  --check : do not write; exit 1 if the committed table is missing or stale.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

CHANGELOG_DIR = ("docs", "changelog")
INDEX_FILE = "README.md"
START_MARKER = "<!-- changelog-index:start -->"
END_MARKER = "<!-- changelog-index:end -->"
HEADER = ("| Version | Entry |", "|---|---|")
JOINER = " · "

ENTRY_RE = re.compile(r"^(\d+\.\d+\.\d+)-[A-Za-z0-9._-]+\.md$")
NOTE_RE = re.compile(r"<!--\s*index-note:\s*(.+?)\s*-->")


class Entry(NamedTuple):
    """One changelog file as the index sees it."""

    version: str
    filename: str
    title: str
    note: str

    def link(self) -> str:
        """The cell fragment for this entry: its link, plus its note when it has one."""
        title = self.title.replace("|", r"\|")
        cell = f"[{title}]({self.filename})"
        return f"{cell} — *{self.note}*" if self.note else cell


def heading(text: str) -> str:
    """The first `# ` heading in a Markdown document, or "" when it has none."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def entry_title(text: str, version: str) -> str:
    """The entry's H1 with a leading `{version} —` (or `-`/`–`) stripped."""
    head = heading(text)
    match = re.match(re.escape(version) + r"\s*[—–-]\s*(.+)$", head)
    return match.group(1).strip() if match else head


def entry_note(text: str) -> str:
    """The entry's `<!-- index-note: … -->` annotation, or "" when it declares none."""
    match = NOTE_RE.search(text)
    return match.group(1).strip() if match else ""


def version_key(version: str) -> Tuple[int, ...]:
    """Sort key ordering versions numerically: 0.10.0 above 0.9.4, not below it."""
    return tuple(int(part) for part in version.split("."))


def load_entries(directory: Path) -> Tuple[List[Entry], List[str]]:
    """Every entry file in `directory`, plus the ones it refuses to index and why."""
    entries: List[Entry] = []
    problems: List[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == INDEX_FILE:
            continue
        match = ENTRY_RE.match(path.name)
        if not match:
            problems.append(f"{path.name}: not named {{version}}-{{slug}}.md")
            continue
        text = path.read_text(encoding="utf-8")
        version = match.group(1)
        title = entry_title(text, version)
        if not title:
            problems.append(f"{path.name}: no `# ` heading to take a title from")
            continue
        entries.append(Entry(version, path.name, title, entry_note(text)))
    return entries, problems


def render_rows(entries: List[Entry]) -> List[str]:
    """One table row per version, newest first, each cell joined in filename order."""
    by_version: Dict[str, List[Entry]] = {}
    for entry in sorted(entries, key=lambda e: e.filename):
        by_version.setdefault(entry.version, []).append(entry)
    rows = []
    for version in sorted(by_version, key=version_key, reverse=True):
        cell = JOINER.join(entry.link() for entry in by_version[version])
        rows.append(f"| {version} | {cell} |")
    return rows


def splice(text: str, rows: List[str]) -> Optional[str]:
    """`text` with the marked region replaced by the table, or None if a marker is missing."""
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < start:
        return None
    block = "\n".join(HEADER + tuple(rows))
    return f"{text[:start]}{START_MARKER}\n{block}\n{text[end:]}"


class Rendered(NamedTuple):
    """The README as it should be, as it is on disk, and what stopped the generator."""

    updated: Optional[str]
    current: str
    rows: int
    entries: int
    problems: List[str]


def build(root: Path) -> Rendered:
    """Render the index for the tree under `root` without writing anything."""
    directory = root.joinpath(*CHANGELOG_DIR)
    index = directory / INDEX_FILE
    location = "/".join(CHANGELOG_DIR) + "/" + INDEX_FILE
    if not index.is_file():
        return Rendered(None, "", 0, 0, [f"{location} does not exist"])
    entries, problems = load_entries(directory)
    if problems:
        return Rendered(None, "", 0, len(entries), problems)
    current = index.read_text(encoding="utf-8")
    rows = render_rows(entries)
    updated = splice(current, rows)
    if updated is None:
        return Rendered(None, current, len(rows), len(entries),
                        [f"{location} has no {START_MARKER} … {END_MARKER} marker pair"])
    return Rendered(updated, current, len(rows), len(entries), [])


def main(argv=None) -> int:
    """CLI entry point: write (or --check) the generated changelog index table."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()

    rendered = build(root)
    if rendered.problems:
        print("CHANGELOG INDEX NOT GENERATED:")
        for problem in rendered.problems:
            print(f"    - {problem}")
        return 1

    tally = f"{rendered.rows} versions, {rendered.entries} entries"
    if args.check:
        if rendered.updated != rendered.current:
            print("/".join(CHANGELOG_DIR) + f"/{INDEX_FILE} is stale — run changelog_index.py")
            return 1
        print(f"changelog index up to date — {tally}")
        return 0

    if rendered.updated != rendered.current:
        bl.atomic_write_text(root.joinpath(*CHANGELOG_DIR, INDEX_FILE), rendered.updated)
    print(f"wrote the changelog index — {tally}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
