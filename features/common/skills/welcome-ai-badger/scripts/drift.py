#!/usr/bin/env python3
"""Report how a scaffolded project has diverged from the framework catalog.

Tier 2 of ADR-0001 decision 5: the expensive per-entry hash walk, run explicitly.
Tier 1 (the cheap version comparison) lives in the task skill's SessionStart hook,
because welcome-ai-badger is plugin-only and is not scaffolded into a project.

Newly-added catalog items are found by `detect_new_items`, which walks index.json for the
stacks a re-scaffold would actually deliver (`badger_lib.resolve_stacks`, so the always-on
`common` stack is included).

Known limitations, accepted rather than solved: an upstream rename reads as "removed",
because a manifest entry's source is a path with no forwarding record; and
directory-valued entries (skills scaffold as directories) are not compared per-entry,
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
from typing import Any, Dict, List, Optional, Union


def _bootstrap_lib() -> Path:
    """Put the framework's scripts/ on sys.path and return its root.

    One predicate, shared with badger_lib.is_framework_root: schemas/ + features/ +
    scripts/badger_lib.py. Ordered inputs: --root, an ancestor walk, $AI_BADGER, the root
    recorded in a .ai-badger/manifest.json above this file, then ~/.ai-badger/framework
    (ADR-0009). Duplicated verbatim in every entry point because locating badger_lib is
    what it is for.
    """
    def is_root(path):
        return ((path / "schemas").is_dir() and (path / "features").is_dir()
                and (path / "scripts" / "badger_lib.py").is_file())

    def argv_root():
        # sys.argv is ours only when this file is the program being run; these modules are
        # also imported into hosts whose own --root means something else entirely.
        try:
            if not sys.argv or Path(sys.argv[0]).resolve() != Path(__file__).resolve():
                return None
        except (OSError, ValueError):
            return None
        argv = sys.argv[1:]
        for i, arg in enumerate(argv):
            if arg == "--root" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--root="):
                return arg.split("=", 1)[1]
        return None

    def checked(value, source):
        root = Path(value).expanduser()
        if not is_root(root):
            raise RuntimeError(
                f"{source} is {root}, which is not an ai-badger framework root "
                f"(no schemas/ + features/ + scripts/badger_lib.py)"
            )
        return root

    def recorded(start):
        # Above this file only. A working directory belongs to whatever repo the user
        # opened, and no repo may steer the sys.path of a hook that runs on session start.
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

    here = Path(__file__).resolve()
    cache = Path.home() / ".ai-badger" / "framework"
    value = argv_root()
    if value:
        root = checked(value, "--root")
    else:
        root = next((anc for anc in [here, *here.parents] if is_root(anc)), None)
        if root is None and os.environ.get("AI_BADGER"):
            root = checked(os.environ["AI_BADGER"], "$AI_BADGER")
        root = root or recorded(here) or (cache if is_root(cache) else None)
    if root is None:
        raise RuntimeError(
            f"could not locate the ai-badger framework: none above {here.parent}, no "
            f"$AI_BADGER, no frameworkRoot in a .ai-badger/manifest.json above it, and no "
            f"cache at {cache} — pass --root <framework> or clone "
            f"https://github.com/Arasz/ai-badger"
        )
    sys.path.insert(0, str(root / "scripts"))
    return root.resolve()


FRAMEWORK_ROOT = _bootstrap_lib()
import badger_lib as bl  # pylint: disable=wrong-import-position


def _load_script(relpath: str, base: Path):
    """Import an ai-badger script by repo-relative path: `base` first, then the resolved root.

    A mock framework passed as `base` need not carry every script, so the root this module
    already bootstrapped from is the fallback — never a second root search.
    """
    candidates = [base] if base == FRAMEWORK_ROOT else [base, FRAMEWORK_ROOT]
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
                     stacks: Union[str, List[str], None] = None,
                     exclude: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Find catalog items in index.json that are not in the manifest.

    `stacks` is what a re-scaffold would deliver — `badger_lib.resolve_stacks(config)`, not
    `config.stacks`, which never names the always-on `common` stack. A bare string is one
    stack name, not five letters. `exclude` is the project's own `config.exclude`: a declined
    item is absent from the manifest by design and must not be reported as new, or every
    refresh nags to install what the project said no to. Returns {name, feature, stack, path}
    per unscaffolded item.
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

    check_stacks = {stacks} if isinstance(stacks, str) else set(stacks or ())
    declined = exclude or {}
    new_items: List[Dict[str, Any]] = []

    for stack_name, stack_data in index.get("stacks", {}).items():
        if stack_name not in check_stacks:
            continue
        # Feature types the registry marks as reportable (skips index "meta")
        for feature in bl.DRIFT_NEW_FEATURES:
            items = stack_data.get(feature, [])
            for item in items:
                if item.get("name") in (declined.get(feature) or ()):
                    continue
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


def project_exclusions(target: Optional[Path]) -> Dict[str, Any]:
    """What a scaffolded project's own config.json declines; empty when there is none to read.

    Read from the target rather than passed in, so every caller of `compare` reports the
    project's declarations without having to know they exist.
    """
    if target is None:
        return {}
    config_path = target / ".ai-badger" / "config.json"
    if not config_path.is_file():
        return {}
    try:
        return bl.exclusions(bl.load_json(config_path))
    except (ValueError, OSError):
        return {}


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

    When ``stacks`` is provided, also detects new items via index.json — minus whatever the
    project's own config.json declines in ``exclude``.
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
    # De-duplicated: adjustments record one entry per written file, all naming one source
    # script, so a single upstream edit would otherwise print the same line ten times.
    result = {
        "changed": sorted(set(changed)),
        "removed": sorted(set(removed)),
        "skipped": sorted(set(skipped)),
        "invalid": invalid,
        "notes": notes,
    }
    if stacks is not None:
        result["newItems"] = detect_new_items(root, manifest, stacks,
                                              exclude=project_exclusions(target))
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
            stacks = bl.resolve_stacks(config)
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
