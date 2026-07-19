#!/usr/bin/env python3
"""Report how a scaffolded project has diverged from the framework catalog.

Tier 2 of ADR-0001 decision 5: the expensive per-entry hash walk, run explicitly.
Tier 1 (the cheap version comparison) lives in the task skill's SessionStart hook,
because welcome-ai-badger is plugin-only and is not scaffolded into a project.

Known limitations, accepted rather than solved: an upstream rename reads as "removed",
because a manifest entry's source is a path with no forwarding record; newly-added
catalog items are invisible, because this walks the manifest rather than the catalog;
and directory-valued entries (skills scaffold as directories) are not compared per-entry,
because the recorded hash covers the scaffolded copy -- produced with tests/evals stripped
and extensions embedded -- which is not a comparable artifact to the framework's source
tree. Such entries are reported as "skipped" rather than silently omitted or falsely
flagged as changed.

Exit code 0 == no drift, 1 == drift found, 2 == usage error. Skipped entries alone do not
count as drift.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def compare(root: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Diff an already-parsed manifest against the framework's current catalog content."""
    changed: List[str] = []
    removed: List[str] = []
    skipped: List[str] = []
    invalid = 0
    for entry in manifest.get("entries", []):
        source_rel = entry.get("source")
        entry_hash = entry.get("hash")
        if source_rel is None or entry_hash is None:
            invalid += 1
            continue
        source = root / source_rel
        if not source.exists():
            removed.append(source_rel)
            continue
        if source.is_dir():
            skipped.append(source_rel)
            continue
        if bl.sha256_file(source) != entry_hash:
            changed.append(source_rel)
    return {
        "changed": sorted(changed),
        "removed": sorted(removed),
        "skipped": sorted(skipped),
        "invalid": invalid,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Print drift between a scaffolded target and the framework catalog; return an exit code."""
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

    try:
        manifest = bl.load_json(manifest_path)
    except (ValueError, OSError) as exc:
        print(f"could not read manifest at {manifest_path}: {exc}")
        return 2

    scaffold_version = manifest.get("frameworkVersion", "?")
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    print(f"scaffolded from {scaffold_version}; framework here is {current_version}")

    result = compare(root, manifest)
    for label in ("changed", "removed"):
        for path in result[label]:
            print(f"  {label:8} {path}")
    if result["skipped"]:
        print("skipped entries are directory-valued: the recorded hash covers the scaffolded "
              "copy, which excludes tests/evals — not comparable to the source tree")
        for path in result["skipped"]:
            print(f"  skipped  {path}")
    if result["invalid"]:
        n = result["invalid"]
        print(f"  invalid  {n} manifest entr{'y' if n == 1 else 'ies'} missing source/hash "
              "— not checked")

    if not result["changed"] and not result["removed"]:
        if result["skipped"]:
            n = len(result["skipped"])
            entry_word = "y was" if n == 1 else "ies were"
            print(f"no drift among the entries that could be compared — "
                  f"{n} skipped entr{entry_word} not checked")
        else:
            print("no drift — every scaffolded item matches the framework's current content")
        return 0
    print("re-scaffold with welcome-ai-badger to pick these up; review the diff before committing")
    return 1


if __name__ == "__main__":
    sys.exit(main())
