# ADR-0049 — A re-scaffold removes what ai-badger wrote for a retired MCP server or hook

**Date:** 2026-11-12
**Status:** Accepted (2026-11-12, 0.219.0)
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code
**Extends:** ADR-0048
**Research:** [`docs/work/2026-11-11-prune-retired-catalog-scaffold-entries-research.md`](../work/2026-11-11-prune-retired-catalog-scaffold-entries-research.md)

## Context

ADR-0048 removed semantica from the catalog. It also recorded a gap: a re-scaffold does not remove
the semantica entries that earlier runs wrote. This ADR closes that follow-up.

The scaffold merges into these files and only adds to them (research Q1, measured):

- `.mcp.json`, `.github/mcp.json` and `.pi/mcp.json`. The catalog entry wins on refresh, but no
  path removes a name that the catalog no longer has.
- `.claude/settings.json`: `enabledMcpjsonServers`, `permissions.allow` and the hook entries.

Codex is safe. Its markers bound the block that ai-badger owns, and the scaffold rebuilds that
block. A JSON object and a string array have no place for a marker.

No record says which entries ai-badger wrote. The `generatedConfig` record in the manifest is
bookkeeping, and it gives no ownership (#194). The existing drop paths for unavailable servers can
prove authorship, because they compare an entry with the rendered template. But they need a
declaration to render, and retiring a server deletes its declaration.

"Not declared in this run" is the wrong test for retirement. That set also holds servers that are
unavailable on this host, declined in `config.exclude`, or user-scoped. Their entries and
approvals are still in use.

Semantica shipped four launches:

| Commit | Launch |
|---|---|
| c5e424bb | `python3 -m semantica.mcp_server` |
| e2b95eac | `semantica mcp start` |
| 240ad606 | `semantica-mcp` |
| 769d94fb^ | `semantica-mcp` with env `SEMANTICA_DISABLE_PROGRESS=1` |

A consumer can hold any one of these four.

A harness probe found that Claude Code ignores both of these. Neither causes a warning (measured):

- a name in `enabledMcpjsonServers` that has no `.mcp.json` entry;
- an allow rule `mcp__<n>__*` for a server that nobody declares.

The real cost is the server entries, because each host launches them or reports a failure.

## Decision

Principle: **the prune never removes a permission rule; it removes only entries whose ownership can be proven.**

1. **Tombstones are catalog data.** A `features/<stack>/stack-mcp.json` file can have a top-level
   `retired` array. Its items have the same schema as `servers` items. A name can repeat, with one
   item for each launch that the server shipped. To retire a server, move every launch that it
   shipped from `servers` to `retired`. Semantica gets four items.
2. **The retired set comes from the whole catalog.** The scaffold reads `retired` from every
   `features/*/stack-mcp.json`, whatever `config.stacks` holds. It then subtracts every name that
   any catalog file still declares in `servers`. The current catalog never reads `retired`.
3. **The MCP files are pruned by shape.** In `.mcp.json`, `.github/mcp.json` and `.pi/mcp.json`,
   the scaffold removes a retired entry only when its launch fields (`_launch_of`) are equal to a
   rendered retired declaration. Those candidates include the `~` and `${HOME}` spellings. The
   scaffold renders the candidates without notes. It never matches by name alone, by command
   basename, or by the whole entry.
   - A retired entry that is present opens that file's gate. The file is cleaned even when the
     project declares no current server for it, or no longer configures the agent that reads it.
   - **Keep-it rule:** a user who wants to keep the server changes any launch field (command, args,
     env or cwd). The scaffold then keeps the entry with a note. An exact copy of a retired launch
     is removed on every refresh.
4. **Claude approvals are reported, not removed.** For each retired name, the Claude adjustment
   writes a note when `enabledMcpjsonServers` holds the name, or when an allow entry starts with
   `mcp__<n>__`. The note lists the exact strings. The adjustment writes the note before its
   "nothing declared or declined" early return. It removes no data. A user's rule for a
   user-global server with the same name has the same text, so the scaffold cannot prove that a
   rule is its own.
5. **Hooks are pruned by disk and catalog.** The scaffold removes a hook from
   `.claude/settings.json`, in any event, only when all three conditions are true:
   - ai-badger owns it (`skill_script_id` is not None);
   - its skill has no directory `features/*/skills/<skill>/` in the catalog;
   - its project script is not None and is missing from the target.

   The prune also runs when the manifest has nothing to wire. It removes only the entries and
   events that it empties itself.
6. **Hermes gets a note.** The scaffold never writes `~/.hermes/config.yaml` (ADR-0014). When the
   MCP prune removes a retired entry and `hermes` is in `config.agents`, the scaffold writes one
   note. The note names each `mcp_servers.<n>` that the operator should delete. The scaffold never
   reads `~/.hermes`.
7. **A test derives the list from history.** A framework test reads the git history of every
   `features/*/stack-mcp.json`. It uses only the events that delete a name from `servers`. Each
   launch that a deleted name ever had must have an equal item in `retired`. The test fails on a
   shallow clone. A synthetic repository proves that its comparator can fail.

## Alternatives

- **Status quo with manual upgrade notes.** Every retirement adds hand-removal steps for four files
  and two settings arrays, and each consumer does them by hand. ADR-0048 shipped this way.
- **Ownership recorded in the manifest.** Record each server name that ai-badger wrote, and prune
  the recorded names that the catalog no longer declares. This does nothing for semantica, because
  no existing manifest recorded it. It also reverses the #194 rule that a record gives no
  ownership.
- **Managed-block rebuild.** Rebuild an owned region on every run, as Codex does. JSON has no
  comments, so the markers would go inside the entries. That risks the host schemas, and
  `permissions.allow` is a string array with no place for a marker.
- **One shape per retired name.** Semantica shipped four launches, so a consumer on an older shape
  keeps a stale entry.
- **A disk-only hook key.** Remove every owned hook whose script is missing. In a git worktree, the
  scripts of a catalog skill can lag behind the settings, so this removes live hooks.
- **A partial-run flag.** Skip the hook prune when `--skills` names a subset. The catalog-source
  condition already keeps every skill that a partial run leaves undelivered, so the flag protects
  nothing.
- **An enabled-name pre-pass.** Compute the MCP prune before the Claude adjustment so that it can
  remove the name from `enabledMcpjsonServers`. A stale name is silent in Claude, and the allow
  rule that stays has the same residual risk. The pre-pass adds a second evaluation and new
  plumbing, and it gives no measured benefit.
- **Retired = existing − declared.** This removes the entries and approvals of servers that are
  unavailable, declined or user-scoped.

## Consequences

- **Positive.** The first refresh at 0.219.0 removes semantica in any of its four shapes, whatever
  manifest the consumer holds. This includes the file of a deselected Copilot or pi agent.
  Future retirements need no hand-removal upgrade notes. No new ownership record is added.
- **Negative.**
  - Stale approval strings stay in `.claude/settings.json`. A note reports them on every run until
    the user deletes them. If a server with that name comes back, the stale rule pre-approves it.
  - A user's exact copy of a retired launch is removed on every refresh until the user changes a
    launch field.
  - Authors must move every launch to `retired`, and never delete it. The history test enforces
    this, and it needs a full clone (CI checks out with `fetch-depth: 0`).
  - Tombstones are permanent: one line for each shipped launch.
- **Neutral.**
  - `permissions.deny`, `disabledMcpjsonServers` and `~/.hermes` are never read or changed by the
    prune.
  - The stale ai-raccoon approval from its move to user scope is out of scope. It is still in use.
  - A hook command with Windows backslashes is not recognised as owned, so the prune keeps it. The
    scaffold writes POSIX paths.
  - `.ai-badger/mcp-tools.json` stays with mcp-index.
- Revisit if a host starts to warn about stale approval strings, or if ai-badger gets an ownership
  record that existing consumers already carry.
