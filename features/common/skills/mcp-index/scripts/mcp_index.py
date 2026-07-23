#!/usr/bin/env python3
"""mcp-index: manage the MCP tool index for ai-badger projects.

Reads Hermes's MCP tool list (hermes mcp list --json) and produces
.ai-badger/mcp-tools.yaml with auto-assigned tags and intents.

Commands:
  init     — create index from MCP tool list
  update   — add new tools, mark removed ones (preserves manual tags)
  validate — check all tools have proper tags and intents
  tag      — set tags for a specific tool
  intent   — set intent for a specific tool
  list     — display all tools, optionally filtered by tag
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml  # pylint: disable=import-error

# ── Tag taxonomy (loaded from features/common/mcp-tags.json or fallback) ──
_DEFAULT_TAXONOMY: dict[str, Any] = {
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


def _load_taxonomy(fw_root: Optional[Path] = None) -> dict[str, Any]:
    """Load tag taxonomy, falling back to the built-in default."""
    if fw_root is None:
        fw_root = _find_framework_root()
    if fw_root:
        tax_path = fw_root / "features" / "common" / "mcp-tags.json"
        if tax_path.exists():
            return json.loads(tax_path.read_text(encoding="utf-8"))
    return _DEFAULT_TAXONOMY


def _find_framework_root() -> Optional[Path]:
    """Walk ancestors for a framework root (has VERSION + schemas/)."""
    start = Path(__file__).resolve()
    for anc in [start, *start.parents]:
        if (anc / "VERSION").is_file() and (anc / "schemas").is_dir():
            return anc
    return None


def _all_valid_tags(taxonomy: dict[str, Any]) -> set[str]:
    """Flatten all valid tags from the taxonomy."""
    return {t for cat in taxonomy["categories"].values() for t in cat["tags"]}


# ── Auto-tagging heuristics ──────────────────────────────────────────────────

def _auto_tags(tool_name: str, server_name: str = "") -> list[str]:
    """Assign tags based on tool name heuristics.

    Returns a list of tag strings. Falls back to ["general"] if no
    heuristics match.
    """
    name = tool_name.lower()
    tags: set[str] = set()

    # Server-level heuristics
    if "playwright" in server_name.lower() or "browser" in server_name.lower():
        tags.add("browser")

    # Name-based heuristics (order matters — more specific first)
    if any(kw in name for kw in ("sql", "database", "schema", "db")):
        tags.update(["database", "sql"])
    if "build" in name or "solution" in name:
        tags.update(["dotnet", "build"])
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
    _is_otel = any(
        kw in name for kw in ("span", "trace", "log", "otel")
    ) or ("service" in name and "map" not in name)
    if _is_otel:
        tags.update(["tracing", "opentelemetry"])
    if "service_map" in name:
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

    # Restrict to valid taxonomy tags
    all_tags = _all_valid_tags(_load_taxonomy())
    valid = sorted(tags & all_tags)

    return valid if valid else ["general"]


# ── MCP tool discovery ──────────────────────────────────────────────────────

def _fetch_mcp_tools(from_json: Optional[str] = None) -> list[dict[str, Any]]:
    """Get MCP tool list.

    If from_json is provided, parse it directly (for testing).
    Otherwise, call `hermes mcp list --json`.
    """
    if from_json is not None:
        data = json.loads(from_json)
        return data.get("servers", [])

    result = subprocess.run(
        ["hermes", "mcp", "list", "--json"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: hermes mcp list --json failed: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    data = json.loads(result.stdout)
    return data.get("servers", [])


# ── Index file operations ────────────────────────────────────────────────────

def _index_path(target: str) -> Path:
    """Return the path to .ai-badger/mcp-tools.yaml for a project."""
    return Path(target) / ".ai-badger" / "mcp-tools.yaml"


def _read_index(target: str) -> Optional[dict[str, Any]]:
    """Read the existing index, or None if it doesn't exist."""
    path = _index_path(target)
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_index(target: str, data: dict[str, Any]) -> None:
    """Write the index file, creating parent directories."""
    path = _index_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_init(target: str, from_json: Optional[str] = None) -> int:
    """Create a new index from the current MCP tool list."""
    servers = _fetch_mcp_tools(from_json)

    sources = []
    for server in servers:
        tools: dict[str, dict[str, Any]] = {}
        for tool in server.get("tools", []):
            name = tool["name"]
            tools[name] = {
                "tags": _auto_tags(name, server.get("name", "")),
                "intent": tool.get(
                    "description", f"TODO: describe what {name} does"
                ),
            }
        entry: dict[str, Any] = {"name": server["name"], "tools": tools}
        if server.get("url"):
            entry["url"] = server["url"]
        sources.append(entry)

    index = {
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": sources,
    }

    _write_index(target, index)
    tool_count = sum(len(s["tools"]) for s in sources)
    general_count = sum(
        1 for s in sources
        for t in s["tools"].values() if t["tags"] == ["general"]
    )
    print(f"Indexed {tool_count} tools across {len(sources)} server(s).")
    if general_count:
        print(
            f"  {general_count} tool(s) tagged as 'general' — "
            "run 'mcp-index tag <tool> <tags...>' to curate."
        )
    return 0


def cmd_validate(target: str) -> int:
    """Validate the index: all tools have non-general, non-empty tags and intents."""
    index = _read_index(target)
    if index is None:
        print(
            "ERROR: .ai-badger/mcp-tools.yaml not found. "
            "Run 'mcp-index init' first.",
            file=sys.stderr,
        )
        return 1

    errors: list[str] = []
    all_tags = _all_valid_tags(_load_taxonomy())

    for source in index.get("sources", []):
        sname = source["name"]
        for tname, tool in source.get("tools", {}).items():
            full = f"{sname}:{tname}"
            tags = tool.get("tags", [])

            if not tags:
                errors.append(f"{full}: no tags")
            elif tags == ["general"]:
                errors.append(
                    f"{full}: still tagged 'general' — needs curation"
                )
            else:
                invalid = [t for t in tags if t not in all_tags]
                if invalid:
                    errors.append(f"{full}: invalid tags: {invalid}")

            intent = tool.get("intent", "")
            if not intent:
                errors.append(f"{full}: no intent")
            elif len(intent) < 10:
                errors.append(
                    f"{full}: intent too short ({len(intent)} chars, min 10)"
                )

    if errors:
        print(
            f"Validation failed: {len(errors)} error(s):", file=sys.stderr
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    total = sum(len(s["tools"]) for s in index.get("sources", []))
    print(f"OK: {total} tool(s) validated")
    return 0


def cmd_update(target: str, from_json: Optional[str] = None) -> int:
    """Update index: add new tools, mark removed ones, preserve manual tags."""
    index = _read_index(target)
    if index is None:
        print("No existing index. Running init instead.", file=sys.stderr)
        return cmd_init(target, from_json)

    servers = _fetch_mcp_tools(from_json)

    # Build set of current tool names per server
    current_tools: dict[str, set[str]] = {}
    for server in servers:
        current_tools[server["name"]] = {
            t["name"] for t in server.get("tools", [])
        }

    changes = 0
    for source in index.get("sources", []):
        sname = source["name"]
        current = current_tools.get(sname, set())
        existing = set(source.get("tools", {}).keys())

        # Mark removed tools
        for name in (existing - current):
            source["tools"][name]["status"] = "removed"
            changes += 1

        # Add new tools
        server_data = next(
            (s for s in servers if s["name"] == sname), None
        )
        for name in (current - existing):
            desc = ""
            if server_data:
                for t in server_data.get("tools", []):
                    if t["name"] == name:
                        desc = t.get("description", "")
                        break
            source["tools"][name] = {
                "tags": _auto_tags(name, sname),
                "intent": desc or f"TODO: describe what {name} does",
            }
            changes += 1

    # Add entirely new servers
    existing_names = {s["name"] for s in index["sources"]}
    for server in servers:
        if server["name"] not in existing_names:
            tools = {}
            for tool in server.get("tools", []):
                tools[tool["name"]] = {
                    "tags": _auto_tags(tool["name"], server["name"]),
                    "intent": tool.get(
                        "description",
                        f"TODO: describe what {tool['name']} does",
                    ),
                }
            entry = {"name": server["name"], "tools": tools}
            if server.get("url"):
                entry["url"] = server["url"]
            index["sources"].append(entry)
            changes += 1

    if changes:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        index["generated_at"] = ts
        _write_index(target, index)
        print(f"Updated: {changes} change(s) applied.")
    else:
        print("No changes — index is up to date.")

    return 0


def cmd_tag(target: str, tool_ref: str, tags: list[str]) -> int:
    """Set tags for a specific tool."""
    if not tags:
        print("ERROR: at least one tag is required.", file=sys.stderr)
        return 2

    all_tags = _all_valid_tags(_load_taxonomy())
    invalid = [t for t in tags if t not in all_tags]
    if invalid:
        print(
            f"ERROR: invalid tags: {invalid}. "
            f"Valid tags: {sorted(all_tags)}",
            file=sys.stderr,
        )
        return 1

    index = _read_index(target)
    if index is None:
        print("ERROR: index not found.", file=sys.stderr)
        return 1

    if ":" not in tool_ref:
        print(
            "ERROR: tool reference must be in format 'server:tool_name'.",
            file=sys.stderr,
        )
        return 2

    server_name, tool_name = tool_ref.split(":", 1)
    for source in index.get("sources", []):
        if source["name"] == server_name:
            if tool_name in source["tools"]:
                source["tools"][tool_name]["tags"] = sorted(tags)
                _write_index(target, index)
                print(f"Tags for {tool_ref} set to: {tags}")
                return 0
            print(
                f"ERROR: tool '{tool_name}' not found "
                f"in server '{server_name}'.",
                file=sys.stderr,
            )
            return 1

    print(f"ERROR: server '{server_name}' not found.", file=sys.stderr)
    return 1


def cmd_intent(target: str, tool_ref: str, intent: str) -> int:
    """Set intent for a specific tool."""
    if len(intent) < 10:
        print(
            f"ERROR: intent must be at least 10 characters "
            f"(got {len(intent)}).",
            file=sys.stderr,
        )
        return 1

    index = _read_index(target)
    if index is None:
        print("ERROR: index not found.", file=sys.stderr)
        return 1

    if ":" not in tool_ref:
        print(
            "ERROR: tool reference must be in format 'server:tool_name'.",
            file=sys.stderr,
        )
        return 2

    server_name, tool_name = tool_ref.split(":", 1)
    for source in index.get("sources", []):
        if source["name"] == server_name:
            if tool_name in source["tools"]:
                source["tools"][tool_name]["intent"] = intent
                _write_index(target, index)
                print(f"Intent for {tool_ref} set.")
                return 0
            print(
                f"ERROR: tool '{tool_name}' not found "
                f"in server '{server_name}'.",
                file=sys.stderr,
            )
            return 1

    print(f"ERROR: server '{server_name}' not found.", file=sys.stderr)
    return 1


def cmd_list(
    target: str, tag: Optional[str] = None, untagged: bool = False
) -> int:
    """List tools, optionally filtered."""
    index = _read_index(target)
    if index is None:
        print("ERROR: index not found.", file=sys.stderr)
        return 1

    total = 0
    for source in index.get("sources", []):
        sname = source["name"]
        header_printed = False
        for tname, tool in source.get("tools", {}).items():
            tags = tool.get("tags", [])
            is_removed = tool.get("status") == "removed"

            # Apply filters
            if tag is not None and tag not in tags:
                continue
            if untagged and tags != ["general"]:
                continue

            if not header_printed:
                print(f"\n[{sname}]")
                header_printed = True

            status = " (removed)" if is_removed else ""
            tag_str = ", ".join(tags)
            print(f"  {sname}:{tname}{status}")
            print(f"    tags:   {tag_str}")
            print(f"    intent: {tool.get('intent', '')}")
            total += 1

    filter_desc = ""
    if tag:
        filter_desc = f" (tag={tag})"
    elif untagged:
        filter_desc = " (untagged only)"
    print(f"\n{total} tool(s){filter_desc}")
    return 0


# ── CLI dispatch ────────────────────────────────────────────────────────────

def _usage() -> int:
    print(__doc__)
    return 2


def _parse_target_and_remaining(
    argv: list[str],
) -> tuple[Optional[str], list[str]]:
    """Extract --target value and return (target, remaining_args)."""
    try:
        target_idx = argv.index("--target")
        target = argv[target_idx + 1]
        remaining = [
            a for i, a in enumerate(argv)
            if i not in (target_idx, target_idx + 1)
        ]
        return target, remaining
    except (ValueError, IndexError):
        return None, argv


def _extract_clean_args(args: list[str]) -> list[str]:
    """Remove --target and its value from args list."""
    clean: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--target":
            skip = True
            continue
        clean.append(a)
    return clean


def main(argv: Optional[list[str]] = None) -> int:
    """Dispatch to the appropriate subcommand."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        return _usage()

    cmd = argv[0]
    target, remaining = _parse_target_and_remaining(argv)

    if target is None:
        print("ERROR: --target <path> is required.", file=sys.stderr)
        return 2

    if cmd == "init":
        from_json = None
        if "--from-json" in remaining:
            ji = remaining.index("--from-json")
            from_json = remaining[ji + 1]
        return cmd_init(target, from_json)

    if cmd == "validate":
        return cmd_validate(target)

    if cmd == "update":
        from_json = None
        if "--from-json" in remaining:
            ji = remaining.index("--from-json")
            from_json = remaining[ji + 1]
        return cmd_update(target, from_json)

    if cmd == "tag":
        clean_args = _extract_clean_args(remaining[1:])
        if len(clean_args) < 2:
            print(
                "ERROR: tag requires tool_ref and at least one tag.",
                file=sys.stderr,
            )
            return 2
        return cmd_tag(target, clean_args[0], clean_args[1:])

    if cmd == "intent":
        clean_args = _extract_clean_args(remaining[1:])
        if len(clean_args) < 2:
            print(
                "ERROR: intent requires tool_ref and intent text.",
                file=sys.stderr,
            )
            return 2
        return cmd_intent(target, clean_args[0], " ".join(clean_args[1:]))

    if cmd == "list":
        tag_filter = None
        if "--tag" in remaining:
            ti = remaining.index("--tag")
            tag_filter = remaining[ti + 1]
        return cmd_list(
            target, tag=tag_filter, untagged="--untagged" in remaining
        )

    return _usage()


if __name__ == "__main__":
    sys.exit(main())
