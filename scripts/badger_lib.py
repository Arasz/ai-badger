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
    """Walk up from `start` (or this file) to the framework root: the dir holding
    schemas/ + features/."""
    p = (start or Path(__file__)).resolve()
    for anc in [p, *p.parents]:
        if (anc / "schemas").is_dir() and (anc / "features").is_dir():
            return anc
    raise RuntimeError("ai-badger framework root not found (no dir with schemas/ + features/)")


def load_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, data: Any) -> None:
    """Write `data` as pretty-printed, newline-terminated JSON."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 digest of `text`."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's bytes, or of a dir's tree (name + content)."""
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
    """Load both JSON files and validate the instance against the schema."""
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
    """Load the framework's generated index.json."""
    return load_json(root / "index.json")


def iter_feature_dirs(root: Path) -> List[Tuple[str, str, Path]]:
    """Yield (stack, feature, dir) for every features/<stack>/<feature> directory present.

    Common skills live at features/common/skills/ and are discovered here like any other
    stack feature — no special-casing needed.
    """
    out: List[Tuple[str, str, Path]] = []
    features_root = root / "features"
    if not features_root.is_dir():
        return out
    for stack_dir in sorted(p for p in features_root.iterdir() if p.is_dir()):
        stack = stack_dir.name
        for feature in FEATURES:
            fdir = stack_dir / feature
            if fdir.is_dir():
                out.append((stack, feature, fdir))
    return out
