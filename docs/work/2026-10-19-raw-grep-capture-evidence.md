# Research: asynchronous raw grep capture and retrieval

**Date:** 2026-10-19
**Question:** Can the memory-first hook remove the shell marker requirement while capturing first-sighting grep and `rg` output for immediate, short-lived retrieval?

## Findings

### F1 — Only denied first sightings start a detached capture [READ]

The gate checks whether patterns are unseen before starting capture, so already-credited searches are not replayed. The worker receives the parsed grep segment, uses the hook working directory, and starts detached from the tool call.

**Evidence:** `features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py:364-393`, `:672-696`.

### F2 — Raw results are bounded, checkout-scoped, and expire after 120 seconds [READ]

The worker retains at most 1 MiB from each output stream, stores results under a working-directory scope with an atomic claim, and removes the scoped row when retrieval finds it expired. POSIX timeouts kill the capture process group.

**Evidence:** `features/common/skills/get-raw-grep-result/scripts/get_raw_grep_result.py:19-167`; `engine/badger_store.py:1489-1515`.

### F3 — The hook-to-database retrieval path and Codex packaging pass the focused checks [MEASURED]

The final scoped run passed 235 tests, including an end-to-end hook launch followed by JSON retrieval from the same working directory, cross-directory isolation, expiry deletion, Codex plugin packaging, and the shared gate adapters.

**Evidence:** `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest -q tests/test_memory_first_gate_first_sighting.py tests/test_raw_grep_result.py tests/test_memory_first_gate_hermes.py tests/test_memory_first_gate_hook.py tests/test_memory_first_gate.py tests/test_memory_first_gate_post_hook.py tests/test_memory_first_gate_worktree.py tests/test_codex.py tests/test_adjust_hooks_copilot.py tests/test_badger_store_vendored.py` — 235 passed on the macOS worktree.

### F4 — The new behavioral assertions reject five targeted regressions [MEASURED]

An inline mutation harness changed detached launch, allowed-search replay, duplicate-pattern launch, output limit, and checkout-scoped storage one at a time. Each mutation made its targeted pytest fail; the harness restored the source after each run. A separate expiry mutation was observed directly: before the scoped-delete fix, `test_result_expires_at_120_seconds` failed because the scoped row remained in the database.

**Evidence:** Five mutation runs reported `KILLED`; `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest -q tests/test_raw_grep_result.py::test_result_expires_at_120_seconds` failed with an assertion that the scoped `hook_state` row was still present.

### F5 — Each host displays the retrieval instruction in the same way [UNVERIFIED]

The unit tests verify the host hook payloads and Codex packaging, but no live Claude, Copilot, or Hermes session was used to inspect how the denial reason is rendered to an agent.

## Still open

- Wait for the pull request CI gate to turn green before merging.
- Confirm the visible denial and hash rendering in live Claude, Copilot, and Hermes sessions if that host-specific presentation needs direct verification.
