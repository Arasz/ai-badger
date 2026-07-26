#!/usr/bin/env python3
"""Plugin-provided SessionStart hook: Tier 1 drift notice (ADR-0001 decision 5, #24).

Registered via `hooks/hooks.json` at the framework repo root, so this fires automatically for
every consumer who installs the ai-badger plugin -- running from the *plugin's own* on-disk
copy. That is load-bearing: `$CLAUDE_PLUGIN_ROOT` is a command-string placeholder the CLI
substitutes into a plugin-provided `hooks.json`'s `command` field, not a session-wide
environment variable (N plugins load per session, so there is no single value one could read
from `os.environ`). A hook registered by a *consumer's own* `.claude/settings.json` -- which is
what the previous, dead implementation on `session_start_hook.py` assumed -- never has it set.

Reads the same SessionStart stdin payload as `session_start_hook.py` (see that script's
docstring for the exact JSON shape) and emits the same `hookSpecificOutput`/`additionalContext`
shape on stdout, but only when the plugin's `VERSION` and the target project's
`.ai-badger/manifest.json` `frameworkVersion` differ. The comparison itself is shared with
`session_start_hook.py`'s prior implementation via `drift_notice.scaffold_drift_notice` --
see that module's docstring for why it was extracted rather than duplicated or imported whole.

Must never crash and must never print anything unconditionally: silent (empty stdout, exit 0)
on a version match, an unscaffolded project, a plugin root that cannot be located, or any read
error. A hook that breaks SessionStart or nags unconditionally defeats its own purpose.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_notice  # pylint: disable=wrong-import-position


def find_plugin_root(start: Path) -> Optional[Path]:
    """Ancestor-walk from `start` for the plugin root: the nearest ancestor (inclusive)
    containing both a `VERSION` file and a `features/common/skills/` directory.

    Deliberately NOT a fixed `Path(__file__).parents[N]` -- a hardcoded `PROJECT_ROOT =
    SCRIPT_DIR.parents[3]` shipped as a real misrooting bug in this repo before, fixed by #12
    (see ADR-0001's Context section). This script's own depth under the plugin root
    (`features/common/skills/task/scripts/drift_notice_hook.py`) is 5, but the walk does not
    assume that; it matches the `_bootstrap_lib()` idiom used by `scaffold.py`/`drift.py`.
    """
    for anc in [start, *start.parents]:
        if (anc / "VERSION").is_file() and (anc / "features" / "common" / "skills").is_dir():
            return anc
    return None


def resolve_project_root(payload: Dict[str, Any]) -> Optional[Path]:
    """`CLAUDE_PROJECT_DIR` is present in a hook's environment (unlike `CLAUDE_PLUGIN_ROOT`) and
    is authoritative when set. Fall back to the SessionStart payload's own `cwd` field."""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    cwd = payload.get("cwd")
    if cwd:
        return Path(cwd)
    return None


def main() -> int:
    """Read the SessionStart payload from stdin; print a drift notice iff versions differ."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    plugin_root = find_plugin_root(Path(__file__).resolve().parent)
    project_root = resolve_project_root(payload)
    if plugin_root is None or project_root is None:
        return 0

    notice = drift_notice.scaffold_drift_notice(project_root, str(plugin_root))
    if notice:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": notice,
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
