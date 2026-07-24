<!-- Managed by ai-badger. Source of truth: .ai-badger/HERMES.md. Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->

# ai-badger

Agent-instruction framework distributed as a Claude Code plugin. Pure-stdlib Python 3.8+ scripts (detect/scaffold/validate/index_build/drift) materialize a per-repo .ai-badger/ scaffold from a features/{stack|common}/{feature} catalog. Two .mjs helper scripts under skills/maintain-agent-instructions/.

> Domain: Developer tooling: agent instruction catalogs and repo scaffolding.
> Stacks: python, js, github
> Scaffolded by ai-badger 0.9.4. Source of truth for this file: `.ai-badger/HERMES.md`.

## Non-negotiable invariants

# Guard clauses over hand-rolled null checks

Prefer a dedicated guard/throw-helper for argument validation over hand-rolled `x ?? throw ...`
or ad hoc `if (x == null) throw` blocks — a guard reads as intent, not boilerplate, and keeps
the exception type/message consistent across the codebase. Use the idiomatic guard utility for
the language/stack in use, and fail fast at the boundary rather than letting invalid state flow in.

# Minimal comments

Keep doc comments to 1-3 lines stating the contract, not the provenance or rationale — point at an ADR or spec doc for the "why" instead of writing an essay inline. Test doc comments are one sentence or none; the test name and body should carry the intent.

# No hand-rolled crypto or security orchestration

Never implement security/cryptographic orchestration yourself — key derivation, token signing, session/cookie protection, encryption-at-rest schemes. Delegate to an audited, platform-provided library rather than composing audited primitives into your own protocol, even when the primitives themselves are sound.

# No hardcoded secrets

No credentials, connection strings, API keys, or tokens in tracked files, examples, or fixtures. Read secrets from configuration or environment variables, and keep sample/test values obviously fake.

# One PR per task

Every unit of work ends in a pull request; never push directly to the main/trunk branch. One task maps to one PR — don't bundle unrelated work into the same change so review and rollback stay scoped.

# Screaming architecture

Organize folders and modules by domain/business concept, not by generic technical bucket. A new folder name should tell a reader what the system *does*, not what kind of file lives there — avoid catch-all `Services/`, `Controllers/`, `Utils/` buckets in favor of concept-named ones. A shared technical chassis (logging, DI wiring, cross-cutting middleware) is the one accepted exception.

# Small commits, early draft PR

Commit one coherent work package at a time and push often. Open a draft PR from the first commit of a unit of work so progress is visible in-flight, rather than surfacing a single large diff at the end.

# TDD is mandatory

Write a failing, behavior-focused test before any production code change. No production code without a test that demanded it — implementation follows the test, never the other way around.

# Always bump VERSION and add changelog entry

Every release — no matter how small — must:
1. Bump `VERSION` (semver patch for fixes, minor for features, major for breaking changes)
2. Add a `docs/changelog/{version}-{slug}.md` entry describing what changed
3. Update `docs/changelog/README.md` if adding a new changelog format convention

This ensures every change is traceable and users can see what changed between versions.

## Commands

- `test`: `python3 -m pytest -q`
- `lint`: `python3 -m pylint scripts features tests`
- `build`: `python3 scripts/index_build.py --check`

## Path-specific instructions

Before editing matching files, read the applicable scoped instruction file:

- `documentation.instructions.md` → `.ai-badger/instructions/documentation.instructions.md`
- `python.instructions.md` → `.ai-badger/instructions/python.instructions.md`
- `javascript.instructions.md` → `.ai-badger/instructions/javascript.instructions.md`

## Agent delegation

_Default routing._

## Hermes-specific guidance

This project is configured for Hermes Agent. The `.ai-badger/` directory is the source of truth
for all agent configuration.

### Skills

Framework skills live under `.ai-badger/skills/`. Load them in-session with `/skill <name>` or
preload with `hermes -s <name>`. Key skills:

- `task` — task orchestration: TDD, PR flow, review loop, token tracking
- `prompt-markers` — `h:`, `f:`, `e:` prefix markers (see below)

### Memory

Hermes persistent memory is available. Use it to save durable facts about the project:
user preferences, environment details, recurring conventions. Do NOT save transient
task progress or TODOs — use `session_search` for that.

### Subagent delegation

Use `delegate_task` for parallel subtasks. The `task` skill adapts its orchestration
pattern for Hermes: plan with `role='orchestrator'`, implement with leaf agents.
Prefer `delegate_task` over spawning separate `hermes` processes for quick subtasks.

### Context file discovery

Hermes reads project context files in priority order (first match wins):
1. `.hermes.md` / `HERMES.md` — walks parents to git root
2. `AGENTS.md` — cwd only
3. `CLAUDE.md` — cwd only

This file (HERMES.md) is at priority 1 and is the authoritative project context for
Hermes agents working in this repo.

## Prompt markers

This project understands prompt markers (see `.ai-badger/skills/prompt-markers`):

- `h:` / `hint:` — a lead to validate before acting (research first).
- `f:` / `feedback:` — a high-priority correction; adjust immediately.
- `e:` / `extension:` — a request to expand the current task's scope.

## Framework

Skills, personas, and instructions here are managed by ai-badger. Run `welcome-ai-badger`
to re-scaffold after changing `.ai-badger/config.json`, and `feed-badger` to contribute
project-agnostic improvements back to the framework. Provenance: `.ai-badger/manifest.json`.
