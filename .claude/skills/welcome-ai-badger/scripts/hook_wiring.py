"""Hook wiring for the Scaffolder.

Reads hooks-manifest.json, generates project-specific hooks.json under
.ai-badger/hooks/, and merges hook registrations into .claude/settings.json.
"""
from __future__ import annotations

from typing import Any, Dict


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
    """Merge *new_hooks* into *existing_hooks* in-place, deduplicating by command.

    Each value is a list of entry dicts, each containing a ``"hooks"`` list of
    individual hook dicts with a ``"command"`` key.  Only genuinely new commands
    are appended; existing entries are never duplicated.
    """
    for event, hook_entries in new_hooks.items():
        existing_event_hooks = existing_hooks.get(event, [])
        registered_cmds = {
            h.get("command", "")
            for entry in existing_event_hooks
            for h in entry.get("hooks", [])
        }
        for new_entry in hook_entries:
            new_hs = [
                h for h in new_entry.get("hooks", [])
                if h.get("command", "") not in registered_cmds
            ]
            if new_hs:
                filtered = dict(new_entry)
                filtered["hooks"] = new_hs
                existing_event_hooks.append(filtered)
                registered_cmds.update(h.get("command", "") for h in new_hs)
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
                rel_path = script_path.relative_to(self.target)
                rewritten = [{
                    "hooks": [{
                        "type": "command",
                        "command": f'python3 "{self.target / rel_path}"'
                    }]
                }]
            else:
                # Rewrite paths from framework to scaffolded project
                rewritten = []
                for entry in source_event_hooks:
                    new_entry = dict(entry)
                    new_hooks_list = []
                    for h in entry.get("hooks", []):
                        new_h = dict(h)
                        cmd = h.get("command", "")
                        cmd = cmd.replace(
                            "${CLAUDE_PLUGIN_ROOT}/features/common/skills/",
                            str(self.aib / "skills") + "/"
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
