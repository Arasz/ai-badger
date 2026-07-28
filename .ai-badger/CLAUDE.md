# ai-badger

Agent-instruction framework distributed as a Claude Code plugin. Python 3.8+ scripts (detect/scaffold/validate/index_build/drift) materialize a per-repo .ai-badger/ scaffold from a features/{stack|common}/{feature} catalog. Stdlib-only except two declared dependencies (engine/requirements.txt): jsonschema is required — validation refuses rather than silently passing — and pyyaml is optional, guarded, and degrades to a printed note. Two .mjs helper scripts under skills/maintain-agent-instructions/.

> Domain: Developer tooling: agent instruction catalogs and repo scaffolding.
> Stacks: python, js, github, claude, hermes, ts, node
> Scaffolded by ai-badger 0.37.0. Source of truth for this file: `.ai-badger/CLAUDE.md`.

## Non-negotiable invariants

### Guard clauses over hand-rolled null checks

Prefer a dedicated guard/throw-helper for argument validation over hand-rolled `x ?? throw ...`
or ad hoc `if (x == null) throw` blocks — a guard reads as intent, not boilerplate, and keeps
the exception type/message consistent across the codebase. Use the idiomatic guard utility for
the language/stack in use, and fail fast at the boundary rather than letting invalid state flow in.

### Minimal comments

Keep doc comments to 1-3 lines stating the contract, not the provenance or rationale — point at an ADR or spec doc for the "why" instead of writing an essay inline. Test doc comments are one sentence or none; the test name and body should carry the intent.

### No hand-rolled crypto or security orchestration

Never implement security/cryptographic orchestration yourself — key derivation, token signing, session/cookie protection, encryption-at-rest schemes. Delegate to an audited, platform-provided library rather than composing audited primitives into your own protocol, even when the primitives themselves are sound.

### No hardcoded secrets

No credentials, connection strings, API keys, or tokens in tracked files, examples, or fixtures. Read secrets from configuration or environment variables, and keep sample/test values obviously fake.

### One PR per task

Every unit of work ends in a pull request; never push directly to the main/trunk branch. One task maps to one PR — don't bundle unrelated work into the same change so review and rollback stay scoped.

**The one exception is an explicit instruction from the person you are working with.** When they ask you to merge locally, push straight to main, or skip the PR for a particular change, that is theirs to decide. An agent never grants itself this exception — not to save a step, not because the change looks trivial, and not because a rebase turned awkward. Absent that instruction, the rule above is absolute.

The exception lifts the PR requirement and nothing else. Every gate still runs before the push: the PR was the record, not the safety net.

### Screaming architecture

Organize folders and modules by domain/business concept, not by generic technical bucket. A new folder name should tell a reader what the system *does*, not what kind of file lives there — avoid catch-all `Services/`, `Controllers/`, `Utils/` buckets in favor of concept-named ones. A shared technical chassis (logging, DI wiring, cross-cutting middleware) is the one accepted exception.

### Small commits, early draft PR

Commit one coherent work package at a time and push often. Open a draft PR from the first commit of a unit of work so progress is visible in-flight, rather than surfacing a single large diff at the end.

### TDD is mandatory

Write a failing, behavior-focused test before any production code change. No production code without a test that demanded it — implementation follows the test, never the other way around.

### Always bump VERSION and add changelog entry

Every release — no matter how small — must:
1. Bump `VERSION` (semver patch for fixes, minor for features, major for breaking changes)
2. Add a `docs/changelog/{version}-{slug}.md` entry describing what changed
3. Update `docs/changelog/README.md` if adding a new changelog format convention

This ensures every change is traceable and users can see what changed between versions.

## Commands

- `test`: `python3 -m pytest -q`
- `lint`: `python3 -m pylint engine tooling features gates tests`
- `build`: `python3 tooling/index_build.py --check`

## Path-specific instructions

Before editing matching files, read the applicable scoped instruction file:

- `documentation.instructions.md` → `.ai-badger/instructions/documentation.instructions.md`
- `python.instructions.md` → `.ai-badger/instructions/python.instructions.md`
- `javascript.instructions.md` → `.ai-badger/instructions/javascript.instructions.md`
- `hermes.instructions.md` → `.ai-badger/instructions/hermes.instructions.md`
- `typescript.instructions.md` → `.ai-badger/instructions/typescript.instructions.md`
- `node.instructions.md` → `.ai-badger/instructions/node.instructions.md`

## Agent delegation

_None configured — work is not dispatched to a persona. Add entries to `personaRouting` in `.ai-badger/config.json` to route it._

## Prompt markers

This project understands prompt markers (see `.ai-badger/skills/prompt-markers`):

- `h:` / `hint:` — a lead to validate before acting (research first).
- `f:` / `feedback:` — a high-priority correction; adjust immediately.
- `e:` / `extension:` — a request to expand the current task's scope.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Reach for the code-review-graph MCP tools before
Grep/Glob/Read** — they cost fewer tokens and return structural context (callers,
dependents, test coverage) that file scanning cannot. Fall back to Grep/Glob/Read only
where the graph doesn't reach.

Entry points: `semantic_search_nodes_tool` to locate code, `query_graph_tool` to trace
callers/callees/imports/tests, `detect_changes_tool` for review, `get_impact_radius_tool`
for blast radius, `get_architecture_overview_tool` for structure. Each tool's own
description covers the rest; the graph auto-updates on file change.



## Framework

Skills, personas, and instructions here are managed by ai-badger. Run `welcome-ai-badger`
to re-scaffold after changing `.ai-badger/config.json`, and `feed-badger` to contribute
project-agnostic improvements back to the framework. Provenance: `.ai-badger/manifest.json`.