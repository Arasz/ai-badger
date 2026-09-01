"""Adjustment: wire ai-badger hooks into .github/hooks/ for Copilot CLI.

Reads the framework's hooks-manifest.json, generates Copilot-format hooks
with paths rewritten to the scaffolded .ai-badger/ directories, and
writes them to .github/hooks/ai-badger-hooks.json. Scripts living in a skill's own
scripts/ directory already reach the project through the skills copy; scripts living
in features/common/hooks/ (the shared hook-script home) are shipped into the project's
.ai-badger/hooks/ by this adjustment, together with the badger_store.py sibling they
import from beside themselves.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Set


def _rewrite_command(cmd: str, hooks_rel: str, scripts_to_ship: Set[str]) -> str:
    """Rewrite one framework command for the scaffolded project; collect hook scripts to ship.

    Skills paths map to the project's .ai-badger/skills/ copy. features/common/hooks/ paths
    map to the project's shipped hook-script home and their script names accrue in
    scripts_to_ship — without the rewrite the command passes through with a
    ${CLAUDE_PLUGIN_ROOT} path Copilot never substitutes, a dead hook that looks wired.
    """
    cmd = cmd.replace(
        "${CLAUDE_PLUGIN_ROOT}/features/common/skills/",
        ".ai-badger/skills/"
    )
    hooks_marker = "${CLAUDE_PLUGIN_ROOT}/features/common/hooks/"
    if hooks_marker in cmd:
        cmd = cmd.replace(hooks_marker, f"{hooks_rel}/")
        tail = cmd.rstrip('"').rsplit("/", 1)[-1]
        if tail.endswith(".py"):
            scripts_to_ship.add(tail)
    return cmd


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Wire hooks for Copilot CLI.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
            'skills': list[str],
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    target = context["target"]
    _skills = context.get("skills", [])

    # Where shipped hook scripts land inside the project (e.g. .ai-badger/hooks).
    hooks_rel = (target_dir / "hooks").relative_to(target).as_posix()

    # Read hooks-manifest.json
    manifest_path = framework_root / "features" / "common" / "hooks" / "hooks-manifest.json"
    if not manifest_path.exists():
        return {"applied": False, "files": [], "notes": "hooks-manifest.json not found"}

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Source hooks.json for path rewriting
    source_hooks_path = framework_root / "features" / "common" / "hooks" / "hooks.json"
    source_hooks = {}
    if source_hooks_path.exists():
        with open(source_hooks_path, encoding="utf-8") as f:
            source_hooks = json.load(f)

    # Build Copilot-format hooks
    copilot_hooks: Dict[str, Any] = {"version": 1, "hooks": {}}
    scripts_to_ship: Set[str] = set()

    for hook in manifest.get("hooks", []):
        copilot_entry = hook.get("agents", {}).get("copilot")
        if not copilot_entry or copilot_entry.get("type") != "hooks-json":
            continue

        event = copilot_entry.get("event")
        if not event:
            continue

        # Event from manifest is already in Copilot camelCase format
        copilot_event = event

        # Map Copilot event names (camelCase) to Claude/PascalCase for source lookup
        event_map = {
            "sessionStart": "SessionStart",
            "userPromptSubmitted": "UserPromptSubmit",
            "sessionEnd": "SessionEnd",
            "preToolUse": "PreToolUse",
            "postToolUse": "PostToolUse",
        }
        source_event = event_map.get(copilot_event, copilot_event)

        # Get this hook's own command from the source, or generate one
        source_event_hooks = source_hooks.get("hooks", {}).get(source_event, [])
        script = copilot_entry.get("script")
        if script:
            source_event_hooks = [
                dict(entry, hooks=[h for h in entry.get("hooks", [])
                                   if h.get("command", "").rstrip('"').endswith(script)])
                for entry in source_event_hooks
            ]
            source_event_hooks = [e for e in source_event_hooks if e["hooks"]]
        if source_event_hooks:
            # Rewrite paths from framework to scaffolded project
            entries = []
            for entry in source_event_hooks:
                # Copilot matches runtime tool names, which are case-sensitive and
                # lowercased (grep/bash) where Claude's are PascalCase (Grep/Bash) — a
                # manifest arm may carry its own `matcher` override for that.
                matcher = copilot_entry.get("matcher") or entry.get("matcher")
                for h in entry.get("hooks", []):
                    # Copilot matches runtime tool names, which are case-sensitive and
                    # lowercased (grep/bash) where Claude's are PascalCase (Grep/Bash) — a
                    # manifest arm may carry its own `matcher` override for that.
                    cmd = _rewrite_command(h.get("command", ""), hooks_rel, scripts_to_ship)
                    hook_entry = {
                        "type": "command",
                        "bash": cmd,
                        "timeoutSec": 10,
                    }
                    if matcher:
                        hook_entry["matcher"] = matcher
                    entries.append(hook_entry)
            copilot_hooks["hooks"].setdefault(copilot_event, []).extend(entries)
        else:
            # Generate from skill name (e.g., prompt-markers)
            hook_name = hook.get("name", "")
            skill_dir = target_dir / "skills" / hook_name / "scripts"
            if skill_dir.exists():
                if script:
                    script_path = skill_dir / script
                    hook_scripts = [script_path] if script_path.exists() else []
                else:
                    hook_scripts = sorted(skill_dir.glob("*_hook.py"))
                    if len(hook_scripts) > 1:
                        names = ", ".join(p.name for p in hook_scripts)
                        raise ValueError(
                            f"hook '{hook_name}': manifest names no script and "
                            f"{skill_dir} has more than one candidate ({names}) — "
                            f"refusing to guess"
                        )
                if hook_scripts:
                    rel_path = hook_scripts[0].relative_to(target)
                    copilot_hooks["hooks"].setdefault(copilot_event, []).append({
                        "type": "command",
                        "bash": f"python3 {rel_path.as_posix()}",
                        "timeoutSec": 5,
                    })

    if not copilot_hooks["hooks"]:
        return {"applied": False, "files": [], "notes": "No Copilot hooks to wire"}

    # Ship every hook script the generated commands name from features/common/hooks/ into the
    # project's .ai-badger/hooks/, each with the badger_store.py sibling it imports beside
    # itself — a command naming a file the project does not have is a dropped event (R7.3).
    files = [".github/hooks/ai-badger-hooks.json"]
    hooks_dest = target / hooks_rel
    hooks_src = framework_root / "features" / "common" / "hooks"
    if scripts_to_ship:
        hooks_dest.mkdir(parents=True, exist_ok=True)
        for script_name in sorted(scripts_to_ship | {"badger_store.py"}):
            src = hooks_src / script_name
            if not src.is_file():
                continue
            dst = hooks_dest / script_name
            shutil.copy2(src, dst)
            files.append(str(dst.relative_to(target)))

    # Write to .github/hooks/ai-badger-hooks.json
    hooks_dir = target / ".github" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = hooks_dir / "ai-badger-hooks.json"
    with open(hooks_file, "w", encoding="utf-8") as f:
        json.dump(copilot_hooks, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return {
        "applied": True,
        "files": files,
        "notes": f"Wired {len(copilot_hooks['hooks'])} hook(s) into .github/hooks/",
    }
