# ADR-0039 — A `tools` feature type, and per-harness wiring for rtk

**Date:** 2026-10-17
**Status:** Accepted; amended 2026-10-17 (0.195.1, Claude arm to propose)

## Context

rtk (`rtk-ai/rtk`) is a CLI that rewrites shell commands so their output reaches the model
compressed. It plugs into each harness through a pre-tool hook that calls `rtk hook <agent>`.
The user asked for it to ship the way code-review-graph and semantica ship, but under its own
category, with detection, an optional install and opt-in hook wiring per harness.

ai-badger had no type for a non-MCP command-line tool. The `mcp` feature type is the closest
model: a registry row, a catalog directory per item, a `meta.json` with a prerequisite, and
per-harness adjustments that write configuration. archify and uv reach projects only as skill
`dependencies.json` entries.

The [research record](../work/2026-10-17-rtk-integration-research.md) measured rtk 1.0.1 in
sandboxed homes. Its synthesis decides most of the shape below:

- A local `rtk init` for Claude writes no hook at all, only a `CLAUDE.md` block and
  `.rtk/filters.toml`.
- A local `rtk init` for Codex and Copilot edits files ai-badger generates (`AGENTS.md` gains
  `@RTK.md`, `copilot-instructions.md` gains a block), which the next re-scaffold overwrites
  and the freshness guard flags.
- pi local init writes only `.pi/extensions/rtk.ts`; `--auto-patch` overwrites a user's edited
  copy with no backup. Hermes has no project scope and always writes `~/.hermes`.
- The default build links the BUSL-1.1 `rtk-engine`. An Apache-only `rtk-oss` edition exists,
  without `rtk pipeline` and PostToolUse compression.

Three plan reviews (security, harness, structure) then tightened the guard and the arms.

## Decision

1. **New feature type.** `tools` is a `FeatureType` row with `drift_reports_new=False` and
   `hashes_source=False`, like `mcp`. rtk is its first member at `features/common/tools/rtk/`
   (`meta.json`, `tool.md`, `scripts/check.py`, `scripts/install.py`). `meta.json` carries the
   prerequisite (floor `rtk >= 1.0.1`) and one mode per agent: `native`, `init` or `propose`.
   Each harness's `adjust_tools.py` owns its file format; the meta does not describe hook
   shapes.
2. **Opt-in through config.** `config.json` gains `tools.<name>.hooks: [agent, ...]`. Nothing
   is wired unless a project lists the agent. Native wiring depends on config alone and never
   probes PATH, so the scaffold output is the same on machines with and without rtk.
3. **Claude, Codex and Copilot: ai-badger writes the hook itself.** Claude gets one PreToolUse
   `Bash` handler in `.claude/settings.json`; Codex gets one entry in `.codex/hooks.json`;
   Copilot gets an owned `.github/hooks/rtk-rewrite.json` in the PascalCase `PreToolUse` shape
   rtk itself writes (no matcher, no camelCase key). Claude and Codex carry `timeout: 5`. Each
   adjustment declares `cleanupOnDeselection`, so dropping the agent or the tool removes only
   the marked entry.

   **Amended 0.195.1: Claude is `propose`, not `native`.** The live check found that Claude
   matches project `permissions.ask` rules against the hook's `updatedInput` only, so a
   `Bash(git push:*)` ask rule stopped prompting once rtk rewrote the command, and the push ran.
   rtk's meta now declares Claude `propose`. The Claude arm wires nothing, removes a handler
   0.194.0 wired, and prints the reason. The native Claude merge stays in the arm for a tool
   whose rewrite preserves ask rules.
4. **pi: rtk writes its own extension.** The pi arm runs `rtk init --agent pi` with the target
   repo as cwd, stdin from `/dev/null`, and `RTK_TELEMETRY_DISABLED=1`. It never passes
   `--auto-patch` or `-g`. It runs only when install is enabled and `check.py` passed; otherwise
   it prints a note. An existing `rtk.ts` that rtk refuses to replace stays byte-identical. Opt-out
   runs `rtk init --agent pi --uninstall` under the same gates, or prints the command.
5. **Hermes: proposal only.** Hermes has no project scope, so ai-badger prints the
   `rtk init -g --agent hermes --auto-patch` command (honouring `HERMES_HOME`) and writes
   nothing.
6. **The guarded command.** Every native entry runs
   `env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c '…'`. The script exits 0 when `rtk`
   is not on PATH, maps any non-zero rtk exit to 0, and passes stdout through only when it starts
   with `{`. stderr is kept, so a broken or tampered rtk (`hook integrity check FAILED`) stays
   visible. Mapping exit 2 to 0 is deliberate: Claude reads exit 2 as a block, and rtk uses it
   for its own pipeline deny rules. Those rtk deny verdicts are therefore dropped by design; the
   harness's own permission rules and ai-badger's guards stay the deny authority.
7. **The marker.** `AI_BADGER_TOOL=rtk` in the command identifies ai-badger's entries. Merge,
   idempotency and cleanup match on it and on nothing else.
8. **No rtk side files.** ai-badger writes no `pipeline.toml`, `RTK.md`, `@RTK.md` import,
   `.rtk/` directory or filters file, and does not touch generated instruction files outside the
   rendered `## Tools: rtk` block.
9. **POSIX only.** The guard is `sh -c`. On Windows the arms write nothing and emit a
   POSIX-only note; the winget recipe is printed, never run.
10. **Licence is the user's choice.** `install.py --run` prints the BUSL-1.1 line and the
    `rtk-oss` alternatives (`RTK_EDITION=oss`, `brew install rtk-ai/tap/rtk-oss`, cargo without
    default features) before it installs. No recipe pipes a download into `sh`.

## Consequences

Positive. A project can turn rtk on per harness with one config line, and the files it gets are
owned, marked and removable. Re-scaffolds stay byte-stable because nothing depends on whether
rtk is installed. The `tools` type gives the next CLI tool a slot that is neither MCP nor a
skill dependency.

Negative, and accepted as opt-in risk:

- **Codex approval bypass.** rtk's Codex hook always answers `permissionDecision: "allow"` with
  its `updatedInput`, because Codex rejects a rewrite with `ask` or no decision. Codex applies
  the replacement before its own approval and sandbox checks, and its safe/dangerous classifiers
  do not unwrap `rtk`. An rtk-wrapped `git push` therefore skips Codex's approval prompt and
  classifier signal. The Codex note says so.
- **rtk cannot see our hook.** rtk recognises its hook only when the command is exactly the
  three tokens `rtk hook <agent>`. Our guarded command is not, so `rtk init --show`, `rtk gain`'s
  hook status and `rtk init` itself report the hook missing, and a later `rtk init` for the same
  agent appends a duplicate. `tool.md` says to verify with `rtk gain` counts and not to opt in an
  agent already wired user-level.
- **Unreviewed code in pi.** `rtk.ts` is TypeScript generated by the rtk binary. pi loads it
  with full extension privilege once the project is trusted; ai-badger does not review it. It
  also loads only in a trusted project, so headless `pi -p` without saved trust skips it.
- **Inert under Claude limited mode.** On machines where policy disables project hooks, the
  Claude rtk hook never runs.
- **Dropped rtk denies.** rtk pipeline deny rules have no effect through ai-badger's guard
  (decision 6).
- **More classifier inputs.** ai-badger's own guards may now see `rtk`-prefixed commands; the
  prefix normalisation is tracked as its own step.

Neutral. rtk keeps a local `history.db` (90 days, plaintext) and a config file in the user's
application-support directory whatever ai-badger does; `tool.md` documents
`tracking.enabled=false`, `RTK_DB_PATH` and `RTK_RECALL=0`. A different `rtk` first on PATH
runs with the user's shell trust, and its non-JSON output is discarded by the guard.

Settled by the live check on 2026-10-17 (Claude Code 2.1.302, rtk 1.0.1); evidence in
`docs/work/2026-10-17-rtk-live-verification.md`:

- VERIFIED, Claude: a parallel PreToolUse hook's deny blocks a call rtk rewrote, and that hook
  sees the original command. Project `permissions.deny` is matched against both the original and
  the rewritten command, and it holds. Project `permissions.ask` is matched against the
  rewritten command only, so it is bypassed. That bypass is the reason for the 0.195.1 amendment.
- UNVERIFIED, Codex: no codex binary was available. How Codex aggregates a guard's deny with rtk's
  `allow` is untested. As a precaution, the arm keeps rtk's entry last, after the guards.
- UNVERIFIED, Copilot: no copilot binary was available. Offline, `rtk hook copilot` answers a
  Copilot CLI payload with `modifiedArgs` (a rewrite) and a VS Code payload with `updatedInput`,
  though rtk's install text calls Copilot CLI deny-with-suggestion. Whether a camelCase
  `preToolUse` deny stops chaining into rtk's PascalCase hook, and whether every surface reads
  both files, remains open.
- NOT VERIFIED, pi: the headless run had no model with credits, and it was stopped after pi wrote
  under `$HOME`. From the code, both rtk extensions skip a command that already starts with
  `rtk `, so stacking them should not double-prefix.

## Alternatives

- **Shell to `rtk init` for every harness.** Rejected. Claude local init writes no hook; Codex
  and Copilot init edit ai-badger-generated instruction files that the next scaffold overwrites;
  `--auto-patch` clobbers user edits; Hermes init is always user-wide. pi is the one harness
  where init writes only its own file, so it is the one place we use it.
- **Reuse the MCP slot** (`features/<stack>/mcp/rtk/`). Rejected. rtk is not a server; the MCP
  pipeline writes `.mcp.json` entries, availability gates and approval rules that mean nothing
  for a shell hook, and the name would mislead every reader.
- **A `stack-tools.json` declaration beside each stack.** Rejected for now. With one tool and an
  explicit opt-in key in `config.json`, a stack-level declaration file adds a schema and a
  validate entry without changing what gets wired.
- **A skill `dependencies.json` entry**, like archify and uv. Rejected. That mechanism installs a
  binary for a skill; it has no seam for per-harness hook wiring or cleanup.
- **Pass `updatedInput` through pi's hook-bridge.** Teaching the global pi adapter to honour a
  Claude-shaped `updatedInput` would let the Claude registration cover pi without `rtk.ts`. It is
  cleaner long-term but a TypeScript change with live pi semantics. Deferred.
