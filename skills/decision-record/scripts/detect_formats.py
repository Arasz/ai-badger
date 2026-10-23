#!/usr/bin/env python3
"""Report which decision-record and spec formats a project already uses, and which CLIs are on PATH.

The tree decides the format; an installed CLI only decides whether to write through it. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

LOG_DIR_NAMES = {"adr", "adrs", "decisions"}
SKIPPED_DIRS = {"node_modules", "vendor", "worktrees", "dist", "build", "target"}
MAX_DEPTH = 4
NUMBERED = re.compile(r"^(\d{3,})-.+\.md$")
INDEX_NAMES = ("README.md", "index.md")
LOG4BRAINS_FOLDER = re.compile(r"^\s*adrFolder:\s*['\"]?([^'\"#\s]+)", re.MULTILINE)
SPEC_MARKERS = (
    ("openspec", "openspec", ("openspec/config.yaml", "openspec/specs")),
    ("spec-kit", ".specify", (".specify",)),
    ("kiro", ".kiro/specs", (".kiro/specs",)),
)
CLIS = ("openspec", "specify", "adr", "log4brains")
FALLBACK_DIR = "docs/decisions"

Which = Callable[[str], Optional[str]]


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _declared_logs(root: Path) -> Dict[str, str]:
    """Map each ADR folder a tool's marker file declares to that tool."""
    declared: Dict[str, str] = {}
    adr_dir = root / ".adr-dir"
    if adr_dir.is_file():
        target = adr_dir.read_text(encoding="utf-8").strip()
        if target:
            declared[Path(target).as_posix()] = "adr-tools"
    log4brains = root / ".log4brains.yml"
    if log4brains.is_file():
        for folder in LOG4BRAINS_FOLDER.findall(log4brains.read_text(encoding="utf-8")):
            declared[Path(folder).as_posix()] = "log4brains"
    return declared


def _discovered_logs(root: Path) -> List[str]:
    """Folders named like an ADR log that hold at least one numbered record."""
    found = []
    for current, dirs, files in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        dirs[:] = [d for d in sorted(dirs)
                   if not d.startswith(".") and d not in SKIPPED_DIRS and depth < MAX_DEPTH]
        if Path(current).name in LOG_DIR_NAMES and any(NUMBERED.match(f) for f in files):
            found.append(_rel(root, Path(current)))
    return found


def _describe_log(root: Path, rel: str, tool: str) -> Dict[str, object]:
    folder = root / rel
    records = sorted(p for p in folder.glob("*.md") if NUMBERED.match(p.name)) if folder.is_dir() else []
    numbers = [NUMBERED.match(p.name).group(1) for p in records]
    width = max((len(n) for n in numbers), default=4)
    highest = max((int(n) for n in numbers), default=0)
    newest = max(records, key=lambda p: int(NUMBERED.match(p.name).group(1)), default=None)
    index = next((folder / name for name in INDEX_NAMES if (folder / name).is_file()), None)
    if tool == "unknown" and rel == "doc/adr":
        tool = "adr-tools"
    return {
        "dir": rel,
        "tool": tool,
        "count": len(records),
        "next": str(highest + 1).zfill(width),
        "newest": _rel(root, newest) if newest else None,
        "index": _rel(root, index) if index else None,
    }


def _adr_logs(root: Path) -> List[Dict[str, object]]:
    declared = _declared_logs(root)
    logs = dict(declared)
    for rel in _discovered_logs(root):
        logs.setdefault(rel, "unknown")
    return [_describe_log(root, rel, tool) for rel, tool in logs.items()
            if rel in declared or (root / rel).is_dir()]


def _spec_frameworks(root: Path) -> List[Dict[str, str]]:
    return [{"framework": name, "dir": folder}
            for name, folder, markers in SPEC_MARKERS
            if any((root / marker).exists() for marker in markers)]


def detect(root: Path, which: Which = shutil.which) -> Dict[str, object]:
    """Describe the project's ADR logs, spec frameworks, CLIs and the resulting write mode."""
    root = Path(root).resolve()
    adr = _adr_logs(root)
    specs = _spec_frameworks(root)
    mode = {(True, True): "combination", (True, False): "adr",
            (False, True): "spec", (False, False): "none"}[(bool(adr), bool(specs))]
    return {
        "mode": mode,
        "adr": adr,
        "specs": specs,
        "clis": {name: which(name) for name in CLIS},
        "fallback": {"dir": FALLBACK_DIR, "next": "0001"},
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=".", help="project root (default: cwd)")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    result = detect(Path(args.root))
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"mode: {result['mode']}")
    for log in result["adr"]:
        print(f"adr: {log['dir']} ({log['tool']}, {log['count']} records, next {log['next']})")
    for spec in result["specs"]:
        print(f"spec: {spec['framework']} at {spec['dir']}")
    installed = [name for name, path in result["clis"].items() if path]
    print(f"clis: {', '.join(installed) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
