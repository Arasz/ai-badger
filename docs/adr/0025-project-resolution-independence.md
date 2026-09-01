# ADR-0025: Project resolution is ai-badger's own — the `.ai-badger/project-id` walk

Date: 2026-09-01 · Status: accepted · Decides the D2 ruling of the
`aib-bus-followups-independence` owner gate (7/7, recorded in
`docs/work/2026-09-01-bus-qa-followups-owner-gate-reconciliation.md`).

## Context

The message bus (0.156.0) resolves a working directory to a project id through the
ai-raccoon memory bank (`~/.ai-raccoon/memory.db`: `ingest.scope.<id>` settings keys plus
`watches` rows, equal-or-ancestor containment on canonicalized paths, several matches →
`ProjectIdAmbiguous`). The dependency was deliberate at P2 — the raccoon already had a
registered project id space — but it makes ai-badger's project identity depend on another
tool's private database: its schema, its scope keys, its installed-ness. Three follow-up
findings made the cost concrete:

1. **The resolver contract needs no registry.** The bus addresses mail by project id and
   session id; the only fact resolution must establish is "which project does this
   directory belong to". A directory either carries an ai-badger scaffold or it does not.
2. **The raccoon bank is not always there.** A repo scaffolded by ai-badger but never
   registered with the raccoon resolved to None — the bus degraded to 1:1 even though the
   project obviously existed.
3. **The owner's independence ruling.** "Where there is `.ai-badger`, there is a project"
   — ai-badger artifacts must be sufficient to run ai-badger features.

## Decision

1. **The project id lives in the project**: `.ai-badger/project-id`, one uuid4 minted at
   scaffold time (before the config write; `Scaffolder.run`), never regenerated.
   den-refresh backfills existing repos (`ensure_project_id` in its pre-flight).
2. **Resolution is a nearest-`.ai-badger` upward walk**: from the canonicalized cwd, the
   first ancestor carrying `.ai-badger/project-id` wins; the walk stops there. Explicit
   `AI_BADGER_PROJECT_ID` still wins unconditionally (the resolver contract's A3 rule).
3. **No compatibility shim.** The raccoon bank reader (`raccoon_registry_surface`),
   `RACCOON_BANK_ENV`/`AI_BADGER_RACCOON_DB`, and `ProjectIdAmbiguous` are deleted in the
   same release that lands the walk. A temporary fallback would keep a dead code path,
   three bank fixtures, and an ambiguity concept alive for nothing — the shim variant was
   implemented, reviewed, and rejected (owner: "remove shim now — no compat").
4. **`ProjectIdAmbiguous` retires.** A single upward walk has exactly one nearest
   directory; ambiguity cannot arise, so the exception and the caller-side
   catch-and-fail-open branches are removed with it. Nested `.ai-badger` directories
   (worktrees) resolve to the nearest — the worktree's own project, deterministically.

## Consequences

- **Id-less repos are a permanent fleet state, not a migration window.** A repo scaffolded
  before this change resolves to None until den-refresh backfills: delivery fails open to
  1:1/env-only; sends refuse with the missing-identity message. The SKILL and changelog
  say so.
- **Per-directory ids make each worktree its own project.** A worktree session and its
  parent repo do not share a bus identity; mail addressed to the repo does not reach the
  worktree session and vice versa. This is intended (a worktree is isolated work) and is
  the documented answer to "nested projects" — the raccoon-era ambiguity question has no
  successor.
- **The raccoon is untouched.** Its own ids, scopes and watches keep working for its own
  features; ai-badger simply no longer reads them.
- **Trust boundary unchanged** (ADR-0024/L8): identity is asserted, not authenticated —
  `AI_BADGER_PROJECT_ID` still forges a project id for anything on the machine. The id
  file is machine-local convenience, not an authentication token.

## References

- Owner gate: `docs/work/2026-09-01-bus-qa-followups-owner-gate-reconciliation.md` (D2)
- Evidence: `docs/work/2026-09-01-aib-bus-followups-independence-research-a.md` (resolver
  surface, scaffold write points, backfill seam), `-research-c.md` (Rule 8 scenarios)
- ADR-0024 (the store the resolver serves); the send-message SKILL's "Sender identity is
  mandatory" section (the trust boundary statement)
