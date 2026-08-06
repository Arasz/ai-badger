# ADR-0016: Remove Junie support — three-agent scope

**Status:** Accepted (2026-08-06, v0.83.0)
**Scope:** Framework catalog, scaffolding, schemas, docs

## Context

ai-badger scaffolded and documented support for four coding agents: `claude`,
`copilot`, `hermes`, and `junie` (JetBrains). Junie support was added incrementally
(0.7.0 plugin-instructions, 0.34.0 `.junie/AGENTS.md` copy, 0.47.0 `.junie/skills/`
symlinking) and carried a full feature surface: `features/junie/` (scaffolding.json,
adjustments, templates), catalog entries in `index.json` and `features/common/support.json`,
agent enums in six schemas, detection in `detect.py`, and `JUNIE_HOOK_EXEMPTION` in
`tooling/validate.py`.

The owner does not use Junie, and there is no capacity to maintain a fourth agent
surface (hooks, scaffolding, docs, tests) alongside claude, copilot, and hermes.

## Decision

Remove Junie support entirely in one change (v0.83.0):

- delete `features/junie/` and its test file;
- drop `junie` from `AGENT_NAMES` (`engine/badger_lib.py`), the agent enums in
  `schemas/agents.schema.json`, `config.schema.json`, `manifest.schema.json`,
  `skills-source.schema.json`, `stack-mcp.schema.json`, `support.schema.json`,
  the catalog (`index.json`), and the support matrix (`features/common/support.json`);
- remove junie branches from `detect.py` / `scaffold.py` / `agent_files.py` and the
  `JUNIE_HOOK_EXEMPTION` machinery in `tooling/validate.py`;
- update tests and live docs (README, SECURITY, getting-started, framework-architecture,
  skills, dictionary, authoring-a-feature) to the three-agent scope;
- record the removal here and in the changelog. Historical changelog entries
  (0.47.0 etc.) are kept as release records.

## Consequences

- A project config naming `junie` fails schema validation — the schemas are the
  enforcement point; no scaffold path can generate `.junie/` files anymore.
- Existing `.junie/` directories in already-scaffolded projects are left untouched:
  the framework stops generating and validating junie but does not delete user files.
- Supported agents are exactly three: `claude`, `copilot`, `hermes`. Re-adding an
  agent is a deliberate catalog decision that must touch the schemas, the manifest
  coverage test, and this ADR together.
- The `JUNIE_HOOK_EXEMPTION` constant is gone; hook coverage tests now only know the
  three hook-capable agents (claude, hermes, copilot all have hook surfaces).
