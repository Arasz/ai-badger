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

try:
    import debug_log  # pylint: disable=wrong-import-position
except ImportError:  # pragma: no cover - a missing logger must never break a hook
    debug_log = None

COMPONENT = "drift_notice_hook"


def _debug(event: str, **fields) -> None:
    """Record that this hook ran. Silent when debug is off or the logger is unavailable."""
    if debug_log is not None:
        debug_log.log_event(COMPONENT, event, **fields)

def _bootstrap_lib() -> Path:
    """Put the framework's scripts/ on sys.path and return its root.

    One predicate, shared with badger_lib.is_framework_root: schemas/ + features/ +
    scripts/badger_lib.py. Ordered inputs: --root, an ancestor walk, $AI_BADGER, the root
    recorded in a .ai-badger/manifest.json above this file, then ~/.ai-badger/framework
    (ADR-0009). Duplicated verbatim in every entry point because locating badger_lib is
    what it is for.
    """
    def is_root(path):
        return ((path / "schemas").is_dir() and (path / "features").is_dir()
                and (path / "scripts" / "badger_lib.py").is_file())

    def argv_root():
        # sys.argv is ours only when this file is the program being run; these modules are
        # also imported into hosts whose own --root means something else entirely.
        try:
            if not sys.argv or Path(sys.argv[0]).resolve() != Path(__file__).resolve():
                return None
        except (OSError, ValueError):
            return None
        argv = sys.argv[1:]
        for i, arg in enumerate(argv):
            if arg == "--root" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--root="):
                return arg.split("=", 1)[1]
        return None

    def checked(value, source):
        root = Path(value).expanduser()
        if not is_root(root):
            raise RuntimeError(
                f"{source} is {root}, which is not an ai-badger framework root "
                f"(no schemas/ + features/ + scripts/badger_lib.py)"
            )
        return root

    def recorded(start):
        # Above this file only. A working directory belongs to whatever repo the user
        # opened, and no repo may steer the sys.path of a hook that runs on session start.
        for anc in [start, *start.parents]:
            manifest = (anc / "manifest.json" if anc.name == ".ai-badger"
                        else anc / ".ai-badger" / "manifest.json")
            if not manifest.is_file():
                continue
            try:
                value = json.loads(manifest.read_text(encoding="utf-8")).get("frameworkRoot")
            except (OSError, ValueError):
                continue
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = manifest.parent.parent / candidate
            if is_root(candidate):
                return candidate.resolve()
        return None

    here = Path(__file__).resolve()
    cache = Path.home() / ".ai-badger" / "framework"
    value = argv_root()
    if value:
        root = checked(value, "--root")
    else:
        root = next((anc for anc in [here, *here.parents] if is_root(anc)), None)
        if root is None and os.environ.get("AI_BADGER"):
            root = checked(os.environ["AI_BADGER"], "$AI_BADGER")
        root = root or recorded(here) or (cache if is_root(cache) else None)
    if root is None:
        raise RuntimeError(
            f"could not locate the ai-badger framework: none above {here.parent}, no "
            f"$AI_BADGER, no frameworkRoot in a .ai-badger/manifest.json above it, and no "
            f"cache at {cache} — pass --root <framework> or clone "
            f"https://github.com/Arasz/ai-badger"
        )
    sys.path.insert(0, str(root / "scripts"))
    return root.resolve()


try:
    FRAMEWORK_ROOT: Optional[Path] = _bootstrap_lib()
except RuntimeError:  # a hook degrades to silence; it never breaks a session
    FRAMEWORK_ROOT = None


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

    project_root = resolve_project_root(payload)
    if FRAMEWORK_ROOT is None or project_root is None:
        _debug("skip", reason="no_root" if project_root is None else "no_framework")
        return 0

    notice = drift_notice.scaffold_drift_notice(project_root, str(FRAMEWORK_ROOT))
    if not notice:
        _debug("skip", reason="no_drift")
    else:
        _debug("fire", project=str(project_root))
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": notice,
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
