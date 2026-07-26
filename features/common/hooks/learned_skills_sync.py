#!/usr/bin/env python3
"""Sync a Hermes learned skill into a project's .ai-badger/skills/learned/ tree.

One-way, event-scoped, confined: every write lands under .ai-badger/skills/learned/ and is
recorded in .ai-badger/skills-data/hermes/learned.json.
Design: docs/design/hermes-learned-skills-sync-impl-plan.md (stages 1-3).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "scripts" / "badger_lib.py"
        if cand.exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    cache = Path.home() / ".ai-badger" / "framework"
    if (cache / "scripts" / "badger_lib.py").exists() and (cache / "schemas").is_dir():
        sys.path.insert(0, str(cache / "scripts"))
        return
    raise RuntimeError(
        "could not locate ai-badger scripts/badger_lib.py locally or at "
        f"{cache} — clone https://github.com/Arasz/ai-badger"
    )


_bootstrap_lib()
import badger_lib as bl

LEARNED_REL = ".ai-badger/skills/learned"
MANIFEST_REL = ".ai-badger/skills-data/hermes/learned.json"
MANIFEST_SCHEMA_REF = "../../../schemas/learned-skills.schema.json"
MANIFEST_VERSION = 1
UNCATEGORIZED = "uncategorized"

SYNC_ACTIONS = frozenset({"create", "edit", "patch", "write_file", "remove_file"})
DELETE_ACTIONS = frozenset({"delete"})

# High-confidence literal shapes only — refuse and report, never redact (plan §5.2).
SECRET_PATTERNS = (
    ("provider api key", re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws secret access key",
     re.compile(r"AWS_SECRET_ACCESS_KEY\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40,}")),
    ("credential assignment",
     re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*"
                r"[\"']?[A-Za-z0-9/+=._-]{20,}")),
)
SECRET_SCAN_MAX_BYTES = 1_000_000
# The only vocabulary a finding may report. Keeping it fixed is what makes a finding
# safe to print: a new pattern contributes a label, never captured text.
SECRET_PATTERN_LABELS = frozenset(label for label, _ in SECRET_PATTERNS)


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


def is_syncable(source_dir: Path, skills_root: Path) -> Tuple[bool, str]:
    """Gate 4: reject symlinked or escaping source dirs before any read (C2)."""
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
    """Read learned.json, returning an empty manifest when it is absent or unreadable."""
    empty = {"$schema": MANIFEST_SCHEMA_REF, "version": MANIFEST_VERSION, "skills": []}
    path = project / MANIFEST_REL
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        return empty
    return data


def save_manifest(project: Path, data: Dict[str, Any]) -> None:
    """Write learned.json deterministically: stable key/record order, trailing newline."""
    path = project / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    data["skills"] = sorted(data.get("skills", []),
                            key=lambda rec: (rec.get("category", ""), rec.get("name", "")))
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    secrets = scan_for_secrets(source_dir)
    if secrets:
        # Fixed reason string; the {file, pattern} findings travel in their own field so
        # no scanned text can ever be interpolated into printable output.
        return {"action": "refused", "target": rel_target,
                "reason": "secret literal detected", "secretFindings": secrets}

    data = load_manifest(project)
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


def scan_for_secrets(source_dir: Path) -> List[Dict[str, str]]:
    """Locate high-confidence secret literals in a skill directory (a guard, not a proof).

    Findings are {file, pattern} pairs. `pattern` is always drawn from
    SECRET_PATTERN_LABELS and scanned text never reaches the return value, so a
    finding is safe to log or print — see docs/adr, CodeQL py/clear-text-logging.
    """
    findings: List[Dict[str, str]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > SECRET_SCAN_MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(source_dir).as_posix()
        for label, pattern in SECRET_PATTERNS:
            # bool() pins the match to a boolean: no match object, group, or span can
            # escape this scope, so no scanned byte can reach a caller.
            if bool(pattern.search(text)):
                findings.append({"file": rel, "pattern": label})
    return findings


def _mark_orphaned(project: Path, name: str, category: str, now: str) -> Dict[str, Any]:
    data = load_manifest(project)
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
    if result.get("secretFindings"):
        detail["secretFindings"] = result["secretFindings"]
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
