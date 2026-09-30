# Research record — aib-scaffold-pi-native-mcp-config

Date: 2026-09-30. Loop: **low**. Scope: the scaffolding fix (option 2) — den-refresh /
welcome-ai-badger must write pi's real MCP config (`.pi/mcp.json`) instead of relying on
`.mcp.json` that pi never reads; plus harden `mcp-plan-tools.md`'s raw JSON-RPC example into
pi's exact call form.

Every finding cites its source; unverified claims are labelled **[HYPOTHESIS]**.

## Findings

### F1 — pi native reads only `mcp.json`, at two locations [MEASURED]
Config lives in `~/.pi/agent/mcp.json` (global) and `.pi/mcp.json` (project; read only after
project trust — headless `-p`/json/rpc with `defaultProjectTrust` ask|never skips it). The
settings `mcp` key is **not** read by pi.
Sources: AiRaccoon memory entry 374749 (pi-badger-integration, verified against installed pi
source 2026-09-30); pi docs `mcp.md` ("Add servers to `~/.pi/agent/mcp.json`, or to
`.pi/mcp.json` in a project"); `features/pi/instructions/pi.instructions.md` (corrected at
0.182.1).

### F2 — the `pi-mcp-tools` fork is retired; the scaffolding still believes it reads `.mcp.json` [READ]
`mcp_tools.py` declares `MCP_JSON.readers=("claude","pi","copilot")` with the rationale "The
pi-mcp-tools fork reads it as well, from its session cwd only (ADR-0023)" and an
`EXPANDS_HOME_ONLY={"pi"}` carve-out for that fork's converter. The fork is gone: the fork
retirement "left `.mcp.json` in place for Claude Code and added tracked `.pi/mcp.json`" in the
consumer, and 0.182.1's own note says "`features/pi/adjustments/adjust_mcp.py` and its
capability-marker gating still name the `pi-mcp-tools` fork … a separate retirement".
Sources: `skills/welcome-ai-badger/scripts/mcp_tools.py` (MCP_JSON, EXPANDS_HOME_ONLY blocks);
memory 374744, 374749 fact 7, 374892.

### F3 — the write path today [READ]
`mcp_tools.py` writes exactly two project files — `.mcp.json` and `.github/mcp.json` — via
`McpDestination` records (`label, readers, requires_reader, pin_cwd, expand_home, all_tools,
consequence`) and `_merge_mcp_servers_json`; orchestration at `scaffold.py:744-749`
(`generate_mcp_json`, `propose_claude_mcp_user`, `generate_copilot_mcp_json`). `expand_home`
rewrites user-tool-dir executables to `${HOME}/...` form; `all_tools` adds `"tools": ["*"]`.
Every write is recorded through `ctx.record_generated_config` (generatedConfig manifest, #194).
Sources: `skills/welcome-ai-badger/scripts/mcp_tools.py:1-160,491-770`;
`skills/welcome-ai-badger/scripts/generated_config.py`.

### F4 — pi-native entry shape differs from the fork's in three load-bearing ways [MEASURED/READ]
1. `command`/`args`/`cwd` get `~` expansion **only** — a `${HOME}/...` command is not expanded
   and stays literal; `${NAME}` and `!command` resolve in `env`/`headers` values only.
   [MEASURED — memory 374749 fact 2; corroborated pi docs mcp.md: "A leading `~/` in `command`,
   an argument, or `cwd` names the home directory"]
2. No fork `tools` filter arrays — native `toolExposure` only overrides a tool's exposure, it
   does not filter. A `tools` allowlist must be dropped at the pi destination.
   [MEASURED — memory 374749 F6-parity note]
3. Exposure: `codemode` (default) leaves tools **undeclared to the model** —
   `"exposure": "direct"` is required for direct `mcp__<server>__<tool>` calls.
   [READ — pi docs/mcp.md Exposure section].

### F5 — the live failure this fixes [OBSERVED]
An earlier session with an empty registry invented `mcp_task_graph_step_start` (prose partial
identifiers + divergent naming priors, no declaration to copy); and with `exposure` left at the
codemode default even a correctly formed `mcp__task-graph__step_start` 404s on a direct call.
Sources: this task's incident diagnosis (session transcript), corroborated by the
pi-badger-integration sibling (bus messages #1590/#1591, 2026-09-30).

### F6 — a verified reference shape already exists [MEASURED]
pi-badger-integration's hand-wired `.pi/mcp.json` carries the 5 ai-badger servers
(code-review-graph, ai-raccoon, semantica, playwright, task-graph) with `"exposure": "direct"`,
`~/`-form commands (bare PATH lookups for code-review-graph/npx), and no `tools` arrays. The
sibling confirmed 5/5 entries match the shape this task scaffolds and offered to review the
den-refresh diff against that file. Source: bus messages #1590/#1591.

### F7 — the mirror chain decides where edits land [READ]
`features/common/skills/**` is the source (catalog); `tooling/sync_plugin_skills.py` copies
SKILL.md + essential files into `skills/` (the only directory Claude Code reads, ADR-0008);
`.ai-badger/**` is this repo's self-scaffold output (tracked). `skills/` and
`features/common/skills/` copies are byte-identical today (sha256 equal for `mcp_tools.py` and
`mcp-plan-tools.md`). Tests exercise the **features** copy
(`tests/test_stack_mcp_servers.py`: `SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"`).
Sources: `tooling/sync_plugin_skills.py` docstring; `git ls-files`; sha256 comparison 2026-09-30.

### F8 — the task-graph declaration is already pi-compatible [READ]
`features/common/stack-mcp.json` declares
`"command": "uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_server.py"`
(project-relative; pi resolves relative against the session cwd) with a `claude` agentOverride
anchoring `${CLAUDE_PROJECT_DIR}/...`. No `exposure` field exists in declarations today.
Source: `features/common/stack-mcp.json`; memory 374749 fact 7.

### F9 — `mcp-plan-tools.md` teaches a call form no host exposes [READ]
The "worked example, both ways" shows raw JSON-RPC
`{"method":"tools/call","params":{"name":"step_start",...}}` — bare tool names, wire protocol.
pi's exact form is the declared tool call `mcp__task-graph__step_start` with the same JSON
arguments (and `codemode`/`tool_search` reach undeclared tools when exposure is not `direct`).
Source: `features/common/skills/task-decomposition/references/mcp-plan-tools.md` (MCP example
block).

### F10 — re-scaffold must preserve hand-tuned `exposure`/`toolExposure`, never flatten [REQUIREMENT, sibling-verified reference state]
The consumer's `.pi/mcp.json` is tuned beyond the default: ai-raccoon/task-graph/semantica stay
`"exposure":"direct"` (hook- and skill-driven, skills name exact call forms) while
code-review-graph (30 tools) and playwright (25 tools) are `"deferred"` — 55 of 106 declarations
cut from every prompt, loaded via `tool_search`. A render that rewrites entries wholesale back
to `direct` would clobber that tuning on the next den-refresh. Required merge semantics: add
missing servers, keep per-entry `exposure`/`toolExposure` (and consider `enabled`, which pi's
`/mcp` also persists) from the existing file; defaults apply to **new** entries only.
Precedent in the write path: `_carry_live_cwd` already preserves recorded `cwd` state across
re-scaffolds for exactly this reason. Source: bus message #1593 (pi-badger-integration sibling,
2026-09-30) with the reference state as MEASURED there; pi docs mcp.md confirms `exposure`
values `codemode | codemode-deferred | deferred | direct | hidden` and per-tool `toolExposure`
with `*` patterns, and that `/mcp` exposure changes persist to `mcp.json`.

### F11 — merge semantics, sharpened: existing entries are immutable; merge is a union [REQUIREMENT, sibling-verified]
Two precision points that sharpen F10 while the design is cheap to change (bus #1595,
2026-09-30):
1. **Whole-entry preservation** — for entries already present in `.pi/mcp.json`, preserve the
   **entire entry** byte-identical (command/args/env/cwd included), not just
   exposure/toolExposure/enabled. The `${HOME}`-vs-`~` migration bug lives exactly in a
   template rewrite of a validated live entry. Template shape governs **new** entries only.
   Acceptance fixture extends to: "an existing entry survives re-scaffold byte-identical, full
   stop."
2. **Union, never eat** — entries the scaffold does not recognize (user-added personal
   servers) are kept untouched and never dropped. Explicit removals stay explicit:
   `config.mcp.decline` (#186) still removes its named servers, and the shape-matched
   unavailable-removal keeps its shape gate — both are removals of *scaffold-declared* servers,
   note-emitting, not template rewrites. [HYPOTHESIS: keep the shape-matched
   `_drop_unavailable` removal for this destination too — plan to confirm.]
Scope note: these semantics apply to the **pi destination only**; `.mcp.json` /
`.github/mcp.json` keep their established update-on-refresh behavior (#186/#193-entangled,
Claude Code's `${VAR}` expansion), which is out of scope.

## Hypotheses (not yet verified)

- **H1** — the next self-scaffold/release will materialize `.pi/mcp.json` in this repo and in
  refreshed consumers; whether it is tracked or gitignored here follows `.mcp.json`'s treatment.
  (Unverified: `tooling/release_paths.py` unread; gitignore rules unchecked.)
- **H2** — `schemas/stack-mcp.schema.json` may reject unknown per-server keys, so a per-server
  `exposure` plumbed through declarations needs a schema change; the simpler alternative is a
  destination-hardcoded `"exposure": "direct"` on the pi render. (Unverified: schema unread.)
- **H3** — `features/pi/adjustments/adjust_mcp.py` / `pi_settings.py` fork machinery is inert or
  misleading under a native-only pi, but retiring it is explicitly a separate task (0.182.1
  note). Out of scope here.

## Scope in / out

**In:** pi destination in `mcp_tools.py` (+ call site, tests red-first, schema if needed) with
F10+F11 merge semantics — existing entries immutable, union merge, template shape for new
entries only; honest pi mechanism strings (`features/common/support.json`, pi
instructions pointer); `mcp-plan-tools.md` pi call form (features source + mirror sync);
version/changelog for the release; gates.

**Out:** retiring the fork-machinery adjustments (H3); consumer-side wiring (pi-badger-integration
point 1, landed by the sibling); user-global `~/.pi/agent/mcp.json` writes (ADR-0014 decision 6
— propose, never write).
