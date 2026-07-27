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
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap_lib() -> Path:
    """Put the framework's scripts/ on sys.path and return its root.

    One predicate, shared with badger_lib.is_framework_root: schemas/ + features/ +
    scripts/badger_lib.py. Ordered inputs: --root, $AI_BADGER, an ancestor walk, the root
    recorded in a nearby .ai-badger/manifest.json, then ~/.ai-badger/framework (ADR-0007).
    Duplicated verbatim in every entry point because locating badger_lib is what it is for.
    """
    def is_root(path):
        return ((path / "schemas").is_dir() and (path / "features").is_dir()
                and (path / "scripts" / "badger_lib.py").is_file())

    def declared():
        argv = sys.argv[1:]
        for i, arg in enumerate(argv):
            if arg == "--root" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--root="):
                return arg.split("=", 1)[1]
        return os.environ.get("AI_BADGER")

    def recorded(start):
        for anc in [start, *start.parents]:
            manifest = (anc / "manifest.json" if anc.name == ".ai-badger"
                        else anc / ".ai-badger" / "manifest.json")
            if not manifest.is_file():
                continue
            try:
                value = json.loads(manifest.read_text(encoding="utf-8")).get("frameworkRoot")
            except (OSError, ValueError):
                continue
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = manifest.parent.parent / candidate
            if is_root(candidate):
                return candidate.resolve()
        return None

    def working_dir():
        try:
            return Path.cwd().resolve()
        except OSError:
            return here

    here = Path(__file__).resolve()
    cache = Path.home() / ".ai-badger" / "framework"
    value = declared()
    if value:
        root = Path(value).expanduser()
        if not is_root(root):
            raise RuntimeError(
                f"--root/$AI_BADGER is {root}, which is not an ai-badger framework root "
                f"(no schemas/ + features/ + scripts/badger_lib.py)"
            )
    else:
        root = next((anc for anc in [here, *here.parents] if is_root(anc)), None)
        root = root or recorded(here) or recorded(working_dir())
        root = root or (cache if is_root(cache) else None)
    if root is None:
        raise RuntimeError(
            f"could not locate the ai-badger framework: none above {here.parent}, no "
            f"$AI_BADGER, no frameworkRoot in a nearby .ai-badger/manifest.json, and no "
            f"cache at {cache} — pass --root <framework> or clone "
            f"https://github.com/Arasz/ai-badger"
        )
    sys.path.insert(0, str(root / "scripts"))
    return root.resolve()


FRAMEWORK_ROOT = _bootstrap_lib()
import badger_lib as bl  # pylint: disable=wrong-import-position


def _load_script(relpath: str, base: Path):
    """Import an ai-badger script by repo-relative path."""
    candidates = [base]
    script_repo = Path(__file__).resolve()
    for anc in script_repo.parents:
        if (anc / "scripts" / "badger_lib.py").exists() and (anc / "schemas").is_dir():
            candidates.append(anc)
            break
    for cand in candidates:
        path = cand / relpath
        if path.exists():
            name = "aib_" + path.stem
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError(f"could not find {relpath} in {candidates}")


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
        # Feature types the registry marks as reportable (skips index "meta")
        for feature in bl.DRIFT_NEW_FEATURES:
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


def detect_new_stacks(target: Path, root: Path,
                      config_stacks: Optional[List[str]] = None,
                      ignore: Optional[List[str]] = None) -> List[str]:
    """Find stacks that have detection signals in the target but are missing from config.

    Reuses detect.py's detection logic against the framework index, then returns
    only stacks that are in the index but not in the project's current config.
    Stacks in the ignore list are excluded from results.
    """
    index_path = root / "index.json"
    if not index_path.exists():
        return []

    try:
        index = bl.load_json(index_path)
    except (ValueError, OSError):
        return []

    # Load detect.py and run stack detection against the target
    detect_mod = _load_script(
        "features/common/skills/welcome-ai-badger/scripts/detect.py", root
    )
    detected = detect_mod.detect_stacks(target, index)
    detected = detect_mod.expand_requires(detected, index)

    # Filter to stacks known by the index but missing from config
    known = set(index.get("stacks", {}).keys())
    current = set(config_stacks or [])
    ignored = set(ignore or [])
    return [s for s in detected if s in known and s not in current and s not in ignored]


def _within(parent: Path, candidate: Path) -> bool:
    """True when `candidate` resolves to `parent` itself or something inside it."""
    try:
        candidate.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def compare(root: Path, manifest: Dict[str, Any],
            stacks: Optional[List[str]] = None,
            target: Optional[Path] = None) -> Dict[str, Any]:
    """Diff an already-parsed manifest against the framework's current catalog content.

    When ``target`` is provided, directory entries (skills) are hashed from the
    scaffolded output directory — matching what ``scaffold.record()`` wrote into
    the manifest.  This avoids false drift when extensions are pruned by config.
    Falls back to hashing the framework source when ``target`` is None or the
    target path doesn't exist.

    When ``stacks`` is provided, also detects new items via index.json.
    """
    changed: List[str] = []
    removed: List[str] = []
    skipped: List[str] = []
    notes: List[str] = []
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
            # Directory entry — hash from the scaffolded target when available,
            # matching scaffold.record() which hashes the target with extensions excluded.
            hash_dir = source
            exclude = bl.SKILL_EXCLUDE_PATTERNS
            if target is not None:
                target_rel = entry.get("target")
                if target_rel:
                    target_path = target / target_rel
                    if not _within(target, target_path):
                        # `Path("/a") / "/etc"` is `/etc`: an absolute or traversing manifest
                        # target would steer the hasher out of the project (security I1).
                        notes.append(
                            f"manifest entry {source_rel}: target resolves outside the "
                            f"project — hashing the framework source instead"
                        )
                    elif target_path.is_dir():
                        hash_dir = target_path
                        exclude = bl.SKILL_EXCLUDE_PATTERNS + ["extensions"]
            try:
                fingerprint = bl.dir_content_hash(hash_dir, exclude=exclude)
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
        "notes": notes,
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

    result = compare(root, manifest, stacks=stacks if stacks else None, target=target)
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
