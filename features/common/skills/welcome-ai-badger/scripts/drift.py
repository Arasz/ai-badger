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
    # Fallback: check cached framework repo at ~/.ai-badger/framework/
    cache = Path.home() / ".ai-badger" / "framework"
    cache_scripts = cache / "scripts" / "badger_lib.py"
    if cache_scripts.exists() and (cache / "schemas").is_dir():
        sys.path.insert(0, str(cache / "scripts"))
        return
    raise RuntimeError(
        "could not locate ai-badger scripts/badger_lib.py locally or at "
        f"{cache} — run with --root <framework> or clone https://github.com/Arasz/ai-badger"
    )


_bootstrap_lib()
import badger_lib as bl  # pylint: disable=wrong-import-position


def detect_new_items(root: Path, manifest: Dict[str, Any],
                     stacks: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Find catalog items in index.json that are not in the manifest.

    Only checks stacks the project actually uses (from config.stacks).
    Returns list of {name, feature, stack, path} for items not scaffolded.
    """
    index_path = root / "index.json"
    if not index_path.exists():
        return []

    try:
        index = bl.load_json(index_path)
    except (ValueError, OSError):
        return []

    # Build set of (stack, feature, name) from manifest
    manifest_keys = set()
    for entry in manifest.get("entries", []):
        manifest_keys.add((entry.get("stack"), entry.get("feature"), entry.get("name")))

    check_stacks = set(stacks) if stacks else set()
    new_items: List[Dict[str, Any]] = []

    for stack_name, stack_data in index.get("stacks", {}).items():
        if stack_name not in check_stacks:
            continue
        # Features that can have new items (skip meta)
        for feature in ("skills", "personas", "invariants", "instructions", "hooks", "adjustments"):
            items = stack_data.get(feature, [])
            for item in items:
                key = (stack_name, feature, item.get("name"))
                if key not in manifest_keys:
                    new_items.append({
                        "name": item["name"],
                        "feature": feature,
                        "stack": stack_name,
                        "path": item.get("path", ""),
                    })

    return sorted(new_items, key=lambda x: (x["stack"], x["feature"], x["name"]))


def compare(root: Path, manifest: Dict[str, Any],
            stacks: Optional[List[str]] = None) -> Dict[str, Any]:
    """Diff an already-parsed manifest against the framework's current catalog content.

    When `stacks` is provided, also detects new items via index.json.

    Directory entries (skills) are compared using dir_content_hash() with a
    two-phase approach: structural pre-check (file/dir counts) then content hash.
    Files matching SKILL_EXCLUDE_PATTERNS are excluded from the hash.
    """
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
            # Directory entry — use content hash with structural pre-check
            try:
                fingerprint = bl.dir_content_hash(source, exclude=bl.SKILL_EXCLUDE_PATTERNS)
            except (ValueError, OSError):
                skipped.append(source_rel)
                continue
            dir_meta = entry.get("dirMeta")
            if dir_meta:
                # Phase 1: structural pre-check (cheap)
                if (fingerprint["file_count"] != dir_meta.get("file_count")
                        or fingerprint["dir_count"] != dir_meta.get("dir_count")):
                    changed.append(source_rel)
                    continue
            # Phase 2: content hash comparison
            if fingerprint["content_hash"] != entry_hash:
                changed.append(source_rel)
            # If hashes match, no drift — don't add to skipped
            continue
        if bl.sha256_file(source) != entry_hash:
            changed.append(source_rel)
    result = {
        "changed": sorted(changed),
        "removed": sorted(removed),
        "skipped": sorted(skipped),
        "invalid": invalid,
    }
    if stacks is not None:
        result["newItems"] = detect_new_items(root, manifest, stacks)
    return result


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

    # Read config for stacks (needed for new items detection)
    config_path = target / ".ai-badger" / "config.json"
    stacks = []
    if config_path.exists():
        try:
            config = bl.load_json(config_path)
            stacks = config.get("stacks", [])
        except (ValueError, OSError):
            pass

    result = compare(root, manifest, stacks=stacks if stacks else None)
    for label in ("changed", "removed"):
        for path in result[label]:
            print(f"  {label:8} {path}")
    if result.get("newItems"):
        for item in result["newItems"]:
            print(f"  new      {item['stack']}/{item['feature']}/{item['name']}")
    if result["skipped"]:
        print("skipped entries are directory-valued: the recorded hash covers the scaffolded "
              "copy, which excludes tests/evals — not comparable to the source tree")
        for path in result["skipped"]:
            print(f"  skipped  {path}")
    if result["invalid"]:
        n = result["invalid"]
        print(f"  invalid  {n} manifest entr{'y' if n == 1 else 'ies'} missing source/hash "
              "— not checked")

    has_drift = bool(result["changed"] or result["removed"] or result.get("newItems"))
    if not has_drift:
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
