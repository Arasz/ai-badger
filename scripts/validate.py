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
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl

KIND_TO_SCHEMA = {
    "config": "config.schema.json",
    "manifest": "manifest.schema.json",
    "index": "index.schema.json",
    "plugins": "plugins.schema.json",
    "marketplaces": "marketplaces.schema.json",
}

PROVENANCE_KEYS = ("frameworkCommit", "frameworkDirty")

PROVENANCE_HINT = (
    "This manifest predates ai-badger 0.2.0, which requires provenance keys "
    "(frameworkCommit, frameworkDirty). There is no migration by design — "
    "re-scaffold with welcome-ai-badger to upgrade it. Seed-once files "
    "(state.json, markers-context.json) are preserved across a re-scaffold; "
    "review the diff before committing. See docs/adr/0001-versioning-and-release-model.md."
)


def provenance_hint(errors: List[str]) -> Optional[str]:
    """Return an actionable upgrade hint when errors are missing-provenance-key errors."""
    if any(key in err and "is a required property" in err
           for err in errors for key in PROVENANCE_KEYS):
        return PROVENANCE_HINT
    return None


def _report(label: str, errors) -> bool:
    if errors:
        print(f"INVALID  {label}")
        for e in errors:
            print(f"    - {e}")
        hint = provenance_hint(errors)
        if hint:
            print(f"    → {hint}")
        return False
    print(f"ok       {label}")
    return True


def validate_all(root: Path) -> int:
    """Validate index.json, every stack's plugins/marketplaces JSON, and the schemas themselves."""
    ok = True
    ok &= _report("schemas self-check", bl.check_schemas_selfvalid(root / "schemas"))
    idx = root / "index.json"
    if idx.exists():
        ok &= _report("index.json", bl.validate_file(idx, root / "schemas" / "index.schema.json"))
    # each stack's single plugins.json + marketplaces.json
    for _stack, feature, fdir in bl.iter_feature_dirs(root):
        if feature != "plugins":
            continue
        pj = fdir / "plugins.json"
        if pj.exists():
            ok &= _report(str(pj.relative_to(root)),
                          bl.validate_file(pj, root / "schemas" / "plugins.schema.json"))
        mj = fdir / "marketplaces.json"
        if mj.exists():
            ok &= _report(str(mj.relative_to(root)),
                          bl.validate_file(mj, root / "schemas" / "marketplaces.schema.json"))
    return 0 if ok else 1


def main(argv=None) -> int:
    """CLI entry point: validate one instance (--schema/--kind) or the whole tree (--all)."""
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

    schema_path = None
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
