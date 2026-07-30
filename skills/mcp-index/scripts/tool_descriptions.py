#!/usr/bin/env python3
"""What an MCP tool is for, and whether its server is talking.

Three sources of a tool's tags and intent, in descending authority: the mcp catalog
(`features/<stack>/mcp/<server>/tools.json`), a human (`mcp-index tag`/`intent`), and the name
heuristics below. Plus the status vocabulary for a server that reported no tools — ADR-0014
decision 7. Imported by mcp_index.py, which owns the index file and the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

# ── Tag taxonomy (loaded from features/common/mcp-tags.json or fallback) ──
DEFAULT_TAXONOMY: dict[str, Any] = {
    "categories": {
        "language": {
            "tags": ["csharp", "typescript", "javascript", "python", "sql", "css", "html"],
        },
        "action": {
            "tags": [
                "navigation", "diagnostic", "build", "run", "refactoring",
                "search", "read", "write", "terminal",
            ],
        },
        "domain": {
            "tags": [
                "database", "tracing", "opentelemetry", "browser",
                "dotnet", "semantic", "files",
            ],
        },
        "meta": {"tags": ["batch", "slow", "unsafe"]},
    },
}


def load_taxonomy(fw_root: Optional[Path]) -> dict[str, Any]:
    """Load the tag taxonomy, falling back to the built-in default."""
    if fw_root:
        tax_path = Path(fw_root) / "features" / "common" / "mcp-tags.json"
        if tax_path.exists():
            return json.loads(tax_path.read_text(encoding="utf-8"))
    return DEFAULT_TAXONOMY


def all_valid_tags(taxonomy: dict[str, Any]) -> set[str]:
    """Flatten all valid tags from the taxonomy."""
    return {t for cat in taxonomy["categories"].values() for t in cat["tags"]}


# ── Auto-tagging heuristics ──────────────────────────────────────────────────

def auto_tags(tool_name: str, server_name: str, valid_tags: set[str]) -> list[str]:
    """Assign tags from tool-name heuristics, or ["general"] when none match."""
    name = tool_name.lower()
    tags: set[str] = set()

    # Server-level heuristics
    if "playwright" in server_name.lower() or "browser" in server_name.lower():
        tags.add("browser")

    # Name-based heuristics (order matters — more specific first).
    # A name substring may infer an *action* (build, search, read, ...); a *technology* only
    # through a tight, unambiguous alias — see issue #171 for the false positives that drove
    # the split, and docs/changelog/0.51.0-a-build-is-not-a-dotnet.md for the two that stayed.
    if any(kw in name for kw in ("database", "schema", "db")):
        tags.add("database")
    if "sql" in name:
        tags.update(["sql", "database"])
    if "build" in name:
        tags.add("build")
    if "run" in name or "execute" in name:
        tags.add("run")
    if "search" in name or "find" in name:
        tags.add("search")
    if any(kw in name for kw in ("refactor", "rename", "reformat", "move_type")):
        tags.add("refactoring")
    if "symbol" in name:
        tags.update(["semantic", "search"])
    if any(kw in name for kw in ("problem", "error", "diagnostic")):
        tags.add("diagnostic")
    if "span" in name or "otel" in name or "service_map" in name:
        tags.update(["tracing", "opentelemetry"])
    if any(kw in name for kw in ("browser", "navigate", "screenshot", "click")):
        tags.add("browser")
    if any(kw in name for kw in ("file", "directory", "tree", "glob")):
        tags.add("files")
    if "editor" in name or "open_" in name:
        tags.add("navigation")
    if "navigate" in name:
        tags.add("navigation")
    if "read" in name:
        tags.add("read")
    if any(kw in name for kw in ("write", "create", "patch", "replace")):
        tags.add("write")
    if "terminal" in name or "shell" in name:
        tags.add("terminal")

    valid = sorted(tags & valid_tags)
    return valid if valid else ["general"]


# ── The mcp catalog: curation outranks the heuristics ────────────────────────

CATALOG, HEURISTIC, MANUAL = "catalog", "heuristic", "manual"

Catalog = Dict[str, Dict[str, Dict[str, Any]]]


def load_catalog(fw_root: Optional[Path]) -> Catalog:
    """Curated tool entries per server name, from every features/*/mcp/<server>/tools.json.

    Stacks in directory order, last writer wins on a duplicate tool. An unreachable framework
    yields `{}` and the name heuristics carry the whole index.
    """
    if fw_root is None:
        return {}
    catalog: Catalog = {}
    for path in sorted(Path(fw_root).glob("features/*/mcp/*/tools.json")):
        if not (path.parent / "meta.json").is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tools = catalog.setdefault(data.get("server") or path.parent.name, {})
        for tool in data.get("tools", []):
            if tool.get("name"):
                tools[tool["name"]] = tool
    return catalog


def describe_tool(server: str, name: str, description: str,
                  catalog: Catalog, valid_tags: set[str]) -> dict[str, Any]:
    """Tags, intent and origin for one tool — the catalog when it knows it, else heuristics."""
    curated = catalog.get(server, {}).get(name)
    if curated:
        return {
            "tags": list(curated.get("tags") or auto_tags(name, server, valid_tags)),
            "intent": curated["intent"],
            "origin": CATALOG,
        }
    return {
        "tags": auto_tags(name, server, valid_tags),
        "intent": description or f"TODO: describe what {name} does",
        "origin": HEURISTIC,
    }


# ── Server status: opposite remedies must not share one silence ──────────────

OK, DISABLED, EMPTY, UNKNOWN, ABSENT = "ok", "disabled", "empty", "unknown", "absent"


def server_status(server: dict[str, Any]) -> str:
    """The status a host listing actually supports for one server (ADR-0014 decision 7).

    `unreachable` is not produced: no `hermes mcp list` mode reports a connection failure
    distinctly from an empty tool list, and a status nothing can set is not a status.
    """
    if server.get("enabled") is False:
        return DISABLED
    if not server.get("tools_known", True):
        return UNKNOWN
    return OK if server.get("tools") else EMPTY
