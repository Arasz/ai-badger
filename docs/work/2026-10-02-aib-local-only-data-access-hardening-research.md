# Research: what data ai-badger sends off the machine, and local stand-ins for Jev

**Date:** 2026-10-02
**Task:** `aib-local-only-data-access-hardening`
**Question:** ai-badger has to work in a corporate environment that handles client data. The rule
there is that only the agent host's own approved model provider may receive data. Two things
follow from that question:
- Which ai-badger surfaces send prompts, code, memory or metadata anywhere else, and which of
  them are on by default?
- Is there a local or company-cloud replacement for the Jev classifier?

The grades used below:
- **READ**: someone saw the line.
- **MEASURED**: run on this machine.
- **INFERRED**: reasoned, not run.
- **UNVERIFIED**: not checked.

## Method

Two read-only lanes ran in isolated worktrees at `2955552e` (0.184.1):
- an egress inventory over `features/ engine/ tooling/ gates/`, classifying every
  `urlopen|http.client|requests.|fetch(|https?://` hit;
- a Hugging Face and web survey of local classifiers.

The integrator re-read the load-bearing lines and spot-checked the Hub claims.

## Findings: egress

### F1: The per-prompt memory-context pipeline reaches OpenRouter whenever `OPENROUTER_API_KEY` is set [READ]

`pipeline_for` (`features/common/skills/ai-raccoon-memory/scripts/memory_context.py:605-628`)
returns a pipeline when two things hold:
- `AI_BADGER_MEMORY_CONTEXT_PIPELINE` is not `"0"`;
- `openrouter_client.api_key(env)` finds a key (`openrouter_client.py:51-53`).

Key presence is the only enable. ADR-0031 D2 made that choice deliberately
(`docs/adr/0031-per-prompt-memory-context-through-the-ai-raccoon-proxy.md:127`). Each qualifying
prompt then leaves the machine twice:
- **Planner.** The full prompt plus the delegator persona goes to
  `https://openrouter.ai/api/v1/chat/completions`, using the medium-tier pin
  `openrouter/deepseek/deepseek-v4.1-flash` (`query_pipeline.py:410-414`;
  `features/common/data/model-groups.json:67`).
- **Scorer.** The prompt (≤32,000 chars) plus up to 48 memory and **source-code** excerpts of
  500 chars each go to `https://openrouter.ai/api/alpha/decisions`, using `typesafe/jev-1.13`
  (`query_pipeline.py:171-190,265-283,511`).

The hook is wired by default on Claude, Copilot and Hermes CLI
(`features/common/hooks/hooks-manifest.json:179-200`).

### F2: On this machine the key is set, so this session's own prompts qualified [MEASURED]

`OPENROUTER_API_KEY` is set (73 chars) in the shell that launched this session.
`AI_BADGER_MEMORY_CONTEXT` and `AI_BADGER_MEMORY_CONTEXT_PIPELINE` are both unset.

The hook also fires on harness-injected turns. A subagent hand-back produced a
`Memory context (ai-raccoon memory_search …)` block whose query was the subagent's report text.
Under F1, a turn like that is sent to the planner too. Whether a planner call actually went out
on that turn is INFERRED: the hook logs failures, not successes.

### F3: The Jev advisory in task-decomposition is already opt-in, but it forwards the OpenRouter key to any `AI_BADGER_JEV_ENDPOINT` [READ]

Both enable checks need literal `"1"` values:
- `tier_enabled` needs `AI_BADGER_JEV=1` and `AI_BADGER_JEV_TIER=1`;
- `waves_enabled` needs `AI_BADGER_JEV=1` and `AI_BADGER_JEV_WAVES=1`

(`features/common/skills/task-decomposition/scripts/jev_choice.py:284-291`).

`endpoint_url` (`:320-330`) needs the OpenRouter key before it will use *any* endpoint. The same
key is then sent as the Bearer token to whatever host `AI_BADGER_JEV_ENDPOINT` names. A
company-cloud or loopback decisions server therefore receives the user's OpenRouter credential.

### F4: The OpenRouter transport ignores proxy settings [READ]

`make_opener` builds `urllib.request.ProxyHandler({})` (`openrouter_client.py:261-266`). That
has two effects:
- on networks where the corporate proxy is the only way out, the calls fail;
- where direct egress exists, they bypass DLP inspection.

The two copies (`ai-raccoon-memory/scripts/` and `task-decomposition/scripts/`) are identical
apart from the one sanctioned env-name line.

### F5: The model registry can only hold OpenRouter ids, and pi routes `level:` through it [READ / INFERRED]

The registry pins every id to OpenRouter:
- `schemas/model-groups.schema.json:46` and `features/common/skills/task/scripts/model_groups.py:25`
  require `^openrouter/<vendor>/<name>$`.
- The registry's pins are DeepSeek, GLM, Xiaomi, OpenAI, Meta and Anthropic, all on OpenRouter.

On pi, `level:` reaches `.pi/agents/*.md` (`features/pi/adjustments/adjust_agents.py:30-34`).
The external pi-badger-integration extension resolves it through the registry (INFERRED).

On Claude, `level:` is stripped at delivery and `model` only accepts Anthropic aliases. A Claude
Code subagent therefore cannot be routed to OpenRouter (INFERRED from
`features/common/templates/delegation.md.tmpl:43`).

### F6: Every other egress surface is on demand or metadata-only [READ]

| Surface | What leaves | Default | Control |
|---|---|---|---|
| archify update check (`check-update.mjs:1347-1365`) | GET plus IP; no content | on, when the SKILL runs it | `ARCHIFY_UPDATE_CHECK_DISABLED=1` |
| archify brand capture (`brand-marks.mjs`) | the URL the author names | on demand | private addresses refused |
| archify rendered HTML (`assets/template.html:37-40`) | the viewer's IP to Google Fonts | on open | none |
| feed-badger `open_pr.py:228,240-245` | generalized files to the **public** `Arasz/ai-badger` | on demand | credential scan only |
| Playwright MCP (`features/common/stack-mcp.json:38`) | `npx @playwright/mcp@latest` from npm, then any site browsed | declared when `npx` exists | `config.mcp.decline` |
| Hermes MCP | messages to chat platforms | declared when `hermes` exists | `config.mcp.decline` |
| ai-raccoon `memory_sync` | memory snapshots to configured cloud storage | off unless configured | ai-raccoon config |

Three more points:
- The remote `openrouter` MCP (`mcp.openrouter.ai`) is **not** shipped. It appears in this repo's
  index only because the owner's host lists it (`host_listings.py:56-82`).
- The message bus, task tracking, the task-graph server, the BM25 recommender and ai-raccoon
  single-search are all local: SQLite, stdio and loopback.
- Internal egress of third-party binaries (ai-raccoon, semantica, code-review-graph) is
  UNVERIFIED.

### F7: Agent-facing text names third-party providers [READ]

- `features/pi/instructions/pi.instructions.md:52` lists OpenRouter as a provider.
- The pi and Hermes `stack.json` summaries list OpenRouter first.
- `features/common/mcp/ai-raccoon/server.md` says "no hit means search externally".

## Findings: local stand-ins for Jev

### F8: An Apache-2.0 open model family speaks Jev's wire format [READ]

`Mapika/decider-{0.8b,2b,4b,35b-a3b}` is fine-tuned from Qwen3.5. It is Apache-2.0, and the Hub
metadata was checked 2026-10-02. Its server takes `POST /v1/systemone` with
`{state, questions}`, using `choice`, `score` and `noul` question types, and answers
`answers.<name>.{choice, confidence, probabilities}`. That is the shape `jev_choice.py` and
`query_pipeline.py` already parse. Sources: `github.com/Mapika/decider` and the Hub cards. The
card states nothing was distilled from Jev.

### F9: On tool retrieval the 2B and 4B models are close to Jev; on broad reasoning they are well below it [READ]

Rows from the community *Jev Decision Index 0.2.1* (hf space `multimodalart/jev-decision-index`,
`data/index.json`). It uses one frozen 38-benchmark panel and was **timed on one RTX PRO 6000 GPU**.

| Entrant | Params | Decision Index | ToolRet nDCG@10 | CLINC+OOS F1 | ECE |
|---|---|---|---|---|---|
| Jev 1.13 (hosted) | n/a | 57.91 | 0.653 | 0.893 | 0.074 |
| pplx-decider-v1-27b | 26B | 56.40 | 0.674 | 0.878 | 0.018 |
| decider-4b v2.1 | 4.2B | 40.70 | 0.650 | 0.866 | 0.084 |
| decider-2b v11 | 1.9B | 28.97 | 0.631 | 0.737 | 0.077 |
| stock Qwen3-4B-Instruct + JSON | 4.0B | 28.42 | 0.603 | 0.417 | 0.371 |

What the table shows:
- A stock small instruct model with a JSON schema is badly calibrated as a classifier (ECE 0.37).
  So "any local chat model" is the weakest option for confidence-gated decisions (INFERRED from
  the table).
- Published laptop latency:
  - decider-2b runs at a 133 ms median on M1 Pro MPS;
  - the Q4_K_M GGUF takes 0.12–0.31 s for 40–120 tokens on 8 CPU threads;
  - decider-4b Q4_K_M takes 0.3–0.7 s on CPU.

  (READ, decider README and GGUF cards; Metal and CPU builds were not run over the card's
  regression set.)

### F10: Cross-encoder rerankers cover relevance scoring and tool re-ranking with threshold abstention [READ]

`ibm-granite/granite-embedding-reranker-english-r2` (150M, Apache-2.0, ModernBERT, `deploy:azure`)
was Hub-checked 2026-10-02. The same family's embedder already ships with ai-raccoon 1.54.0
(`granite-embedding-small-english-r2`, 97 MB fp16, measured from the installed manifest). The
alternative is `Alibaba-NLP/gte-reranker-modernbert-base` (Apache-2.0). Both serve through
Hugging Face Text Embeddings Inference (`/rerank`), which runs as a CPU image locally or as a
VNet container in a company cloud.

### F11: The memory pipeline has a generative planner that a classifier cannot replace [READ]

The planner writes 2–6 search queries. Its failure already falls back to a single local search
(ADR-0031 D2.4). The local options are:
- turn the planner off;
- run a small instruct model (Qwen3-4B-Instruct-2507, Apache-2.0) behind Ollama `format: <schema>`
  or vLLM structured outputs.

### F12: Licenses exclude some candidates [READ]

Three candidates are not cleared for commercial use:
- `jina-reranker-v2-base-multilingual` is CC-BY-NC;
- `kirp/jpt-4b` and `HopitAI/hopper-g` are non-commercial or "other";
- `katanemo/Arch-Router-1.5B` carries an "other" license that needs review.

## Still open

1. The decider wire compatibility has not been run against `jev_choice.py`. Two points are
   UNVERIFIED: whether the server ignores `model`, and the shape of its error envelope. Pass
   condition: `jev_choice.py --both` against a local `decider.serve`.
2. The tier (0.6) and wave (0.7) thresholds were tuned for Jev and need refitting per model.
   Neither job has a labelled set.
3. The MCP re-rank needs measuring. Pass condition: the false-fire rate on
   `features/common/retrieval/eval` falls below 0.200 (baseline 0.2667), with recall@3 not lower.
4. The memory pipeline has no eval (decision-points F12). Before a local scorer replaces Jev, it
   needs about 30 prompt→relevant-document pairs.
