# ADR-0045 — The memory context never feeds itself, and the gate's result never speaks as the user

**Date:** 2026-10-20
**Status:** Accepted
**Extends:** [ADR-0017](0017-memory-first-gate.md) (the quiet memory-first gate) and
[ADR-0031](0031-per-prompt-memory-context-through-the-ai-raccoon-proxy.md) (per-prompt
memory context). Both stand; this ADR fixes where the model-side context is delivered and
what the prompt hook refuses to search.
**Supersedes:** nothing.

## Context

Two mechanisms deliver memory to a model, and they were allowed to collide.

The first is the **prompt hook** (`memory_context.py`): on every user prompt it searches
this project's memory bank and injects a block — `Memory context (ai-raccoon
memory_search, snippets — query: "…"):` plus the hits it found. The second is the
**memory-first gate** (`memory_first_gate.py`): on a text search whose patterns the project
has not memory-searched yet, it runs the search itself and hands the model the result as
`additionalContext` on the tool call's decision.

Both are model-side context, and both were supposed to be invisible to the user: the block is
a retrieval aid, not something the person said, and ADR-0017 says so in as many words — the
result is the agent's, not the user's.

Two things broke that.

**The hook searched its own block.** The hook's guard for harness-written turns is
`injected_turn()`: a prompt that starts with one of `INJECTED_PREFIXES` is never searched,
because a prompt the *harness* wrote must not send the hook looking for memory. The list
covered `<task-notification>`, `<agent-message from=…>`, `[SYSTEM NOTIFICATION …]` and the
rest — every *other* harness-written turn. It did not cover the hook's own block. A host that
renders injected context back into the conversation (pi does) therefore fed the hook its own
output: the hook read the identifiers inside the block it had just injected, searched memory
for them, and produced a new block whose query was the previous block's header. The block
re-entered, was searched, and the next block arrived. A live pi session recorded six
consecutive turns in which the person typed nothing and every turn was the previous turn's
block, one generation deeper.

**pi delivered the gate's context as a user turn.** The pi adapter sent the gate's
`additionalContext` with `pi.sendMessage(…, { deliverAs: "followUp" })`. In pi a follow-up
message is a user-role message: it occupies the channel the person's own words use, and it
starts another LLM call. The model was therefore told, in the user's voice, that a memory
result had arrived — and the session paid an extra model call for it. The adapter already
had the right channel and used it for post-hook context: the tool result. pi persists the
tool result and re-sends it on every later call, so context placed there is model-side,
stays in the transcript, and costs nothing.

## Decision

**1. The prompt hook never searches a turn that is its own block.** The block's header is
one constant, `BLOCK_HEADER`, and it is both the first line `format_block()` writes and an
entry in `INJECTED_PREFIXES`. One prefix covers both producers of the block: the prompt
hook's `format_block()` and the gate's `search_block()` render the same header, and the
gate's `context_text()` appends its `textSearchInput` to a block that already starts with
it. A turn that starts with that header is harness-written, and the hook stops there.

**2. The gate's model-side context rides the tool result.** In pi, the PreToolUse gate's
`additionalContext` is stashed against the call's `toolCallId` and delivered in the
`tool_result` seam, in front of the call's own output. No message is sent, so the user
channel stays the user's and no extra LLM call is made. A call the gate blocks stashes
nothing — a blocked call has no result, and nothing it carried may reach a later one. A
nested call (`<parent id>/<n>`, which pi never reports as its own result) travels with its
parent, and the store is bounded so a call whose result never arrives cannot grow it
without end.

**3. The guard stays one list.** `INJECTED_PREFIXES` remains the single place that says
"this turn is not a person's turn". A host that writes its own harness turns adds its
prefix there once; it does not grow a second, parallel mechanism.

## Alternatives considered

**Deliver the block as a user message.** Rejected: it makes the model's own retrieval look
like an instruction from the person, and it re-creates the extra LLM call this ADR removes.
The same objection applies to the gate's context, and is the reason for decision 2.

**Give the hook a "search only real prompts" flag instead of a prefix list.** Rejected: the
question is not "is this a real prompt" but "did the harness write it", and the answer is
per-shape, not per-flag. The prefix list already carries that judgement for the other
harness turns; a flag would duplicate it in a second place that cannot see the shapes.

**Have the gate remember the patterns it injected, so a repeat search is skipped.**
Rejected as the fix, and kept as a non-fix: the repeat was never the gate re-searching its
own patterns — the gate remembers what it searched, per project, and the log shows it did.
The repetition came from the *prompt hook* searching the block the gate and the hook had
already produced. Fixing the source of the block (decision 1) closes the loop; remembering
the injected identifiers would have hidden its symptoms.

**Let the tool result carry the context for every host.** Rejected: Claude and Copilot
already have a model-side context channel on the tool seam, and the adapter's change is
pi-specific on purpose. The framework-side fix (decision 1) is host-independent.

## Consequences

- A prompt hook that receives its own block as a prompt now searches nothing. The block
  stops being a source of new queries, and a session cannot be driven by its own memory
  context.
- pi's memory-first search no longer costs an extra model call, and the memory result
  arrives in the same turn as the search it belongs to, in front of that search's output.
- The memory result's place in the transcript is the tool result, not a message. A host
  that renders tool results differently from messages will show the difference; pi does not
  render either, and the memory context is agent-side by contract.
- A blocked tool call carries no memory result forward. If a gate wants to inform the model
  about a call it blocks, that information has to reach the model by another route.
- The prefix list grows by one entry. That is the whole maintenance cost, and it is the
  same cost every other harness-written turn already pays.

## Where the code lives

- `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` — `BLOCK_HEADER`,
  `INJECTED_PREFIXES`, `format_block()`.
- `features/pi/adjustments/adapter/hook-bridge.ts` — `takeGateContext()`,
  `withPreContext()`, `GATE_CONTEXT_MAX`.
- `features/pi/adjustments/adapter/index.ts` — the stash in the `tool_call` seam and the
  delivery in the `tool_result` seam.
- `tests/fixtures/memory_context/injected_turns.json` — the block as a harness-written
  turn, consumed by the injected-turn test.
- `features/pi/tests/adapter-memory-context.test.ts`,
  `features/pi/tests/hook-bridge.test.ts` — the delivery contract and the store's
  semantics.
