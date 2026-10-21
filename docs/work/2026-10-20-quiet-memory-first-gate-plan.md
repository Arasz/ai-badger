# Quiet memory-first gate — plan (2026-10-20)

Task: `aib-quiet-memory-first-gate` (framework) + `pbi-quiet-memory-first-gate` (pi adapter).

## Objective

The memory-first gate must stop being a user-visible event. On every harness the agent
must still receive the memory results, the user must see no memory output at all, and the
gate's payload must speak about *text search* rather than *grep*.

Owner request (verbatim intent):

- remove the card for memory results — the gate's output is not for the user;
- do not present the memory gate result as a failure — the process must be transparent;
- remove the user-facing part from ai-badger for each harness — those logs are noise;
- the agent must still get correct data;
- rename `grep` → `textSearchInput` in the model and in the ai-badger skill
  (`get-raw-grep-result` → `get-raw-text-search`);
- bug: `rawGrepInput` was empty for a `find` call that had arguments — the text-search
  input must carry every search pattern, not only the captured grep ones.

## Why the gate looks like a failure today

`memory_first_gate.decide()` denies the search call and puts the memory hits into the
denial reason. The host renders that reason as a permission refusal: Claude Code shows a
permission prompt, Codex shows a blocked tool call, pi shows the blocked call's reason as
the tool result, Hermes shows a block message. The user reads a memory dump as an error.

The denial is also the only channel the hits travel through, which is why the data cannot
simply be dropped.

## Host capability matrix (measured, 2026-10-20)

| Host | Model-visible context on the tool-call seam | Evidence |
|---|---|---|
| Claude Code 2.1.303 | `hookSpecificOutput.additionalContext` on `PreToolUse` (applied whether the decision is allow, ask or deny) | the installed binary's hook-output parser (`XN()` case `"PreToolUse"` reads `n.additionalContext`); cap ≈ 8000 chars |
| Codex 0.163.0 | `hookSpecificOutput.additionalContext` on `pre-tool-use.command.output` | the JSON schema shipped inside the binary (`pre-tool-use.command.output`) |
| pi | the adapter owns the seam; the model-side seams are the `context` event and `pi.sendMessage({display:false})` | `dist/core/extensions/types.d.ts` (`ContextEvent`, `ToolCallEventResult`) and `docs/message-types.md` (`display` controls terminal rendering only) |
| Copilot CLI | **not documented** for `preToolUse` (`additionalContext` is documented under `postToolUse`, `sessionStart`, `notification`, `subagentStart`, `postToolUseFailure` only) | `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md` (Copilot docs read 2026-09-28) |
| Hermes CLI | **none** — `pre_tool_call` returns only a block/allow decision; context injection exists only per turn (`pre_llm_call`) | `features/common/hooks/ai_badger_hooks.py` |

So: hosts that can carry model-side context on the tool seam get **allow + context**;
hosts that cannot keep a **deny**, but with a one-line reason instead of a data dump.

## The new contract

### 1. The payload model (the "model" the owner wants renamed)

```json
{
  "textSearchInput": [
    { "pattern": "memory_first_gate", "rawResultHash": "<sha256>" }
  ],
  "searchResult": { "mem_search_result_output": "<Memory context block>" }
}
```

- `rawGrepInput` is renamed `textSearchInput` (the gate's subject is text search, not grep).
- **Every** unsearched pattern of the call appears in `textSearchInput` — grep, rg *and*
  find. `rawResultHash` is present only for a pattern whose raw output the gate captured
  (shell grep/rg only); find patterns carry the pattern without a hash.
  This is the `rawGrepInput` bug: a `find` call produced an empty array.

### 2. The decision per host

`memory_first_gate.build_decision(host, ...)` gains the context-carrying shape:

| host | output |
|---|---|
| `claude` (Claude Code, Codex, pi — all speak the Claude envelope) | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "additionalContext": "<memory block>\n\n<textSearchInput json>"}}` |
| `copilot` | `{"permissionDecision": "deny", "permissionDecisionReason": "<one line>"}` |
| `hermes` | `{"action": "block", "message": "<one line>"}` |

The one line is a plain instruction, never a payload:

```
Memory-first: search memory for "foo" first, then re-run this search.
```

### 3. When the memory lookup cannot run

No proxy, no timeout, no hits: the gate cannot deliver context. It then denies with the
one line above, so the agent performs the search itself and the data is still correct. The
Codex adapter keeps its existing fail-open rule (the denial is suppressed when the shared
lookup is unavailable) — unchanged.

### 4. What the agent receives

- Claude Code / Codex: the memory block as `additionalContext` on the allowed call.
- pi: the adapter turns the same envelope into a model-side message with
  `display: false` — the agent gets it, the terminal shows nothing.
- Copilot CLI / Hermes: the agent's own `query` (its normal tool call) — the
  pattern unlocks through the existing credit rule (`credit_search`), so the re-issued
  search passes.

## The rename map (framework)

| before | after |
|---|---|
| `features/common/skills/get-raw-grep-result/` | `features/common/skills/get-raw-text-search/` |
| `scripts/get_raw_grep_result.py` | `scripts/get_raw_text_search.py` |
| skill name `get-raw-grep-result` | `get-raw-text-search` |
| `RAW_GREP_SCRIPT` in `memory_first_gate.py` | `RAW_TEXT_SEARCH_SCRIPT` |
| payload key `rawGrepInput` | `textSearchInput` |
| entry field `rawGrepInput` in the JSONL log | `textSearchInput` |

Every reference (index.json, hooks-manifest.json, docs, tests, the pi repo's vendored
copy of the skill) moves with it. The script's CLI flags (`--pattern`, `--pattern-hash`)
keep their names.

## Acceptance criteria

**Framework (ai-badger)**

- AC-F1: a first-sighting `Grep`/`Glob`/bash-grep call on a Claude-shaped payload is
  **allowed** and the hook output carries the memory block in
  `hookSpecificOutput.additionalContext` — no `deny`, no `permissionDecisionReason`.
- AC-F2: a first-sighting call on a Copilot payload is denied with the one-line reason
  and **no** JSON payload in the reason.
- AC-F3: a first-sighting call on a Hermes payload blocks with the one-line message and
  no JSON payload.
- AC-F4: `textSearchInput` carries every unsearched pattern of the call — a `find` call
  with `-name` arguments produces a non-empty array (regression for the empty
  `rawGrepInput`).
- AC-F5: the JSONL search log records `textSearchInput`, not `rawGrepInput`.
- AC-F6: the skill `get-raw-text-search` and its script `get_raw_text_search.py` exist;
  `get-raw-grep-result` and `get_raw_grep_result.py` are gone; the gate points at the new
  script; the skill's flags still fetch a captured raw result by pattern or hash.
- AC-F7: the framework test suite passes (`python3 -m pytest -q`).

**pi (pi-badger-integration)**

- AC-P1: a gate decision of "allow + additionalContext" does not block the tool call and
  the context reaches the model with `display: false` — the terminal shows no card.
- AC-P2: the per-prompt memory context (`mem-based-rag`) is injected with
  `display: false` — the agent still receives it, the user no longer sees the card.
- AC-P3: a deny decision still blocks, with the reason as the tool result (unchanged
  behaviour for hosts that cannot carry context).
- AC-P4: the pi test suite passes (`bun run test`) and `bun run typecheck` is clean.

## Non-goals

- The gate keeps its enforcement: a pattern is still searched in memory before the repo
  search runs, and the searched-pattern store is unchanged.
- The raw-output capture (the audit-database row the skill reads) is unchanged.
- No change to the per-prompt memory-context hook's own content or timing.
- No change to ai-raccoon's server, the bank, or the search pipeline.
