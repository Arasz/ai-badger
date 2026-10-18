# ADR-0040 — Codex user plugins with one active ai-badger scope

**Date:** 2026-10-19  
**Status:** Accepted

## Context

ADR-0038 established project-native Codex delivery and explicitly deferred marketplace
installation and user-global configuration. Codex now supports native plugin marketplaces,
plugin skills, and plugin-bundled hooks. At the same time, Codex discovers skills from both
user and project locations and can list same-named skills twice.

## Decision

Keep project scaffolding as the default. Add a Codex compatibility manifest to the existing
ai-badger marketplace plugin so users can install its skills and checked hooks in Codex user
scope. Add `codexScope` with `project` and `user` values. In user mode, project adjustments
remove ai-badger-owned Codex skill links and hooks while preserving operator-owned entries.
The scaffold does not edit `$CODEX_HOME` or user files.

Codex marketplace-backed skills use Codex CLI commands from the installer. Claude plugin
contents are not assumed compatible solely because Codex can read a marketplace; commands,
hooks, and MCP configuration must use a Codex-supported interface.

The memory-first gate runs synchronously on `PreToolUse` for shell search calls. Its denial
uses Codex's native `hookSpecificOutput` response. A `PostToolUse` observer credits a memory
search only after it succeeds; this observer records compliance but cannot prevent a search.
The Codex PreToolUse adapter allows a search when the shared lookup reports that the backend
is unavailable. A reachable backend with no hits still denies the first sighting. Other
harnesses retain the shared gate policy.

## Consequences

Codex users can choose user-wide plugin delivery or project-local scaffold delivery without
duplicating the same ai-badger skills and hooks. The default remains project-local and does not
mutate a user's Codex home. Plugin hooks still require Codex trust review. Marketplace command
generation does not guarantee that every third-party Claude plugin is Codex-compatible.

## Alternatives considered

- Write directly into `$CODEX_HOME`: rejected because project scaffolding should not mutate
  user-global configuration.
- Enable user plugin and project links together: rejected because Codex lists same-named skills
  separately and runs hooks accumulated from each scope.
- Move Codex behavior into shared skills: rejected because the existing shared catalog remains
  canonical and harness-specific behavior belongs in Codex adjustments.

Research evidence: [Codex native support research](../work/2026-10-19-codex-native-support-research.md).
