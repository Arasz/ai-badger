#!/usr/bin/env python3
"""Find project additions that are candidates to contribute back to the framework.

Diffs the target repo's .ai-badger/ tree against its manifest.json (what the framework
originally placed). Emits candidates as JSON to stdout for the agent to classify
(agnostic/generalizable/project-specific), generalize, and place. MECHANICAL: no LLM.

A candidate is:
  - NEW: a managed-feature file present in .ai-badger/ but not recorded in the manifest.
  - CHANGED: a managed file whose current content hash differs from the manifest hash.

Usage: detect_additions.py [--target <dir>] [--root <framework>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        if (anc / "scripts" / "badger_lib.py").exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    raise RuntimeError("could not locate ai-badger scripts/badger_lib.py")


_bootstrap_lib()
import badger_lib as bl

# managed dirs inside .ai-badger that map to framework features
MANAGED = {
    "agents": "personas",
    "instructions": "instructions",
    "invariants": "invariants",
    "skills": "skills",
}


def main(argv=None) -> int:
    """CLI entry point: emit new/changed contribution candidates for --target as JSON."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=".")
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    target = Path(args.target).resolve()
    aib = target / ".ai-badger"
    if not (aib / "manifest.json").exists():
        print(json.dumps({
            "error": "no .ai-badger/manifest.json — repo not scaffolded by ai-badger",
        }))
        return 1

    manifest = bl.load_json(aib / "manifest.json")
    entries = manifest.get("entries", [])
    # split manifest targets into files vs directories (skills scaffold as directories)
    file_targets: Dict[str, Dict] = {}
    dir_targets: Dict[str, Dict] = {}
    for e in entries:
        tp = target / e["target"]
        (dir_targets if tp.is_dir() else file_targets)[e["target"]] = e

    def under_dir_target(rel: str) -> bool:
        return any(rel == d or rel.startswith(d + "/") for d in dir_targets)

    candidates: List[Dict] = []

    # directory-level entries (skills): one changed candidate per whole skill
    for rel, entry in sorted(dir_targets.items()):
        if bl.sha256_file(target / rel) != entry.get("hash"):
            candidates.append({
                "status": "changed", "feature": entry["feature"], "path": rel,
                "name": entry["name"], "originStack": entry["stack"],
                "originSource": entry["source"],
            })

    # file-level entries + genuinely new files in managed dirs
    for subdir, feature in MANAGED.items():
        base = aib / subdir
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(target).as_posix()
            if under_dir_target(rel):
                continue  # part of a scaffolded skill dir — handled above
            entry = file_targets.get(rel)
            if entry is None:
                candidates.append({
                    "status": "new", "feature": feature,
                    "path": rel, "name": f.stem,
                    "suggestedGeneralization": (
                        "review for project-specific tokens before contributing"
                    ),
                })
            elif bl.sha256_file(f) != entry.get("hash"):
                candidates.append({
                    "status": "changed", "feature": feature, "path": rel,
                    "name": entry["name"], "originStack": entry["stack"],
                    "originSource": entry["source"],
                })

    print(json.dumps({
        "frameworkVersion": manifest.get("frameworkVersion"),
        "candidateCount": len(candidates),
        "candidates": candidates,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
