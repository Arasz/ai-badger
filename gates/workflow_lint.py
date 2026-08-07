#!/usr/bin/env python3
"""Fail when a workflow re-fetches remote code or runs on the repository's default token scope.

Both halves of one invariant (`features/github/invariants/pin-actions-to-sha.md`): every `uses:`
is pinned to a full commit SHA, and every workflow — or, where jobs need different scopes, every
job — declares an explicit `permissions:` block. 0.97.0 pinned all nine references by hand and
nothing kept them pinned, which is how the invariant shipped violated nine times to begin with.

Usage: workflow_lint.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

WORKFLOWS = ".github/workflows"

# Line-oriented on purpose: pyyaml is optional here (ADR-0005), so nothing that runs in a gate
# may require it. Every predicate below fails loudly rather than skipping what it cannot read.
USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)")
PINNED_RE = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}")
JOBS_RE = re.compile(r"^jobs:\s*$")
JOB_RE = re.compile(r"^ {2}([A-Za-z_][\w-]*):(.*)$")
TOP_PERMISSIONS_RE = re.compile(r"^permissions:")
JOB_PERMISSIONS_RE = re.compile(r"^ {4}permissions:")


def workflow_files(root: Path) -> List[Path]:
    """Every workflow file, both spellings of the extension."""
    directory = root / WORKFLOWS
    return sorted(p for p in directory.glob("*.y*ml") if p.suffix in (".yml", ".yaml"))


def unpinned_uses(lines: List[str]) -> List[str]:
    """`<line>: <ref>` for every `uses:` that is not a 40-hex commit SHA.

    A `./` reference is a local action already in this commit, so there is nothing to pin.
    """
    bad = []
    for number, line in enumerate(lines, 1):
        match = USES_RE.match(line)
        if not match:
            continue
        ref = match.group(1).strip("'\"")
        if not ref.startswith("./") and not PINNED_RE.fullmatch(ref):
            bad.append(f"{number}: {ref}")
    return bad


def job_blocks(lines: List[str]) -> Dict[str, List[str]]:
    """Each job id under `jobs:` mapped to its lines, or `{}` when there is no `jobs:` key."""
    blocks: Dict[str, List[str]] = {}
    current = None
    in_jobs = False
    for line in lines:
        if JOBS_RE.match(line):
            in_jobs, current = True, None
            continue
        if not in_jobs:
            continue
        if line.strip() and not line.startswith(" "):
            break
        match = JOB_RE.match(line)
        if match:
            current = match.group(1)
            blocks[current] = [match.group(2)]
        elif current is not None:
            blocks[current].append(line)
    return blocks


def workflow_violations(path: Path, rel: str) -> List[str]:
    """Every pinning and permissions violation in one workflow file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    violations = [f"{rel}:{bad} is not pinned to a 40-character commit SHA"
                  for bad in unpinned_uses(lines)]
    if any(TOP_PERMISSIONS_RE.match(line) for line in lines):
        return violations
    jobs = job_blocks(lines)
    if not jobs:
        violations.append(f"{rel}: no top-level permissions: and no jobs: block this lint "
                          f"can read — refusing to report a pass on a file it cannot see into")
        return violations
    violations += [f"{rel}: job {job!r} runs on the repository's default token scope: no "
                   f"permissions: block in the job and none at the top of the file"
                   for job, block in jobs.items()
                   if not any(JOB_PERMISSIONS_RE.match(line) for line in block)]
    return violations


def workflow_lint(root: Path) -> List[str]:
    """Violations across every workflow. An empty workflow directory is itself one."""
    files = workflow_files(root)
    if not files:
        return [f"{WORKFLOWS}/: matched no workflow file; refusing to report a pass"]
    violations: List[str] = []
    for path in files:
        violations += workflow_violations(path, str(path.relative_to(root)))
    return violations


def main(argv=None) -> int:
    """CLI entry point: report every violation across the workflows, or say there are none."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root (default: auto-detect).")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()

    violations = workflow_lint(root)
    if not violations:
        print(f"ok       workflow lint — {len(workflow_files(root))} workflow(s) checked")
        return 0
    print("WORKFLOW LINT FAILED")
    for violation in violations:
        print(f"    - {violation}")
    print("Pin every `uses:` to a commit SHA and declare a permissions: block; see "
          "features/github/invariants/pin-actions-to-sha.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
