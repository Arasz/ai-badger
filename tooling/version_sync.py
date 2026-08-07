#!/usr/bin/env python3
"""Sync VERSION into plugin.json, marketplace.json, and (via index_build) index.json.

`VERSION` at the framework root is the single source of truth for ai-badger's version
(see docs/adr/0001-versioning-and-release-model.md). This script keeps the other version
literals in lockstep with it:

  .claude-plugin/plugin.json       -> top-level "version"
  .claude-plugin/marketplace.json  -> "version" of every plugins[] entry named like plugin.json
  index.json                       -> "frameworkVersion"

index.json already has a dedicated generator, index_build.py, which derives frameworkVersion
from VERSION as one field among many it computes from the framework tree. Rather than add a
second writer that could disagree with it, version_sync delegates index.json entirely to
index_build.py — both for writing (calls its `main`) and for --check (calls its `--check`).
This script owns plugin.json / marketplace.json directly, since index_build.py has no
business with those (they are not part of the scanned feature tree).

Usage: version_sync.py [--root <dir>] [--check]
  --check : do not write; exit 1 if any target disagrees with VERSION.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
# Its own directory too: `index_build` is a sibling, and a bare import of one resolves only
# when something else has already put `tooling/` on the path. Running the script does that
# implicitly; importing it does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl
import index_build

PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")


def _plugin_mismatches(plugin_data: Dict[str, Any], version: str) -> List[Tuple[str, Any, str]]:
    current = plugin_data.get("version")
    if current != version:
        return [(PLUGIN_MANIFEST.as_posix(), current, version)]
    return []


def _marketplace_mismatches(
    marketplace_data: Dict[str, Any], version: str, plugin_name: str,
) -> List[Tuple[str, Any, str]]:
    mismatches: List[Tuple[str, Any, str]] = []
    for entry in marketplace_data.get("plugins", []):
        if entry.get("name") != plugin_name:
            continue
        current = entry.get("version")
        if current != version:
            label = f"{MARKETPLACE_MANIFEST.as_posix()} plugins[{entry.get('name')!r}]"
            mismatches.append((label, current, version))
    return mismatches


def sync(root: Path, version: str) -> None:
    """Write `version` into plugin.json and marketplace.json, then regenerate index.json."""
    plugin_path = root / PLUGIN_MANIFEST
    plugin_data = bl.load_json(plugin_path)
    plugin_data["version"] = version
    bl.dump_json(plugin_path, plugin_data)

    marketplace_path = root / MARKETPLACE_MANIFEST
    marketplace_data = bl.load_json(marketplace_path)
    for entry in marketplace_data.get("plugins", []):
        if entry.get("name") == plugin_data.get("name"):
            entry["version"] = version
    bl.dump_json(marketplace_path, marketplace_data)

    index_build.main(["--root", str(root)])


SCAFFOLD_MANIFEST = Path(".ai-badger/manifest.json")
# Anchored on a leading digit so prose *about* the stamp is not mistaken for one:
# CONTRIBUTING.md documents it as `Scaffolded by ai-badger <v>`. The trailing period is
# prose too — the stamp reads "Scaffolded by ai-badger 0.97.0." — so it is stripped.
STAMP_RE = re.compile(r"Scaffolded by ai-badger (\d\S*)")


def _scaffold_stamp_mismatches(root: Path, version: str) -> List[Tuple[str, Any, str]]:
    """Targets the scaffolder stamps, not this script — reported, never rewritten.

    Writing them here would assert a scaffold that never ran. The freshness guard exempts
    version stamps on purpose ("a version bump alone must not fail this"), so a release that
    skips the re-scaffold is otherwise invisible: 3 of the 14 tags in the 0.87-0.99 window
    shipped a manifest one release behind.
    """
    mismatches: List[Tuple[str, Any, str]] = []
    manifest_path = root / SCAFFOLD_MANIFEST
    if manifest_path.is_file():
        stamped = bl.load_json(manifest_path).get("frameworkVersion")
        if stamped != version:
            mismatches.append((str(SCAFFOLD_MANIFEST) + ":frameworkVersion", stamped, version))
    seen = {}
    for pattern in ("*.md", ".*.md", ".ai-badger/*.md", ".github/*.md"):
        for found_path in root.glob(pattern):
            seen[found_path.resolve()] = found_path
    for path in sorted(seen.values()):
        try:
            found = STAMP_RE.search(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if found and found.group(1).rstrip(".") != version:
            mismatches.append(
                (str(path.relative_to(root)), found.group(1).rstrip("."), version))
    return mismatches


def check(root: Path, version: str) -> int:
    """Report any target whose version disagrees with VERSION; return 0 clean, 1 mismatch."""
    plugin_data = bl.load_json(root / PLUGIN_MANIFEST)
    marketplace_data = bl.load_json(root / MARKETPLACE_MANIFEST)

    mismatches = _plugin_mismatches(plugin_data, version)
    mismatches += _marketplace_mismatches(marketplace_data, version, plugin_data.get("name"))
    stale_stamps = _scaffold_stamp_mismatches(root, version)

    if mismatches:
        print(f"version literals disagree with VERSION ({version!r}):")
        for label, current, expected in mismatches:
            print(f"    - {label}: {current!r} (expected {expected!r})")

    if stale_stamps:
        print(f"the scaffold stamps disagree with VERSION ({version!r}) — the re-scaffold step "
              f"was skipped; re-run welcome-ai-badger and commit the result:")
        for label, current, expected in stale_stamps:
            print(f"    - {label}: {current!r} (expected {expected!r})")

    index_rc = index_build.main(["--root", str(root), "--check"])

    if mismatches or stale_stamps or index_rc != 0:
        return 1
    print("version literals up to date")
    return 0


def main(argv=None) -> int:
    """CLI entry point: sync (default) or --check the version literals against VERSION."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()

    try:
        version = bl.read_version(root)
    except bl.MissingVersion as exc:
        print(f"VERSION SYNC COULD NOT RUN: {exc}")
        return 1

    if args.check:
        return check(root, version)

    sync(root, version)
    print(f"synced version {version} into plugin.json, marketplace.json, index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
