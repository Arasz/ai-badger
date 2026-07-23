#!/usr/bin/env python3
"""Regenerate index.json by scanning the ai-badger framework tree.

index.json is the source of truth consumed by welcome-ai-badger / feed-badger. Run this
after ANY change to framework content. Mechanical; no LLM, no network.
Feature discovery rules per <stack>/<feature>/:
  skills        -> each subdir containing SKILL.md
  personas      -> each *.md (excluding README.md), name = stem
  invariants    -> each *.md (excluding README.md), name = stem
  instructions  -> each *.md (excluding README.md), name = stem
  plugins       -> each subdir containing plugins.json
  templates     -> each top-level file/dir (common only)

Common skills live at features/common/skills/ and are discovered by iter_feature_dirs
like any other stack feature.

Skill extensions: a dir at <stack>/skills/<base>-extensions/<ext>/ attaches <ext> to the
skill named <base> (searched across stacks). Per-stack metadata is read from
<stack>/stack.json (validated against schemas/stack.schema.json when present).

Usage: index_build.py [--root <dir>] [--check]
  --check : do not write; exit 1 if index.json is missing or stale.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl

VERSION_FILE = "VERSION"


def _framework_version(root: Path) -> str:
    vf = root / VERSION_FILE
    if vf.exists():
        return vf.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _md_items(fdir: Path, root: Path):
    items = []
    for f in sorted(fdir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        items.append({"name": f.stem, "path": f.relative_to(root).as_posix()})
    return items


def _skill_items(fdir: Path, root: Path):
    items = []
    for d in sorted(p for p in fdir.iterdir() if p.is_dir()):
        if d.name.endswith("-extensions"):
            continue
        if (d / "SKILL.md").exists():
            items.append({"name": d.name, "path": d.relative_to(root).as_posix()})
    return items


def _plugin_items(fdir: Path, root: Path):
    """One index item per plugin listed in the single <stack>/plugins/plugins.json."""
    pj = fdir / "plugins.json"
    if not pj.exists():
        return []
    rel = pj.relative_to(root).as_posix()
    data = bl.load_json(pj)
    return [{"name": p["name"], "path": rel} for p in data.get("plugins", [])]


def _template_items(fdir: Path, root: Path):
    return [{"name": p.name, "path": p.relative_to(root).as_posix()}
            for p in sorted(fdir.iterdir()) if p.name != "README.md"]


def build_index(root: Path) -> dict:
    """Scan the framework tree under `root` and return the assembled index.json contents."""
    stacks: dict = {}

    def ensure(stack: str) -> dict:
        return stacks.setdefault(stack, {})

    for stack, feature, fdir in bl.iter_feature_dirs(root):
        bucket = ensure(stack)
        if feature == "skills":
            items = _skill_items(fdir, root)
        elif feature == "plugins":
            items = _plugin_items(fdir, root)
        elif feature == "templates":
            items = _template_items(fdir, root)
        else:  # personas / invariants / instructions
            items = _md_items(fdir, root)
        if items:
            bucket[feature] = items

    # skill extensions: features/<stack>/skills/<base>-extensions/<ext>/
    for stack_dir in sorted(p for p in (root / "features").iterdir() if p.is_dir()):
        sk = stack_dir / "skills"
        if not sk.is_dir():
            continue
        for extroot in sorted(
            p for p in sk.iterdir() if p.is_dir() and p.name.endswith("-extensions")
        ):
            base = extroot.name[: -len("-extensions")]
            exts = [d.name for d in sorted(p for p in extroot.iterdir() if p.is_dir())]
            if not exts:
                continue
            for _s, b in stacks.items():
                for entry in b.get("skills", []):
                    if entry["name"] == base:
                        entry.setdefault("extensions", []).extend(exts)

    # per-stack metadata from features/<stack>/stack.json
    feat_root = root / "features"
    stack_names = set(stacks) | {d.name for d in feat_root.iterdir()
                                 if d.is_dir() and (d / "stack.json").exists()}
    for stack in stack_names:
        sj = feat_root / stack / "stack.json"
        if sj.exists():
            meta = bl.load_json(sj)
            meta.pop("name", None)
            ensure(stack)["meta"] = meta

    return {
        "$schema": "./schemas/index.schema.json",
        "frameworkVersion": _framework_version(root),
        "stacks": dict(sorted(stacks.items())),
    }


def main(argv=None) -> int:
    """CLI entry point: build (or --check) index.json for the framework root."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()

    index = build_index(root)
    errors = bl.validate(index, bl.load_json(root / "schemas" / "index.schema.json"))
    if errors:
        print("generated index.json FAILS its own schema:")
        for e in errors:
            print(f"    - {e}")
        return 1

    target = root / "index.json"
    if args.check:
        if not target.exists() or bl.load_json(target) != index:
            print("index.json is missing or stale — run index_build.py")
            return 1
        print("index.json up to date")
        return 0

    bl.dump_json(target, index)
    n = sum(len(v) for s in index["stacks"].values() for k, v in s.items() if k != "meta")
    print(f"wrote index.json — {len(index['stacks'])} stacks, {n} feature items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
