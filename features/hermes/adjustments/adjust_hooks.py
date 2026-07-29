"""Adjustment: install Hermes plugin hooks during scaffold.

Copies the framework hook modules into the project's .ai-badger/hooks/ and — because
Hermes loads plugins only from ~/.hermes/plugins/ — into that user-scope directory too.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

PROJECT_HOOKS = ("ai_badger_hooks.py", "mcp_index_hook.py")
USER_PLUGINS = ("ai_badger_hooks.py", "learned_skills_sync.py")

# Files that live under a skill's own scripts/ dir, not features/common/hooks/, but must
# still land beside ai_badger_hooks.py in both destinations so its lazy sibling-import
# (_load_commit_reminder/_load_impact_estimator) finds them post-copy. Kept separate from
# PROJECT_HOOKS/USER_PLUGINS so their resolution against a different source dir is explicit,
# not a special case buried inside one shared tuple.
SHARED_SKILL_MODULES = (
    ("commit-reminder", "commit_reminder.py"),
    ("commit-reminder", "impact_estimator.py"),
)

# The BM25 MCP matcher (docs/adr/0012): tokenizer, scoring, gate and document
# construction live here, not in ai_badger_hooks.py, so they need their own copy
# beside it in every deployment shape — same reasoning as SHARED_SKILL_MODULES.
RETRIEVAL_MODULES = ("tokenizer.py", "bm25.py", "mcp_matcher.py")


def _shared_skill_module_src(framework_root: Path, skill_name: str, filename: str) -> Path:
    return (framework_root / "features" / "common" / "skills" / skill_name / "scripts"
            / filename)


def _retrieval_module_src(framework_root: Path, filename: str) -> Path:
    return framework_root / "features" / "common" / "retrieval" / filename


def _record_framework_root(plugins_dir: Path, framework_root: Path) -> None:
    """Record where these copies came from and at which version, beside them and outside any repo.

    ~/.hermes/plugins/ has no framework above it, so only a recorded pointer can answer it —
    and it must be one no cloned repo can write (ADR-0009 decision 6). The version stamps the
    copies so a later run can tell they have gone stale against a root that moved on.
    """
    root = Path(framework_root).resolve()
    record = {"frameworkRoot": str(root)}
    try:
        record["copiedFromVersion"] = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass  # an unreadable VERSION leaves the copies unjudged, never unwritten
    manifest = plugins_dir / ".ai-badger" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _install_user_plugins(hooks_dir: Path, framework_root: Path) -> List[str]:
    """Copy (and refresh) the Hermes plugin modules into ~/.hermes/plugins/."""
    plugins_dir = Path.home() / ".hermes" / "plugins"
    installed: List[str] = []
    for name in USER_PLUGINS:
        src = hooks_dir / name
        if not src.is_file():
            continue
        plugins_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugins_dir / name)
        installed.append(name)
    for skill_name, filename in SHARED_SKILL_MODULES:
        src = _shared_skill_module_src(framework_root, skill_name, filename)
        if not src.is_file():
            continue
        plugins_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugins_dir / filename)
        installed.append(filename)
    for filename in RETRIEVAL_MODULES:
        src = _retrieval_module_src(framework_root, filename)
        if not src.is_file():
            continue
        plugins_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugins_dir / filename)
        installed.append(filename)
    if installed:
        _record_framework_root(plugins_dir, framework_root)
    return installed


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install Hermes plugin hooks.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/hermes/adjustments/
            'target_dir': Path,     # .ai-badger/
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    config = context.get("config") or {}
    if "hermes" not in (config.get("agents") or []):
        return {"applied": False, "files": [], "notes": "hermes not in config.agents"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    hooks_dir = framework_root / "features" / "common" / "hooks"

    files = []
    for hook_file in PROJECT_HOOKS:
        src = hooks_dir / hook_file
        if src.exists():
            dst = target_dir / "hooks" / hook_file
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target_dir.parent)))
    for skill_name, filename in SHARED_SKILL_MODULES:
        src = _shared_skill_module_src(framework_root, skill_name, filename)
        if src.exists():
            dst = target_dir / "hooks" / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target_dir.parent)))
    for filename in RETRIEVAL_MODULES:
        src = _retrieval_module_src(framework_root, filename)
        if src.exists():
            dst = target_dir / "hooks" / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target_dir.parent)))

    # User-scope copies are deliberately absent from 'files': the scaffolder records every
    # returned file relative to the project target, which a home path cannot be.
    installed = _install_user_plugins(hooks_dir, framework_root)

    notes = []
    if files:
        notes.append(f"Installed {len(files)} Hermes plugin hooks")
    if installed:
        notes.append("installed into ~/.hermes/plugins: " + ", ".join(installed))
    if not notes:
        return {"applied": False, "files": [], "notes": "No hook files found"}
    return {"applied": True, "files": files, "notes": "; ".join(notes)}
