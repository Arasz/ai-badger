#!/usr/bin/env python3
"""Sync a Hermes learned skill into a project's .ai-badger/skills/learned/ tree.

One-way, event-scoped, confined: every write lands under .ai-badger/skills/learned/ and is
recorded in .ai-badger/skills-data/hermes/learned.json.
Design: docs/design/hermes-learned-skills-sync-impl-plan.md (stages 1-3).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


try:
    FRAMEWORK_ROOT: Optional[Path] = _bootstrap_lib()
except RuntimeError:  # a hook degrades to silence; it never breaks a session
    FRAMEWORK_ROOT = None

if FRAMEWORK_ROOT is not None:
    import badger_lib as bl
    import unsafe_literals as ul
else:
    # No engine on sys.path: import still succeeds so the host's plugin load does, and every
    # entry point below declines rather than syncing without a writer or a scanner.
    bl = ul = None  # pylint: disable=invalid-name  # module aliases, not constants


class ManifestUnreadable(RuntimeError):
    """learned.json exists but cannot be parsed; overwriting it would discard its records."""


LEARNED_REL = ".ai-badger/skills/learned"
MANIFEST_REL = ".ai-badger/skills-data/hermes/learned.json"
MANIFEST_SCHEMA_REF = "../../../schemas/learned-skills.schema.json"
MANIFEST_VERSION = 1
UNCATEGORIZED = "uncategorized"

SYNC_ACTIONS = frozenset({"create", "edit", "patch", "write_file", "remove_file"})
DELETE_ACTIONS = frozenset({"delete"})

NO_FRAMEWORK = "no ai-badger framework root resolved"

# The scanner is shared with feed-badger's outbound PR path; see scripts/unsafe_literals.py.
UNSAFE_LITERAL_PATTERNS = ul.UNSAFE_LITERAL_PATTERNS if ul else ()
LITERAL_SCAN_MAX_BYTES = ul.LITERAL_SCAN_MAX_BYTES if ul else 0
UNSAFE_LITERAL_LABELS = ul.UNSAFE_LITERAL_LABELS if ul else frozenset()


def target_project(cwd: str) -> Optional[Path]:
    """Return the scaffolded project root for `cwd`, or None when it is not one (C6)."""
    if not cwd:
        return None
    project = Path(cwd)
    if not (project / ".ai-badger" / "manifest.json").is_file():
        return None
    return project.resolve()


def _is_unsafe_segment(segment: str) -> bool:
    return not segment or "/" in segment or "\\" in segment or ".." in segment


def resolve_source_dir(name: str, category: Optional[str],
                       skills_root: Path) -> Optional[Path]:
    """Locate the Hermes source directory for a skill, or None when it is absent/unsafe."""
    if _is_unsafe_segment(name or ""):
        return None
    if category is not None and _is_unsafe_segment(category):
        return None

    if category:
        candidate = skills_root / category / name
        return candidate if candidate.is_dir() else None

    direct = skills_root / name
    if direct.is_dir():
        return direct
    if not skills_root.is_dir():
        return None
    for child in sorted(skills_root.iterdir()):
        candidate = child / name
        if child.is_dir() and candidate.is_dir():
            return candidate
    return None


def _relative_parts(path: Path, base: Path) -> Optional[Tuple[str, ...]]:
    for candidate, root in ((path, base), (path.resolve(), base.resolve())):
        try:
            return candidate.relative_to(root).parts
        except ValueError:
            continue
    return None


def contains_symlink(source_dir: Path) -> bool:
    """True when any entry under a skill directory is a symlink.

    Refusal, not resolution: the scanner cannot read through a link and the target can
    change between scan and copy, so a link is never syncable (F-05).
    """
    return any(path.is_symlink() for path in source_dir.rglob("*"))


def is_syncable(source_dir: Path, skills_root: Path) -> Tuple[bool, str]:
    """Gate 4: reject escaping source dirs, and symlinks inside or above one, before a read (C2)."""
    parts = _relative_parts(source_dir, skills_root)
    if not parts:
        return False, "outside skills root"

    current = skills_root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return False, "symlink"

    try:
        source_dir.resolve().relative_to(skills_root.resolve())
    except ValueError:
        return False, "outside skills root"

    if not source_dir.is_dir():
        return False, "not a directory"
    if not (source_dir / "SKILL.md").is_file():
        return False, "no SKILL.md"
    if contains_symlink(source_dir):
        return False, "symlink"
    return True, ""


def is_framework_owned(project: Path, name: str) -> bool:
    """Gate 5: True when the framework manifest already owns a skill of that name (C7)."""
    manifest = project / ".ai-badger" / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    prefix = ".ai-badger/skills/"
    for entry in data.get("entries", []):
        target = str(entry.get("target", ""))
        if target.startswith(prefix) and target[len(prefix):].split("/", maxsplit=1)[0] == name:
            return True
    return False


def load_manifest(project: Path) -> Dict[str, Any]:
    """Read learned.json, returning an empty manifest only when it is genuinely absent.

    Raises ManifestUnreadable when the file exists but cannot be parsed: every caller
    writes the result back, so treating unreadable as empty discards every prior record.
    """
    empty = {"$schema": MANIFEST_SCHEMA_REF, "version": MANIFEST_VERSION, "skills": []}
    path = project / MANIFEST_REL
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestUnreadable(f"{path} exists but could not be read: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise ManifestUnreadable(f"{path} is not a learned-skills manifest (no skills list)")
    return data


def save_manifest(project: Path, data: Dict[str, Any]) -> None:
    """Write learned.json atomically and deterministically: stable order, trailing newline."""
    data["skills"] = sorted(data.get("skills", []),
                            key=lambda rec: (rec.get("category", ""), rec.get("name", "")))
    bl.atomic_write_text(project / MANIFEST_REL,
                         json.dumps(data, indent=2, sort_keys=True) + "\n")


def _find_record(data: Dict[str, Any], name: str, category: str) -> Optional[Dict[str, Any]]:
    for record in data.get("skills", []):
        if record.get("name") == name and record.get("category") == category:
            return record
    return None


def _refused(reason: str) -> Dict[str, Any]:
    return {"action": "refused", "target": "", "reason": reason}


def sync_skill(project: Path, source_dir: Path, name: str, category: Optional[str],
               *, now: str, source_path: Optional[str] = None,
               dry_run: bool = False) -> Dict[str, Any]:
    """Copy one skill into learned/ and record it. Returns a result dict; never raises (D4)."""
    if bl is None or ul is None:
        # Without the scanner there is no evidence a skill is safe to copy.
        return _refused(NO_FRAMEWORK)
    if _is_unsafe_segment(name or ""):
        return _refused("unsafe name")
    if category is not None and category != "" and _is_unsafe_segment(category):
        return _refused("unsafe category")
    if is_framework_owned(project, name):
        return _refused("framework-owned")

    segment = category or UNCATEGORIZED
    learned_root = project / ".ai-badger" / "skills" / "learned"
    dest = learned_root / segment / name
    try:
        dest.resolve().relative_to(learned_root.resolve())
    except ValueError:
        return _refused("escapes learned root")

    rel_target = f"{LEARNED_REL}/{segment}/{name}"
    if contains_symlink(source_dir):
        # Ahead of the literal scan: the scan skips links, but copytree(symlinks=False)
        # would inline their targets' bytes into the repo.
        return {"action": "refused", "target": rel_target, "reason": "symlink"}
    unsafe = scan_for_unsafe_literals(source_dir)
    if unsafe:
        # Fixed reason string; the {file, pattern} findings travel in their own field so
        # no scanned text can ever be interpolated into printable output.
        return {"action": "refused", "target": rel_target,
                "reason": "unsafe literal detected", "unsafeLiterals": unsafe}

    try:
        data = load_manifest(project)
    except ManifestUnreadable as exc:
        return _refused(str(exc))
    record = _find_record(data, name, segment)
    if record is None and dest.exists():
        return {"action": "conflict", "target": rel_target, "reason": "untracked path exists"}

    source_hash = bl.dir_content_hash(source_dir)["content_hash"]
    unchanged = (record is not None and record.get("sourceHash") == source_hash
                 and record.get("status") == "synced" and dest.exists())
    if unchanged:
        return {"action": "skipped", "target": rel_target, "reason": "unchanged"}

    action = "updated" if record is not None else "created"
    if dry_run:
        return {"action": action, "target": rel_target, "reason": "dry-run"}

    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, dest, dirs_exist_ok=True, symlinks=False)

    new_record = {
        "name": name,
        "category": segment,
        "target": rel_target,
        "sourcePath": source_path or (f"{category}/{name}" if category else name),
        "sourceHash": source_hash,
        "syncedAt": now,
        "status": "synced",
    }
    if record is None:
        data["skills"].append(new_record)
    else:
        record.update(new_record)
    save_manifest(project, data)
    return {"action": action, "target": rel_target, "reason": ""}


def scan_for_unsafe_literals(source_dir: Path) -> List[Dict[str, str]]:
    """Locate high-confidence risky literal shapes in a skill directory (a guard, not proof).

    Delegates to the shared scanner so the inbound and outbound paths cannot drift apart.
    """
    return ul.scan_tree(source_dir)


def _mark_orphaned(project: Path, name: str, category: str, now: str) -> Dict[str, Any]:
    try:
        data = load_manifest(project)
    except ManifestUnreadable as exc:
        return _refused(str(exc))
    record = _find_record(data, name, category)
    if record is None:
        return {"action": "skipped", "target": "", "reason": "not tracked"}
    record["status"] = "orphaned"
    record["syncedAt"] = now
    save_manifest(project, data)
    return {"action": "orphaned", "target": record.get("target", ""), "reason": "deleted in hermes"}


def on_skill_manage(args: Dict[str, Any], status: str, cwd: str, *, skills_root: Path,
                    now: str, tool_name: str = "skill_manage") -> Optional[Dict[str, Any]]:
    """Hook entry point: sync the one skill a successful skill_manage call named."""
    if bl is None or ul is None:
        return None
    if tool_name != "skill_manage" or status != "ok" or not isinstance(args, dict):
        return None

    action = str(args.get("action") or "")
    if action not in SYNC_ACTIONS and action not in DELETE_ACTIONS:
        return None

    project = target_project(cwd)
    if project is None:
        return None

    name = str(args.get("name") or "")
    category = str(args.get("category") or "").strip() or None
    if _is_unsafe_segment(name) or (category is not None and _is_unsafe_segment(category)):
        return None

    if action in DELETE_ACTIONS:
        return _mark_orphaned(project, name, category or UNCATEGORIZED, now)

    source_dir = resolve_source_dir(name, category, skills_root)
    if source_dir is None:
        return {"action": "skipped", "target": "", "reason": "source not found"}
    syncable, reason = is_syncable(source_dir, skills_root)
    if not syncable:
        return {"action": "skipped", "target": "", "reason": reason}

    return sync_skill(project, source_dir, name, category, now=now,
                      source_path=_source_path(source_dir, skills_root))


def _source_path(source_dir: Path, skills_root: Path) -> str:
    parts = _relative_parts(source_dir, skills_root) or (source_dir.name,)
    return "/".join(parts)


def reconcile(project: Path, skills_root: Path, *, now: str,
              dry_run: bool = False) -> Dict[str, Any]:
    """Backfill pass over the whole Hermes skills root, under the same gates. Opt-in only."""
    summary = {"created": 0, "updated": 0, "skipped": 0, "conflict": 0,
               "refused": 0, "details": []}
    if not skills_root.is_dir():
        return summary

    for entry in sorted(skills_root.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_symlink():
            _record(summary, entry.name, None, {"action": "skipped", "reason": "symlink"})
            continue
        if not entry.is_dir():
            continue
        if (entry / "SKILL.md").is_file():
            candidates = [(entry, None)]
        else:
            candidates = [(child, entry.name) for child in sorted(entry.iterdir())
                          if child.is_symlink() or child.is_dir()]
        for source_dir, category in candidates:
            _record(summary, source_dir.name, category,
                    _reconcile_one(project, source_dir, category, now, dry_run, skills_root))
    return summary


def _reconcile_one(project: Path, source_dir: Path, category: Optional[str], now: str,
                   dry_run: bool, skills_root: Path) -> Dict[str, Any]:
    syncable, reason = is_syncable(source_dir, skills_root)
    if not syncable:
        return {"action": "skipped", "reason": reason}
    return sync_skill(project, source_dir, source_dir.name, category, now=now,
                      source_path=_source_path(source_dir, skills_root), dry_run=dry_run)


def _record(summary: Dict[str, Any], name: str, category: Optional[str],
            result: Dict[str, Any]) -> None:
    action = result.get("action", "skipped")
    if action in summary:
        summary[action] += 1
    detail = {"name": name, "category": category, "action": action,
              "reason": result.get("reason", "")}
    # Safe to carry through: findings are {file, pattern} pairs, never scanned text.
    if result.get("unsafeLiterals"):
        detail["unsafeLiterals"] = result["unsafeLiterals"]
    summary["details"].append(detail)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: --reconcile a target project against a Hermes skills root."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reconcile", action="store_true", required=True,
                    help="Backfill every eligible skill from --skills-root.")
    ap.add_argument("--target", default=".")
    ap.add_argument("--skills-root", default=str(Path.home() / ".hermes" / "skills"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if bl is None or ul is None:
        # A CLI says why it did nothing; only the hook path is allowed to be silent.
        print(json.dumps({"error": NO_FRAMEWORK, "target": args.target}))
        return 1

    project = target_project(args.target)
    if project is None:
        print(json.dumps({"error": "not an ai-badger project", "target": args.target}))
        return 1

    summary = reconcile(project, Path(args.skills_root),
                        now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
