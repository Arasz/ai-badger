"""MCP servers and external tools, one of the scaffold's collaborators.

Collects stack-declared MCP servers and external tools, merges them with
user config, and scaffolds into agent-specific config files (.mcp.json,
~/.hermes/config.yaml, ~/.claude/settings.json, .github/copilot/mcp-config.json).
"""
from __future__ import annotations

import json as _json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import config_guard as cg
from scaffold_context import ScaffoldContext

# Directories user-level package managers install executables into that a non-login
# process does not have on PATH.  (probe directory, ``${HOME}``-relative prefix emitted
# into the config).  See docs/changelog/0.28.0-mcp-user-tool-paths.md.
USER_TOOL_DIRS = (
    (Path.home() / ".dotnet" / "tools", "${HOME}/.dotnet/tools"),
    (Path.home() / ".local" / "bin", "${HOME}/.local/bin"),
)


def split_on_whitespace(command: str) -> Tuple[str, List[str]]:
    """Split *command* into ``(executable, args)``: every word after the first is an argument."""
    parts = command.split()
    return parts[0], parts[1:]


def split_package_args(command: str) -> Tuple[str, List[str]]:
    """Split *command* only when an argument looks like a package name (``-``, ``@``, ``/``).

    Keeps ``echo v2`` whole while parsing ``uvx mcp-server-pyright`` into executable + args.
    """
    parts = command.split()
    if len(parts) >= 2 and any("-" in p or "@" in p or "/" in p for p in parts[1:]):
        return parts[0], parts[1:]
    return command, []


class McpDestination(NamedTuple):
    """One generated MCP config file — these columns are the only differences between them."""

    label: str
    owner: str  # the one agent that reads the file; its agentOverrides are the ones applied (F-22)
    requires_owner: bool  # written only for that agent, vs written whether or not it is configured
    pin_cwd: bool
    split_command: Callable[[str], Tuple[str, List[str]]]
    expand_home: bool  # rewrite a user-tool-dir command to ``${HOME}`` form
    consequence: str  # what a refusal to write costs, for the note


# ``.mcp.json`` alone expands ``${VAR}`` (documented by Claude Code) and alone pins ``cwd``;
# it also keeps a command whole unless an argument looks like a package name.  Every other
# destination splits on whitespace and writes the command bare.  The asymmetry is deliberate:
# docs/changelog/0.28.0-mcp-user-tool-paths.md.
MCP_JSON = McpDestination(
    label=".mcp.json", owner="claude", requires_owner=False, pin_cwd=True,
    split_command=split_package_args, expand_home=True,
    consequence=".mcp.json not updated",
)
COPILOT_MCP_CONFIG = McpDestination(
    label=".github/copilot/mcp-config.json", owner="copilot", requires_owner=True, pin_cwd=False,
    split_command=split_on_whitespace, expand_home=False,
    consequence="copilot MCP config not updated",
)
CLAUDE_USER_SETTINGS = McpDestination(
    label="~/.claude/settings.json", owner="claude", requires_owner=True, pin_cwd=False,
    split_command=split_on_whitespace, expand_home=False,
    consequence="claude user MCP servers not registered",
)
HERMES_USER_CONFIG = McpDestination(
    label="~/.hermes/config.yaml", owner="hermes", requires_owner=True, pin_cwd=False,
    split_command=split_on_whitespace, expand_home=False,
    consequence="hermes user MCP servers not registered",
)


class McpTools:
    """Collects, merges and writes MCP server declarations into each agent's config file."""

    def __init__(self, ctx: ScaffoldContext):
        self.ctx = ctx

    # -- MCP stack declarations -------------------------------------------------------

    def collect_stack_mcp_servers(self) -> List[Dict[str, Any]]:
        """Read mcp-servers.json from features/common/ and each active stack.

        Common first, then stacks in config order.  The last writer wins on name
        conflict (later stack overrides earlier).
        """
        result = []  # type: List[Dict[str, Any]]
        for stack in self.ctx.stacks:
            mcp_path = self.ctx.root / "features" / stack / "mcp-servers.json"
            if not mcp_path.exists():
                continue
            try:
                data = _json.loads(mcp_path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                self.ctx.notes.append(
                    f"features/{stack}/mcp-servers.json is unreadable "
                    f"({type(exc).__name__}) — its entries were not scaffolded"
                )
                continue
            for srv in data.get("servers", []):
                # Last writer wins: remove any earlier entry with the same name
                result = [s for s in result if s.get("name") != srv.get("name")]
                result.append(srv)
        return result

    # -- the mcp catalog ---------------------------------------------------------------

    def collect_catalog_mcp_servers(self) -> List[Dict[str, Any]]:
        """Read stack-mcp.json from features/common/ and each active stack.

        Same merge as :meth:`collect_stack_mcp_servers` — common first, then stacks in config
        order, last writer wins on name.
        """
        result = []  # type: List[Dict[str, Any]]
        for stack in self.ctx.stacks:
            path = self.ctx.root / "features" / stack / "stack-mcp.json"
            if not path.exists():
                continue
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                self.ctx.notes.append(
                    f"features/{stack}/stack-mcp.json is unreadable "
                    f"({type(exc).__name__}) — its entries were not scaffolded"
                )
                continue
            for srv in data.get("servers", []):
                result = [s for s in result if s.get("name") != srv.get("name")]
                result.append(srv)
        return result

    def _server_instructions(self, name: str) -> str:
        """`server.md` for a catalog server, found through the index, or '' when there is none."""
        import badger_lib as bl

        for stack in self.ctx.stacks:
            for item in bl.feature_items(self.ctx.index, stack, "mcp"):
                if item.get("name") != name:
                    continue
                doc = self.ctx.root / item.get("path", "") / "server.md"
                if doc.is_file():
                    return doc.read_text(encoding="utf-8")
                return ""
        return ""

    def fill_mcp_described(self) -> None:
        """Fill ``ctx.mcp_described`` once: each declared server plus its ``server.md`` prose.

        A declaration naming no catalog directory is reported rather than silently dropped —
        the name is the join between the two files and a typo in it is invisible otherwise.
        """
        if self.ctx.mcp_described_filled:
            return
        described = []  # type: List[Dict[str, Any]]
        for srv in self.collect_catalog_mcp_servers():
            name = srv.get("name")
            instructions = self._server_instructions(name) if name else ""
            if not instructions:
                self.ctx.notes.append(
                    f"stack-mcp.json declares '{name}', which names no mcp catalog entry with a "
                    f"server.md — no instructions were injected for it"
                )
            entry = dict(srv)
            entry["instructions"] = instructions
            described.append(entry)
        self.ctx.mcp_described = described
        self.ctx.mcp_described_filled = True

    def fill_instruction_sources(self) -> None:
        """Fill both instruction caches the document slots read — catalog and legacy."""
        self.fill_merged_external_tools()
        self.fill_mcp_described()

    def collect_external_tools(self) -> List[Dict[str, Any]]:
        """Read external-tools.json from features/common/ and each active stack.

        Common first, then stacks in config order.  The last writer wins on name
        conflict (later stack overrides earlier).  Mirrors _collect_stack_mcp_servers.
        """
        result = []  # type: List[Dict[str, Any]]
        for stack in self.ctx.stacks:
            tools_path = self.ctx.root / "features" / stack / "external-tools.json"
            if not tools_path.exists():
                continue
            try:
                data = _json.loads(tools_path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                self.ctx.notes.append(
                    f"features/{stack}/external-tools.json is unreadable "
                    f"({type(exc).__name__}) — its entries were not scaffolded"
                )
                continue
            for tool in data.get("tools", []):
                result = [t for t in result if t.get("name") != tool.get("name")]
                result.append(tool)
        return result

    @staticmethod
    def merge_external_tools(
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

    def fill_merged_external_tools(self) -> None:
        """Fill ``ctx.merged_external_tools`` once, so template rendering can read it.

        The cache lives on the context rather than on either collaborator: whoever renders
        the externalTools instructions must not have to know who collected them.
        """
        if self.ctx.external_tools_merged:
            return
        self.ctx.merged_external_tools = self.merge_external_tools(
            self.collect_external_tools(),
            self.ctx.config.get("externalTools", []),
        )
        self.ctx.external_tools_merged = True

    def merge_mcp_servers(
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

    def split_servers_by_scope(
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

    def _destination_applies(
        self, dest: McpDestination, servers: Dict[str, Dict[str, Any]]
    ) -> bool:
        """Whether *dest* is written at all: it needs servers, and may need its owner configured."""
        if not servers:
            return False
        return not dest.requires_owner or dest.owner in self.ctx.config.get("agents", [])

    def _override_owner(
        self, dest: McpDestination, servers: Dict[str, Dict[str, Any]]
    ) -> Optional[str]:
        """Return *dest*'s owner if it is a configured agent, else None + a note if overrides drop.

        Each generated file has exactly one reading agent, so its overrides are that
        agent's — never whichever agent happens to come first in config.agents (F-22).
        """
        owner = dest.owner
        if owner in self.ctx.config.get("agents", []):
            return owner
        dropped = sorted(name for name, srv in servers.items() if srv.get("agentOverrides"))
        if dropped:
            self.ctx.notes.append(
                f"{dest.label} written without agent overrides ({', '.join(dropped)}) — "
                f"'{owner}' is not in config.agents and the file is read by {owner}"
            )
        return None

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

    def _render_entries(
        self, servers: Dict[str, Dict[str, Any]], dest: McpDestination
    ) -> Dict[str, Dict[str, Any]]:
        """Render *servers* as *dest*'s config entries, resolved for its owning agent."""
        owner = self._override_owner(dest, servers)
        entries = {
            name: self._render_entry(
                self._resolve_server_for_agent(srv, owner) if owner else dict(srv), dest)
            for name, srv in servers.items()
        }
        if dest.expand_home:
            self._home_relative_commands(entries)
        return entries

    def _render_entry(self, srv: Dict[str, Any], dest: McpDestination) -> Dict[str, Any]:
        """Render one resolved server declaration as one *dest* entry."""
        entry = {}  # type: Dict[str, Any]
        if "args" in srv:
            entry["command"] = srv.get("command", "")
            entry["args"] = srv["args"]
        else:
            exe, args = dest.split_command(srv.get("command", ""))
            entry["command"] = exe
            if args:
                entry["args"] = args
        if dest.pin_cwd:
            entry["cwd"] = str(self.ctx.target)
        if "env" in srv:
            entry["env"] = srv["env"]
        return entry

    def _home_relative_command(self, name: str, command: str) -> str:
        """Rewrite a bare executable that lives in a user tool dir to its ``${HOME}`` form.

        Leaves anything already pathed, already expandable, or resolvable elsewhere on PATH
        alone; notes a command that resolves nowhere.
        """
        if not command or " " in command or "/" in command or command.startswith("${"):
            return command
        for probe_dir, prefix in USER_TOOL_DIRS:
            candidate = Path(probe_dir) / command
            if candidate.is_file() and os.access(str(candidate), os.X_OK):
                return prefix + "/" + command
        if shutil.which(command) is None:
            self.ctx.notes.append(
                f"MCP server '{name}' command '{command}' was not found on PATH or in any "
                f"known user tool directory — that server will fail to start"
            )
        return command

    def _home_relative_commands(
        self, entries: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Apply :meth:`_home_relative_command` to each rendered entry's executable."""
        for name, entry in entries.items():
            entry["command"] = self._home_relative_command(name, entry.get("command", ""))
        return entries

    def _carry_live_cwd(
        self, section: Dict[str, Any], entries: Dict[str, Dict[str, Any]]
    ) -> None:
        """Keep a recorded ``cwd`` that still names a scaffolded project.

        ``.mcp.json`` is tracked, so re-scaffolding from a second checkout would otherwise
        restage every entry's ``cwd`` onto a directory the original checkout never used.
        """
        for name, entry in entries.items():
            recorded = section.get(name, {}).get("cwd")
            if not isinstance(recorded, str) or not recorded:
                continue
            if recorded != entry.get("cwd") and (Path(recorded) / ".ai-badger").is_dir():
                entry["cwd"] = recorded
                self.ctx.notes.append(
                    f"MCP server '{name}': kept the recorded cwd {recorded} rather than "
                    f"repointing it at {self.ctx.target}"
                )

    def _merge_mcp_servers_json(
        self,
        path: Path,
        entries: Dict[str, Dict[str, Any]],
        dest: McpDestination,
    ) -> bool:
        """Merge rendered *entries* into the ``mcpServers`` object of the JSON file at *path*.

        Returns False without writing when the existing file is not a readable mapping.
        """
        existing, note = cg.read_json_mapping(path)
        section = cg.mapping_section(existing, "mcpServers") if existing is not None else None
        if section is None:
            note = note or cg.refusal(path, "mcpServers is not a mapping")
            self.ctx.notes.append(f"{note} ({dest.consequence})")
            return False
        if dest.pin_cwd:
            self._carry_live_cwd(section, entries)
        section.update(entries)
        cg.write_json_with_backup(path, existing)
        return True

    def scaffold_hermes_mcp_user(
        self, user_servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Write scope:user servers into ``~/.hermes/config.yaml`` mcp.servers.

        Merge-only (never overwrites existing entries).  Gated on ``"hermes"``
        being present in ``config.agents``.
        """
        if not self._destination_applies(HERMES_USER_CONFIG, user_servers):
            return
        try:
            import yaml  # type: ignore
        except ImportError:
            self.ctx.notes.append("yaml not available — skipping hermes user MCP config")
            return

        config_path = Path.home() / ".hermes" / "config.yaml"
        existing, note = cg.read_mergeable_mapping(
            config_path, yaml.safe_load, (yaml.YAMLError, ValueError)
        )
        section = cg.mapping_section(existing, "mcp", "servers") if existing is not None else None
        if section is None:
            note = note or cg.refusal(config_path, "mcp.servers is not a mapping")
            self.ctx.notes.append(f"{note} ({HERMES_USER_CONFIG.consequence})")
            return

        section.update(self._render_entries(user_servers, HERMES_USER_CONFIG))

        cg.write_with_backup(
            config_path, yaml.safe_dump(existing, default_flow_style=False)
        )

    def scaffold_claude_mcp_user(
        self, user_servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Write scope:user servers into ``~/.claude/settings.json`` mcpServers.

        JSON merge-only.  Gated on ``"claude"`` in ``config.agents``.
        """
        if not self._destination_applies(CLAUDE_USER_SETTINGS, user_servers):
            return

        self._merge_mcp_servers_json(
            Path.home() / ".claude" / "settings.json",
            self._render_entries(user_servers, CLAUDE_USER_SETTINGS),
            CLAUDE_USER_SETTINGS,
        )

    def generate_copilot_mcp_config(
        self, servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Generate ``.github/copilot/mcp-config.json``.

        Merge-only.  Gated on ``"copilot"`` in ``config.agents``.
        """
        if not self._destination_applies(COPILOT_MCP_CONFIG, servers):
            return

        self._merge_mcp_servers_json(
            self.ctx.target / ".github" / "copilot" / "mcp-config.json",
            self._render_entries(servers, COPILOT_MCP_CONFIG),
            COPILOT_MCP_CONFIG,
        )

    # -- orchestrate ----------------------------------------------------------------

    def generate_mcp_json(self) -> None:
        """Generate .mcp.json for merged stack + external tool MCP servers.

        Commands stay portable — no absolute paths; a bare executable found in a user tool
        directory is emitted ``${HOME}``-relative.  Only project-scoped servers are written.
        """
        self.fill_merged_external_tools()

        # Collect from stacks and external tools
        stack_servers = self.collect_stack_mcp_servers()
        merged = self.merge_mcp_servers(stack_servers, self.ctx.merged_external_tools)
        project_servers, _ = self.split_servers_by_scope(merged)

        if not self._destination_applies(MCP_JSON, project_servers):
            return

        mcp_servers = self._render_entries(project_servers, MCP_JSON)
        written = self._merge_mcp_servers_json(
            self.ctx.target / ".mcp.json", mcp_servers, MCP_JSON
        )
        if written:
            self.ctx.notes.append(
                f"generated .mcp.json with {len(mcp_servers)} external tool(s)"
            )
