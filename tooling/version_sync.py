#!/usr/bin/env python3
"""Sync VERSION into plugin.json, marketplace.json, the model-groups registry, and (via
index_build) index.json.

`VERSION` at the framework root is the single source of truth for ai-badger's version
(see docs/adr/0001-versioning-and-release-model.md). This script keeps the other version
literals in lockstep with it:

  .claude-plugin/plugin.json       -> top-level "version"
  .claude-plugin/marketplace.json  -> "version" of every plugins[] entry named like plugin.json
  index.json                       -> "frameworkVersion" (via index_build)
  every other shipped *.json with a top-level "frameworkVersion" -> that field (N-1)

index.json already has a dedicated generator, index_build.py, which derives frameworkVersion
from VERSION as one field among many it computes from the framework tree. Rather than add a
second writer that could disagree with it, version_sync delegates index.json entirely to
index_build.py — both for writing (calls its `main`) and for --check (calls its `--check`).
This script owns plugin.json / marketplace.json directly, since index_build.py has no
business with those (they are not part of the scanned feature tree).

The remaining "*.json with frameworkVersion" targets (features/common/data/model-groups.json
today) are DERIVED, not hand-listed (N-1): a hand list drifts the moment a new such file
appears and nobody remembers to add it — exactly how model-groups.json itself went unstamped
for four releases. `stamp_targets()` walks the same shipped roots release_guard diffs against
(`tooling/release_paths.py`), so the two readers agree on what "shipped" means (R42); this
module never imports from `gates/`.

Usage: version_sync.py [--root <dir>] [--check]
  --check : do not write; exit 1 if any target disagrees with VERSION.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
# Its own directory too: `index_build` (and `release_paths`) are siblings, and a bare import
# of one resolves only when something else has already put `tooling/` on the path. Running
# the script does that implicitly; importing it does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl
import index_build
import release_paths

PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")

# The one field name a stamp target carries, shared with the scaffold manifest (N-1 uses the
# same key badger_lib already reads for it).
FRAMEWORK_VERSION_KEY = bl.MANIFEST_VERSION_KEY
# index.json is index_build's own target (see module docstring) — explicitly excepted so
# the derivation below never fights it for ownership.
INDEX_JSON = "index.json"


def _plugin_mismatches(plugin_data: Dict[str, Any], version: str) -> List[Tuple[str, Any, str]]:
    current = plugin_data.get("version")
    if current != version:
        return [(PLUGIN_MANIFEST.as_posix(), current, version)]
    return []


def _marketplace_mismatches(
    marketplace_data: Dict[str, Any], version: str, plugin_name: str,
) -> List[Tuple[str, Any, str]]:
    mismatches: List[Tuple[str, Any, str]] = []
    matched = False
    for entry in marketplace_data.get("plugins", []):
        if entry.get("name") != plugin_name:
            continue
        matched = True
        current = entry.get("version")
        if current != version:
            label = f"{MARKETPLACE_MANIFEST.as_posix()} plugins[{entry.get('name')!r}]"
            mismatches.append((label, current, version))
    if not matched:
        # L8-8: skills_lint has the same shape (a glob that finds nothing still passes) —
        # an empty or non-matching marketplace must not read as "nothing to disagree with".
        mismatches.append((
            f"{MARKETPLACE_MANIFEST.as_posix()}: no plugins[] entry named {plugin_name!r}",
            None, plugin_name,
        ))
    return mismatches


def _has_string_framework_version(path: Path) -> bool:
    try:
        data = bl.load_json(path)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get(FRAMEWORK_VERSION_KEY), str)


def _json_files_under(base: Path) -> List[Path]:
    """Every *.json a shipped root holds — the root may itself be a single file (index.json)."""
    if base.is_dir():
        return sorted(base.rglob("*.json"))
    if base.is_file() and base.suffix == ".json":
        return [base]
    return []


def _tracked_json_paths(root: Path) -> Set[str]:
    """Tracked *.json paths under the shipped roots. Empty when `root` is not a git repo."""
    proc = bl.run_git(["ls-files", "--", *release_paths.SHIPPED_PATHS], root)
    if proc.returncode != 0:
        return set()
    return {p for p in proc.stdout.splitlines() if p.strip().endswith(".json")}


def stamp_targets(root: Path) -> List[Path]:
    """Every tracked-or-present shipped *.json with a top-level string frameworkVersion (N-1).

    "Tracked-or-present" is a union, not an intersection: a file just added and not yet
    committed must still be found (a plain `git status` alone would miss it), and a still-
    tracked file that is simply absent from this checkout cannot be stamped either way.
    `index.json` is explicitly excepted — it is index_build's own target (module docstring).
    """
    candidates: Set[Path] = set()
    for rel in release_paths.SHIPPED_PATHS:
        for found in _json_files_under(root / rel):
            candidates.add(found.relative_to(root))
    for tracked in _tracked_json_paths(root):
        candidates.add(Path(tracked))

    targets = []
    for rel in sorted(candidates, key=lambda p: p.as_posix()):
        if rel.as_posix() == INDEX_JSON:
            continue
        full = root / rel
        if full.is_file() and _has_string_framework_version(full):
            targets.append(full)
    return targets


def sync(root: Path, version: str) -> None:
    """Write `version` into plugin.json, marketplace.json, every derived stamp target, then
    regenerate index.json."""
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

    for target in stamp_targets(root):
        data = bl.load_json(target)
        if data.get(FRAMEWORK_VERSION_KEY) != version:
            data[FRAMEWORK_VERSION_KEY] = version
            bl.dump_json(target, data)

    index_build.main(["--root", str(root)])


SCAFFOLD_MANIFEST = Path(".ai-badger/manifest.json")
SCAFFOLD_DIR = SCAFFOLD_MANIFEST.parent
# Anchored on a leading digit so prose *about* the stamp is not mistaken for one:
# CONTRIBUTING.md documents it as `Scaffolded by ai-badger <v>`. The trailing period is
# prose too — the stamp reads "Scaffolded by ai-badger 0.97.0." — so it is stripped.
STAMP_RE = re.compile(r"Scaffolded by ai-badger (\d\S*)")


def _stamp_target_mismatches(root: Path, version: str) -> List[Tuple[str, Any, str]]:
    """Derived shipped-json targets (N-1) whose stamped frameworkVersion disagrees."""
    mismatches: List[Tuple[str, Any, str]] = []
    for target in stamp_targets(root):
        stamped = bl.load_json(target).get(FRAMEWORK_VERSION_KEY)
        if stamped != version:
            mismatches.append((str(target.relative_to(root)), stamped, version))
    return mismatches


def _ai_badger_json_mismatches(root: Path, version: str) -> List[Tuple[str, Any, str]]:
    """Every `.ai-badger/*.json` with a top-level string frameworkVersion (N-1).

    Reported, never rewritten by `sync()`: these are scaffold output, and writing one here
    would assert a scaffold that never ran. The freshness guard exempts version stamps on
    purpose ("a version bump alone must not fail this"), so a release that skips the
    re-scaffold is otherwise invisible: 3 of the 14 tags in the 0.87-0.99 window shipped a
    manifest one release behind.
    """
    mismatches: List[Tuple[str, Any, str]] = []
    aib_dir = root / SCAFFOLD_DIR
    if not aib_dir.is_dir():
        return mismatches
    for path in sorted(aib_dir.glob("*.json")):
        if not _has_string_framework_version(path):
            continue
        stamped = bl.load_json(path).get(FRAMEWORK_VERSION_KEY)
        if stamped != version:
            mismatches.append((str(path.relative_to(root)), stamped, version))
    return mismatches


def _scaffold_stamp_mismatches(root: Path, version: str) -> List[Tuple[str, Any, str]]:
    """Targets the scaffolder stamps, not this script — reported, never rewritten."""
    mismatches: List[Tuple[str, Any, str]] = _ai_badger_json_mismatches(root, version)
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
    mismatches += _stamp_target_mismatches(root, version)
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
