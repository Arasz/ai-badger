# Delegation map — ai-badger

> Scaffolded by ai-badger 0.60.1. Regenerated on every scaffold; do not edit.

## Stacks

python, js, github, claude, hermes, ts, node, changelog

## Personas available here

- `api-engineer` — API-contract specialist — REST endpoint/contract design (spec-first, ambiguous-schema questions asked before scaffolding) for a Node/TypeScript backend. Lane: sonnet.
- `architect` — Design and decomposition specialist — architecture decisions (module/layer boundaries, extension-point interfaces, folder structure), ADR authoring, multi-file change blueprints, and well-architected-style trade-off analysis (cost vs resilience vs velocity). Lane: opus.
- `code-reviewer` — Independent quality and security gate — OWASP Top 10 (plus OWASP LLM Top 10 when an LLM-integration surface is present) review scoped to a targeted plan (pick the 3-5 relevant risk categories for the diff, not a blanket checklist), two-pass performance/anti-pattern analysis, and adversarial verification of AI-generated claims. Lane: opus.
- `delegator` — Work-routing lead for long, multi-package sessions — decomposes a task into independently verifiable packages, dispatches each to the persona and model lane that fits it, and does only integration, arbitration and gate-running itself. Lane: opus.
- `hermes-agent-author` — Default persona for authoring and maintaining Hermes Agent skills, configuration, and automation. Lane: sonnet.
- `test-engineer` — Testing specialist — designs test strategy, writes failing tests first, plans phased test coverage (leaf types unmocked → mid-layer with leaf mocks → top-layer), audits test quality/coverage gaps, and enforces edit-boundary discipline between test files and production code. Lane: sonnet.

## Routing (config.json personaRouting)

- Design, decomposition and ADRs — before any non-trivial multi-file change → `architect`
- Test strategy, the failing test that precedes a change, and auditing whether an existing test can actually fail → `test-engineer`
- Quality gate before merge, security review, and adversarially verifying a claim this session made about its own work → `code-reviewer`
- Hermes skills, hooks and gateway configuration, and HERMES.md → `hermes-agent-author`
- Long, multi-package or autonomous sessions — route work instead of doing it → `delegator`

## Verifiers

- `test`: `python3 -m pytest -q`
- `lint`: `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`
- `build`: `python3 tooling/index_build.py --check`

## MCP servers reachable here

- `code-review-graph` — This project has a knowledge graph
