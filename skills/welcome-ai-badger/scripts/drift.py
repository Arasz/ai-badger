#!/usr/bin/env python3
"""Report how a scaffolded project has diverged from the framework catalog.

Tier 2 of ADR-0001 decision 5: the expensive per-entry hash walk, run explicitly.
Tier 1 (the cheap version comparison) lives in the task skill's SessionStart hook,
because welcome-ai-badger is plugin-only and is not scaffolded into a project.

Known limitations, accepted rather than solved: an upstream rename reads as "removed",
because a manifest entry's source is a path with no forwarding record; and newly-added
catalog items are invisible, because this walks the manifest rather than the catalog.

Exit code 0 == no drift, 1 == drift found, 2 == usage error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List


def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "scripts" / "badger_lib.py"
        if cand.exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    raise RuntimeError("could not locate ai-badger scripts/badger_lib.py")


_bootstrap_lib()
import badger_lib as bl  # pylint: disable=wrong-import-position


def compare(root: Path, target: Path) -> Dict[str, List[str]]:
    """Diff a target's manifest against the framework's current catalog content."""
    manifest: Dict[str, Any] = bl.load_json(target / ".ai-badger" / "manifest.json")
    changed: List[str] = []
    removed: List[str] = []
    recorded = set()
    for entry in manifest.get("entries", []):
        source_rel = entry["source"]
        recorded.add(source_rel)
        source = root / source_rel
        if not source.exists():
            removed.append(source_rel)
            continue
        if source.is_file() and bl.sha256_file(source) != entry["hash"]:
            changed.append(source_rel)
    return {"changed": sorted(changed), "removed": sorted(removed)}


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="framework repo root (default: autodetect)")
    parser.add_argument("--target", required=True, help="scaffolded project root")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()
    target = Path(args.target).resolve()
    manifest_path = target / ".ai-badger" / "manifest.json"
    if not manifest_path.exists():
        print(f"no manifest at {manifest_path} — is this a scaffolded project?")
        return 2

    manifest = bl.load_json(manifest_path)
    scaffold_version = manifest.get("frameworkVersion", "?")
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    print(f"scaffolded from {scaffold_version}; framework here is {current_version}")

    result = compare(root, target)
    for label in ("changed", "removed"):
        for path in result[label]:
            print(f"  {label:8} {path}")
    if not result["changed"] and not result["removed"]:
        print("no drift — every scaffolded item matches the framework's current content")
        return 0
    print("re-scaffold with welcome-ai-badger to pick these up; review the diff before committing")
    return 1


if __name__ == "__main__":
    sys.exit(main())
