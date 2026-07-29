"""End-to-end regression: the REAL hooks-manifest.json + hooks.json wire context-enrichment
onto both Claude and Copilot without disturbing prompt-markers, which already lives on the same
event (issue #147's exact risk — #150 fixed the Copilot collision bug this would have hit, and
#158 fixed the Claude-side fallback risk, both before this landed).

Unlike tests/test_hook_wiring_claude.py and tests/test_adjust_hooks_copilot.py, which build a
synthetic hooks-manifest.json to pin specific defect shapes, this test loads the framework's
actual manifest and hooks.json — the thing that was "tested, scaffolded, and never executed"
three times over is exactly the gap between a synthetic fixture passing and the real catalog
doing the same. See tests/test_sync_plugin_skills.py's TestRealCatalogParity for the same
philosophy applied to skill copies.
"""
from __future__ import annotations

import json
import sys

from scaffold_helpers import _config


def _load(load_script, root, relpath):
    for entry in (str(root / "features/common/skills/welcome-ai-badger/scripts"),
                  str(root / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(relpath)


def _scaffold_mcp_index_and_prompt_markers(target):
    for skill, script in (("mcp-index", "context_enrichment_hook.py"),
                          ("prompt-markers", "user_prompt_hook.py")):
        scripts_dir = target / ".ai-badger" / "skills" / skill / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / script).write_text("", encoding="utf-8")


def test_claude_wires_context_enrichment_and_prompt_markers_both(tmp_path, load_script, root):
    ctx_mod = _load(load_script, root, "features/common/skills/welcome-ai-badger/scripts/scaffold_context.py")
    bl = load_script("engine/badger_lib.py")
    hook_wiring = _load(load_script, root,
                        "features/common/skills/welcome-ai-badger/scripts/hook_wiring.py")

    target = tmp_path / "proj"
    _scaffold_mcp_index_and_prompt_markers(target)
    config = _config(agents=["claude"])
    ctx = ctx_mod.ScaffoldContext(
        root=root, target=target, aib=target / ".ai-badger", config=config,
        index={}, stacks=[], skills=[], excluded=bl.exclusions(config),
    )

    hook_wiring.HookWiring(ctx).wire()

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    wired = [h.get("command", "").rstrip('"').rsplit("/", 1)[-1]
             for entry in settings.get("hooks", {}).get("UserPromptSubmit", [])
             for h in entry.get("hooks", [])]
    assert sorted(wired) == ["context_enrichment_hook.py", "user_prompt_hook.py"], wired


def test_copilot_wires_context_enrichment_and_prompt_markers_both(tmp_path, load_script, root):
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    _scaffold_mcp_index_and_prompt_markers(target)

    result = adjust_hooks.adjust({
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["mcp-index", "prompt-markers"],
    })

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    commands = [h["bash"] for h in hooks["hooks"]["userPromptSubmitted"]]
    names = sorted(c.rstrip('"').rsplit("/", 1)[-1] for c in commands)
    assert names == ["context_enrichment_hook.py", "user_prompt_hook.py"], names
