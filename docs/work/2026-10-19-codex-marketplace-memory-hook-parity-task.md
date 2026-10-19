# Codex native support and scope deduplication

## Objective

Provide Codex-specific user and project support in ai-badger. Support Codex-compatible
marketplace installation, native plugin skills and hooks, correct Codex hook environments,
and a single active ai-badger delivery scope. Keep Codex-specific changes in Codex adjustments
or plugin metadata; do not edit shared skill source files.

## Acceptance criteria

- Codex project scope remains the default; user scope uses the ai-badger Codex plugin and
  removes project copies of ai-badger skills and hooks.
- Codex-generated commands do not inject Claude project or home variables.
- Codex marketplace-backed skill sources emit native Codex CLI marketplace and plugin
  commands without Claude-only scope flags.
- Codex memory-first gating uses synchronous `PreToolUse` and the Codex deny response shape.
- Codex instructions and discovery target only the native AGENTS filenames; duplicate
  skill/hook delivery is guarded.
- Documentation and ADR describe the verified scope and hook boundaries; release metadata
  and changelog are updated.
- Relevant tests and validators pass.
