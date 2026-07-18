"""Shared helpers for ai-badger scripts.

Deterministic and offline (Python 3.9+): scripts must be runnable wherever the plugin is
installed. JSON Schema validation uses the audited `jsonschema` library (see
scripts/requirements.txt) rather than a hand-rolled validator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema  # scripts/requirements.txt: jsonschema>=4
from jsonschema import Draft202012Validator

FEATURES = ["skills", "personas", "invariants", "instructions", "plugins", "templates"]


# --------------------------------------------------------------------------- roots / io
def find_root(start: Optional[Path] = None) -> Path:
    """Walk up from `start` (or this file) to the framework root: the dir holding schemas/."""
    p = (start or Path(__file__)).resolve()
    for anc in [p, *p.parents]:
        if (anc / "schemas").is_dir() and (anc / "common").is_dir():
            return anc
    raise RuntimeError("ai-badger framework root not found (no dir with schemas/ + common/)")


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                h.update(f.relative_to(path).as_posix().encode("utf-8"))
                h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()


# -------------------------------------------------------------- validation (jsonschema)
def _loc(err: "jsonschema.exceptions.ValidationError") -> str:
    path = "$" + "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path)
    return path


def validate(instance: Any, schema: Dict[str, Any]) -> List[str]:
    """Return a sorted list of human-readable validation errors (empty == valid)."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{_loc(e)}: {e.message}" for e in errors]


def validate_file(instance_path: Path, schema_path: Path) -> List[str]:
    return validate(load_json(instance_path), load_json(schema_path))


def check_schemas_selfvalid(schemas_dir: Path) -> List[str]:
    """Meta-check: every *.schema.json is itself a valid Draft 2020-12 schema."""
    problems: List[str] = []
    for sp in sorted(schemas_dir.glob("*.schema.json")):
        try:
            Draft202012Validator.check_schema(load_json(sp))
        except jsonschema.exceptions.SchemaError as exc:  # pragma: no cover
            problems.append(f"{sp.name}: {exc.message}")
    return problems


# ------------------------------------------------------------------------ catalog access
def read_index(root: Path) -> Dict[str, Any]:
    return load_json(root / "index.json")


def iter_feature_dirs(root: Path) -> List[Tuple[str, str, Path]]:
    """Yield (stack, feature, dir) for every <stack>/<feature> directory present."""
    out: List[Tuple[str, str, Path]] = []
    for stack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        stack = stack_dir.name
        # root skills/ is the installable plugin skills dir (== common.skills), handled
        # separately by index_build; never treat it as a stack.
        if stack in {".git", "schemas", "docs", "scripts", ".claude-plugin", "skills"}:
            continue
        for feature in FEATURES:
            fdir = stack_dir / feature
            if fdir.is_dir():
                out.append((stack, feature, fdir))
    return out
