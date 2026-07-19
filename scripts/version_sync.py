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
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl
import index_build

VERSION_FILE = "VERSION"
PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")


def read_version(root: Path) -> str:
    """Read and strip the single-line VERSION file at the framework root."""
    return (root / VERSION_FILE).read_text(encoding="utf-8").strip()


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


def check(root: Path, version: str) -> int:
    """Report any target whose version disagrees with VERSION; return 0 clean, 1 mismatch."""
    plugin_data = bl.load_json(root / PLUGIN_MANIFEST)
    marketplace_data = bl.load_json(root / MARKETPLACE_MANIFEST)

    mismatches = _plugin_mismatches(plugin_data, version)
    mismatches += _marketplace_mismatches(marketplace_data, version, plugin_data.get("name"))

    if mismatches:
        print(f"version literals disagree with VERSION ({version!r}):")
        for label, current, expected in mismatches:
            print(f"    - {label}: {current!r} (expected {expected!r})")

    index_rc = index_build.main(["--root", str(root), "--check"])

    if mismatches or index_rc != 0:
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

    version = read_version(root)

    if args.check:
        return check(root, version)

    sync(root, version)
    print(f"synced version {version} into plugin.json, marketplace.json, index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
