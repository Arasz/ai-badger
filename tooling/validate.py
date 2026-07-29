#!/usr/bin/env python3
"""Validate an ai-badger JSON model against its schema.

Usage:
  validate.py <instance.json> [--schema <schema.json>]
  validate.py --kind {config|manifest|index|skills-source|skills|plugins-instructions|adjustment|hooks-manifest|learned-skills} <instance.json>
  validate.py --all         # validate index.json + all feature data + self-check schemas

Exit code 0 == valid, 1 == invalid, 2 == usage error. Mechanical; no LLM, no network.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

KIND_TO_SCHEMA = {
    "config": "config.schema.json",
    "manifest": "manifest.schema.json",
    "index": "index.schema.json",
    "skills-source": "skills-source.schema.json",
    "skills": "skills.schema.json",
    "plugins-instructions": "plugins-instructions.schema.json",
    "adjustment": "adjustment.schema.json",
    "hooks-manifest": "hooks-manifest.schema.json",
    "learned-skills": "learned-skills.schema.json",
}

# Every catalog file --all validates, as root-relative globs per schema. Adding a schema
# without a line here fails test_every_schema_has_a_coverage_decision.
SCHEMA_INSTANCES = {
    "index.schema.json": ["index.json"],
    "skills-source.schema.json": ["features/*/skills-source.json"],
    "skills.schema.json": ["features/*/skills.json"],
    "hooks-manifest.schema.json": ["features/*/hooks/hooks-manifest.json"],
    "adjustment.schema.json": ["features/*/adjustments/adjustment.json"],
    "plugins-instructions.schema.json": ["features/*/plugins-instructions.json"],
    "mcp-servers.schema.json": ["features/*/mcp-servers.json"],
    "external-tools.schema.json": ["features/*/external-tools.json"],
    "stack.schema.json": ["features/*/stack.json"],
    "dependencies.schema.json": ["features/*/dependencies.json"],
    "scaffolding.schema.json": ["features/*/scaffolding.json"],
    "support.schema.json": ["features/*/support.json"],
    "model.schema.json": ["features/*/agent-instructions/model.json"],
}

# Schemas with no instance in this repo, and why. Listed so the completeness check stays
# honest rather than silently shrinking.
SCHEMAS_WITHOUT_LOCAL_INSTANCES = {
    "config.schema.json": "instances live in consumer projects (.ai-badger/config.json)",
    "manifest.schema.json": "instances live in consumer projects (.ai-badger/manifest.json)",
    "learned-skills.schema.json": "instances live in consumer projects (skills-data/)",
    "agents.schema.json": "vocabulary schema, referenced by others; no standalone instance",
    "mcp-tools.schema.json": "instances live in consumer projects (.ai-badger/mcp-tools.json)",
}

PROVENANCE_KEYS = ("frameworkCommit", "frameworkDirty")

PROVENANCE_HINT = (
    "This manifest predates ai-badger 0.2.0, which requires provenance keys "
    "(frameworkCommit, frameworkDirty). There is no migration by design — "
    "re-scaffold with welcome-ai-badger to upgrade it. Seed-once files "
    "(state.json, markers-context.json, agent-instructions/model.json) are preserved "
    "across a re-scaffold; "
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


def undecided_schemas(root: Path) -> List[str]:
    """Schemas in schemas/ that SCHEMA_INSTANCES and the exemption list both ignore."""
    shipped = {p.name for p in (root / "schemas").glob("*.schema.json")}
    decided = set(SCHEMA_INSTANCES) | set(SCHEMAS_WITHOUT_LOCAL_INSTANCES)
    return sorted(shipped - decided)


def validate_all(root: Path) -> int:
    """Validate every catalog file SCHEMA_INSTANCES maps, plus the schemas themselves."""
    ok = True
    ok &= _report("schemas self-check", bl.check_schemas_selfvalid(root / "schemas"))

    undecided = undecided_schemas(root)
    if undecided:
        ok &= _report("schema coverage",
                      [f"{name} validates nothing: add it to SCHEMA_INSTANCES or to "
                       f"SCHEMAS_WITHOUT_LOCAL_INSTANCES with a reason" for name in undecided])

    for schema_name, patterns in sorted(SCHEMA_INSTANCES.items()):
        schema_path = root / "schemas" / schema_name
        if not schema_path.is_file():
            ok &= _report(f"schemas/{schema_name}", ["declared in SCHEMA_INSTANCES but missing"])
            continue
        for pattern in patterns:
            for instance in sorted(root.glob(pattern)):
                ok &= _report(str(instance.relative_to(root)),
                              bl.validate_file(instance, schema_path))
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
