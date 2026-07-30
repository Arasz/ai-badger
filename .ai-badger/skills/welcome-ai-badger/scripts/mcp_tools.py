"""MCP servers, one of the scaffold's collaborators.

Collects the servers the mcp catalog declares — `stack-mcp.json` and nothing else since
ADR-0014 step 8 — and writes them into the two project config files ai-badger owns:
`.mcp.json` and `.github/mcp.json`, the Copilot CLI's repo-committed config (#189). Every
user-global destination is proposed and never written (ADR-0014 decision 6) —
`~/.claude/settings.json` here, `~/.hermes/config.yaml` in the Hermes adjustment. A server
named by `config.mcp.decline` is not declared at all, and is removed from either file if an
earlier run wrote it (#186).
"""
from __future__ import annotations

import json as _json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import config_guard as cg
from scaffold_context import ScaffoldContext

# Directories user-level package managers install executables into that a non-login
# process does not have on PATH.  (probe directory, ``${HOME}``-relative prefix emitted
# into the config).  See docs/changelog/0.28.0-mcp-user-tool-paths.md.
USER_TOOL_DIRS = (
    (Path.home() / ".dotnet" / "tools", "${HOME}/.dotnet/tools"),
    (Path.home() / ".local" / "bin", "${HOME}/.local/bin"),
)

# The keys the renderer below emits into an MCP entry, and the authorship test for a file
# ai-badger is about to retire: anything else in it came from a hand (:func:`only_generated_entries`).
GENERATED_ENTRY_KEYS = frozenset({"command", "args", "cwd", "env", "tools"})

# Written until 0.51.0 and read by no Copilot surface (#189); retired on the next scaffold.
LEGACY_COPILOT_MCP_CONFIG = (".github", "copilot", "mcp-config.json")

# The two per-stack declaration files ADR-0014 replaced with `stack-mcp.json`. No reader
# consults them any more, so a stack that still ships one is named in a note: an overlay
# whose servers silently stopped being declared is the failure this list exists to prevent.
RETIRED_DECLARATION_FILES = ("mcp-servers.json", "external-tools.json")


def only_generated_entries(data: Dict[str, Any]) -> bool:
    """Whether *data* is exactly the shape this module's writer produces, and nothing more.

    The test behind retiring a generated config file: a top level of `mcpServers` alone, and
    entries carrying only :data:`GENERATED_ENTRY_KEYS`. A `type`, `url` or `inputs` key is
    valid Copilot configuration that ai-badger has never written, so the file is someone's own.

    Kept for the one migration that shipped before the record existed (#189). A new retirement
    should read the manifest's `generatedConfig` instead: from 0.52.0 every destination write is
    recorded there, so authorship is proven rather than inferred from key shape (#194).
    """
    if set(data) - {"mcpServers"}:
        return False
    section = data.get("mcpServers", {})
    if not isinstance(section, dict):
        return False
    return all(isinstance(entry, dict) and not set(entry) - GENERATED_ENTRY_KEYS
               for entry in section.values())


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
    all_tools: bool  # carry the per-server ``tools`` allowlist — Copilot's schema alone has one
    consequence: str  # what a refusal to write costs, for the note


# ``.mcp.json`` alone expands ``${VAR}`` (documented by Claude Code) and alone pins ``cwd``;
# it also keeps a command whole unless an argument looks like a package name.  Every other
# destination splits on whitespace and writes the command bare.  The asymmetry is deliberate:
# docs/changelog/0.28.0-mcp-user-tool-paths.md.
MCP_JSON = McpDestination(
    label=".mcp.json", owner="claude", requires_owner=False, pin_cwd=True,
    split_command=split_package_args, expand_home=True, all_tools=False,
    consequence=".mcp.json not updated",
)
# The Copilot CLI's repo-committed config, and the only schema here with a per-server ``tools``
# array: ``["*"]`` is every tool, and pruning happens at registration (#189).
COPILOT_MCP_JSON = McpDestination(
    label=".github/mcp.json", owner="copilot", requires_owner=True, pin_cwd=False,
    split_command=split_on_whitespace, expand_home=False, all_tools=True,
    consequence="copilot MCP config not updated",
)
CLAUDE_USER_SETTINGS = McpDestination(
    label="~/.claude/settings.json", owner="claude", requires_owner=True, pin_cwd=False,
    split_command=split_on_whitespace, expand_home=False, all_tools=False,
    consequence="claude user MCP servers not proposed",
)


class McpTools:
    """Collects, merges and writes MCP server declarations into each agent's config file."""

    def __init__(self, ctx: ScaffoldContext):
        self.ctx = ctx

    # -- the mcp catalog ---------------------------------------------------------------

    def collect_catalog_mcp_servers(self) -> List[Dict[str, Any]]:
        """Read stack-mcp.json from features/common/ and each active stack.

        Common first, then stacks in config order, last writer wins on name (a later stack
        overrides an earlier one).
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

    def note_retired_declaration_files(self) -> None:
        """Name a stack still shipping a :data:`RETIRED_DECLARATION_FILES` file, once per run.

        Presence is the whole test: the file is never parsed, so a stale overlay hears that
        its servers stopped being declared instead of discovering it from an empty `.mcp.json`.
        """
        if self.ctx.mcp_retired_files_noted:
            return
        self.ctx.mcp_retired_files_noted = True
        for stack in self.ctx.stacks:
            for filename in RETIRED_DECLARATION_FILES:
                if not (self.ctx.root / "features" / stack / filename).exists():
                    continue
                self.ctx.notes.append(
                    f"features/{stack}/{filename} is no longer read (ADR-0014 step 8) — move "
                    f"the servers it declared into features/{stack}/stack-mcp.json, where "
                    f"'declare: true' is what writes a launch config now"
                )

    def declined_servers(self) -> List[str]:
        """Server names ``config.mcp.decline`` refuses, in order, blanks dropped (#186)."""
        mcp = self.ctx.config.get("mcp") or {}
        return [name for name in (mcp.get("decline") or []) if name]

    def declared_servers(self) -> Dict[str, Dict[str, Any]]:
        """Every server whose launch config ai-badger writes, keyed by name.

        One reader: ``stack-mcp.json``'s ``declare: true`` (ADR-0014 step 8 removed the two
        legacy ones; :meth:`note_retired_declaration_files` reports what they left behind).

        A name in ``config.mcp.decline`` is dropped: declining a server ai-badger declared in
        the same run is a contradiction the generated files should not carry (#186).
        """
        self.note_retired_declaration_files()
        declared = {srv["name"]: dict(srv) for srv in self.collect_catalog_mcp_servers()
                    if srv.get("declare")}
        for name in self.declined_servers():
            declared.pop(name, None)
        return declared

    def declarations_for_agent(self, agent: str) -> Dict[str, Dict[str, Any]]:
        """Declared servers resolved for *agent*'s own ``agentOverrides``, keyed by name.

        What an adjustment is handed: it is loaded by path and cannot resolve
        ``stack-mcp.json`` itself. Scope does not filter — the two hosts that only ever
        receive a *proposal* have no project route for scope to select between.
        """
        return {name: self._resolve_server_for_agent(srv, agent)
                for name, srv in self.declared_servers().items()}

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
        self, dest: McpDestination, servers: Dict[str, Dict[str, Any]],
        declined: Sequence[str] = (),
    ) -> bool:
        """Whether *dest* is touched at all: it needs something to say, and may need its owner.

        A run with nothing left to declare still has something to say when a server was
        declined — the entry an earlier run wrote has to come back out (#186).
        """
        if not servers and not declined:
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
        if dest.all_tools:
            entry["tools"] = ["*"]
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
        declined: Sequence[str] = (),
    ) -> bool:
        """Merge rendered *entries* into the ``mcpServers`` object of the JSON file at *path*.

        *declined* names come back out of the section, so a decline reaches a file an earlier
        run already wrote.  Returns False without writing when the existing file is not a
        readable mapping, or when there is neither an entry to add nor a file to clean.
        """
        if not entries and not path.exists():
            return False
        existing, note = cg.read_json_mapping(path)
        section = cg.mapping_section(existing, "mcpServers") if existing is not None else None
        if section is None:
            note = note or cg.refusal(path, "mcpServers is not a mapping")
            self.ctx.notes.append(f"{note} ({dest.consequence})")
            return False
        if dest.pin_cwd:
            self._carry_live_cwd(section, entries)
        section.update(entries)
        self._drop_declined(section, declined, dest)
        cg.write_json_with_backup(path, existing)
        self.ctx.record_generated_config(path, dest.label)
        return True

    def _drop_declined(
        self, section: Dict[str, Any], declined: Sequence[str], dest: McpDestination
    ) -> None:
        """Remove every declined server from *section*, reporting what left (#186)."""
        removed = [name for name in declined if name in section]
        for name in removed:
            section.pop(name)
        if removed:
            self.ctx.notes.append(
                f"{dest.label}: removed declined MCP server(s) {', '.join(removed)} — "
                f"config.mcp.decline names them")

    def propose_claude_mcp_user(
        self, user_servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Print the ``~/.claude/settings.json`` snippet for scope:user servers; never write it.

        ADR-0014 decision 6: ai-badger proposes user-global configuration and writes only the
        project-scoped files it owns.  Gated on ``"claude"`` in ``config.agents``.
        """
        if not self._destination_applies(CLAUDE_USER_SETTINGS, user_servers):
            return

        entries = self._render_entries(user_servers, CLAUDE_USER_SETTINGS)
        self.ctx.notes.append(
            f"{len(entries)} MCP server(s) are declared scope:user — ai-badger never writes "
            f"user-global agent configuration (ADR-0014 decision 6). To register them, merge "
            f"this into ~/.claude/settings.json yourself: "
            f"{_json.dumps({'mcpServers': entries}, ensure_ascii=False, sort_keys=True)}"
        )

    def generate_copilot_mcp_json(
        self, servers: Dict[str, Dict[str, Any]]
    ) -> None:
        """Generate ``.github/mcp.json`` — the config the Copilot CLI actually reads (#189).

        Merge-only, plus the per-server ``tools`` allowlist.  Gated on ``"copilot"`` in
        ``config.agents``; the dead path it replaces is retired either way.
        """
        self._retire_copilot_mcp_config()
        declined = self.declined_servers()
        wanted = {name: srv for name, srv in servers.items() if name not in declined}
        if not self._destination_applies(COPILOT_MCP_JSON, wanted, declined):
            return

        self._merge_mcp_servers_json(
            self.ctx.target / ".github" / "mcp.json",
            self._render_entries(wanted, COPILOT_MCP_JSON),
            COPILOT_MCP_JSON,
            declined,
        )

    def _retire_copilot_mcp_config(self) -> None:
        """Retire ``.github/copilot/mcp-config.json`` — no Copilot surface reads it (#189).

        Removed with a backup when it is the shape ai-badger's own writer produced; anything
        else is someone's own file and is reported, never deleted.
        """
        path = self.ctx.target.joinpath(*LEGACY_COPILOT_MCP_CONFIG)
        if not path.exists():
            return
        data, refusal = cg.read_json_mapping(path)
        if data is None or not only_generated_entries(data):
            self.ctx.notes.append(
                f"{path} is read by no Copilot surface (issue #189), and was not written by "
                f"ai-badger ({refusal or 'it carries keys ai-badger never writes'}) — left in "
                f"place; move anything you need into .github/mcp.json and delete it yourself")
            return
        backup = cg.remove_with_backup(path)
        self.ctx.notes.append(
            f"removed {path} — no Copilot surface reads it (issue #189); the servers it "
            f"declared are in .github/mcp.json now, and a copy is at {backup.name}")

    # -- orchestrate ----------------------------------------------------------------

    def generate_mcp_json(self) -> None:
        """Generate .mcp.json for every declared MCP server (:meth:`declared_servers`).

        Commands stay portable — no absolute paths; a bare executable found in a user tool
        directory is emitted ``${HOME}``-relative.  Only project-scoped servers are written.
        """
        project_servers, _ = self.split_servers_by_scope(self.declared_servers())
        declined = self.declined_servers()

        if not self._destination_applies(MCP_JSON, project_servers, declined):
            return

        mcp_servers = self._render_entries(project_servers, MCP_JSON)
        written = self._merge_mcp_servers_json(
            self.ctx.target / ".mcp.json", mcp_servers, MCP_JSON, declined
        )
        if written:
            self.ctx.notes.append(
                f"generated .mcp.json with {len(mcp_servers)} MCP server(s)"
            )
