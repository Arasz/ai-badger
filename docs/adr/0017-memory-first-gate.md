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

## Amendment (2026-10-18, v0.196.0): first sighting of each pattern, `# memory-checked` marker

The session-wide unlock let one unrelated `memory_search` open every later grep, and the
gate read only a Bash command's first word, so `sed ...; echo; grep -n "a\|b" f | head`
passed untouched. The gate now keys on the search pattern, not the session.

- **Rule.** A text-search call passes only when (a) every pattern it searches for was already
  memory-searched for this project, and (b) a call whose input has a `command` string ends its
  last line with the trailing comment `# memory-checked`. Grep/Glob/search_files have no
  command string and need only (a). The marker is read from the raw text (the lexer drops
  comments) and accepted only when `shell_parser.parse` of the command equals the parse with
  the trailing marker removed, so a marker the lexer reads as a word (quoted, or glued on by
  an escaped blank) cannot spoof it, while `grep memory-checked docs # memory-checked` works.
- **Detection.** Every segment of a compound command, through the vendored `shell_parser.py`:
  grep/egrep/fgrep/rg/find, a piped grep included (but see the excluded list). Patterns:
  `-e`/`--regexp` values, else the
  first operand after the options that take a value; split on `\|`, and on a bare `|` under
  rg/`-E`/egrep; find's `-name/-iname/-path/-ipath/-regex/-iregex` values; the tool's
  `pattern` (or `query`). A segment with no pattern is keyed on its own words.
- **First sighting.** The hook runs one in-process ai-raccoon search
  (`memory_context.search_block`: no prompt gate, no session check, one 4 s budget from hook
  start over open+search+close) with the unsearched patterns as the query. A reply (hits or
  empty) records them and its hits go into the deny reason; a search that could not run
  records nothing and the reason tells the agent to call `memory_search` with the pattern.
  Every deny reason names the marker.
- **Searched means.** Stored entries carry their kind: `p:` a pattern the gate searched,
  `q:` an agent's query. A pattern counts as searched when its normalized form (regex escapes
  undone, `^ $ \b` and grouping parentheses dropped, lowercase, whitespace collapsed) equals a
  recorded pattern, or is a contiguous whole-word run of a recorded query (`def` is not inside
  `default`). Only the patterns that fit the 500-char query are recorded. The PostToolUse
  `memory_search` hook records the call's
  `query` (Copilot's string `toolArgs` included); `record_search` stays as telemetry.
- **Store.** `hook_state` row `memory_first.searched.<project_id>` via `kv_update`; file
  fallback `~/.ai-badger/memory-first-searched/<project_id>`, one entry per line. Never reset,
  no cap. The store opens with a 1 s lock timeout (`STORE_TIMEOUT_SECONDS`), so a read and a
  write stay well inside the 10 s hook timeout.
- **Fail open.** A project id that cannot be persisted (`unknown`) or a failed record makes
  `decide` return `{}` on every host: a pattern the gate cannot remember would be denied
  forever. The PostToolUse hook is unchanged.
- **Excluded list.** A grep/egrep/fgrep/rg segment reading a `|`/`|&` pipe from a program on
  `EXCLUDED_UPSTREAM` (git, gh, ps, ls, env, printenv, history, docker, kubectl, pip, npm, lsof,
  brew, dotnet) is skipped before it counts as a search segment, so a command
  whose only search segments are exempt is not text search at all (no search, no marker).
  Memory cannot answer a filter over live command output. `shell_parser.Command.upstream`
  names the feeding command; its program is resolved through rtk/sudo/env wrappers. Only the
  immediate upstream counts: `git log | head -50 | grep fix` is gated because `head` is not
  listed. Never exempt: a file operand (every operand under `-e`/`-f`), `-r`/`-R`/
  `--recursive`/`-d recurse`, `rg --files`, find, an input redirect (`< f`, `<<<`), a grep run
  by `xargs`, a grep nested in `bash -c` (its stdin is not proven), and the shlex fallback.
  Exception: a listed program that prints repo files is not exempt — `git ls-files`, `git ls-tree`, `git grep` (subcommand found past `-C`/`-c`/`--git-dir`/`--work-tree`) and `ls -R`/`--recursive`; a grep over their output stays gated.
- **Untrusted hits.** The search hits quoted in a deny reason are bank content, untrusted data
  exactly as in the prompt hook's injected context.
- **Removed.** `MAX_DENIALS` and the denial counter (`deny_count`, `increment_denials`),
  `search_consulted`, and the Hermes per-process `_memory_consulted`/`_gate_denials`/
  `reset_gate_state`. Hermes keys on `gate.project_id(cwd)` in the same store, and session
  start clears nothing. There is no pass-through: the escape is a search, then the marker.
- Tests: `tests/test_memory_first_gate_first_sighting.py` covers the rule end to end; each
  row was mutation-checked (the mutation applied, the suite red, reverted).
