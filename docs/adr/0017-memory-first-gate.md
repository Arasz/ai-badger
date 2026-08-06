# ADR-0017: Memory-first gate — enforce memory consultation before text search

**Status:** Accepted (2026-08-06, v0.84.0)
**Scope:** Framework hooks, scaffolding, all three agents

## Context

Every scaffolded project instructs agents to "search memory FIRST" (`.hermes.md`,
`CLAUDE.md`, pre_llm_call context injection), but nothing enforces it: an agent can
grep its way through a repo without ever touching the AiRaccoon memory bank, and the
bank's value is proportional to how often it is consulted. The framework already ships
hook surfaces on all three agents (Hermes plugin, Claude `hooks.json`, Copilot
`.github/hooks/`), and the memory-grade telemetry (0.79.0) already observes
`memory_search` calls — observing was not enough.

## Decision

Add a **memory-first gate**: block repo text-search tools until the session has
consulted `memory_search`, with a deny reason that names the tool to run and explicitly
permits re-issue after consultation. Memory-first, never memory-only.

- One shared pure-logic module (`memory_first_gate.py`) with the tool matchers, the
  per-session consulted markers (`~/.ai-badger/memory-first/<session_id>`), the denial
  counters, and the per-host deny builders.
- Bash/terminal matching is first-token-only (`grep|rg|find|rg.exe`): a build step with
  a piped grep (`git status | grep x`) is not text search and must not be blocked.
- **3-strike pass-through**: after 3 denials in a session the gate stops blocking, so an
  agent cannot stall on a bank that simply has no hit for its query. The strike count is
  a pilot question; 3 is the initial constant.
- Hermes wires it as a `pre_tool_call` plugin hook with in-process state keyed by
  project cwd (plugin payloads carry no session_id); the consulted flag is recorded in
  `post_tool_observer` using the single `memory_grade.is_memory_search` matcher.
- Claude wires a PreToolUse matcher `Grep|Glob|Bash` (the Bash arm inspects the command
  itself — Claude's commonest text search is `Bash` grep, and Claude's `if:` prefix
  conditions would not survive the scaffold wiring's script-identity dedupe).
- Copilot wires `preToolUse` with a manifest `matcher` override
  (`grep|rg|Glob|bash` — Copilot matches runtime tool names case-sensitively, so the
  Claude-cased source matcher is not reusable). The hook exits 0 on every path because
  Copilot command preToolUse is fail-closed: a crash would deny the very tool call the
  gate only meant to gate.
- The consulted marker is recorded by the existing PostToolUse memory_search entry
  (folded into `memory_grade_hook.py`, unconditional), so Claude/Copilot run one
  process per search; a separate recorder entry was rejected because the wiring's
  endswith script filter cannot match a command with a trailing flag.
- Matcher strictness is deliberate: only repo text search is gated; `read_file`,
  `memory_search` itself, and non-search commands always pass. Missing gate module on
  Hermes fails open.

## Consequences

- Fresh scaffolds on all three agents enforce memory-first out of the box; existing
  repos pick it up via `den-refresh`.
- **Known limitations**: Hermes gateway multi-session shares the consulted flag per
  project until the next `on_session_start` reset (plugin callbacks carry no
  session_id; shell hooks would be the alternative if it bites — out of scope for v1).
  Copilot cloud-agent jobs are ephemeral, so the per-session marker has no cross-job
  meaning there; the instruction layer remains the fallback for hosts without a hook
  surface.
- The instruction layer stays in place — the gate complements, never replaces it.
- The 3-strike constant and matcher table are covered by unit tests
  (`tests/test_memory_first_gate.py`, `test_memory_first_gate_hook.py`,
  `test_memory_first_gate_hermes.py`) and can be tuned without schema changes.
