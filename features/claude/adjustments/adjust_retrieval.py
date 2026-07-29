"""Adjustment: deliver the BM25 retrieval modules beside the Claude context-enrichment hook.

`context_enrichment_hook.py` (mcp-index skill, issue #147) needs `tokenizer.py`, `bm25.py`,
`mcp_matcher.py` and `context_enrichment.py` as siblings — the same modules
`features/hermes/adjustments/adjust_hooks.py` copies beside `ai_badger_hooks.py`. Delivered here
to `.ai-badger/skills/mcp-index/scripts/` instead, which is where Claude's hook wiring
(`hook_wiring.py`) actually points `context_enrichment_hook.py`'s command.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

RETRIEVAL_MODULES = ("tokenizer.py", "bm25.py", "mcp_matcher.py", "context_enrichment.py")


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Copy the retrieval modules beside the scaffolded mcp-index skill's hook script.

    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'target_dir': Path,     # .ai-badger/
            'target': Path,         # project root
            'skills': list[str],
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    if "claude" not in (context.get("config", {}).get("agents") or []):
        return {"applied": False, "files": [], "notes": "claude not in config.agents"}
    if "mcp-index" not in (context.get("skills") or []):
        return {"applied": False, "files": [], "notes": "mcp-index skill not scaffolded"}

    framework_root = context["framework_root"]
    target_dir = context["target_dir"]
    dest_dir = target_dir / "skills" / "mcp-index" / "scripts"
    if not dest_dir.is_dir():
        return {"applied": False, "files": [], "notes": "mcp-index scripts/ not scaffolded"}

    src_dir = framework_root / "features" / "common" / "retrieval"
    files: List[str] = []
    for filename in RETRIEVAL_MODULES:
        src = src_dir / filename
        if not src.is_file():
            continue
        dst = dest_dir / filename
        shutil.copy2(src, dst)
        files.append(str(dst.relative_to(target_dir.parent)))

    if not files:
        return {"applied": False, "files": [], "notes": "no retrieval modules found"}
    return {
        "applied": True,
        "files": files,
        "notes": f"copied {len(files)} retrieval module(s) beside context_enrichment_hook.py",
    }
