#!/usr/bin/env python3
"""Fail when shipped code imports a third-party module `engine/requirements.txt` never declared.

CONTRIBUTING.md's "do not add a third runtime dependency without a very good reason" had no
mechanical backing, and an undeclared import is invisible until it crashes in a consumer repo.
The gate parses every `*.py` under engine/, tooling/, features/ and gates/ with `ast` — it never imports the
module, so a file with a top-level side effect is read, not run — and sorts each imported
top-level name into one of three buckets:

  * FIRST-PARTY — a module this repo ships. Skill scripts and hooks `sys.path.insert` their own
    directory and then import a sibling or an engine/ module by bare name, so first-party is
    decided by what exists in the tree, before any resolution is attempted.
  * STDLIB — resolvable, and coming from the interpreter's own library.
  * THIRD-PARTY — everything else, INCLUDING a name that resolves nowhere. An absent module is
    not proof of innocence: a missing dependency is exactly what it looks like.

Stdlib detection uses `importlib.util.find_spec` and its origin, not `sys.stdlib_module_names`
(available since this repo's floor moved to 3.10, but not adopted here — this approach needs
no floor-conditional branch and was left as is): no origin at all means built-in or frozen;
a path under site-packages means third-party; a path under `sysconfig`'s stdlib means stdlib.
Site-packages is tested FIRST because in a system install it sits *inside* the stdlib directory.

Distribution names are not module names: `pyyaml` is declared, `yaml` is imported. Each declared
distribution is expanded through its installed metadata (`top_level.txt`, else its file list),
which needs no network but does need the package present — so ALIASES carries the same mapping
statically, keeping the verdict identical in an environment where an optional dependency is not
installed.

Usage: deps_guard.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import os
import re
import sys
import sysconfig
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
# gate_report is a sibling: running this file puts gates/ on the path, importing it does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl
from gate_report import Problem, report

CODE_ROOTS = ("engine", "tooling", "features", "gates")
REQUIREMENTS = "engine/requirements.txt"
SITE_DIRS = ("site-packages", "dist-packages")
RESOLUTION_ERRORS = (ImportError, AttributeError, OSError, TypeError, ValueError)

# Declared distribution -> module names it provides, for environments where it is not installed
# and its metadata therefore cannot be read. Only needed where the two names differ.
ALIASES: Dict[str, Tuple[str, ...]] = {"pyyaml": ("yaml", "_yaml")}

STDLIB = "stdlib"
FIRST_PARTY = "first-party"
THIRD_PARTY = "third-party"


class Import(NamedTuple):
    """A top-level module name as imported by one line of one file."""

    module: str
    path: str
    line: int


def _paths(*keys: str) -> Tuple[str, ...]:
    found = []
    for key in keys:
        path = sysconfig.get_paths().get(key)
        if path:
            found.append(os.path.realpath(path) + os.sep)
    return tuple(found)


STDLIB_PREFIXES = _paths("stdlib", "platstdlib")
SITE_PREFIXES = _paths("purelib", "platlib")


def source_files(root: Path) -> List[str]:
    """Repo-relative `*.py` under the code roots, sorted."""
    found: List[str] = []
    for name in CODE_ROOTS:
        base = root / name
        if base.is_dir():
            found += [rel_to(root, p) for p in base.rglob("*.py")]
    return sorted(found)


def rel_to(root: Path, path: Path) -> str:
    """`path` relative to `root` with forward slashes."""
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def shipped_modules(root: Path) -> Set[str]:
    """Bare module names this repo itself provides — a sibling file or a package directory."""
    names: Set[str] = set()
    for rel in source_files(root):
        path = Path(rel)
        names.add(path.parent.name if path.name == "__init__.py" else path.stem)
    return names


def imported_names(tree: ast.AST, rel: str) -> List[Import]:
    """Every top-level module name imported anywhere in one parsed file.

    `ast.walk` rather than a scan of `tree.body`: this repo imports inside functions and inside
    `try:` blocks on purpose, and an optional dependency hidden in a `try:` is still a dependency.
    Relative imports (`from . import x`) name nothing outside the tree and are skipped.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [Import(a.name.split(".")[0], rel, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.append(Import(node.module.split(".")[0], rel, node.lineno))
    return found


def _origin(name: str) -> Optional[str]:
    """Where the interpreter would load `name` from: a path, "", or None when unresolvable."""
    try:
        spec = importlib.util.find_spec(name)
    except RESOLUTION_ERRORS:
        return None
    if spec is None:
        return None
    if spec.origin in (None, "built-in", "frozen"):
        locations = list(spec.submodule_search_locations or [])
        return locations[0] if locations else ""
    return spec.origin


def _under(path: str, prefixes: Sequence[str]) -> bool:
    return os.path.realpath(path).startswith(tuple(prefixes))


def classify(name: str, shipped: Set[str]) -> str:
    """Sort one top-level module name into first-party, stdlib or third-party."""
    if name in shipped:
        return FIRST_PARTY
    origin = _origin(name)
    if origin is None:
        return THIRD_PARTY
    if origin == "":
        return STDLIB
    if set(Path(origin).parts) & set(SITE_DIRS) or _under(origin, SITE_PREFIXES):
        return THIRD_PARTY
    return STDLIB if _under(origin, STDLIB_PREFIXES) else THIRD_PARTY


def normalize(name: str) -> str:
    """PEP 503 normalization, so `PyYAML`, `pyyaml` and `py_yaml` are one distribution."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def declared_distributions(path: Path) -> Set[str]:
    """Distribution names in a requirements file, stripped of extras, specifiers and markers."""
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if match:
            names.add(normalize(match.group(0)))
    return names


def _metadata_modules(distribution: str) -> Set[str]:
    """Module names an INSTALLED distribution provides, per its own recorded metadata."""
    try:
        dist = importlib.metadata.distribution(distribution)
        listed = dist.read_text("top_level.txt") or ""
        names = {line.strip() for line in listed.splitlines() if line.strip()}
        if names:
            return names
        for entry in dist.files or []:
            parts = entry.parts
            if len(parts) == 1 and parts[0].endswith(".py"):
                names.add(parts[0][:-3])
            elif len(parts) == 2 and parts[1] == "__init__.py":
                names.add(parts[0])
        return names
    except RESOLUTION_ERRORS:
        return set()


def declared_modules(distributions: Set[str]) -> Set[str]:
    """Every module name the declared distributions may legitimately be imported as."""
    modules: Set[str] = set()
    for distribution in distributions:
        modules.add(distribution.replace("-", "_"))
        modules.update(ALIASES.get(distribution, ()))
        modules.update(_metadata_modules(distribution))
    return {normalize(name) for name in modules}


def collect(root: Path) -> Tuple[List[Problem], List[str], Set[str]]:
    """All findings in the tree, the files scanned, and the third-party modules accepted."""
    requirements = root / REQUIREMENTS
    if not requirements.is_file():
        return ([Problem(REQUIREMENTS, 0, "no such file: nothing is declared")], [], set())

    allowed = declared_modules(declared_distributions(requirements))
    shipped = shipped_modules(root)
    files = source_files(root)
    problems: List[Problem] = []
    accepted: Set[str] = set()
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            problems.append(Problem(rel, exc.lineno or 0, f"cannot parse: {exc.msg}"))
            continue
        for entry in imported_names(tree, rel):
            if classify(entry.module, shipped) != THIRD_PARTY:
                continue
            if normalize(entry.module) in allowed:
                accepted.add(entry.module)
            else:
                problems.append(Problem(rel, entry.line,
                                        f"undeclared third-party import: {entry.module}"))
    return problems, files, accepted


def check(root: Path) -> int:
    """Run the dependency guard; print its verdict; return 0 pass / 1 fail."""
    problems, files, accepted = collect(root)
    if not problems:
        declared = ", ".join(sorted(accepted)) or "none"
        print(f"{len(files)} file(s) scanned; every third-party import is declared in "
              f"{REQUIREMENTS} ({declared}) — PASS")
        return 0

    return report(
        f"DEPENDENCY GUARD FAILED: {len(problems)} finding(s) across {len(files)} file(s):",
        problems,
        f"Declare it in {REQUIREMENTS} — deciding first, per CONTRIBUTING.md, whether it is "
        "required (imported unguarded) or optional (guarded, degrading to a printed note).")


def main(argv=None) -> int:
    """CLI entry point: run the dependency guard against --root (default: auto-detected)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main())
