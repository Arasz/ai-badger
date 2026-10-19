# Codex auto-wm hook compatibility

The reported failure is `PreToolUse hook returned unsupported permissionDecision:allow`.
The active Codex user configuration invoked the Claude auto-wm gate directly. Its
`emit()` returns a Claude PreToolUse decision for both partner and away modes.

## Evidence

- `features/claude/skills/auto-wm/hooks/awm_gate.py` checks project scope, expiry and the
  denylist, then logs `auto_approve` and emits `allow`. That source remains unchanged.
- `hooks/codex-hooks.json` did not provide an auto-wm adapter in 0.203.0.
- [Codex hook protocol](https://learn.chatgpt.com/docs/hooks), reviewed 2026-10-19:
  PreToolUse permits `allow` with an input rewrite; PermissionRequest approves using
  `hookSpecificOutput.decision.behavior`. Returning no decision retains normal approval.
  Other hooks can still deny. Specialized tools may bypass the general hook path.
- The existing Claude tests in `tests/test_awm_gate.py` cover the shared policy but do
  not execute installed Codex commands or validate native output.

## Implementation decision

Adapt auto-wm under `features/codex/adjustments/`. Native PermissionRequest approvals
reuse the existing policy. PreToolUse emits no generic approval and records no approval
that did not happen. Supported away-mode question denials remain available where Codex
runs the hook. Unknown tools, patch inputs and malformed requests defer to normal policy.
The context adapter describes these limits and uses the delivered command path.

Plugin and project delivery must select one scope. An explicit migration command removes
only recognized legacy user hook handlers after checking the replacement plugin, keeps
operator hooks and metadata, saves a backup, and does nothing on a second run.

Simply suppressing `allow` would remove the error while losing supported autoapproval and
leaving misleading audit rows. A small Codex adapter preserves the shared policy without
adding a dependency or changing the Claude implementation.

## Acceptance and gates

1. Armed partner and away PreToolUse requests emit no unsupported approval or approval
   audit row. PermissionRequest uses the native schema and logs exactly one approval.
2. Disabled, expired, wrong-project, broad-root, destructive, network, MCP, patch,
   unknown-tool and malformed requests defer. Context agrees with gate scope.
3. Away questions deny on supported paths; partner questions defer. Claude tests pass.
4. Delivered plugin/project commands execute in isolated subprocess tests. Repeated
   delivery, scope switches and exclusions preserve operator configuration.
5. Migration verifies replacement assets, preserves mixed groups, backs up once and is
   idempotent. Active local registration contains no legacy auto-wm gate after repair.

Write the failing behavior tests first. Use the existing Claude suites plus a focused
Codex adapter suite; a separate reviewer checks that removing each guard makes its test
fail. Repository gates and CI cover the integrated release.
