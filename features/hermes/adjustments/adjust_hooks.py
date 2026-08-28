"""Adjustment: install Hermes plugin hooks during scaffold.

Hermes loads plugins only from ~/.hermes/plugins/<name>/ as DIRECTORY plugins
(plugin.yaml + __init__.py exposing register(ctx), opt-in via plugins.enabled) —
flat .py drops are invisible to its loader. This adjustment therefore ships the
framework hooks as a real plugin directory: ~/.hermes/plugins/ai-badger/ with
plugin.yaml, __init__.py re-exporting ai_badger_hooks.register, and every sibling
module the lazy imports resolve beside it. The installer record (frameworkRoot +
version) moves INSIDE the plugin dir so badger_lib.copy_skew keeps judging the
copies (it reads copies_dir/.ai-badger/manifest.json). Legacy flat copies from
older ai-badger versions are removed so the user scope stays clean.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

PROJECT_HOOKS = ("ai_badger_hooks.py", "mcp_index_hook.py", "debug_log.py",
                 "grounded_feedback.py", "hermes_isolation.py")
USER_PLUGINS = ("ai_badger_hooks.py", "learned_skills_sync.py", "debug_log.py",
                "follow_through.py", "grounded_feedback.py", "hermes_isolation.py")

# Files that live under a skill's own scripts/ dir, not features/common/hooks/, but must
# still land beside ai_badger_hooks.py in both destinations so its lazy sibling-import
# (_load_commit_reminder/_load_impact_estimator/_load_memory_first_gate)
# finds them post-copy.
SHARED_SKILL_MODULES = (
    ("commit-reminder", "commit_reminder.py"),
    ("commit-reminder", "impact_estimator.py"),
    ("ai-raccoon-memory", "memory_first_gate.py"),
    ("semantica-knowledge-graph", "export_semantica_graph.py"),
    ("git-work", "git_internals_guard.py"),
)

# Modules the framework used to ship but no longer does; every adjust run must delete
# stale copies from both destinations (the memory-grade file-logging feature, removed
# 2026-08-11, is the first member).
REMOVED_MODULES = ("memory_grade.py",)

# The BM25 MCP matcher (docs/adr/0012): tokenizer, scoring, gate and document
# construction live here, not in ai_badger_hooks.py, so they need their own copy
# beside it in every deployment shape — same reasoning as SHARED_SKILL_MODULES.
RETRIEVAL_MODULES = ("tokenizer.py", "bm25.py", "mcp_matcher.py")

# Every flat file older ai-badger versions dropped directly into ~/.hermes/plugins/.
LEGACY_FLAT_FILES = tuple(
    dict.fromkeys(USER_PLUGINS + tuple(name for _, name in SHARED_SKILL_MODULES)
                  + RETRIEVAL_MODULES + REMOVED_MODULES))

PLUGIN_DIR_NAME = "ai-badger"
HERMES_HOME_ENV = "HERMES_HOME"
PLUGIN_YAML = """\
name: ai-badger
version: {version}
description: >-
  ai-badger framework hooks: framework drift notice (on_session_start), MCP context
  enrichment and commit reminders (pre_llm_call / post_tool_call), and the memory-first
  gate that blocks text search until memory_search is consulted (pre_tool_call).
hooks:
  - on_session_start
  - pre_llm_call
  - pre_tool_call
  - post_tool_call
provides_hooks:
  - on_session_start
  - pre_llm_call
  - pre_tool_call
  - post_tool_call
"""
PLUGIN_INIT = '"""ai-badger framework hooks plugin (Hermes)."""\n' \
              "from .ai_badger_hooks import register  # noqa: F401\n"


def _shared_skill_module_src(framework_root: Path, skill_name: str, filename: str) -> Path:
    return (framework_root / "features" / "common" / "skills" / skill_name / "scripts"
            / filename)


def _retrieval_module_src(framework_root: Path, filename: str) -> Path:
    return framework_root / "features" / "common" / "retrieval" / filename


def _framework_version(framework_root: Path) -> str:
    try:
        return (framework_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _record_framework_root(plugin_dir: Path, framework_root: Path) -> None:
    """Record where these copies came from and at which version, beside them.

    ~/.hermes/plugins/ai-badger/ has no framework above it, so only a recorded pointer
    can answer it — and it must be one no cloned repo can write (ADR-0009 decision 6).
    The manifest sits INSIDE the plugin dir because badger_lib.copy_skew reads
    copies_dir/.ai-badger/manifest.json; anywhere else and the staleness check silently
    no-ops. The version stamps the copies so a later run can tell they have gone stale
    against a root that moved on.
    """
    record = {"frameworkRoot": str(Path(framework_root).resolve())}
    version = _framework_version(framework_root)
    if version:
        record["copiedFromVersion"] = version
    manifest = plugin_dir / ".ai-badger" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _remove_legacy_flat_copies(plugins_dir: Path) -> None:
    """Delete the flat files and the old manifest dir previous versions left in
    ~/.hermes/plugins/. Only framework-owned names are touched."""
    for name in LEGACY_FLAT_FILES:
        (plugins_dir / name).unlink(missing_ok=True)
    legacy_manifest = plugins_dir / ".ai-badger"
    if legacy_manifest.is_dir():
        shutil.rmtree(legacy_manifest)


def _hermes_home() -> Path:
    """Hermes's own home: $HERMES_HOME when set, else ~/.hermes."""
    override = os.environ.get(HERMES_HOME_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".hermes"


def _install_user_plugins(hooks_dir: Path, framework_root: Path, install: bool) -> List[str]:
    """Copy (and refresh) the Hermes plugin as a directory plugin in $HERMES_HOME/plugins/.

    A no-op under `--no-install`: this is user-global state, and a caller that asked for no
    installation must not have its own machine rewritten (the scaffold-freshness gate
    re-scaffolds a throwaway copy on every commit).
    """
    if not install:
        return []
    plugins_dir = _hermes_home() / "plugins"
    plugin_dir = plugins_dir / PLUGIN_DIR_NAME
    installed: List[str] = []
    for name in USER_PLUGINS:
        src = hooks_dir / name
        if not src.is_file():
            continue
        plugin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugin_dir / name)
        installed.append(name)
    for skill_name, filename in SHARED_SKILL_MODULES:
        src = _shared_skill_module_src(framework_root, skill_name, filename)
        if not src.is_file():
            continue
        plugin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugin_dir / filename)
        installed.append(filename)
    for filename in RETRIEVAL_MODULES:
        src = _retrieval_module_src(framework_root, filename)
        if not src.is_file():
            continue
        plugin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, plugin_dir / filename)
        installed.append(filename)
    for filename in REMOVED_MODULES:
        (plugin_dir / filename).unlink(missing_ok=True)
    if installed:
        version = _framework_version(framework_root)
        (plugin_dir / "plugin.yaml").write_text(
            PLUGIN_YAML.format(version=version or "0"), encoding="utf-8")
        (plugin_dir / "__init__.py").write_text(PLUGIN_INIT, encoding="utf-8")
        _record_framework_root(plugin_dir, framework_root)
        _remove_legacy_flat_copies(plugins_dir)
    return installed


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install Hermes plugin hooks.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # features/hermes/adjustments/
            'target_dir': Path,     # .ai-badger/
            'install': bool,        # False under --no-install: skip user-global state
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
    for filename in REMOVED_MODULES:
        (target_dir / "hooks" / filename).unlink(missing_ok=True)

    # User-scope copies are deliberately absent from 'files': the scaffolder records every
    # returned file relative to the project target, which a home path cannot be.
    installed = _install_user_plugins(hooks_dir, framework_root,
                                      context.get("install", True))

    notes = []
    if files:
        notes.append(f"Installed {len(files)} Hermes plugin hooks")
    if installed:
        notes.append(
            f"installed into {_hermes_home()}/plugins/{PLUGIN_DIR_NAME}: "
            + ", ".join(installed)
            + "; enable with `hermes plugins enable ai-badger` "
            + "(or add plugins.enabled: [ai-badger] to ~/.hermes/config.yaml)")
    if not notes:
        return {"applied": False, "files": [], "notes": "No hook files found"}
    return {"applied": True, "files": files, "notes": "; ".join(notes)}
