#!/usr/bin/env python3
"""Fail when the documentation stops matching the tree it describes.

The 2026-07-27 docs refactor moved files and broke links that nothing could catch, because
nothing checked (deferred-work plan, Wave 19). This gate checks only what a machine can prove
offline and without a toolchain — no prose linter, no markdown linter, no network link checker:

  1. Relative Markdown links in root `*.md` and under `docs/` resolve to something that exists.
  2. Backticked repo paths (`tooling/foo.py`) name a file that exists.
  3. Every `docs/changelog/*.md` is reachable from that directory's README index, and VERSION
     has an entry.

Check 3's first half now overlaps `tooling/changelog_index.py --check` on purpose, and is the
weaker of the two: since issue #160 the index table is generated, so a missing row cannot
survive that check. It is kept because this gate is pointed at trees the generator is not (a
`--root` with no marked region still gets check 3), and because the VERSION half has no other
owner. If the two ever disagree, the generator is right.

Check 2 is deliberately timid: a noisy gate gets disabled, so a span is only considered a repo
path when it has no whitespace, no glob or placeholder character, a known file extension, and a
first segment naming this framework's own tracked surface (CHECKED_ROOTS). `.ai-badger/…` is
outside that surface on purpose — in documentation it means "in a scaffolded consumer repo",
which this repo only coincidentally is. Everything else is ignored, which means real misses —
accepted, because one false positive costs more than ten of them.

Check 2 also skips RECORD_DIRS. A changelog entry, ADR or dated work record describes a tree as
it was or as it is proposed to be; its dead paths are the record working, not rot, and ADRs may
not be edited after acceptance at all. Those documents still get check 1, because a link that no
longer opens is broken for a reader whatever the document is.

RECORD_DIRS named seven directories grouped by document kind (`design/`, `plans/`, `research/`,
`reviews/`, `specs/`, `incidents/`, `archive/`) until 2026-08-01. All seven were deleted in PR
#111 and the list went on freezing paths no longer in the tree — dead config that reads as a live
rule. `docs/work/` replaces them: one dated home, grouped by nothing, because kind is not a
subject.

Fenced code blocks are skipped entirely: they hold examples, not claims about this tree.

Exemptions: `docs/archive/` is not scanned at all (an archive is supposed to preserve dead
references). Anything else goes one-per-line in `.docs-guard-ignore` at the repo root, matched
as a repo-relative path prefix against both the scanned document and the referenced path.

Line numbers in citations (`scaffold.py:772`) are NOT checked: such a citation is usefully
wrong, and any check strict enough to catch it is noisy enough to be turned off.

Usage: docs_guard.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Sequence, Tuple
from urllib.parse import unquote

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

DOCS_DIR = "docs"
IGNORE_FILE = ".docs-guard-ignore"
BUILTIN_EXEMPT = ("docs/archive/",)
CHECKED_ROOTS = ("engine", "tooling", "gates", "features", "schemas", "hooks", "tests", "docs",
                 ".github", ".claude-plugin")
RECORD_DIRS = ("docs/adr/", "docs/changelog/", "docs/work/")
PATH_SUFFIXES = (".py", ".md", ".mjs", ".js", ".json", ".yaml", ".yml", ".toml", ".sh", ".txt")
PLACEHOLDER_CHARS = "<>{}$()[]|,*?!\"'\\ \t"

FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)<>\s]+)>?[^)]*\)")
REF_LINK_RE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?([^>\s]+)>?")
CODE_SPAN_RE = re.compile(r"`+([^`\n]+)`+")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
ENTRY_RE = re.compile(r"^(\d+\.\d+\.\d+)-[A-Za-z0-9._-]+\.md$")


class Problem(NamedTuple):
    """One actionable finding: where it is, and what does not resolve."""

    path: str
    line: int
    message: str

    def location(self) -> str:
        """`file:line`, or just the file when the finding has no single line."""
        return f"{self.path}:{self.line}" if self.line else self.path


def exempt_prefixes(root: Path) -> Tuple[str, ...]:
    """Repo-relative path prefixes the guard ignores: built-ins plus `.docs-guard-ignore`."""
    extra: List[str] = []
    ignore = root / IGNORE_FILE
    if ignore.is_file():
        for raw in ignore.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                extra.append(line)
    return tuple(BUILTIN_EXEMPT) + tuple(extra)


def is_exempt(rel: str, prefixes: Sequence[str]) -> bool:
    """True when a repo-relative path sits under one of the exempt prefixes."""
    return any(rel == p or rel.startswith(p) for p in prefixes)


def scanned_docs(root: Path, prefixes: Sequence[str]) -> List[str]:
    """Repo-relative Markdown files under review: root-level files plus everything in docs/."""
    found = [p.name for p in sorted(root.glob("*.md"))]
    found += [rel_to(root, p) for p in sorted((root / DOCS_DIR).rglob("*.md"))]
    return [rel for rel in found if not is_exempt(rel, prefixes)]


def rel_to(root: Path, path: Path) -> str:
    """`path` relative to `root` with forward slashes; may start with `..` if outside."""
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def prose_lines(text: str) -> List[Tuple[int, str]]:
    """1-based numbered lines with fenced code blocks removed — examples make no claims."""
    out: List[Tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((number, line))
    return out


def link_targets(line: str) -> List[str]:
    """Every link destination on one line: inline `[a](b)` plus a `[a]: b` reference.

    Code spans become a placeholder first: documentation about link syntax writes
    `[text](target)` inside backticks, and that is prose about Markdown, not a link. The
    placeholder rather than removal keeps `[`x.md`](x.md)` — a real link — intact.
    """
    prose = CODE_SPAN_RE.sub("CODE", line)
    targets = INLINE_LINK_RE.findall(prose)
    ref = REF_LINK_RE.match(prose)
    if ref:
        targets.append(ref.group(1))
    return targets


def is_local_link(target: str) -> bool:
    """False for anything the guard cannot resolve offline: URLs, mailto, anchors, absolute."""
    if not target or target.startswith(("#", "/")):
        return False
    return not SCHEME_RE.match(target)


def broken_links(root: Path, rel: str, text: str, prefixes: Sequence[str]) -> List[Problem]:
    """Relative links in one document that do not resolve to an existing path."""
    base = (root / rel).parent
    problems = []
    for number, line in prose_lines(text):
        for target in link_targets(line):
            if not is_local_link(target):
                continue
            path = unquote(target.split("#", 1)[0])
            if not path:
                continue
            resolved = (base / path)
            if resolved.exists() or is_exempt(rel_to(root, resolved), prefixes):
                continue
            problems.append(Problem(rel, number, f"broken link: {target}"))
    return problems


def looks_like_repo_path(root: Path, span: str) -> bool:
    """True only for a code span that unambiguously names a path in THIS repository.

    Every clause exists to suppress a false positive: placeholders, globs, prose with spaces,
    URLs, extension-less prefixes, and any first segment outside this framework's own tracked
    surface — `.ai-badger/config.json` in a document means a scaffolded consumer repo.
    """
    if "/" not in span or not span.endswith(PATH_SUFFIXES):
        return False
    if any(c in span for c in PLACEHOLDER_CHARS) or SCHEME_RE.match(span):
        return False
    if span.split("/", 1)[0] not in CHECKED_ROOTS:
        return False
    return (root / span.split("/", 1)[0]).is_dir()


def broken_path_refs(root: Path, rel: str, text: str, prefixes: Sequence[str]) -> List[Problem]:
    """Backticked repo paths in one document that name nothing in the tree."""
    if is_exempt(rel, RECORD_DIRS):
        return []
    problems = []
    for number, line in prose_lines(text):
        for span in CODE_SPAN_RE.findall(line):
            span = span.strip()
            if not looks_like_repo_path(root, span) or is_exempt(span, prefixes):
                continue
            if not (root / span).exists():
                problems.append(Problem(rel, number, f"missing path: {span}"))
    return problems


def changelog_problems(root: Path) -> List[Problem]:
    """Entries unreachable from the changelog index, and a VERSION with no entry at all."""
    directory = root / DOCS_DIR / "changelog"
    if not directory.is_dir():
        return []
    index = directory / "README.md"
    listed = index.read_text(encoding="utf-8") if index.is_file() else ""
    problems = []
    versions = set()
    for entry in sorted(directory.glob("*.md")):
        if entry.name == "README.md":
            continue
        rel = f"{DOCS_DIR}/changelog/{entry.name}"
        match = ENTRY_RE.match(entry.name)
        if not match:
            problems.append(Problem(rel, 0, "not named {version}-{slug}.md"))
        elif entry.name not in listed:
            versions.add(match.group(1))
            problems.append(Problem(rel, 0, "no row in docs/changelog/README.md"))
        else:
            versions.add(match.group(1))
    version_file = root / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else ""
    if version and version not in versions:
        problems.append(Problem("VERSION", 1,
                                f"{version} has no docs/changelog/{version}-<slug>.md entry"))
    return problems


def collect(root: Path) -> Tuple[List[Problem], int]:
    """All problems in the tree, plus the number of documents scanned."""
    prefixes = exempt_prefixes(root)
    docs = scanned_docs(root, prefixes)
    problems: List[Problem] = []
    for rel in docs:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        problems += broken_links(root, rel, text, prefixes)
        problems += broken_path_refs(root, rel, text, prefixes)
    return problems + changelog_problems(root), len(docs)


def check(root: Path) -> int:
    """Run the docs guard; print its verdict; return 0 pass / 1 fail."""
    problems, scanned = collect(root)
    if not problems:
        print(f"{scanned} document(s) scanned; every link, repo path and changelog entry "
              f"resolves — PASS")
        return 0

    print(f"DOCS OUT OF SYNC: {len(problems)} unresolved reference(s) in {scanned} document(s):")
    for problem in problems:
        print(f"    {problem.location()}  {problem.message}")
    print("Fix the reference, or — only when the path is meant to be absent — add it to "
          f"{IGNORE_FILE}.")
    return 1


def main(argv=None) -> int:
    """CLI entry point: run the docs guard against --root (default: auto-detected)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main())
