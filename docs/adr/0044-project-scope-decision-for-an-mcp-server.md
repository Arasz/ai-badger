# ADR-0044 — A project's own scope decision for an MCP server

**Date:** 2026-10-20
**Status:** Accepted
**Extends:** ADR-0014 (MCP support is configuration, not retrieval) — decision 6 stands
unchanged: ai-badger proposes user-global configuration and never writes it. This ADR adds
the project's say in *which* scope a declared server belongs to.
**Supersedes:** nothing. The catalog's per-server `scope` field (ADR-0014) remains the
framework's default.

## Context

ADR-0014 gave every declared MCP server a scope. `project` meant ai-badger writes the
launch config into the project files it owns; `user` meant the server belongs in a
user-global config, which ai-badger proposes and never writes. The scope lived in one
place: the framework's own catalog, `features/<stack>/stack-mcp.json`. That is the
framework's opinion about a server, and a project had no way to disagree with it.

The disagreement became concrete with `ai-raccoon`. It is a memory server, and the way it
is used is per machine, not per repository: one registration serves every repository the
operator works in. The catalog declared it project-scoped, so every scaffold wrote an
`ai-raccoon` entry into the project's `.mcp.json`. An operator who had already registered
the server at user scope (`claude mcp add --scope user`) then had two registrations of one
server, and the two hosts disagreed about which one a session used. The workaround was
manual and repeated: `claude mcp remove ai-raccoon` in every repository, after every
refresh.

The framework could not fix this from the operator's side. `config.mcp.decline` looked like
the knob, but a decline is a refusal: on Claude it also writes a `permissions.deny` rule
for the server, which would block the operator's own user-scoped registration as well. The
project needed a third thing — *this server is mine to register, not yours to write* — and
the framework had no word for it.

Two shapes were possible for the project's word. A one-way list (`userScoped: ["ai-raccoon"]`)
says "put this server at user scope" and nothing else; with the framework's default flipped
to `user` for `ai-raccoon`, such a list leaves no way back for a project that wants the
launch config in its own files. A map of name to scope says the same thing and keeps the
other direction open, at the same cost to the reader.

## Decision

1. **`config.mcp.scope` is a map of server name to `project` or `user`.** It is the
   project's own decision about a named server, and it overrides the catalog's `scope` in
   either direction. An absent block means the catalog decides, which is what every
   project that says nothing gets.

2. **`user` means the server is in no project file.** ai-badger writes it into no
   `.mcp.json`, no `.github/mcp.json` and no `.pi/mcp.json`, and it removes an entry an
   earlier run wrote into one of them — by name, whether that entry was ai-badger's
   template or the operator's own hand-written one. The removal is reported in a note. The
   reason is the collision this scope exists to end: two registrations of one server, in
   two scopes, with no rule about which one a session uses.

3. **`config.mcp.decline` wins over `config.mcp.scope`.** A declined server is refused
   outright: it is in neither scope, it is not proposed, and it is not registered anywhere.
   The decline route is the stronger statement about a server's tools.

4. **A name in `config.mcp.scope` that matches no declared server is reported.** A typo
   must not read as a server that is simply not there. The report names the unmatched
   names and says their scope is unchanged.

5. **`ai-raccoon` ships user-scoped by default.** The catalog declares it `scope: user`,
   so no project writes it into a project file any more. The operator registers it once, in
   a user-global config, and every repository the operator works in uses that one
   registration. A project that wants the launch config in its own files says so:
   `config.mcp.scope` names it `project`.

6. **User scope is a proposal, not a write.** The registration snippet is proposed for the
   operator's user-global config, exactly as ADR-0014 decision 6 requires. ai-badger does
   not read, write or verify the operator's user-global configuration, and it does not
   claim the operator has registered the server.

7. **The tool index still describes the server.** A user-scoped server keeps its catalog
   entry, its `server.md` prose and its tool catalog: the agent still knows the tools
   exist. Scope decides where the launch config lives, not whether the server is known.

## Consequences

- The operator's step is explicit and one-time: register the server at user scope once
  (`claude mcp add --scope user ai-raccoon -- ai-raccoon`, or the equivalent snippet
  ai-badger proposes). A project that does not does not get the server — that is what
  user scope means, and it is visible in the run's notes.
- The framework's default changed for one server, so a refresh of an existing project
  removes an `ai-raccoon` entry it wrote earlier. That removal is reported, and it is the
  behaviour that ends the per-repository `claude mcp remove` ritual.
- A project that wants the old behaviour has one line of config, and the direction of that
  override is the reason the knob is a map rather than a list.
- Scope is now decided in two places, so the precedence is stated rather than implied:
  `config.mcp.decline` first, then `config.mcp.scope`, then the catalog's `scope`.
- The host-specific surfaces keep their own rules. Hermes reads MCP configuration only
  from `~/.hermes/config.yaml` and has no project route, so a user-scoped server is
  proposed there like every other; the Copilot CLI's repo-committed file and the Codex
  project file carry project-scoped servers only.

## Alternatives considered

- **`config.mcp.decline` for `ai-raccoon`.** Rejected: on Claude it also writes a
  `permissions.deny` rule for the server, and that rule beats the operator's own
  user-scoped registration — the user's own registration would stop working.
- **A one-way `userScoped` list.** Rejected: with the framework's default flipped, it
  leaves no way for a project to pull a server back to project scope.
- **Skipping any server the operator already registered at user scope.** Rejected for now:
  it requires reading the operator's user-global configuration, which ADR-0014 decision 6
  keeps out of ai-badger's way, and a wrong reading of that file silently drops a server
  the project asked for. The cost of not doing it is a proposal the operator can ignore.
- **Writing the user-global registration itself.** Rejected: ADR-0014 decision 6 — ai-badger
  proposes user-global configuration, it never writes it.
