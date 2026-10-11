# ADR-0038 — Deliver Codex through project-native surfaces

**Date:** 2026-10-11
**Status:** Accepted

## Context

ai-badger handled Claude Code, Copilot, Hermes and pi, but had no Codex catalog stack or
capability entry. Codex discovers instructions, skills, personas and MCP through different
project paths. Its hook payloads and trust checks also differ from Claude's.

## Decision

Add Codex as a configured agent and agent stack. Keep canonical content in `.ai-badger/`,
then deliver a full `AGENTS.md` discovery copy, project `.agents/skills/` directory symlinks,
standalone `.codex/agents/*.toml` persona files, project MCP tables in `.codex/config.toml`,
and a tested subset of native command hooks in `.codex/hooks.json`.

Persona TOML contains the native required fields `name`, `description` and
`developer_instructions`. Claude model lanes and provider pins are not translated to OpenAI
model identifiers. Codex inherits model and reasoning settings unless the project owner
configures them separately.

Respect existing user configuration and discovery files. Scaffolding neither edits global
Codex configuration nor grants project or hook trust. Hook support is partial and local;
unsupported manifest entries remain unsupported instead of being treated as equivalent to
Claude hooks. The capability matrix records these boundaries.

A root pi `AGENTS.override.md` takes precedence over Codex's `AGENTS.md`. The managed pi
template includes the same full project guidance. Hand-authored
instruction overrides remain their owner's responsibility.

## Consequences

Codex projects can consume the same catalog without a second skill or persona source tree.
Project trust and exact-definition hook trust still require the normal Codex review flow.
Local command hooks do not imply support for cloud orchestration. External plugin install
recipes and hook parity remain separate capabilities.

The benefit is shared catalog content without user-global configuration changes. The cost is
partial hook coverage and inherited model settings that do not implement Claude tier routing.
Normal Codex project and hook trust remain an operator responsibility.

## Alternatives considered

An instructions-only integration leaves skills, personas and MCP undiscovered. Writing to
`~/.codex/config.toml` expands a project scaffold into machine-wide configuration. Translating
Claude personas and hooks verbatim would send invalid model lanes and incompatible patch
payloads to Codex. A new plugin distribution channel adds work without fixing those project
contracts. Native project delivery is the smaller complete integration.

The [research record](../work/2026-10-11-codex-harness-research.md) captures upstream evidence.
[`codex.md`](../codex.md) documents setup, ownership and runtime limits.

Hook commands bind the scaffolded absolute root and isolate Python imports. Relocation requires
re-scaffolding and hook review. The MCP, hook, persona and skill-link adapters opt into
deselection cleanup, removing only their owned entries while preserving operator files and
malformed configuration. Manifest pruning cannot cover them: it skips directory symlinks and
keeps persona files while `codex` remains a detected stack.
