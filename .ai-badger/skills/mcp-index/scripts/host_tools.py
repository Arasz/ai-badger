#!/usr/bin/env python3
"""Tool names from Claude Code's own headless init event: `read_init`, `map_tools`, `fill`.

`claude -p --output-format stream-json --verbose` prints a `system/init` event whose `tools`
carry `mcp__<server>__<tool>` for every server the host connected, and whose `mcp_servers`
carry each server's status. The host does the authenticating — OAuth servers and `claude.ai`
connectors included — so this module handles no credentials and reads no token store.

Measured on Claude Code 2.1.302 (2026-10-18): the prompt `/cost` is a local command, so the
init event arrives (~5.5s) with 0 API requests and `total_cost_usd: 0`; `--settings
{"disableAllHooks": true}` ran 0 settings hooks (43 without it); `--no-session-persistence`
left no transcript. Names only: the event carries no descriptions.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set

# mcp_client.py sits beside this file in every deployment shape.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_client as mc  # noqa: E402  pylint: disable=wrong-import-position,import-error

CLAUDE_ENV = "MCP_INDEX_CLAUDE"
TIMEOUT = 60.0
CONNECTED = "connected"
VIA = "claude-init"
ARGV = ("-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
        "--settings", json.dumps({"disableAllHooks": True}), "/cost")
# Claude Code's own name for a tool: `mcp__<server>__<tool>`, the server name with every
# character outside [A-Za-z0-9_-] replaced by `_` (code.claude.com/docs/en/mcp, plugin tools).
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
PREFIX, SEP = "mcp__", "__"
# A host status this listing has a phrase for (tool_descriptions.HOST_STATUS_PHRASES).
STATUS_PHRASES = {"needs-auth": "Needs authentication", "failed": "Failed to connect"}

Server = Dict[str, Any]


class HostToolsError(RuntimeError):
    """The init event could not be read; the message is one line naming why."""


class HostInit(NamedTuple):
    """What the init event says: tool names by listing name, statuses, refused names."""

    tools: Dict[str, List[str]]
    statuses: Dict[str, str]
    ambiguous: Set[str]


def executable() -> Optional[str]:
    """`$MCP_INDEX_CLAUDE` when set (empty means none), else the `claude` on PATH."""
    if CLAUDE_ENV in os.environ:
        return os.environ[CLAUDE_ENV] or None
    return shutil.which("claude")


def prefixes(name: str) -> Set[str]:
    """The `mcp__` prefix forms one server name may take: the documented rule, and the same
    with runs of `_` collapsed and trimmed, which `claude.ai <Name>` connectors match too."""
    plain = _UNSAFE.sub("_", name)
    return {plain, re.sub(r"_+", "_", plain).strip("_")} - {""}


def map_tools(init: Dict[str, Any]) -> HostInit:
    """Assign each `mcp__` tool to exactly one listed server; refuse every guess.

    A server whose prefix another server shares, or that could own a tool another server could
    own too, is refused whole: a misfiled tool would make per-server removal wrong.
    """
    statuses = {str(s["name"]): str(s.get("status") or "")
                for s in init.get("mcp_servers") or []
                if isinstance(s, dict) and isinstance(s.get("name"), str)}
    owners: Dict[str, Set[str]] = {}
    for name in statuses:
        for form in prefixes(name):
            owners.setdefault(form, set()).add(name)
    ambiguous = {n for names in owners.values() if len(names) > 1 for n in names}
    tools: Dict[str, List[str]] = {name: [] for name in statuses}
    for full in init.get("tools") or []:
        if not isinstance(full, str) or not full.startswith(PREFIX):
            continue
        rest = full[len(PREFIX):]
        claims = {(n, rest[len(f) + len(SEP):]) for f, names in owners.items() for n in names
                  if rest.startswith(f + SEP) and len(rest) > len(f) + len(SEP)}
        servers = {n for n, _ in claims}
        if len(servers) > 1:
            ambiguous |= servers
        elif claims:
            name, tool = claims.pop()
            if tool not in tools[name]:
                tools[name].append(tool)
    return HostInit({n: t for n, t in tools.items() if n not in ambiguous}, statuses, ambiguous)


def _last(stderr) -> str:
    return mc._one_line(stderr[-1]) if stderr else "no stderr"  # pylint: disable=protected-access


def read_init(exe: str, cwd: str, timeout: float = TIMEOUT) -> Dict[str, Any]:
    """Run `exe` in `cwd` until its init event, then kill its process group; raise on failure."""
    deadline = time.monotonic() + timeout
    try:
        session = mc._Stdio({"command": exe, "args": list(ARGV)},  # pylint: disable=protected-access
                            deadline, cwd)
    except mc.McpClientError as exc:
        raise HostToolsError(str(exc)) from exc
    try:
        session.proc.stdin.close()  # a prompt is on argv; an open stdin only delays the start
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HostToolsError(f"timed out after {timeout:g}s waiting for the init event")
            try:
                line = session.stdout.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                # A child it spawned can hold stdout open after claude itself has exited.
                line = None if session.proc.poll() is not None else b""
            if line is None:
                time.sleep(0.05)  # let the stderr pump catch the last line
                raise HostToolsError(f"claude exited ({session.proc.poll()}) before its init "
                                     f"event: {_last(session.stderr)}")
            if line is mc._TOO_LARGE:  # pylint: disable=protected-access
                raise HostToolsError(f"a line too large (over {mc.MAX_MESSAGE_BYTES} bytes)")
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (isinstance(event, dict) and event.get("type") == "system"
                    and event.get("subtype") == "init"):
                return event
    finally:
        session.close()


def fill(pending: List[Server], found: HostInit) -> Dict[str, str]:
    """Fill each pending server the host reports connected; return `name: note` for every one.

    A connected server's list is the whole truth (`tools_known` True, so removal applies). Any
    other status leaves the server's tools as they were; its status is noted, and becomes its
    `host_status` when the listing had none.
    """
    notes: Dict[str, str] = {}
    for server in pending:
        name = server.get("name", "")
        status = found.statuses.get(name)
        if name in found.ambiguous:
            notes[name] = "claude init: ambiguous tool names, not filled"
        elif status is None:
            notes[name] = "not in claude init"
        elif status == CONNECTED:
            names = found.tools.get(name, [])
            server["tools"] = [{"name": tool, "description": ""} for tool in names]
            server["tools_known"] = True
            server.pop("host_status", None)
            server["discovered_via"] = VIA
            notes[name] = f"enumerated {len(names)} tool(s) via claude init"
        else:
            notes[name] = f"claude init reports {mc._one_line(status, 40)}"  # pylint: disable=protected-access
            if not server.get("host_status") and status in STATUS_PHRASES:
                server["host_status"] = STATUS_PHRASES[status]
    return notes
