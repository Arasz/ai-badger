"""MCP server and external tool management for the Scaffolder.

Collects stack-declared MCP servers and external tools, merges them with
user config, and scaffolds into agent-specific config files (.mcp.json,
~/.hermes/config.yaml, ~/.claude/settings.json, .github/copilot/mcp-config.json).
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import config_guard as cg


class McpToolsMixin:
    """Mixin providing MCP server and external tool scaffolding methods."""

    # -- MCP stack declarations -------------------------------------------------------

    def _collect_stack_mcp_servers(self) -> List[Dict[str, Any]]:
        """Read mcp-servers.json from features/common/ and each active stack.

        Common first, then stacks in config order.  The last writer wins on name
        conflict (later stack overrides earlier).
        """
        result = []  # type: List[Dict[str, Any]]
        for stack in self.stacks:
            mcp_path = self.root / "features" / stack / "mcp-servers.json"
            if not mcp_path.exists():
                continue
            try:
                data = _json.loads(mcp_path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                self.notes.append(
                    f"features/{stack}/mcp-servers.json is unreadable "
                    f"({type(exc).__name__}) — its entries were not scaffolded"
                )
                continue
            for srv in data.get("servers", []):
                # Last writer wins: remove any earlier entry with the same name
                result = [s for s in result if s.get("name") != srv.get("name")]
                result.append(srv)
        return result

    def _collect_external_tools(self) -> List[Dict[str, Any]]:
        """Read external-tools.json from features/common/ and each active stack.

        Common first, then stacks in config order.  The last writer wins on name
        conflict (later stack overrides earlier).  Mirrors _collect_stack_mcp_servers.
        """
        result = []  # type: List[Dict[str, Any]]
        for stack in self.stacks:
            tools_path = self.root / "features" / stack / "external-tools.json"
            if not tools_path.exists():
                continue
            try:
                data = _json.loads(tools_path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                self.notes.append(
                    f"features/{stack}/external-tools.json is unreadable "
                    f"({type(exc).__name__}) — its entries were not scaffolded"
                )
                continue
            for tool in data.get("tools", []):
                result = [t for t in result if t.get("name") != tool.get("name")]
                result.append(tool)
        return result

    @staticmethod
    def _merge_external_tools(
        catalog_tools: List[Dict[str, Any]],
        user_tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge catalog-declared tools with config.externalTools.

        Catalog tools are added first; user tools override on name conflict.
        Returns a list of tool dicts.
        """
        by_name = {}  # type: Dict[str, Dict[str, Any]]
        for tool in catalog_tools:
            by_name[tool["name"]] = dict(tool)
        for tool in user_tools:
            by_name[tool["name"]] = dict(tool)
        return list(by_name.values())

    def _merge_mcp_servers(
        self,
        stack_servers: List[Dict[str, Any]],
        user_tools: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Merge stack-declared servers with externalTools.

        Stack servers are added first; externalTools with
        ``generate_mcp_json=True`` override on name conflict (user wins).
        Returns a dict keyed by server name.
        """
        merged = {}  # type: Dict[str, Dict[str, Any]]
        for srv in stack_servers:
            merged[srv["name"]] = dict(srv)
        for tool in user_tools:
            if not tool.get("generate_mcp_json"):
                continue
            name = tool["name"]
            merged[name] = dict(tool)
        return merged

    def _split_servers_by_scope(
        self, servers: Dict[str, Dict[str, Any]]
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Split merged servers into (project_servers, user_servers).

        Default scope is ``"project"``.
        """
        project = {}  # type: Dict[str, Dict[str, Any]]
        user = {}  # type: Dict[str, Dict[str, Any]]
        for name, srv in servers.items():
            if srv.get("scope", "project") == "user":
                user[name] = srv
            else:
                project[name] = srv
        return project, user

    def _resolve_server_for_agent(
        self, server: Dict[str, Any], agent_name: str
    ) -> Dict[str, Any]:
        """Apply agentOverrides for *agent_name* and return resolved dict."""
        overrides = server.get("agentOverrides", {})
        agent_ovr = overrides.get(agent_name)
        if agent_ovr:
            resolved = dict(server)
            resolved.update(agent_ovr)
            return resolved
        return dict(server)

    @staticmethod
    def _parse_command(command: str) -> Tuple[str, List[str]]:
        """Split *command* string into ``(executable, args_list)``."""
        parts = command.split()
        return parts[0], parts[1:]

    def _server_entry(self, srv: Dict[str, Any]) -> Dict[str, Any]:
        """Render one server declaration as an agent config entry."""
        entry = {}  # type: Dict[str, Any]
        if "args" in srv:
            entry["command"] = srv["command"]
            entry["args"] = srv["args"]
        else:
            exe, args = self._parse_command(srv.get("command", ""))
            entry["command"] = exe
            if args:
                entry["args"] = args
        if "env" in srv:
            entry["env"] = srv["env"]
        return entry

    def _merge_mcp_servers_json(
        self,
        path: Path,
        entries: Dict[str, Dict[str, Any]],
        consequence: str,
    ) -> bool:
        """Merge rendered *entries* into the ``mcpServers`` object of the JSON file at *path*.

        Returns False without writing when the existing file is not a readable mapping.
        """
        existing, note = cg.read_json_mapping(path)
        section = cg.mapping_section(existing, "mcpServers") if existing is not None else None
        if section is None:
            note = note or cg.refusal(path, "mcpServers is not a mapping")
            self.notes.append(f"{note} ({consequence})")
            return False
        section.update(entries)
        cg.write_json_with_backup(path, existing)
        return True

    def _scaffold_hermes_mcp_user(
        self, user_servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Write scope:user servers into ``~/.hermes/config.yaml`` mcp.servers.

        Merge-only (never overwrites existing entries).  Gated on ``"hermes"``
        being present in ``config.agents``.
        """
        if "hermes" not in self.config.get("agents", []):
            return
        if not user_servers:
            return
        try:
            import yaml  # type: ignore
        except ImportError:
            self.notes.append("yaml not available — skipping hermes user MCP config")
            return

        config_path = Path.home() / ".hermes" / "config.yaml"
        existing, note = cg.read_mergeable_mapping(
            config_path, yaml.safe_load, (yaml.YAMLError, ValueError)
        )
        section = cg.mapping_section(existing, "mcp", "servers") if existing is not None else None
        if section is None:
            note = note or cg.refusal(config_path, "mcp.servers is not a mapping")
            self.notes.append(f"{note} (hermes user MCP servers not registered)")
            return

        for name, srv in user_servers.items():
            section[name] = self._server_entry(srv)

        cg.write_with_backup(
            config_path, yaml.safe_dump(existing, default_flow_style=False)
        )

    def _scaffold_claude_mcp_user(
        self, user_servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Write scope:user servers into ``~/.claude/settings.json`` mcpServers.

        JSON merge-only.  Gated on ``"claude"`` in ``config.agents``.
        """
        if "claude" not in self.config.get("agents", []):
            return
        if not user_servers:
            return

        self._merge_mcp_servers_json(
            Path.home() / ".claude" / "settings.json",
            {name: self._server_entry(srv) for name, srv in user_servers.items()},
            "claude user MCP servers not registered",
        )

    def _generate_copilot_mcp_config(
        self, servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Generate ``.github/copilot/mcp-config.json``.

        Merge-only.  Gated on ``"copilot"`` in ``config.agents``.
        """
        if "copilot" not in self.config.get("agents", []):
            return
        if not servers:
            return

        self._merge_mcp_servers_json(
            self.target / ".github" / "copilot" / "mcp-config.json",
            {name: self._server_entry(srv) for name, srv in servers.items()},
            "copilot MCP config not updated",
        )

    # -- orchestrate ----------------------------------------------------------------

    def _generate_mcp_json(self) -> None:
        """Generate .mcp.json for merged stack + external tool MCP servers.

        Uses portable commands (uvx for Python packages) — no hardcoded paths.
        Only project-scoped servers are written to .mcp.json.
        """
        # Lazy-init: merge catalog + config external tools if not yet done
        if not self._external_tools_merged:
            self._merged_external_tools = self._merge_external_tools(
                self._collect_external_tools(),
                self.config.get("externalTools", []),
            )
            self._external_tools_merged = True

        # Collect from stacks and external tools
        stack_servers = self._collect_stack_mcp_servers()
        merged = self._merge_mcp_servers(stack_servers, self._merged_external_tools)
        project_servers, _ = self._split_servers_by_scope(merged)

        agents = self.config.get("agents", [])
        mcp_servers = {}  # type: Dict[str, Any]
        for name, srv in project_servers.items():
            # Apply agent override for the first configured agent
            resolved = srv
            for agent in agents:
                resolved = self._resolve_server_for_agent(srv, agent)
                break

            # Parse command into executable + args
            command = resolved.get("command", "")
            if "args" in resolved:
                # Agent override provides explicit args
                entry = {
                    "command": command,
                    "args": resolved["args"],
                    "cwd": str(self.target),
                }
            else:
                parts = command.split()
                # Split into executable + args only when arguments contain
                # package-name characters (hyphens, @, /) — keeps simple
                # commands like "echo v2" intact while parsing
                # "uvx mcp-server-pyright" correctly.
                has_pkg_args = (
                    len(parts) >= 2
                    and any("-" in p or "@" in p or "/" in p for p in parts[1:])
                )
                if has_pkg_args:
                    entry = {
                        "command": parts[0],
                        "args": parts[1:],
                        "cwd": str(self.target),
                    }
                else:
                    entry = {"command": command, "cwd": str(self.target)}
            if "env" in resolved:
                entry["env"] = resolved["env"]
            mcp_servers[name] = entry

        if not mcp_servers:
            return
        written = self._merge_mcp_servers_json(
            self.target / ".mcp.json", mcp_servers, ".mcp.json not updated"
        )
        if written:
            self.notes.append(
                f"generated .mcp.json with {len(mcp_servers)} external tool(s)"
            )
