# ADR-0048 — Decisions live in ai-raccoon; semantica is removed

**Date:** 2026-11-11
**Status:** Accepted (2026-11-11, 0.218.0)
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code
**Supersedes:** ADR-0019
**Extends:** ADR-0047
**Research:** [`docs/work/2026-11-11-replace-semantica-with-raccoon-decisions-research.md`](../work/2026-11-11-replace-semantica-with-raccoon-decisions-research.md)

## Context

ADR-0019 shipped semantica as a second MCP server for decisions and causal graphs. Its graph lived
in process memory, so ADR-0019 added a PostToolUse hook that dumped `export_graph` to
`.semantica/<session>.json`, an ai-raccoon watch on that directory, and a once-per-session prompt
nudge to make agents record decisions at all. That is one server, one Python wrapper with a pip
dependency, one hook, one nudge with its own store table, and one skill, all to keep decisions
alive past the session.

ai-raccoon, already the project memory server, now has a native decision graph. Decisions are
recorded under a registered task, versioned, moved through a status machine (proposed, accepted,
rejected, superseded, deprecated), linked by typed edges, and stored durably. Reads are
`query_decisions`, `find_decision_precedents`, `get_decision`, `get_decision_graph`,
`preview_decisions` and `export_decisions`. The `ai-raccoon decisions` CLI is the twin of the
tools. Every write takes a `requestId`, and a resend with the same id replays the first result.

## Decision

1. ai-badger drops semantica: the MCP catalog entry, the `semantica-knowledge-graph` skill, the
   export autosave hook, the seed template, the prompt nudge and its `semantica_nudge` store
   family, the Hermes shared module, and the `semantica` entry in `engine/requirements.txt`.
2. Decision recording points at ai-raccoon. Guidance lives in the existing ai-raccoon catalog entry
   and the `ai-raccoon-memory` skill. The `decision-record` skill gains an optional step to also
   record the decision in ai-raccoon. The project's own format (ADR-0047) stays the primary record.
3. No nudge replaces the deleted one. The ai-raccoon section in every generated agent file already
   tells agents to record decisions.

## Alternatives

- **Keep both servers.** Two decision stores with overlapping tools; agents would have to pick one,
  and semantica still loses its graph at process exit.
- **A new decisions skill.** More surface for the same guidance; the owner chose to fold it into
  `ai-raccoon-memory` and `decision-record`.
- **Drop the `semantica_nudge` table and bump the schema.** The user database is shared by every
  project on the machine; older installs still write the table, so dropping it breaks them.

## Consequences

- One server fewer to install, check and keep in the doc budget. No per-session JSON dump: the
  decisions are durable where they are written.
- Through ai-raccoon 2.6.0 the decision tools commit on the server, but Claude Code rejects the
  reply because the output schema marks null fields as required. The guidance says: do not retry;
  verify with `ai-raccoon decisions query`; use the CLI. A retry must reuse the same `requestId`.
  ai-raccoon 2.6.1 (Arasz/ai-raccoon#932) makes the replies match the schema; the upgrade notes
  recommend it, and the fallback text stays bounded to 2.6.0 and earlier.
- The scaffold merges MCP servers, permission rules and hooks additively. A re-scaffold does not
  remove the semantica entries from `.claude/settings.json`, `.mcp.json`, `.github/mcp.json` or
  `.pi/mcp.json`, nor the export hook entry in `.claude/settings.json`, nor a Hermes operator's
  `~/.hermes/config.yaml` `mcp_servers` entry. This release removes them by hand here, and the
  upgrade notes tell consumers to do the same. A scaffold prune for catalog-retired servers and
  hooks is a follow-up issue, not built here.
- The `semantica_nudge` table stays in existing user databases, and `~/.ai-badger/semantica-nudge/`
  stays on disk. The user database is shared by every project on the machine, and older installs
  still write to the table. No code reads either one any more.
- Existing `.semantica/` exports are not migrated by ai-badger. Newer ai-raccoon releases can import
  Semantica export files.
- Revisit if ai-raccoon's decision graph is withdrawn, or if causal-chain reasoning that only
  semantica offered becomes a need.
