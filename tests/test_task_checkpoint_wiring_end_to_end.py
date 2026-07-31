"""End-to-end regression: the REAL hooks-manifest.json + hooks.json wire stop_hook.py onto
Claude's `Stop` and `SessionEnd`.

`stop_hook.py` shipped tested and scaffolded from the framework's first release and was
registered nowhere; three consumer repos wired it by hand instead (issue #141, and the commit
that did it is titled "wire the missing runtime"). A synthetic manifest passing proves nothing
about that gap, so this test loads the framework's actual catalog — the same philosophy as
tests/test_context_enrichment_wiring_end_to_end.py.
"""
from __future__ import annotations

import json
import re
import sys

from scaffold_helpers import _config


def _load(load_script, root, relpath):
    for entry in (str(root / "features/common/skills/welcome-ai-badger/scripts"),
                  str(root / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(relpath)


def _scaffold_task_scripts(target):
    scripts_dir = target / ".ai-badger" / "skills" / "task" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for script in ("stop_hook.py", "session_start_hook.py", "drift_notice_hook.py",
                   "user_prompt_hook.py"):
        (scripts_dir / script).write_text("", encoding="utf-8")


def _wired(tmp_path, load_script, root):
    ctx_mod = _load(load_script, root,
                    "features/common/skills/welcome-ai-badger/scripts/scaffold_context.py")
    bl = load_script("engine/badger_lib.py")
    hook_wiring = _load(load_script, root,
                        "features/common/skills/welcome-ai-badger/scripts/hook_wiring.py")

    target = tmp_path / "proj"
    _scaffold_task_scripts(target)
    config = _config(agents=["claude"])
    ctx = ctx_mod.ScaffoldContext(
        root=root, target=target, aib=target / ".ai-badger", config=config,
        index={}, stacks=[], skills=[], excluded=bl.exclusions(config),
    )

    hook_wiring.HookWiring(ctx).wire()

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return {
        event: sorted((re.search(r"([\w.-]+\.py)", h.get("command", "")) or [""])[0]
                      for entry in entries for h in entry.get("hooks", []))
        for event, entries in settings.get("hooks", {}).items()
    }


def test_stop_is_wired_to_stop_hook_and_nothing_else(tmp_path, load_script, root):
    assert _wired(tmp_path, load_script, root).get("Stop") == ["stop_hook.py"]


def test_session_end_is_wired_to_stop_hook_too(tmp_path, load_script, root):
    """The per-turn `Stop` never fires for an interrupted final turn; `SessionEnd` is the
    only event that flushes that turn's checkpoint."""
    assert _wired(tmp_path, load_script, root).get("SessionEnd") == ["stop_hook.py"]


def test_session_start_keeps_its_own_script_and_does_not_adopt_stop_hook(
    tmp_path, load_script, root
):
    """The task skill's scripts/ holds four *_hook.py files; #158's fallback would have wired
    whichever sorted first. Both new entries name their script, so this stays exact."""
    wired = _wired(tmp_path, load_script, root)

    assert wired.get("SessionStart") == ["session_start_hook.py"]
