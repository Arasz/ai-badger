# Plan: memory gate — first sighting of each grep pattern runs a memory search

Task: `aib-grep-first-sighting-memory-search` · loop: low · target version 0.196.0

## Request

Replace each grep tool call with a memory search the first time its search pattern is seen;
the second attempt with that pattern runs grep. Example that slipped through the 0.84 gate:
`sed -n 50,95p ...; echo '---'; grep -n "def merge_hooks\|def _prune\|append\|extend" ... | head -20`.

## Decisions

1. The hook runs the search itself: deny the first sighting, run an ai-raccoon search with the
   grep pattern(s) as the query, return the hits in the deny reason plus "re-issue to run it".
   Search failure, timeout, no proxy or no project id → plain deny reason. Exit 0 on every path.
2. A search call passes only when BOTH hold: (a) a memory search for every one of its
   patterns has already run — the hook's own first-sighting search records the pattern, and so
   does an agent `query` whose query contains it (post hook) — and (b) the call carries
   the marker `# memory-checked` (trailing shell comment). The deny reason and the
   ai-raccoon-memory SKILL.md both name the marker. Grep/Glob tools carry no free-text field, so
   for them (a) alone suffices. No extractable pattern → key on the segment's words.
3. Searched patterns are never reset: no session-start clear, no FIFO eviction; keyed per
   project id (not session). The session-wide unlock and the 3-strike pass-through are removed.
   `record_search` stays as telemetry.
4. Detection covers every segment of a compound Bash command via `shell_parser.parse`.

## Design

`memory_first_gate.py` gains `search_patterns`, `pattern_keys`, `seen_keys`/`remember_keys`
(persisted per project id, never reset; marker-dir `<project>.seen` fallback), `first_sighting`, `search_query`, `deny_reason`, `memory_hits` (lazy
sibling import of `memory_context.py`). `MAX_DENIALS`, `deny_count`, `increment_denials`,
`_denials_path`, `search_consulted` are removed. `memory_context.py` gains `search_block()`,
which `build()` delegates to. `shell_parser.py` is vendored beside the gate. Hermes plugin uses the same persisted per-project store; nothing clears it on session start. Search budget 4 s (hook timeouts
are 10 s; Hermes abandons at 30 s).

## Steps

| id | goal | files | depends_on | gate |
|---|---|---|---|---|
| S1 | failing tests first | `tests/test_memory_first_gate_first_sighting.py`, rewrite of unlock/3-strike tests | — | new tests red on current code |
| S2 | `search_block` extracted | `memory_context.py` | — | `pytest -q tests -k memory_context` |
| S3 | vendor `shell_parser.py` | ai-raccoon-memory/scripts | — | `pytest -q tests/test_shell_parser.py` |
| S4 | gate module | `memory_first_gate.py` | S1 S2 S3 | `pytest -q tests/test_memory_first_gate*.py` + pylint |
| S5 | PreToolUse hook | `memory_first_gate_hook.py` | S4 | hook tests; exit 0 on garbage stdin |
| S6 | Hermes plugin | `features/common/hooks/ai_badger_hooks.py` | S4 | hermes gate tests |
| S7 | docs + release | ADR-0017 amendment, `VERSION`, changelog + README row | S4 | `tooling/index_build.py --check` |
| S8 | refresh copies | `tooling/sync_plugin_skills.py`, re-scaffold | S5 S6 | `--check` + scaffold freshness |
| S9 | join | — | S7 S8 | test + lint + build |

## Test list

| behavior | failure targeted | mutation |
|---|---|---|
| user's example denied on first sight, reason carries hits | tokens[0]-only detection | revert to tokens[0] |
| identical retry WITHOUT marker still denied | marker not enforced | drop marker check |
| retry with `# memory-checked` passes | keys not recorded | skip `remember_keys` |
| marker on a never-searched pattern denied | marker alone unlocks | drop seen check |
| same pattern, other flags/path + marker passes | key on command | key on command string |
| agent query containing the pattern counts as searched | post hook not recording | skip post-hook record |
| Grep tool: seen pattern passes without marker | marker demanded where impossible | require marker for Grep tool |
| new pattern in same shape denied | session-wide open | always "seen" |
| compound: seen + unseen grep denied | `any` instead of `all` | swap |
| `a\|b` seen → `rg b` passes | no alternation split | drop split |
| `find -name '*.py'` keyed on pattern; `find -type f` on words | empty key set allowed | return empty set |
| `grep -A 3 -e foo` pattern is `foo` | value-flag parsing | drop skip |
| search raises/times out → plain deny, exit 0 | crash blocks tool | remove try/except |
| 4th new-pattern denial still denies | 3-strike leftover | restore MAX_DENIALS |
| query consult unlocks nothing | session unlock leftover | restore `search_consulted` |
| store missing → `.seen` fallback persists | fallback lost | skip fallback write |
| seen pattern survives a new session / session start | reset leftover | clear on session start |
| `sed`/`cat` never touched | over-matching | match any segment |

## Plan review fold-in (code-reviewer, APPROVE-WITH-FIXES)

1. **Marker read from the raw string.** `shell_parser.parse` drops comments (`shell_parser.py:302`). Accept the
   marker only when the raw command's last line matches `(?:^|\s)#\s*memory-checked\s*$` AND no parsed
   word contains `memory-checked` (blocks `grep '# memory-checked' f` spoofing). Test row: spoof denied.
2. **Store.** Not the session-keyed `memory_first` table (its marker importer and resurrection guard,
   `badger_store.py:1841,1891`). Use `hook_state` key `memory_first.searched.<project_id>` via
   `kv_update` (`badger_store.py:1490`, one `BEGIN IMMEDIATE` read-modify-write). File fallback in its own
   dir `~/.ai-badger/memory-first-searched/<project_id>`. A set of normalized pattern strings, no hashing,
   no cap. No project id (`"unknown"`) → do not persist (deny stays plain).
3. **What counts as "searched" (owner rule kept literal).** Record a pattern only when a search actually
   ran: the hook's in-process search got a reply (hits or empty), or the PostToolUse `query`
   payload's `query` contains the pattern. When the hook cannot search (no executable/project id/timeout),
   the deny reason tells the agent to call `query` with that pattern; the post hook then records it.
   Test row: no executable → deny names query; post hook with that query → marker retry passes.
4. **`memory_context.search_block(query, project_id, session_id, budget)`** applies neither `should_enrich`
   nor the session-id check; `build()` keeps both and delegates. One `Budget(4)` from hook start covers
   open+search+close; project id resolved once and passed in.
5. Copilot `toolArgs` may be a JSON string — `json.loads` in both hooks; post-hook test with string args.
6. Hermes keys on `gate.project_id(cwd)` (same store as Claude/Copilot); `reset_gate_state` removed with
   its callers (`ai_badger_hooks.py:431`, `tests/test_hermes_plugin_payloads.py:44`,
   `tests/test_memory_first_gate_hermes.py:35`).
7. Marker exemption = tool input has no `command` string (covers Grep/Glob/search_files/grep/glob).
8. Pattern comparison normalizes regex escapes (`foo\.bar` ≡ `foo.bar`).
9. Extra files: `tests/test_memory_first_gate_post_hook.py` (search_consulted asserts),
   ADR-0036:95 (MAX_DENIALS mention), SKILL.md of ai-raccoon-memory (marker documented).
10. S2, S3 depend on S1.

## Owner change: excluded list (2026-10-18)

A grep/rg/egrep/fgrep segment is exempt from the gate when it reads stdin from a pipe (no file or
path operand of its own) and the program feeding that pipe is on `EXCLUDED_UPSTREAM` in
`memory_first_gate.py`: git, gh, ps, ls, env, printenv, history, docker, kubectl, pip, npm, lsof,
brew, dotnet. Memory cannot answer a filter over live command output. A file-reading grep in the
same compound command is still gated. Tests: `git log | grep fix` passes with no search and no
marker; `git log | grep fix && grep -rn fix src/` is gated on `fix`; `cat f | grep x` stays gated
(cat not listed); `git log | grep fix file.txt` stays gated (has a file operand). Mutation: drop the
upstream check → `cat f | grep x` passes → red.
