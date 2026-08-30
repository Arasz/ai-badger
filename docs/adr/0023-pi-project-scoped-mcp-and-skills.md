# ADR-0023 — pi MCP and skills discovery is project-scoped runtime reading, not scaffold-written global state

**Date:** 2026-08-30
**Status:** Accepted (2026-08-30, task aib-pi-stack-mcp-skills-parity; owner gate 5/5 APPROVE)
**Author:** Rafał Araszkiewicz (Arasz), with the MoE planning panel (architect, test-engineer, code-reviewer), the plan-review panel (api-engineer, qa, hermes-agent-author) and the implementation lanes
**Extends:** ADR-0022 (pi arms hooks dynamically), ADR-0015 (mechanisms, not prose)
**Scope:** `pi-mcp-tools-fork/src/` (ConfigLoader, claudeMcpConfig, index, McpToolAdapter),
`features/pi/adjustments/adapter/index.ts`, `features/pi/adjustments/{adjust_mcp,adjust_skills,pi_settings}.py`,
`features/common/support.json` (pi rows)

## Context

Since 0.144.0, pi got a "simple usable form" of MCP and skills: the scaffold merged the
project's declared servers into the **user-global** `~/.pi/agent/settings.json` `mcp` key
(read solely by the pi-mcp-tools fork — pi core consumes no MCP), and merged the project's
`.ai-badger/skills/` absolute path into the global `skills` array. That form leaks by
construction: the global `mcp` key accumulates every scaffolded project's servers
(same-named-overwrite), the global `skills` array accumulates one path per project, and
every pi session sees every project's servers and skills. Claude Code compares: a
project-managed `.mcp.json` plus project-local skills — discovery defined by the project.

Two measured facts reshaped the design en route (both verified in pi 0.84.4 dist source by
two independent lanes, then by the orchestrator):

1. **The trust short-circuit.** pi's trust-requiring resources are exactly
   `.pi/{settings.json,extensions,skills,prompts,themes,SYSTEM.md,APPEND_SYSTEM.md}` and
   ancestor `.agents/skills` — not `.mcp.json`, not `.ai-badger/`, not `.pi/agents/`. A
   project holding none resolves `projectTrusted = true` **before** any saved decision,
   extension, or `defaultProjectTrust` is consulted. Every ai-badger-scaffolded project
   (whose only project-side pi writes are `.pi/agents/` personas) therefore resolves
   trusted **in every mode, including headless `-p`/`--mode json`/`--mode rpc`**. The
   original plan's premise — "headless arms nothing until `/trust`" — was false, in the
   safe direction. The gate is vacuous today and live tomorrow: the moment a project gains
   `.pi/settings.json` (an ordinary model/theme tweak) or an ancestor gains
   `.agents/skills`, headless arming silently stops (no `trust.json` exists;
   `defaultProjectTrust: "ask"`).
2. **Extension lifecycle.** pi re-invokes the extension factory on every session
   replacement (`/new`, `/resume`, `/fork` — fresh module state per invocation), and a
   factory throw exits headless pi. Config loading therefore belongs in `session_start`
   (where `ctx.cwd` and `ctx.isProjectTrusted()` exist), wrapped defensively; per-session
   Maps make tool re-registration safe by construction (name-keyed overwrite; no
   unregister API, no guard needed).

## Decision

**The fork reads the project's claude-format `.mcp.json` at `session_start` and merges it
project-over-global; the adapter contributes the project's skills path via
`resources_discover`, ungated; the scaffold's pi adjustments become migration-only
removers.** Five owner-gated decisions (all APPROVE, no notes):

1. **Trust gate: `ctx.isProjectTrusted()`, with the measured semantics** — scaffolded
   projects arm in all modes day one; the gate bites only in the fragile case above, which
   is named here, pinned by tests in both directions, and made visible in reporting rather
   than smoothed away. Auto-trust via a `project_trust` handler was rejected twice over:
   the event only fires for projects that already carry trust-requiring resources (dead
   code for minimal scaffolded projects), and the marker (`​.ai-badger/config.json`) is
   forgeable. Scaffold-written `trust.json` rejected (unversioned schema, only effective
   in the fragile case).
2. **Skills: ungated** — a deliberate, recorded divergence from pi's own classification
   (pi trust-gates project skills). Calibration: the adapter has executed project-declared
   hook **shell commands** ungated in every mode since ADR-0022; skills are strictly
   weaker than what already runs. The effective trust decision for ai-badger-equipped pi
   is installing the adapter user-globally. The subagent precedent (`.pi/agents` via fs)
   is not the rationale — pi does not gate that path, so it proves nothing about skills.
3. **Migration-only adjustments, shape-aware and per-extension marker-gated.** Removal
   keys on a regenerated-from-declaration shape match (deep-equal fields, command compared
   shlex-split-or-literal to tolerate the historical split→shlex drift), never on name
   alone — all scaffolded projects share the same five server names, and name-keyed
   removal would destroy user edits. Removal is gated on **capability marker files** in
   the installed extensions (`.ai-badger-capability-project-scope-mcp` for the fork,
   `.ai-badger-capability-resources-discover` for the adapter) — never on version numbers
   (the installed version equals the fork's upstream-owned one), and per-extension so a
   pre-adapter machine never loses its only skills route. Marker absent ⇒ skip with
   warning, file untouched.
4. **`mcpDisabledTools` stays global** (accepted residual: a tool-noise toggle made in
   project A applies in project B); the fork's `saveDisabledTools` became atomic
   (unique temp + rename) as a drive-by.
5. **Remote servers map**: claude `type:"http"/"sse"` → fork `type:"remote"` (the fork
   already shipped both transports; live `rider` servers exist in two scaffolded projects).
   Without this, "same server set as Claude Code" would be false in real projects.

Converter rules pinned by test: `type:"stdio"`/absent → local; `${HOME}` prefixes expanded
in command/args/cwd (the scaffold emits them; the fork spawning the literal string fails
with silent ENOENT); any other unexpanded `${VAR}` skips the entry with a warning;
`tools:["*"]`/empty/absent → **no filtering** — never `filterPatterns` (a pass-through
would throw `RegExp("*")` per tool and kill every tool of every scaffolded server,
debug-only visible); glob-ish patterns anchor to regex; **every `RegExp` construction is
try/caught — a poison pattern fails open per-pattern, one tool's match decision at most,
never the server**; unparseable `.mcp.json` ⇒ global-only fallback, never a partial arm.

Reporting: a merge ledger records, per server, its source — `project:.mcp.json` /
`global settings` / `skipped:unsupported-shape` / `skipped:unexpanded-var` /
`untrusted-project` — plus skipped and untrusted counts. **`mcp_list_servers` (a tool,
callable headless) reports the ledger; `/mcp-status` renders it** — extension commands
throw when queued headless, so the tool is the only headless-visible channel, and the
ledger is what makes the divergence (pi core ignores `.mcp.json`; the fork honors it)
observable rather than silent. A skipped project entry shadows the same-named global
entry (the project claimed the name and it is broken); an untrusted project's gated
declaration is reported additively alongside the global entry that genuinely arms — the
fragile-case vanish must be visible, not absorbed.

## Consequences

- **Positive:** parity with Claude Code by construction (same file, same server set,
  remote included); the cross-project leak is eliminated at the source; headless behavior
  is honest and now machine-verified (channel probe in a scaffolded project armed exactly
  the declared set, remote included, no trust bootstrap; skills probe and its negative
  control both passed); migration of the accumulated global state is idempotent and safe
  on machines this task never touches (marker gates).
- **Negative / accepted:** the fork now parses a claude-format file (coupling to a stable
  external shape; unknown shapes skip with warnings). The capability markers are an
  install contract between repo A's publish flow and repo B's adjustments — a manual
  install that drops them degrades to warn-and-leave, never to data loss. The fragile-case
  headless flip remains silent at the pi layer; the ledger's `untrusted-project` rows are
  the mitigation. `mcpDisabledTools` remains cross-project. The stale upstream
  `main`/`pi.extensions` package.json fields were corrected to `./index.ts` — creating the
  npm-style `src/` layout in the canonical copy would double-load the extension.
- **ADR-0022 boundary holds, extended:** nothing here adds manifest `pi` keys or static
  registration. `.mcp.json` is read at event time exactly like the generated `hooks.json`
  — dynamic arming; `registerTool` inside `session_start` is pi's documented dynamic path.
  A new hook wired for claude is still armed for pi with zero manifest edits.

## Verification anchor

`tests/claudeMcpConfig.test.ts`, `tests/ConfigLoader.test.ts`, `tests/lifecycle.test.ts`
(fork, vitest); `tests/pi-mcp-tools/*` + `tests/pi-mcp-tools/fork-canonical-parity.test.ts`
(repo A, bun); `tests/test_pi_adjustments.py` (flipped removal pins, shape matcher,
marker gates, real-home guard), `tests/test_support_json_honesty.py` (pi-row substrings),
`test_scaffold_writes_no_trust_requiring_resource_into_project_pi` (repo B, pytest); live
cutover checklist in the task's verification notes (ship-order proof, migration byte-diff,
minimal-project headless arming, fragile-case flip both directions, cross-project
isolation + remote, skills two-sided probe, `/new` lifecycle, idempotence, marker-gate
live proof, honesty readback).
