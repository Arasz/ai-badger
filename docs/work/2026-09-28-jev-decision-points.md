# Research: where a Jev "system one" call earns its place in ai-badger

**Date:** 2026-09-28
**Question:** Which ai-badger runtime decision points would a Jev (`typesafe/jev-1.13` on OpenRouter's alpha decisions endpoint) call serve better than their current mechanism, and at what latency, cost and accuracy?

```chart:range
title: seconds per classification call (this machine, 2026-09-28)
jev 8 options: 0.47..0.54..0.64
jev 30 options: 0.45..0.54..0.86
jev skill routing: 0.47..0.51..0.62
medium chat model: 0.67..1.02..4.80
```

## Findings

### F1 — A Jev choice call takes about half a second regardless of option count up to 30 [READ]

Ten sequential 8-option calls: min 0.473, median 0.536, max 0.644 s, all HTTP 200. Five
30-option calls with a ~1.9 KB task (7,002-byte payload): min 0.452, median 0.540, max 0.865 s.
Nearly four times the input tokens barely moved the median. This agrees with pi's
independent 2026-09-21 probe (0.47–0.89 s over 9 calls).

**Evidence:** Measured by a research lane in this session on Darwin 27.0.0 arm64 (MacBook Air),
2026-09-28 14:26 +0200, direct HTTPS, no proxy; raw per-call rows in the session scratchpad
`jev_results.json` (keys `A`, `B`, `summary`), spot-checked by the integrator. pi figure:
`pi-badger-integration/docs/work/2026-09-21-typesafe-jev-routing-tool-and-model-selection.md:26-30`.

### F2 — One call costs $0.00002–0.00009, and the cost is linear in input tokens [READ]

The response carries `usage.cost` directly. 8 options: 737 input / 85 output tokens, $3.10e-05.
30 options: 2,172 / 270 tokens, $9.12e-05. Skill routing with 6 options: about $2.2e-05. Pricing is
$0.042 per 1M prompt tokens; completion is free.

**Evidence:** `jev_results.json` `A[*].usage`, `B[*].usage`, `C.jev[*].usage`; pricing from
`pi-badger-integration/docs/work/2026-09-21-typesafe-jev-routing-tool-and-model-selection.md:34-36`.

### F3 — On a 10-prompt skill-routing smoke set, Jev matched the medium chat model's accuracy at half the latency [READ]

Ten hand-labelled prompts mapped to 6 ai-badger skills, using one-line descriptions as criteria.
Jev got 10/10, with confidence 1.0 on 9 prompts and 0.68 on one, and a 0.506 s median. The
medium-tier chat model (`deepseek/deepseek-v4.1-flash`, resolved from `model-groups.json`) also
got 10/10, with a 1.025 s median and a 4.80 s outlier.

Ten easy prompts cannot tell two good classifiers apart. This rules out "Jev can't route skills";
it does not show Jev routes better.

**Evidence:** `jev_results.json` `C.jev`, `C.chat`, `summary`. Same machine and conditions as F1.

### F4 — The medium chat model silently returns empty content when max_tokens is small [READ]

With `max_tokens=20`, all 10 chat answers came back empty. Hidden reasoning tokens used the whole
budget (completion_tokens = reasoning_tokens = 20). Jev has no such failure mode: its typed
`choice`/`confidence` answer is the output. This is a concrete reason to prefer Jev over a chat
call for classification in a hook, where an empty answer is indistinguishable from "no match".

**Evidence:** `jev_results.json` `note_max_tokens_fix`; lane report.

### F5 — The MCP tool recommender is the one decision point with a measured, structural error rate [READ]

`mcp-index` runs BM25 over name×3, tags×2 and intent×1, on every `UserPromptSubmit`. It fires when
query-term coverage is at least 0.20 and returns the top 3 tools. Its eval has 58 fixtures and a
26.7% false-fire rate. Sweeping all 343 field-weight combinations leaves that rate at exactly
0.2667. Only removing a field changes it: dropping tags lowers it to 0.200.

**Evidence:** `features/common/retrieval/mcp_matcher.py:24-46` (weights, threshold 0.20, TOP_N 3,
term cap 6); `docs/retrieval.md:282-290`; `docs/adr/0012-bm25-retrieval-with-a-falsifiable-eval.md:208`.

### F6 — This session's own hook output shows the false fires [READ]

On system-generated turns, the recommender suggested
`plugin:dotnet-msbuild:binlog:binlog_task_details` and `claude.ai Vercel:get_agent_run` for a
subagent task notification. It suggested `openrouter:list-task-classifications` and
`semantica:run_reasoning` for a subagent report. None of these fit a Python/Jev research turn. It
also fires on harness-injected text, which is not a user prompt at all.

**Evidence:** the `[ai-badger] Relevant MCP tools:` hook context injected on each turn of this
session, 2026-09-28.

### F7 — The MCP index holds 499 tools, above Jev's 255-option limit for one choice question [READ]

`.ai-badger/mcp-tools.json` lists 28 sources with 499 tools in total. pi records a 255-option
maximum per choice question, but also notes that a real 255-option catalogue was never sent.
One Jev question therefore cannot hold the catalogue. A Jev stage would re-rank a BM25 shortlist
(say the top 12–30) rather than replace retrieval.

**Evidence:** counted with `python3 -c` over `.ai-badger/mcp-tools.json` `sources[*].tools`;
`pi-badger-integration/extensions/decision-router/decision-router-client.ts:34-35`;
`pi-badger-integration/docs/work/2026-09-21-jev-decision-router-adr.md:175-176`.

### F8 — Multiplexed stack skills have no runtime router; the host model picks the member in context [READ]

`dotnet-workload` is a gateway with 11 members. Each member declares `triggers` in
`manifest.json`, but the only code that reads `triggers` is the structure lint. No hook or script
routes a prompt to a member. A Jev router here would be new behaviour, not a replacement, and it
competes with the host model's own choice. pi deliberately left its equivalent (skill routing) in
shadow mode as "least validated of the three".

**Evidence:** `features/dotnet/skills/dotnet-workload/manifest.json` (`members`, 11 entries);
`gates/skills_lint.py:192-196` (only `triggers` consumer outside tests);
`pi-badger-integration/extensions/decision-router/decision-router-core.ts:314-345` (route recorded,
never actuated); `pi-badger-integration/docs/work/2026-09-21-jev-decision-router-adr.md:139-164`.

### F9 — Prompt markers, the memory-first gate and the test-run classifier are exact-match rules with nothing for Jev to resolve [READ]

The prompt markers are a case-insensitive prefix match against 5 markers. The memory-first gate
matches command and tool names. The test-run classifier parses argv. All three are deterministic,
and none has an ambiguity or a measured error rate for Jev to improve.

**Evidence:** `features/common/skills/prompt-markers/scripts/user_prompt_hook.py:140-159`;
`features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py:77-115`;
`features/common/skills/test-economy/scripts/suite_economy.py:108`.

### F10 — Model-tier choice is made in prose by the calling model; the hook only checks that a model is named [READ]

`dispatch_gate_hook.py` denies any `Agent` dispatch that names no model; it does not choose a tier.
pi's decision router does make a tier call, gated asymmetrically: upgrade at confidence ≥ 0.6,
demote at ≥ 0.85. It was designed that way because Jev over-rated a mechanical rename as `medium`
(0.84) when `low` was intended.

**Evidence:** `features/common/skills/task/scripts/dispatch_gate_hook.py:118,212,229`;
`pi-badger-integration/extensions/decision-router/decision-router-core.ts:270-302`;
`pi-badger-integration/docs/work/2026-09-21-typesafe-jev-routing-tool-and-model-selection.md:50-54`.

### F11 — Jev scores relevance but cannot say "none of these answer it" [READ]

In pi's RAG research, Jev gave partial scores to structurally similar but wrong documents when
the bank had thin coverage. For tool recommendation, where the right answer is often "no tool",
this matters. A Jev stage needs an explicit "none" option or a confidence floor, and that
threshold has to be calibrated against the 15 negative fixtures in the existing eval.

**Evidence:** `pi-badger-integration/docs/work/2026-09-21-delegated-multi-query-rag-with-jev-selection.md` F11.

### F12 — The memory-context gate has no eval, so a Jev replacement could not be judged [READ]

`should_enrich` is a deterministic port of pi's gate (min 20 chars, min 6 content words, a noise
dictionary and control words). There is no fixture set for it, so neither the current gate nor a
Jev one has a measured error rate.

**Evidence:** `features/common/skills/ai-raccoon-memory/scripts/memory_context.py:61-117`; inventory
lane grep found no eval for it.

### F13 — The best first prototype is a Jev re-rank behind the mcp-index BM25 shortlist, judged by the existing eval [INFERRED]

This reasons from F5, F6, F7, F11 and F1–F2. It is the only decision point that has all three of:
a measured error, a ready falsifiable eval (58 fixtures plus the 70 hard and 48 long sets), and a
hook budget with room for a ~0.5 s call. Its false-fire rate cannot be tuned lower with the
current knobs.

The shape is: BM25 with a lowered threshold produces a shortlist of about 12–30, then one Jev
`choice` question over the shortlist plus a "none" option. The top 3 are kept above a confidence
floor. The prototype sits behind a flag and falls back to plain BM25 on any error, as pi does.
Roughly $0.00003–0.00009 and 0.5 s per prompt.

Skill routing (F8) and tier choice (F10) come second: neither has an eval here, and pi kept both
in shadow or asymmetric mode for good reason.

### F14 — The per-turn cost is negligible at session scale [INFERRED]

This reasons from F2. At about $0.00005 per call and one call per user prompt, 200 prompts a day
costs about $0.01. Latency (F1) is the real budget, not money.

### F15 — Behaviour under rate limits and data-retention terms are unknown [UNVERIFIED]

Neither pi nor this session probed sustained load, 429 behaviour or TypeSafe/OpenRouter's
retention terms. Every prompt would be sent to a third party on every turn.

## Still open

- Does a Jev re-rank lower the 26.7% false-fire rate on the existing 58-fixture eval without losing
  recall? This is the prototype's acceptance criterion. It is settled by running
  `features/common/retrieval/eval` with the Jev stage on and off.
- What shortlist size and confidence floor are right? The eval sweep above settles it, including a
  run at 60–100 options toward the untested 255 limit.
- Should the recommender skip non-user turns (task notifications, agent hand-backs)? F6 suggests
  yes, independent of Jev. It is cheap to test against a fixture of injected turns.
- Does Jev beat the host model at picking a `dotnet-workload` member? This needs a labelled
  prompt set for the 11 members, and nothing like it exists.
- Data-retention terms for sending every prompt to the decisions endpoint (F15). The privacy
  default decided for the RAG hook (on when a key exists) may not transfer to a per-turn classifier.
