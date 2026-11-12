"""Build tests/fixtures/retired-semantica-shapes.json: the four semantica launches as shipped.

Run once from a full clone (``python3 tests/fixtures/build_retired_semantica_shapes.py``); the
output is committed and the end-to-end prune tests read it. Every seed names its origin under
``_source``. Seeds read from a commit are what that commit actually held; the rest come from
:func:`render`, a frozen copy of the 0.217-era ``_render_entry`` rules.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().with_name("retired-semantica-shapes.json")
NAME = "semantica"
CATALOG = "features/common/stack-mcp.json"
SKILL = "semantica-knowledge-graph"
# (shape id, the commit where that launch was live)
SHAPES = (("shape1", "c5e424bb"), ("shape2", "e2b95eac"), ("shape3", "240ad606"),
          ("shape4", "769d94fb^"))
# The main checkout's gitignored .mcp.json entry, read 2026-11-12 (MEASURED). Recorded here
# because that file is live state and loses the entry once the prune ships.
MCP_JSON_SHAPE4 = {"command": "semantica-mcp", "env": {"SEMANTICA_DISABLE_PROGRESS": "1"},
                   "tools": ["*"]}
CIRCULARITY = (
    "A seed marked 'frozen renderer' proves only that the prune matches what this builder's "
    "render() writes, not what the old scaffold wrote. Bounds: the correctness review read "
    "pin_cwd=False and the same _render_entry shape at all four commits, and the prune compares "
    "_launch_of (command, args, env, cwd) only, so a decoration (tools, exposure) cannot cause "
    "a mismatch.")
# Per-destination decorations of the 0.217-era renderer: .mcp.json and .github/mcp.json carry
# the Copilot tools allowlist, .pi/mcp.json the pi exposure default. No destination pins cwd.
DECORATIONS = {".mcp.json": {"tools": ["*"]}, ".github/mcp.json": {"tools": ["*"]},
               ".pi/mcp.json": {"exposure": "direct"}}


def git_show(rev: str, path: str) -> Optional[str]:
    """The text of *path* at *rev*, or None when that commit has no such file."""
    done = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{path}"],
                          capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else None


def declaration(rev: str) -> dict:
    """The catalog declaration of the server at *rev*."""
    servers = json.loads(git_show(rev, CATALOG))["servers"]
    return next(srv for srv in servers if srv["name"] == NAME)


def render(srv: dict, dest: str) -> dict:
    """Frozen 0.217-era render of one declaration for *dest*: split, keep args/env, no cwd."""
    entry = {}
    if "args" in srv:
        entry["command"], entry["args"] = srv["command"], srv["args"]
    else:
        parts = srv["command"].split()
        entry["command"] = parts[0]
        if parts[1:]:
            entry["args"] = parts[1:]
    if "env" in srv:
        entry["env"] = srv["env"]
    entry.update(DECORATIONS[dest])
    return entry


def committed(rev: str, path: str) -> Optional[dict]:
    """The server's entry in the committed *path* at *rev*, or None."""
    text = git_show(rev, path)
    return None if text is None else json.loads(text).get("mcpServers", {}).get(NAME)


def main_checkout_mcp_json() -> Optional[dict]:
    """The entry in the main checkout's .mcp.json (read only), or None."""
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True, check=True)
    path = Path(common.stdout.strip()).parent / ".mcp.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["mcpServers"].get(NAME)
    except (OSError, ValueError, KeyError):
        return None


def hook_entry(rev: str, path: str, events_key: str, event: str) -> dict:
    """The hook entry at *rev* in *path* whose JSON names the retired skill."""
    hooks = json.loads(git_show(rev, path))[events_key][event]
    return next(entry for entry in hooks if SKILL in json.dumps(entry))


def build() -> dict:
    source, shapes = {}, []
    for shape, rev in SHAPES:
        srv = declaration(rev)
        files = {}
        for dest in (".github/mcp.json", ".pi/mcp.json", ".mcp.json"):
            key = f"{shape}/{dest}"
            seed = committed(rev, dest)
            if seed is not None:
                source[key] = f"committed output: git show {rev}:{dest} (MEASURED)"
            elif dest == ".mcp.json" and shape == "shape4":
                live = main_checkout_mcp_json()
                if live is not None and live != MCP_JSON_SHAPE4:
                    raise SystemExit(f"main checkout .mcp.json changed: {live}")
                seed = MCP_JSON_SHAPE4
                source[key] = ("main checkout .mcp.json, gitignored, read 2026-11-12 (MEASURED); "
                               "literal recorded in the builder as MCP_JSON_SHAPE4")
            else:
                seed = render(srv, dest)
                why = "no committed file at that commit" if dest != ".mcp.json" else \
                    ".mcp.json is gitignored"
                source[key] = (f"frozen renderer over git show {rev}:{CATALOG} ({why}); "
                               f"see circularity_limit")
            files[dest] = seed
        shapes.append({"id": shape, "commit": rev, "declaration": srv, "files": files})
    last = SHAPES[-1][1]
    source["claude_hook"] = f"git show {last}:.claude/settings.json hooks.PostToolUse (MEASURED)"
    source["copilot_hook"] = (f"git show {last}:.github/hooks/ai-badger-hooks.json "
                              f"hooks.postToolUse (MEASURED)")
    source["circularity_limit"] = CIRCULARITY
    source["builder"] = "tests/fixtures/build_retired_semantica_shapes.py"
    return {
        "_source": source,
        "name": NAME,
        "skill": SKILL,
        "claude_hook": {"PostToolUse": hook_entry(last, ".claude/settings.json", "hooks",
                                                  "PostToolUse")},
        "copilot_hook": {"postToolUse": hook_entry(last, ".github/hooks/ai-badger-hooks.json",
                                                   "hooks", "postToolUse")},
        "shapes": shapes,
    }


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
