"""A synthetic catalog tool, and a framework root that carries it.

The `tools` feature type (ADR-0039) ships no tool of its own, so the tests that cover it
need one that exists only for the test: a `meta.json` naming the prerequisite and the
per-agent arms, a check/install script pair, and the guard a native arm runs in place of
the tool's own hook.

`install_tool` adds that tool to a framework root. `overlay_root` builds a root that is
the real tree with the tool added — every other entry symlinked, `features/common/tools/`
real — so the scaffolder sees a complete framework and the tool at the same time, and the
real tree is never written to.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

TOOL = "shim"
TOOL_PATH = f"features/common/tools/{TOOL}"

META = {
    "$schema": "../../../../schemas/tool.schema.json",
    "name": TOOL,
    "package": TOOL,
    "description": "A CLI proxy that rewrites shell commands; the catalog tool the tests use.",
    "homepage": "https://example.test/shim",
    "prerequisite": {
        "summary": "the shim CLI on PATH",
        "check": f"python3 {TOOL_PATH}/scripts/check.py",
        "install": f"python3 {TOOL_PATH}/scripts/install.py --run",
    },
    "hooks": {
        "claude": {"mode": "native", "arg": "claude", "guard": "scripts/shim_guard.py"},
        "codex": {"mode": "propose", "arg": "codex", "guard": "scripts/shim_guard.py"},
        "copilot": {"mode": "native", "arg": "copilot"},
        "pi": {"mode": "init", "arg": "pi"},
        "hermes": {"mode": "propose", "arg": "hermes"},
    },
}

CHECK = '''#!/usr/bin/env python3
"""Prerequisite check for the synthetic catalog tool: the shim CLI on PATH.

Exit code: 0 = ready, 1 = absent.
"""
import shutil
import sys

sys.exit(0 if shutil.which("shim") else 1)
'''

INSTALL = '''#!/usr/bin/env python3
"""Prerequisite install for the synthetic catalog tool: a no-op that reports what it did."""
import sys

if "--run" not in sys.argv:
    print("usage: install.py --run")
    sys.exit(2)
print("shim installed")
'''

GUARD = '''#!/usr/bin/env python3
"""The guard the native arm runs in place of the tool's own hook.

Reads the hook payload on stdin and prints the `shim rewrite` — the rewritten command the
harness then judges. ai-badger inlines this file into the hook command (ADR-0039), so it
must stay one stdlib-only file.
"""
import json
import sys

# shim-guard-marker: the tests look for this line in the inlined hook command.
MARKER = "shim-guard-marker"


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return
    print(json.dumps({"hookSpecificOutput": {"updatedInput": {"command": "shim " + command}}}))


if __name__ == "__main__":
    main()
'''


TOOL_MD = """<!-- shim tool -->
## Tools: shim

The synthetic catalog tool: a CLI proxy that rewrites shell commands. It exists for the
tests of the `tools` feature type, which ships no tool of its own.
"""


def install_tool(root: Path) -> Path:
    """Add the synthetic tool to *root*: its catalog directory and its index entry."""
    tool = root / TOOL_PATH
    (tool / "scripts").mkdir(parents=True, exist_ok=True)
    (tool / "meta.json").write_text(json.dumps(META, indent=2) + "\n", encoding="utf-8")
    (tool / "tool.md").write_text(TOOL_MD, encoding="utf-8")
    (tool / "scripts" / "check.py").write_text(CHECK, encoding="utf-8")
    (tool / "scripts" / "install.py").write_text(INSTALL, encoding="utf-8")
    (tool / "scripts" / "shim_guard.py").write_text(GUARD, encoding="utf-8")

    index_path = root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    tools = index["stacks"]["common"].setdefault("tools", [])
    if not any(item.get("name") == TOOL for item in tools):
        tools.append({"name": TOOL, "path": TOOL_PATH})
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return tool


def overlay_root(tmp_path: Path, repo_root: Path) -> Path:
    """A framework root: the real tree's entries symlinked, with the synthetic tool added."""
    root = tmp_path / "framework"
    root.mkdir(parents=True, exist_ok=True)
    for entry in sorted(repo_root.iterdir()):
        if entry.name in {".git", "features", "index.json"}:
            continue
        (root / entry.name).symlink_to(entry)

    features = root / "features"
    features.mkdir()
    for entry in sorted((repo_root / "features").iterdir()):
        if entry.name != "common":
            (features / entry.name).symlink_to(entry)

    common = features / "common"
    common.mkdir()
    for entry in sorted((repo_root / "features" / "common").iterdir()):
        if entry.name != "tools":
            (common / entry.name).symlink_to(entry)
    (common / "tools").mkdir()

    shutil.copy2(repo_root / "index.json", root / "index.json")
    install_tool(root)
    return root
