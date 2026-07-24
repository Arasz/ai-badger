"""Adjustment: wire ai-badger hooks into .github/hooks/ for Copilot CLI.

Reads the framework's hooks-manifest.json, generates Copilot-format hooks
with paths rewritten to the scaffolded .ai-badger/skills/ directory, and
writes them to .github/hooks/ai-badger-hooks.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


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
    skills = context.get("skills", [])

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
            "preToolUse": "PreToolUse",
            "postToolUse": "PostToolUse",
        }
        source_event = event_map.get(copilot_event, copilot_event)

        # Get hook config from source or generate
        source_event_hooks = source_hooks.get("hooks", {}).get(source_event, [])
        if source_event_hooks:
            # Rewrite paths from framework to scaffolded project
            entries = []
            for entry in source_event_hooks:
                for h in entry.get("hooks", []):
                    cmd = h.get("command", "")
                    # Rewrite: ${CLAUDE_PLUGIN_ROOT}/features/common/skills/ → .ai-badger/skills/
                    cmd = cmd.replace(
                        "${CLAUDE_PLUGIN_ROOT}/features/common/skills/",
                        ".ai-badger/skills/"
                    )
                    # Remove surrounding quotes if present
                    cmd = cmd.strip('"')
                    entries.append({
                        "type": "command",
                        "bash": cmd,
                        "timeoutSec": 10,
                    })
            copilot_hooks["hooks"][copilot_event] = entries
        else:
            # Generate from skill name (e.g., prompt-markers)
            hook_name = hook.get("name", "")
            skill_dir = target_dir / "skills" / hook_name / "scripts"
            if skill_dir.exists():
                hook_scripts = list(skill_dir.glob("*_hook.py"))
                if hook_scripts:
                    rel_path = hook_scripts[0].relative_to(target)
                    copilot_hooks["hooks"][copilot_event] = [{
                        "type": "command",
                        "bash": f"python3 {rel_path.as_posix()}",
                        "timeoutSec": 5,
                    }]

    if not copilot_hooks["hooks"]:
        return {"applied": False, "files": [], "notes": "No Copilot hooks to wire"}

    # Write to .github/hooks/ai-badger-hooks.json
    hooks_dir = target / ".github" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = hooks_dir / "ai-badger-hooks.json"
    with open(hooks_file, "w", encoding="utf-8") as f:
        json.dump(copilot_hooks, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return {
        "applied": True,
        "files": [".github/hooks/ai-badger-hooks.json"],
        "notes": f"Wired {len(copilot_hooks['hooks'])} hook(s) into .github/hooks/",
    }
