"""Hook wiring for the Scaffolder.

Reads hooks-manifest.json, generates project-specific hooks.json under
.ai-badger/hooks/, and merges hook registrations into .claude/settings.json.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Hook commands must name their script through this placeholder, never an absolute path:
# every checkout of a project (worktree, second clone, framework cache) spells the same
# script differently, and a dedupe keyed on the literal command never recognises them.
PROJECT_DIR_VAR = "${CLAUDE_PROJECT_DIR}"

# The layouts an ai-badger hook script can be reached through; the text after the marker
# (skill/scripts/hook.py) is the script's checkout-independent identity.
_SKILL_PATH_MARKERS = (
    "/.ai-badger/skills/",
    "/features/common/skills/",
    "/features/claude/skills/",
)


def skill_script_id(command: str) -> Optional[str]:
    """The skill-relative script path a command runs, or None if it is not ours."""
    for marker in _SKILL_PATH_MARKERS:
        idx = command.rfind(marker)
        if idx != -1:
            return command[idx + len(marker):].rstrip('"')
    return None


def _hook_key(command: str) -> str:
    """Dedupe key: script identity for framework hooks, the literal command otherwise."""
    return skill_script_id(command) or command


def _prune(event_hooks: List[Any], superseded: set) -> List[Any]:
    """Drop framework hooks that an incoming command replaces, and their own repeats.

    Hooks the framework does not own are copied through untouched.
    """
    kept_entries = []
    seen = set()
    for entry in event_hooks:
        hooks = entry.get("hooks", [])
        kept = []
        for hook in hooks:
            script_id = skill_script_id(hook.get("command", ""))
            if script_id is None:
                kept.append(hook)
                continue
            if script_id in superseded or script_id in seen:
                continue
            seen.add(script_id)
            kept.append(hook)
        if not kept and hooks:
            continue
        pruned = dict(entry)
        pruned["hooks"] = kept
        kept_entries.append(pruned)
    return kept_entries


def select_hooks(source_event_hooks, script):
    """Keep only the commands belonging to *script*, dropping now-empty entries.

    An event carries one command per hook that registers for it, so a manifest entry
    must take its own command and no one else's.
    """
    if not script:
        return list(source_event_hooks)
    selected = []
    for entry in source_event_hooks:
        matching = [h for h in entry.get("hooks", [])
                    if h.get("command", "").rstrip('"').endswith(script)]
        if matching:
            picked = dict(entry)
            picked["hooks"] = matching
            selected.append(picked)
    return selected


def merge_hooks(existing_hooks: Dict[str, Any], new_hooks: Dict[str, Any]) -> None:
    """Merge *new_hooks* into *existing_hooks* in-place, deduplicating by script identity.

    A framework hook is identified by the skill-relative script it runs, so the same
    script wired from another checkout collapses instead of accumulating; anything else
    is matched on its literal command and left alone.
    """
    for event, hook_entries in new_hooks.items():
        superseded = {
            script_id
            for entry in hook_entries
            for script_id in [skill_script_id(h.get("command", ""))
                              for h in entry.get("hooks", [])]
            if script_id is not None
        }
        existing_event_hooks = _prune(existing_hooks.get(event, []), superseded)
        registered_cmds = {
            _hook_key(h.get("command", ""))
            for entry in existing_event_hooks
            for h in entry.get("hooks", [])
        }
        for new_entry in hook_entries:
            new_hs = [
                h for h in new_entry.get("hooks", [])
                if _hook_key(h.get("command", "")) not in registered_cmds
            ]
            if new_hs:
                filtered = dict(new_entry)
                filtered["hooks"] = new_hs
                existing_event_hooks.append(filtered)
                registered_cmds.update(_hook_key(h.get("command", "")) for h in new_hs)
        existing_hooks[event] = existing_event_hooks


class HookWiringMixin:
    """Mixin providing hook wiring methods."""

    def wire_hooks(self) -> None:
        """Wire framework hooks into .claude/settings.json for Claude Code projects.

        Reads hooks-manifest.json, generates a project-specific hooks.json under
        .ai-badger/hooks/ with paths rewritten to the scaffolded .ai-badger/skills/
        directory, and merges hook registrations into .claude/settings.json.
        """
        import badger_lib as bl
        import config_guard as cg

        if "claude" not in self.config.get("agents", []):
            return

        manifest_path = self.root / "features" / "common" / "hooks" / "hooks-manifest.json"
        if not manifest_path.exists():
            return

        try:
            manifest = bl.load_json(manifest_path)
        except (ValueError, OSError):
            return

        # Source hooks.json (framework plugin version)
        source_hooks_path = self.root / "features" / "common" / "hooks" / "hooks.json"
        source_hooks = {}
        if source_hooks_path.exists():
            try:
                source_hooks = bl.load_json(source_hooks_path)
            except (ValueError, OSError):
                pass

        # Build the target hooks.json by rewriting paths
        target_hooks: Dict[str, Any] = {"hooks": {}}
        settings_hooks: Dict[str, Any] = {}

        for hook in manifest.get("hooks", []):
            claude_entry = hook.get("agents", {}).get("claude")
            # "plugin-hooks-json" hooks are registered by the plugin's own hooks/hooks.json
            # and rely on ${CLAUDE_PLUGIN_ROOT}, which is never set for a hook a consumer
            # registers itself — wiring them here would only look like the feature works.
            if not claude_entry or claude_entry.get("type") != "hooks-json":
                continue

            event = claude_entry.get("event")
            if not event:
                continue

            # Get this hook's own command from the source hooks.json
            source_event_hooks = select_hooks(
                source_hooks.get("hooks", {}).get(event, []), claude_entry.get("script"))
            if not source_event_hooks:
                # Generate a default hook entry for skills not in the framework hooks.json
                hook_name = hook.get("name", "")
                skill_hook_script = self.aib / "skills" / hook_name / "scripts"
                hook_scripts = list(skill_hook_script.glob("*_hook.py")) if skill_hook_script.exists() else []
                if not hook_scripts:
                    self.notes.append(f"hook '{hook_name}': no hook script found — skipped")
                    continue
                script_path = hook_scripts[0]
                rel_path = script_path.relative_to(self.target).as_posix()
                rewritten = [{
                    "hooks": [{
                        "type": "command",
                        "command": f'python3 "{PROJECT_DIR_VAR}/{rel_path}"'
                    }]
                }]
            else:
                # Rewrite paths from framework to scaffolded project
                aib_rel = self.aib.relative_to(self.target).as_posix()
                rewritten = []
                for entry in source_event_hooks:
                    new_entry = dict(entry)
                    new_hooks_list = []
                    for h in entry.get("hooks", []):
                        new_h = dict(h)
                        cmd = h.get("command", "")
                        cmd = cmd.replace(
                            "${CLAUDE_PLUGIN_ROOT}/features/common/skills/",
                            f"{PROJECT_DIR_VAR}/{aib_rel}/skills/"
                        )
                        new_h["command"] = cmd
                        new_hooks_list.append(new_h)
                    new_entry["hooks"] = new_hooks_list
                    rewritten.append(new_entry)

            # Accumulate: two manifest entries may register for the same event.
            target_hooks["hooks"].setdefault(event, []).extend(rewritten)
            settings_hooks.setdefault(event, []).extend(rewritten)

        if not target_hooks["hooks"]:
            return

        # Write .ai-badger/hooks/hooks.json
        hooks_dir = self.aib / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        bl.dump_json(hooks_dir / "hooks.json", target_hooks)

        # Merge into .claude/settings.json — never over an unreadable file
        settings_path = self.target / ".claude" / "settings.json"
        settings, note = cg.read_json_mapping(settings_path)
        if settings is None:
            self.notes.append(f"{note} (hooks not wired)")
            return

        existing_hooks = settings.get("hooks", {})
        merge_hooks(existing_hooks, settings_hooks)

        settings["hooks"] = existing_hooks
        cg.write_json_with_backup(settings_path, settings)
        self.notes.append(f"wired {len(settings_hooks)} hook(s) into .claude/settings.json")
