"""The plugin must expose the skills and hooks it claims, at the paths Claude Code reads."""
from __future__ import annotations

import json
import subprocess

# Claude Code loads this path from a plugin automatically. Naming it in the manifest as well
# is a duplicate registration and aborts the plugin's entire hook load.
AUTO_LOADED_HOOKS = "hooks/hooks.json"

# The only directory Claude Code scans for a plugin's skills (ADR-0008).
PLUGIN_SKILLS_DIR = "skills"


def _manifest(root):
    return json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def _marketplace_entry(root):
    data = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    return next(p for p in data["plugins"] if p["name"] == "ai-badger")


class TestPluginHooksAreNotDoubleRegistered:
    """Regression: 0.27.0 shipped a manifest that made every plugin hook fail to load."""

    def test_the_manifest_does_not_name_the_auto_loaded_hooks_file(self, root):
        declared = _manifest(root).get("hooks")

        assert declared is None or AUTO_LOADED_HOOKS not in str(declared).replace("./", ""), (
            f"plugin.json declares {declared!r}; Claude Code already loads "
            f"{AUTO_LOADED_HOOKS} on its own, and the duplicate aborts the whole hook load. "
            "manifest.hooks is only for additional hook files."
        )

    def test_the_auto_loaded_hooks_file_still_exists(self, root):
        """Removing the declaration must not be confused with removing the hooks."""
        assert (root / AUTO_LOADED_HOOKS).is_file()

    def test_the_hooks_file_is_valid_json_with_hook_entries(self, root):
        data = json.loads((root / AUTO_LOADED_HOOKS).read_text(encoding="utf-8"))

        assert data.get("hooks"), "hooks.json declares no hooks"


class TestPluginExposesItsSkills:
    """Regression: 0.31.1 shipped every skill outside the one path Claude Code scans."""

    def test_every_default_scope_skill_ships_at_the_plugin_skill_path(self, root, load_script):
        bl = load_script("engine/badger_lib.py")

        missing = [name for name in bl.default_skill_names()
                   if not (root / PLUGIN_SKILLS_DIR / name / "SKILL.md").is_file()]

        assert not missing, (
            f"{missing} are scoped 'default' but absent from {PLUGIN_SKILLS_DIR}/ — "
            "Claude Code loads plugin skills from there and nowhere else, so the plugin "
            "contributes them to nobody. Run: python3 tooling/sync_plugin_skills.py"
        )

    def test_every_skill_the_plugin_advertises_is_actually_shipped(self, root, load_script):
        bl = load_script("engine/badger_lib.py")
        blurb = _manifest(root)["description"] + " " + _marketplace_entry(root)["description"]
        advertised = [name for name in bl.default_skill_names() if name in blurb]

        assert advertised, "no skill is named in the plugin description; nothing is being checked"
        for name in advertised:
            assert (root / PLUGIN_SKILLS_DIR / name / "SKILL.md").is_file(), (
                f"the plugin description promises {name} and ships no copy of it"
            )

    def test_the_sync_script_targets_the_plugin_skill_path(self, root, load_script):
        sps = load_script("tooling/sync_plugin_skills.py")

        assert sps.TARGET == root / PLUGIN_SKILLS_DIR

    def test_the_shipped_skills_are_tracked_and_not_ignored(self, root, load_script):
        bl = load_script("engine/badger_lib.py")
        paths = [f"{PLUGIN_SKILLS_DIR}/{name}/SKILL.md" for name in bl.default_skill_names()]

        ignored = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(paths),
                                 cwd=root, capture_output=True, text=True, check=False).stdout

        assert not ignored.strip(), f"ignored, so never published with the plugin: {ignored}"
