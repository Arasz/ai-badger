# R4 — The Jev decision-mechanism contract for plan-time choices

**Method:** read-only over the worktree (`task/aib-task-decomposition-workflow-graph-mcp`, HEAD `f40d8240`) and the main checkout. No files written. Evidence labels: **MEASURED** (live probe with numbers), **READ** (source/doc), **INFERRED**, **UNVERIFIED**.
Path shorthands: `qp.py` = `features/common/skills/ai-raccoon-memory/scripts/query_pipeline.py`; `client.py` = same dir `openrouter_client.py`; `mc.py` = same dir `memory_context.py`; `dr-client.ts` / `dr-core.ts` = `/Users/arasz/RiderProjects/pi-badger-integration/extensions/decision-router/decision-router-client.ts` / `decision-router-core.ts`; `RES` = `/Users/arasz/RiderProjects/pi-badger-integration/docs/work/2026-09-21-typesafe-jev-routing-tool-and-model-selection.md`; `WP` = `/Users/arasz/RiderProjects/ai-badger/docs/work/2026-09-28-jev-decision-points.md`.

## 1. What Jev is today and exactly how the call is made

**1.1 Product vs. repo mechanism.** "Jev" is **TypeSafe Jev 1.13** (`typesafe/jev-1.13`), a third-party structured-decision ("system one") model reached through OpenRouter's alpha decisions endpoint — not this repo's own classifier. `POST https://openrouter.ai/api/alpha/decisions` with `{model, state, questions}` returned 200 on 9 live calls; `chat/completions` hard-refuses the model with HTTP 400 ("is a decisions model … use the /api/alpha/decisions endpoint instead") — **MEASURED**, `RES:14` (F1) and `RES:65-69` (F9: modality `text->decisions`, context 32k, and "does not write replies, produce code, or generate explanations of its reasoning"). This repo's half is a **port of pi's `jev-client.ts`** into three stdlib-only modules: `qp.py` (pure request/parse/retry), `client.py` (the one network surface), `mc.py` (Budget + env wiring). Its prompt strings, constants and wire bodies are pinned equal to pi's by `tests/test_memory_context_jev.py:89-101` (J1) and `:135-154` (J2).

**1.2 Transport.** Direct HTTPS, **no proxy** — the ai-raccoon proxy carries memory searches only; Jev and the planner go straight to OpenRouter. `client.py:19` `PRODUCTION_BASE = "https://openrouter.ai"`; `qp.py:174` `DECISIONS_PATH = "/api/alpha/decisions"`; `client.py:304-305` `post_json(url, body, key, budget)` POSTs JSON with `Authorization: Bearer <key>`, using one opener with `ProxyHandler({})`, `NoRedirect()`, a DNS-deadline resolver thread and a watchdog timer covering every byte (`client.py:202-221`, `client.py:304-322`). The call is wired only in `mc.py:605-627 pipeline_for()`: when `AI_BADGER_MEMORY_CONTEXT_PIPELINE == "0"`, or `client.api_key(env)` is `None`, or a sibling fails to load, the pipeline is never constructed and `query_pipeline.run()` is never called (`mc.py:612-616`; ADR-0031 D2.2). Per call it passes `functools.partial(stages.score, post=client.post_json, base=base, key=key)` (`mc.py:622-624`).

**1.3 Which model tier it uses.** Jev itself has **no tier** — the wire model is fixed: `qp.py:173 MODEL = "typesafe/jev-1.13"`, sent in every score body (`qp.py:510`). The *medium-tier* model in this pipeline is the **planner** (a normal chat call), resolved at `mc.py:583-594 planner_model()` via `model_groups.resolve(level="medium", …)`; the Jev scorer gets no resolver. So "Jev uses a model tier" is false; "the pipeline's planner uses the medium tier, and the classifier is a separate fixed model" is the accurate statement.

**1.4 Prompt shape.** Body: `{"model": MODEL, "state": state, "questions": questions}` (`qp.py:510`), where `state` is the raw prompt capped at `STATE_CHAR_CAP = 32000` (`qp.py:171`, `qp.py:507`). One question per candidate, named `c0..` in pool order (`qp.py:511-512`), each a `score` question:

```
qp.py:432-450  build_score_question:
  {"type": "score",
   "instructions": {"candidate": {"path": …, "kind": …, "excerpt": snippet[:500]},
                    "question": SCORE_QUESTION},
   "criteria": list(SCORE_CRITERIA)}
qp.py:175-176  SCORE_QUESTION = "How much does `candidate` help answer or implement the
               user's request in the state? Rate only this candidate."
qp.py:177-182  SCORE_CRITERIA = ("unrelated — it does not touch the request",
               "related background — same area, but answers none of the request",
               "partially answers — covers one need, misses the rest",
               "directly answers — a specific need in the request is answered or implemented")
```

The API also accepts `choice` (single winner + probabilities + confidence, ≤255 options) and `noul` questions, several fanned out per call (`RES:20-24`, F2) — but this repo's port implements **only `score`**: `_answer` rejects anything whose `type != "score"` (`qp.py:453-459`). Batching: ≤12 questions per HTTP call, each pool position keeps its `c{i}` name (`qp.py:168`, `qp.py:511-515`; tests J3 `:169-180`).

**1.5 Output contract and parsing.** Response `answers` maps each question name to `{"type":"score","score":n}`. `classify()` (`qp.py:461-481`) maps transport failure / non-200 statuses through `_STATUS_KINDS` (`qp.py:186`: 400 misrouted-refusal, 401 auth, 402 billing, 429 rate-limited, other non-200 server), rejects non-JSON/non-object bodies as `malformed`, and returns `Verdict("ok", {name: _answer(...)})`. `_answer` requires `type == "score"` **and** a finite numeric score, then clamps to `[0,3]` (`qp.py:453-459`); tolerance rows J8 (`:307-324`) show `4.2→3.0`, `-1→0.0`, `"2"`/`true`/`NaN`→`None`. Nothing in `plan`, `score` or `classify` raises (J4 `:203-221`), and error bodies/keys never surface (J9 `:326-335`).

**1.6 Timeout and retries.** `ATTEMPTS = 3`, `ATTEMPT_SECONDS = 15.0`, retryable kinds `("server","transport-timeout","malformed","rate-limited")`, non-retryable `("misrouted-refusal","auth","billing")` (`qp.py:169-170`, `qp.py:183-186`). Each attempt is `budget.child(ATTEMPT_SECONDS)` (`qp.py:490`), so it is also capped by the stage's share — the score stage is `Limits(90.0, 15.0, 15.0, 8.0)` seconds (`qp.py:207`; `mc.py:40-44`), and `mc.stage_limits()` scales it down when the total cannot hold a full planner + two searches + score (`mc.py:598-603`). Retries **do not sleep** and **ignore `Retry-After`** (test J5 `:238-247`) — a divergence from pi's 429→cooldown clamp (ADR R4, `dr-client.ts:21`). A failed batch nulls only its own entries; other batches survive (J7 `:294-304`).

**1.7 Fallback.** Missing/blank key or base, an empty pool, or an exhausted budget posts **nothing** and leaves every score `None` (`qp.py:503-505`; J6a `:273-287`). A Jev failure is deliberately **not** a pipeline fallback trigger: ADR-0031 D2.4 (`docs/adr/0031…md:141-146`) states the run still reports `("pipeline","ok")`, merged by ai-raccoon's server rank instead of Jev's score; only planner failure, an empty query set, or an empty pool trigger the one-shot single-search fallback. Key handling: `OPENROUTER_API_KEY` is read by `client.api_key` (`client.py:51-53`; listed in `mc.py:23-30 ENV_NAMES`), lives only in the `Authorization` header, and is stripped from the proxy child's env (`mc.py:331-334 child_env`). The test seam is `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE` + an `sk-test-` key that resolves **only** to `http://127.0.0.1:<port>`, else `None` (`client.py:20-21`, `client.py:56-67`).

## 2. The "JAV" reading — confirmed as Jev

**Confirmed: "JAV" is a misspelling of "Jev."** Evidence: (1) the project's own next-work pointer says "the Jev 'system one' exploration … where a TypeSafe Jev classifier call could replace or supplement ai-badger's decision points (mcp-index tool ranking, multiplexed stack skills, tier choice)" — `.ai-badger/state.json:3`; (2) `2026-09-28-jev-decision-points.md:3` names exactly this mechanism ("a Jev (`typesafe/jev-1.13` on OpenRouter's alpha decisions endpoint) call"); (3) no `JAV`/`Jav` identifier exists anywhere in the repo (case-sensitive grep over the checkout: no matches). The requester's sentence — "for choices (what model use, can be done in parallel etc) we could use JAV with correctly defined prompt" — maps cleanly onto Jev's `choice` primitive. Best alternative if that is ever refuted: a phonetic typo for the **TypeSafe Jev** brand itself (the `choice` endpoint is the only "correctly defined prompt" classifier in this stack); nothing else in the repo answers to those letters. **Confidence: high, but the confirmation is INFERRED from project context, not from the requester's own text.**

## 3. Decision (a) — step → model tier

**What the Jev call adds beyond direct `effort` mapping: nothing when the step declares a tier.** The plan-time step already carries the answer: `.ai-badger/skills/task/SKILL.md:134-139` — "`effort` (low/high) picks the loop; `level` picks the model tier"; `level` is resolved deterministically to the registry's preferred pin by `model_groups.resolve(level=…)` (`skills/task/scripts/model_groups.py:5`, `.ai-badger/model-groups.json`), and an explicit `model` always wins. `delegation.md:42-47` already defines the three levels ("high — the answer must be *derived*; medium — *determined by a spec that already exists*; low — a *transformation with no judgment*"). pi's own probe measured a **tier misclassification** (a rename the rubric called `low` came back `medium` at 0.84 — `RES:50-54`, F7), which is why pi kept tier actuation asymmetric and demotion gated (`dr-core.ts:276-302`; `RES:81-83`). **Forced judgment below: replace with direct mapping.** The prompt below is the design for the one residual case where **no tier is declared** — the dispatch gate today only checks that *some* model is named (`skills/task/scripts/dispatch_gate_hook.py:2`, `:16-21`; WP F10 `:113-122`) — and even there it is advisory-only.

**Prompt (one `choice` question over the frozen three levels, criteria reused verbatim from `dr-client.ts:49-56`):**

```json
{
  "model": "typesafe/jev-1.13",
  "state": {
    "step": {
      "id": "P2",
      "goal": "<one-line outcome>",
      "instructions": "<what the plan says to do>",
      "acceptance_criteria": ["<checkable AC>", "..."],
      "declared_effort": "medium",
      "files": ["<touched paths>"],
      "verifier": "<command or check that decides the step>"
    }
  },
  "questions": {
    "tier": {
      "type": "choice",
      "instructions": "Which model tier is sufficient to implement this step as specified? Judge the derivation the step demands, not its size.",
      "criteria": {
        "low": "Mechanical, single-file or rename-level change",
        "medium": "Multi-file change needing judgement",
        "high": "Design, debugging, architecture"
      }
    }
  }
}
```

**Output schema:** `answers.tier = {"type":"choice","choice":"low|medium|high","probabilities":{"low":p,"medium":p,"high":p},"confidence":c}` in `[0,1]`.
**Validation (fail-closed; port `dr-client.ts:214-276` into Python):** reject non-object / `type != "choice"` / winner not one of the three criteria keys (`unknown-choice`) / missing winner probability; missing or NaN confidence → `0`; missing probabilities → winner-only with confidence `0`; clamp every probability into `[0,1]`; ignore unknown fields; never raise. **Gate:** a `high` answer at confidence ≥ `0.6` may *propose* an upgrade (`dr-client.ts:21`); a `low` answer **never demotes** a declared tier and is recorded as a disagreement with the planner; `medium` holds; a step that declares `level`/`model` is never overridden. **Fallback:** no key, timeout, malformed, unknown choice, or below gate → the plan's declared `level`/`effort` mapping, or the medium pin when neither exists. The call is one extra question in the *same* fanned-out Jev call that would carry (b) — no additional latency.

## 4. Decision (b) — parallelizability / wave membership

**The dependency edges alone derive readiness; they do not derive safe concurrency, and Jev does not supply the missing fact either.** Readiness is deterministic: a step is in the next wave iff every dependency edge points at a completed step. The missing fact is resource conflict, and this repo's rule already answers it without a classifier: "Lanes running at the same time need their own tree, not just their own files" (`.ai-badger/delegation.md:29-33`), and "disjoint files are not isolation — shared build output means a green run proves nothing" (`skills/task/SKILL.md:143-147`, `references/prompting-rules.md:36-41`). Given a worktree per lane, the whole DAG-ready set is dispatchable as one wave; what remains is *external* shared resources worktrees do not isolate (ports, a shared test DB, a service, a generated artifact outside the tree). A Jev call could rank those risk pairs, but there is no fixture set to calibrate it — WP F12 (`:133-140`) shows exactly what an eval-less gate looks like. **Forced judgment below: derive waves from the DAG + isolation capability; Jev is unnecessary.** The prompt is designed only for the residual shadow/advisory conflict hint, never as the wave gate.

**Prompt (one pairwise `choice` question per ready pair, all in one call):**

```json
{
  "model": "typesafe/jev-1.13",
  "state": {
    "steps": [
      {"id": "P2", "goal": "...", "instructions": "...", "files": ["..."], "runs": ["<command/services/ports>"]},
      {"id": "P3", "goal": "...", "instructions": "...", "files": ["..."], "runs": ["..."]}
    ],
    "done": ["P1"],
    "edges": [["P1","P2"],["P1","P3"]]
  },
  "questions": {
    "P2_P3": {
      "type": "choice",
      "instructions": "Both steps are ready (their dependencies are done). May they run as concurrent lanes in this wave, each in its own worktree?",
      "criteria": {
        "share-wave": "No shared writable external resource: no shared port, service, database, lockfile, generated artifact outside the tree, or ordered output contract between the two — concurrency cannot invalidate either lane's green run",
        "serialize": "Any shared writable external resource, ordered output contract, or race between the two — run them in separate waves, dependencies first"
      }
    }
  }
}
```

**Output schema:** same choice shape per pair, names `{id_i}_{id_j}`. **Validation:** winner must be a criteria key; missing/invalid → `serialize`; confidence below the activation gate (use pi's `0.7`, `dr-client.ts:20`) → `serialize`; a pair admits concurrency only on `share-wave` at ≥ gate. **Fallback:** no key/timeout/malformed → **serialize** (one step per wave) — the safe direction, because a wrong parallel dispatch corrupts green runs while a wrong serialization only costs time. Question count is N(N−1)/2: cap the ready set at ~10 per call (45 questions) and chunk above it; the 255-option cap applies per question, not per call.

## 5. Where the calls live in the target Python stdio MCP server

**Packaging.** A new local stdio MCP server in this framework is declared in `features/common/stack-mcp.json` (shape: `{"name", "command", "declare": true, "availability": {"command": …}}`, e.g. `ai-raccoon` at `stack-mcp.json:16-23`) with a `features/common/mcp/<name>/{meta.json,server.md,tools.json}` packet (existing examples: `features/common/mcp/ai-raccoon/`). The Jev call belongs in the **plan-tool handler** that emits waves, not in a per-prompt hook — MCP tools run on demand and are not bound by the hosts' 30 s `UserPromptSubmit` deadline that forced the 90 s/25 s pipeline budgets (ADR-0031 Context, `:37-45`).

**What to reuse vs. what is coupled.**

| Part | Location | Verdict |
|---|---|---|
| `post_json`, deadline opener, `Reply` | `client.py:19-322` | **Reuse as-is** (copy byte-identical, the repo's vendoring discipline — ADR-0009 precedent, `badger_store.py` duplicated per skill) |
| `Budget`/`child` | `memory_context.py:284-302` | **Reuse** (stdlib, ~20 lines) |
| `classify` status mapping, `ERROR_KINDS`, retry loop, no-raise contract | `qp.py:183-186`, `:461-496` | **Reuse shape**, but the parser must be extended |
| `build_score_question`, `score`, `make_pool`, `merge_select` | `qp.py:432-516`, `:529-560` | **Coupled to the memory pipeline** — pool positions, `c{i}` names, hit fields (`path`/`kind`/`snippet`/`hash`), score-only answers, merge slots. Do not reuse; copy only the one-line-per-question builder idiom |
| `choice` parsing (winner, probabilities, confidence, 255 options) | `dr-client.ts:214-276`, `:49-56` | **Missing here entirely** — the port to Python is the one new classifier piece (ai-badger cannot even parse a `choice` answer today, `qp.py:453-459`) |

**Key handling.** Read `OPENROUTER_API_KEY` from the server process env only (same name everywhere: `client.py:52`, `mc.py:29`, `dr-client.ts:43`); never log it; never write it to disk (`.ai-badger/invariants/no-hardcoded-secrets.md`). Keep the ai-raccoon proxy key-free (`mc.py:331-334`); an OpenRouter-directed MCP server needs no identity proof because it never touches ai-raccoon's token. Give the new server its own test seam in the `sk-test-` + loopback style (`client.py:20-21`, `:56-67`) — do not reuse the memory-context env name. Proposed names (nothing implemented): `AI_BADGER_JEV_MODEL`, `AI_BADGER_JEV_ENDPOINT`, `AI_BADGER_JEV_TIMEOUT_MS` (mirroring `dr-client.ts:44-46`), kill switch `AI_BADGER_JEV=0`, test base `AI_BADGER_JEV_TEST_OPENROUTER_BASE`.

**Cost/latency envelope.** ~0.47–0.89 s per call, median ~0.51–0.54 s, nearly flat from 8 to 30 options (**MEASURED**, WP F1 `:16-25`; pi's independent probe 0.47–0.89 s, `RES:39-43`); $0.00002–$0.00009 per call, priced $0.042/1M prompt with free completion, linear in input (**MEASURED**, WP F2 `:28-35`; `RES:45-47`). At session scale this is negligible (~$0.01 per 200 calls, WP F14 `:157-161`); latency is the budget. One fanned-out call carrying (a)+(b) costs one round trip; budget it like the score stage: per-attempt cap ~8–15 s, stage share ≤ the plan tool's own deadline, one retry at most, fail-open. **UNVERIFIED:** sustained-load 429/402 behaviour and TypeSafe/OpenRouter retention terms (WP F15 `:162-168`, `RES:93-96`) — every step's goal/AC text would leave the machine.

## 6. "Correctly defined prompt" principles for these calls (5 bullets max)

1. **One-turn specification** — state, question, criteria and schema go out together in the single call; the operative ask is last. Highest-ranked lever (multi-turn loss), `references/prompting-rules.md:16-18`, `docs/research/prompt-eng/prompt-rules-ranking-framework-plan.md:11`.
2. **Tool schema + success criteria beat persona** — spend tokens on option definitions, confidence gates and validation, not role prose; Jev is a system-one model that "does not write replies … or explanations" (`RES:65-69`), so persona text cannot help. Rank 4, same plan `:14`.
3. **Positive constraints + machine validation** — every criterion defines an option positively; every returned answer is checked by a fail-closed parser rather than trusted (rank 8; pattern: `dr-client.ts:214-276`).
4. **Final output schema separation** — the machine-checkable schema is carried by typed `criteria` keys and validated after the call; never infer a decision from prose (rank 7).
5. **Few-shot only for format; length is a cost center** — the measured prompts are one question line + 3–4 criteria lines, no examples; each added rule compounds non-compliance (rank 9 and prompting rule 10, `prompting-rules.md:44-46`).

## Forced judgments

**(a) Step → model tier: replace the Jev call with the direct `effort`/`level` mapping** — the step already declares its tier and `model_groups.resolve` flips it deterministically, while Jev measurably mislabels its own rubric (`RES` F7) and adds ~0.5 s plus a third-party call for a value that cannot be demoted anyway; keep the prompt only as an advisory upgrade proposal for steps that declare no tier.

**(b) Parallelizability: derive waves from the dependency DAG plus the per-lane isolation capability; the Jev call is not needed** — readiness is deterministic graph traversal and resource safety is answered by "its own worktree" (`delegation.md:29`) plus the plan's declared external resources, so a probabilistic conflict classifier with no fixture set would only add a failure mode where a serialization default is already safe.