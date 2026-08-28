# pi full-support gap audit — simple usable form of every daily feature (2026-08-28)

Owner bar: **pi replaces hermes as the daily harness.** For every feature the owner uses daily
and that ai-badger needs, pi gets at least a **simple, usable form**. Full parity is out of
scope; every deferral carries a one-line justification. This doc is the §7 of the master plan
(`2026-08-28-pi-review-fixes-plan.md`).

Evidence sources: `features/common/hooks/hooks-manifest.json` (18 hooks / 37 agent arms,
counted this session), `features/common/support.json`, `features/*/adjustments/`,
`docs/work/2026-08-28-pi-harness-support.md` (F3: all six Claude events ai-badger uses have pi
counterparts; 12/16 hooks live day one), machine state of `~/.pi/agent/` (settings.json holds
only `{lastChangelogVersion, theme}`; `extensions/`, `skills/`, `agents/` empty/absent).

## 1. Replacement blockers (hermes features with no pi form today) — CLOSED BY THIS PLAN

| # | Blocker | pi today | Closed by |
|---|---|---|---|
| B1 | **Hooks**: hermes gets the full plugin surface (drift-notice, context-enrichment, commit-reminder, memory-first/grade, follow-through, semantica-autosave, grounded-feedback) user-scope | nothing installed (`extensions/` empty) | adapter extension (plan P1/D1) — translates `input`/`tool_call`/`tool_result`/`session_start`/`session_shutdown`/`agent_settled`; research F3 measured 12/16 hooks live day one |
| B2 | **Skills**: pi reads its own discovery paths only; `features/pi/skills.json` is `{"skills": []}`; scaffold delivers to `.ai-badger/skills/` which pi never reads | zero skills | G1 below |
| B3 | **MCP**: hermes/claude get written configs; pi gets a printed proposal only (`adjust_mcp.py` proposal-only) | servers absent | G2 below |
| B4 | **Unattended runs**: pi has no away/auto-approve mode; project-local extensions are silently ignored headless (research F20) | cannot run unattended safely | away-mode extension (plan P2/D2, user-scope default-off env) |

## 2. Daily-features checklist

| Feature | claude | hermes | copilot | pi today | pi simple form (planned) | Deliberately deferred (parity beyond simple form) |
|---|---|---|---|---|---|---|
| Instructions file (CLAUDE.md-equivalent) | CLAUDE.md | HERMES.md | copilot-instructions | AGENTS.override.md delivered by scaffolding.json | **ships today** ✓ | — |
| Invariants + scoped instructions | ✓ | ✓ | ✓ | same file | **ships today** ✓ | — |
| Skills distribution | .claude/skills symlinks | plugin copy | .github/skills | **nothing** | G1: settings `skills` array entry → `.ai-badger/skills/` | per-skill install commands; discovery UX |
| Hooks: drift-notice / context-enrichment | ✓ | ✓ | ✓ | nothing | adapter (B1) | — |
| Hooks: commit-reminder / grounded-feedback | ✓ | ✓ | ✓ | nothing | adapter (B1) | — |
| Hooks: memory-first/grade, follow-through, semantica-autosave | ✓ | ✓ | ✓ | nothing | adapter (B1) | hermes-only payload quirks (pre_llm stash) get adapter-side equivalents where the event exists; none need new mechanism |
| Hooks: claude-only arms (session-start-tracking, task-checkpoint ×2, dispatch-gate, kill-guard, cross-worktree warning) | claude-only by manifest | n/a | n/a | n/a | none needed — these arms were never claude-external | transcript-shaped session tracking (needs pi transcript format study) |
| Git-dir / git-config guards | ✓ | ✓ (git-dir) | ✓ (config) | nothing | adapter covers `tool_call`-shaped guards (git-internals-guard) | git-config-health copilot arm stays copilot-only |
| MCP servers | .mcp.json written | config.yaml written | mcp-config written | printed snippet | G2: merge `mcp` key into `~/.pi/agent/settings.json` | per-server tool allowlists UI |
| Persona agents / delegation map | personas + dispatch gate | delegation.md | .github/agents/*.agent.md | delegation.md via instructions | **usable today** ✓ (pi subagents = `pi -p --mode json` child procs; delegation map delivered) | G5/deferred: `~/.pi/agent/agents/*.agent.md` generation |
| Task tracking: session id + resume | claude_session_source | hermes_session_source | — | pi_session_source (F3 fix planned) | **after F3 fix**: correct `--session` resume ✓ | — |
| Task tracking: token checkpoints | real | real | n/a | **zeroed** | G3: read usage from pi session files (timeboxed) | per-model breakdown if pi doesn't expose it |
| Cron | crontab (opt-in) | plugin | — | broken extension | P3 repair (planned) | — |
| Subagents | personas via delegate | delegate_task | cloud agents | CLI child procs | **usable today** ✓ (extension.md documents the spawn line) | example subagent extension remains manual-install (F7 doc fix) |
| Unattended / away mode | `--dangerously-skip-permissions`-shaped flows | gateway jobs | — | nothing | P2 away-mode (planned) | remote orchestration (no messaging integration in pi) |

## 3. Gap packages

### G1 — skills delivery (effort S/M) — closes B2
**Mechanism (ask-if-simpler):** `features/pi/adjustments/adjust_skills.py` — on scaffold,
read `~/.pi/agent/settings.json`, merge the project's `.ai-badger/skills/` directory into the
`skills` array (idempotent, dedupe, preserve unknown keys), write back. Settings-array entries
are user-config, **not trust-gated** → works headless (the F20 constraint). Symlink farms
rejected: per-project paths in a global dir collide across projects. `adjustment.json` gains
the arm; `support.json` pi.skills flips `aiBadgerSupport: true` with `scaffoldedBy` naming the
adjustment (replacing D8's interim honest-false).
**Files:** `features/pi/adjustments/adjust_skills.py` (new), `adjustment.json` (+1 arm),
`features/common/support.json` (pi.skills row), `tests/test_pi_adjustments.py` (module-constant
`PI_SETTINGS_PATH` monkeypatched to tmp; merge/idempotent/preserve-unknown tests).
**Gate:** settings file gains exactly one entry per scaffold run, unknown keys survive;
red-proof: revert merge → test red. Depends on: nothing (independent of adapter).

### G2 — MCP apply instead of propose (effort S) — closes B3
**Mechanism:** extend `adjust_mcp.py`: when `install=True`, merge declared servers into
`~/.pi/agent/settings.json` under `mcp` (same read-modify-write helper as G1, shared module
`pi_settings.py`); keep the printed snippet for `install=False`. Precedent: claude gets
`.mcp.json` written without a manual step. Machine target is a fresh file (only
`lastChangelogVersion`/`theme`) — merge semantics still mandatory.
**Files:** `features/pi/adjustments/adjust_mcp.py`, new `pi_settings.py` sibling, `support.json`
pi.mcpServers row (`aiBadgerSupport: true`, `scaffoldedBy` updated), tests (merge, dedupe,
decline-filter respected, unknown keys preserved).
**Gate:** declared servers appear under `mcp` with `toolPrefix` intact; declined servers absent;
red-proof: revert write → red. Depends on: nothing.

### G3 — real token checkpoints (effort M, timeboxed, owner decision) 
**Mechanism:** pi persists sessions under `~/.pi/agent/sessions/` (dir exists, timestamps
active). `pi_session_source.py` checkpoint lambda gains a reader that finds the session file by
`PI_SESSION_ID` and extracts usage if the format carries it. Timebox: one implementation
attempt; if the session format exposes no usage, zeroes stay and the docstring says so
honestly (current behavior, documented).
**Files:** `features/pi/adjustments/pi_session_source.py`, tests with a fixture session file.
**Gate:** fixture-based: usage present → checkpoint carries it; absent → zeros (both asserted).
Depends on: F3 fix (same file).

### G4 — hook-arm coverage contract (effort S, docs + one test)
**Mechanism:** the adapter ships with a coverage table in its docstring derived from the
current manifest (18 hooks/37 arms — the research's 16-hook count predates the git guards):
which arms the six translated events cover, which stay claude/hermes/copilot-only and why.
One pytest source-contract test pins the adapter's event set against the manifest's non-claude
arms so a new arm without a pi path is a visible decision, not drift (derive-or-delete).
**Files:** adapter docstring (TS lane's file), `tests/test_pi_adjustments.py` (+1).
**Gate:** test red if an arm is added to the manifest without a pi disposition.

### G5 — persona agent files (DEFERRED — justification)
pi custom agents live user-global (`~/.pi/agent/agents/`); personas are per-project. A simple
form would write global state per project and collide across repos. The usable path already
exists: delegation map + persona lanes reach pi via AGENTS.override.md and subagents spawn as
`pi -p --mode json` child procs with explicit `--model/--tools`. Revisit only if the owner
wants `/agent`-style persona switching inside pi.

## 4. Owner decisions

1. G1+G2 write `~/.pi/agent/settings.json` (user-global, currently fresh) — approve direct
   write, or keep proposal-only for MCP (G2) while writing skills (G1)? Default proposed: write
   both (claude/hermes precedent; merge semantics preserve user keys).
2. G3 timebox: attempt real checkpoints (default) or accept documented zeroes this release?
3. G5 deferral accepted? Default: deferred per justification above.

## 5. Sequencing

G1, G2, G4 are independent of the adapter and can join Wave 1 (parallel with python + TS
lanes; shared files: `support.json` — serialize via the python lane, `adjustment.json` —
python lane). G3 joins Wave 2 with the gaps package. All feed the machine-cutover gate
(master plan §4 E): after install, `~/.pi/agent/` shows the extensions, the settings keys, and
a live pi session exercises skills + hooks + MCP + cron + task resume.
