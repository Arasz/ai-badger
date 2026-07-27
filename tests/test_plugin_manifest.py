"""The plugin manifest must not re-declare hook files Claude Code already loads."""
from __future__ import annotations

import json

# Claude Code loads this path from a plugin automatically. Naming it in the manifest as well
# is a duplicate registration and aborts the plugin's entire hook load.
AUTO_LOADED_HOOKS = "hooks/hooks.json"


def _manifest(root):
    return json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


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
