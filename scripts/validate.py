#!/usr/bin/env python3
"""Validate an ai-badger JSON model against its schema.

Usage:
  validate.py <instance.json> [--schema <schema.json>]
  validate.py --kind {config|manifest|index|plugin-entry|marketplaces} <instance.json>
  validate.py --all         # validate index.json + every plugin entry + self-check schemas

Exit code 0 == valid, 1 == invalid, 2 == usage error. Mechanical; no LLM, no network.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl

KIND_TO_SCHEMA = {
    "config": "config.schema.json",
    "manifest": "manifest.schema.json",
    "index": "index.schema.json",
    "plugin-entry": "plugin-entry.schema.json",
    "marketplaces": "marketplaces.schema.json",
}


def _report(label: str, errors) -> bool:
    if errors:
        print(f"INVALID  {label}")
        for e in errors:
            print(f"    - {e}")
        return False
    print(f"ok       {label}")
    return True


def validate_all(root: Path) -> int:
    ok = True
    ok &= _report("schemas self-check", bl.check_schemas_selfvalid(root / "schemas"))
    idx = root / "index.json"
    if idx.exists():
        ok &= _report("index.json", bl.validate_file(idx, root / "schemas" / "index.schema.json"))
    # every plugin entry + its marketplaces.json
    for _stack, feature, fdir in bl.iter_feature_dirs(root):
        if feature != "plugins":
            continue
        for entry in sorted(p for p in fdir.iterdir() if p.is_dir()):
            pj = entry / "plugins.json"
            if pj.exists():
                ok &= _report(str(pj.relative_to(root)),
                              bl.validate_file(pj, root / "schemas" / "plugin-entry.schema.json"))
            mj = entry / "marketplaces.json"
            if mj.exists():
                ok &= _report(str(mj.relative_to(root)),
                              bl.validate_file(mj, root / "schemas" / "marketplaces.schema.json"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("instance", nargs="?", help="Path to the JSON instance to validate.")
    ap.add_argument("--schema", help="Explicit schema path.")
    ap.add_argument("--kind", choices=sorted(KIND_TO_SCHEMA))
    ap.add_argument("--all", action="store_true", help="Validate the whole framework tree.")
    ap.add_argument("--root", help="Framework root (default: auto-detect).")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()

    if args.all:
        return validate_all(root)

    if not args.instance:
        ap.error("provide an instance path or --all")
    inst = Path(args.instance).resolve()

    if args.schema:
        schema_path = Path(args.schema).resolve()
    elif args.kind:
        schema_path = root / "schemas" / KIND_TO_SCHEMA[args.kind]
    else:
        ap.error("provide --schema or --kind")

    ok = _report(str(inst), bl.validate_file(inst, schema_path))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
