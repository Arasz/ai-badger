"""Shared helpers for ai-badger scripts.

Deterministic and offline (Python 3.8+, the floor CI tests): scripts must be runnable wherever
the plugin is
installed. `ensure_root(allow_network=True)` is the single exception and the only function
here that may reach the network; it is opt-in and pinned to a release tag. JSON Schema
validation uses the audited `jsonschema` library (see scripts/requirements.txt) rather than
a hand-rolled validator.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema  # scripts/requirements.txt: jsonschema>=4
from jsonschema import Draft202012Validator

FEATURES = ["skills", "personas", "invariants", "instructions", "templates", "hooks", "adjustments"]

# Canonical agent list — keep in sync with schemas/agents.schema.json and
# schemas/config.schema.json agents enum.
AGENT_NAMES = ["claude", "copilot", "hermes", "junie"]


# ---------------------------------------------------------------------- breaking versions
def read_breaking_versions(root: Path) -> List[str]:
    """Read BREAKING_VERSIONS file — one semver per line, comments start with #."""
    bv = root / "BREAKING_VERSIONS"
    if not bv.exists():
        return []
    versions = []
    for line in bv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            versions.append(line)
    return versions


def _parse_semver(v: str) -> tuple:
    """Parse 'major.minor.patch' into (major, minor, patch) ints."""
    parts = v.split(".")
    return tuple(int(p) for p in parts[:3])


def is_breaking_transition(from_version: str, to_version: str, root: Path) -> bool:
    """Check if the version transition crosses a breaking version boundary.

    A transition from_version -> to_version is breaking if any version in
    BREAKING_VERSIONS satisfies from_version < breaking <= to_version.
    """
    breaking = read_breaking_versions(root)
    if not breaking:
        return False
    try:
        from_v = _parse_semver(from_version)
        to_v = _parse_semver(to_version)
    except (ValueError, IndexError):
        return False
    for bv in breaking:
        try:
            bv_v = _parse_semver(bv)
        except (ValueError, IndexError):
            continue
        if from_v < bv_v <= to_v:
            return True
    return False


# --------------------------------------------------------------------------- roots / io
FRAMEWORK_REPO = "https://github.com/Arasz/ai-badger"
FRAMEWORK_CACHE = Path.home() / ".ai-badger" / "framework"
RELEASE_TAG_PREFIX = "ai-badger--v"


class FrameworkRootNotFound(RuntimeError):
    """No usable ai-badger framework root, and none may be fetched without consent."""


def _is_root(path: Path) -> bool:
    return (path / "schemas").is_dir() and (path / "features").is_dir()


def find_root(start: Optional[Path] = None) -> Path:
    """Find the ai-badger framework root. Pure lookup: no network, ever.

    Walks up from `start` (or this file) for schemas/ + features/, then falls back to an
    already-populated ~/.ai-badger/framework/. Raises FrameworkRootNotFound if neither
    exists — fetching one is `ensure_root(..., allow_network=True)`, never a side effect
    of looking.
    """
    p = (start or Path(__file__)).resolve()
    for anc in [p, *p.parents]:
        if _is_root(anc):
            return anc

    if _is_root(FRAMEWORK_CACHE):
        return FRAMEWORK_CACHE

    raise FrameworkRootNotFound(
        f"ai-badger framework root not found above {p} and no usable cache at "
        f"{FRAMEWORK_CACHE}. Pass --root <framework checkout>, or call "
        f"ensure_root(allow_network=True) to fetch the release matching your installed "
        f"VERSION from {FRAMEWORK_REPO}."
    )


def installed_version(start: Optional[Path] = None) -> Optional[str]:
    """Read the VERSION file of the tree this code is installed in, or None."""
    p = (start or Path(__file__)).resolve()
    for anc in [p, *p.parents]:
        version_file = anc / "VERSION"
        if version_file.is_file():
            text = version_file.read_text(encoding="utf-8").strip()
            if text:
                return text
    return None


def ensure_root(start: Optional[Path] = None, allow_network: bool = False,
                version: Optional[str] = None) -> Path:
    """Find the framework root, optionally fetching the pinned release if none is present.

    Network access is opt-in and pinned: the clone targets the tag matching `version`
    (default: the installed VERSION), never an unpinned branch. See ADR-0001 decision 2.
    """
    try:
        return find_root(start)
    except FrameworkRootNotFound:
        if not allow_network:
            raise

    release = version or installed_version(start)
    if not release:
        raise FrameworkRootNotFound(
            "cannot fetch the framework: no release version is known (no VERSION file "
            "above the installed scripts). Pass version=<x.y.z> or --root <checkout>."
        )
    return _clone_pinned(release)


def _clone_pinned(version: str) -> Path:
    """Clone the framework at tag ai-badger--v{version} into FRAMEWORK_CACHE."""
    if FRAMEWORK_CACHE.exists():
        raise FrameworkRootNotFound(
            f"{FRAMEWORK_CACHE} exists but is not a usable framework root (no schemas/ + "
            f"features/). It is never updated in place — inspect it, remove it, and retry."
        )

    tag = f"{RELEASE_TAG_PREFIX}{version}"
    FRAMEWORK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["git", "clone", "--depth=1", "--branch", tag, FRAMEWORK_REPO,
             str(FRAMEWORK_CACHE)],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise FrameworkRootNotFound(f"git clone of {tag} failed: {exc}") from exc

    if result.returncode != 0:
        raise FrameworkRootNotFound(
            f"failed to clone {FRAMEWORK_REPO} at {tag}: {result.stderr.strip()}. "
            f"Releases before 0.20.0 carry no tag "
            f"(docs/incidents/2026-07-27-untagged-releases.md)."
        )
    if not _is_root(FRAMEWORK_CACHE):
        raise FrameworkRootNotFound(
            f"cloned {tag} into {FRAMEWORK_CACHE} but it has no schemas/ + features/"
        )
    return FRAMEWORK_CACHE


def load_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` via a temp file in the same directory + os.replace, preserving mode.

    An interrupted write leaves the previous content intact and no temp file behind.
    `config_guard._atomic_write` is the same contract for scripts that must load without
    badger_lib on the path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o7777 if path.exists() else None
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dump_json(path: Path, data: Any) -> None:
    """Write `data` atomically as pretty-printed, newline-terminated JSON."""
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


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


# Patterns matching scaffold.py's _test_ignore — files/dirs excluded from skill hashing.
SKILL_EXCLUDE_PATTERNS = ["tests", "test_*.py", "*_test.py", "evals", "__pycache__", "*.pyc"]


def _matches_exclude(name: str, patterns: List[str]) -> bool:
    """Check if a name matches any of the exclude glob patterns."""
    import fnmatch
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def dir_content_hash(path: Path, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
    """Compute a structural fingerprint + content hash for a directory.

    Two-phase approach for efficiency:
    1. Structural: file_count + dir_count (cheap O(n) walk)
    2. Content: SHA-256 of sorted (relative_path + file_content) for each file

    Files/dirs matching `exclude` glob patterns are skipped entirely.

    Returns:
        {"file_count": int, "dir_count": int, "content_hash": str}
    """
    if not path.is_dir():
        raise ValueError(f"Not a directory: {path}")

    exclude = exclude or []
    h = hashlib.sha256()
    file_count = 0
    dir_count = 0

    for item in sorted(path.rglob("*")):
        rel = item.relative_to(path)
        name = item.name

        # Check if any ancestor in the relative path matches exclude
        excluded = False
        for part in rel.parts:
            if _matches_exclude(part, exclude):
                excluded = True
                break
        if excluded:
            continue

        if item.is_dir():
            dir_count += 1
        elif item.is_file():
            file_count += 1
            h.update(rel.as_posix().encode("utf-8"))
            h.update(item.read_bytes())

    return {
        "file_count": file_count,
        "dir_count": dir_count,
        "content_hash": h.hexdigest(),
    }


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


DEFAULT_COMMON_STACKS = ["common"]


def resolve_stacks(config: Dict[str, Any]) -> List[str]:
    """Catalog stacks to read, always-included ones first, deduplicated in order.

    `config.commonStacks` names the always-included stack(s) — config.stacks may not
    contain them (config.schema.json forbids it), so a caller reading config.stacks
    alone never sees that catalog at all.
    """
    common = config.get("commonStacks", DEFAULT_COMMON_STACKS)
    if isinstance(common, str):
        common = [common]
    seen = set()
    return [s for s in list(common) + list(config.get("stacks", []))
            if not (s in seen or seen.add(s))]


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