# Semantica Integration Plan — Architecture Review

**Date:** 2026-08-12  
**Reviewer:** Architect subagent  
**Sources:** Plan (`2026-08-12-semantica-integration-plan.md`), Evidence review (`2026-08-12-semantica-integration-review.md`), reference patterns (`code-review-graph/meta.json`, `code-review-graph/server.md`, `ai-raccoon-memory/SKILL.md`, `stack-mcp.json`, `mcp-tags.json`, schemas)

## Recommendation: APPROVE-WITH-FIXES

The plan is well-structured, follows ai-badger catalog conventions correctly, and has a solid TDD approach with clear acceptance criteria per lane. However, it has one critical honesty gap (broken tool presented as working), a fatally incomplete persistence story (export without import), and several understated risks that need attention before execution. All fixable — none are architectural blockers.

---

## Findings

### Finding 1 — CRITICAL: `get_graph_analytics` is broken but presented as working

**Severity:** CRITICAL  
**Section:** 1.3 (tools.json), table row 12

The evidence review dogfooded all 12 tools against the live MCP server (v0.6.5) and found:

```
get_graph_analytics | BROKEN | PageRank calculation failed: 'dict' object is not callable — Python API mismatch in semantica 0.6.5
```

Yet the plan lists `get_graph_analytics` in tools.json with `["diagnostic", "read"]` tags and no qualification. The risk register (Section 7) has no entry for this. Agents will call this tool, get a Python traceback, and lose trust in the catalog.

**Fix (choose one):**
- **Option A (preferred):** Remove `get_graph_analytics` from tools.json. It's better to have 11 honest tools than 12 with one broken. Re-add when semantica fixes the bug.
- **Option B:** Keep it in tools.json but add a `"notes"` field (if the schema supports it) or document the known bug in the skill's gotchas with explicit guidance: "`get_graph_analytics` is known to throw on semantica 0.6.5 — avoid until upgraded."
- If keeping: add a risk to the register: "`get_graph_analytics` throws `PageRank calculation failed` — known semantica 0.6.5 bug" (Likelihood: Certain, Impact: Low since it's a diagnostic tool).

Additionally, the tool count in acceptance criteria (1.3) says "All 12 tools present" — this should change to 11 if Option A is chosen.

---

### Finding 2 — CRITICAL: Export has no corresponding import — persistence story is a dead end

**Severity:** CRITICAL  
**Section:** 2.1 (skill gotcha), Section 7 (risk #2)

The plan handles statelessness by recommending `export_graph(format="json")` at session end. But there is no `import_graph` tool in Semantica's MCP surface. The exported JSON artifact cannot be restored. This makes the persistence story a one-way trip — you can save but you can never resume.

The evidence review confirmed this gap implicitly:
> "The MCP server as designed is a thin wrapper over in-memory ContextGraph — useful for one-shot extraction/recording, not for building a persistent knowledge base across sessions."

**Implications:**
- Risk #2 ("In-memory graph store limits utility") is rated Impact: Medium but should be Impact: High. The graph is genuinely ephemeral — no round-trip exists.
- The dogfooding Scenario 5 ("Graph persistence across sessions") is misleading — it says "Note: In-memory limitation means the exported artifact is the session's deliverable" but doesn't mention there's no way to use that deliverable.
- The skill's gotcha says "Export the graph before ending a session if persistence matters" — this implies the export is useful, but without import it's an archival dead end.

**Fix:**
- Re-rate Risk #2 to Impact: High.
- Reword the skill's gotcha: "The graph is session-scoped and ephemeral — there is no import mechanism. `export_graph` produces an archival snapshot only; it cannot be re-loaded into a future session. For durable facts, write to AiRaccoon memory (`memory_write`); use Semantica for session-scoped reasoning and export for audit trails."
- Add to the risk register: "No graph import mechanism — exported graphs cannot be re-loaded" (Likelihood: Certain, Impact: Medium).
- Note this as an explicit non-goal for v0.116.3 in the "Nice to have" section.

---

### Finding 3 — HIGH: Compound state accumulation not verified

**Severity:** HIGH  
**Section:** 6.2 (Dogfooding scenarios), evidence review finding

The evidence review tested each of the 12 tools independently against a fresh MCP server. No compound scenario tested whether state accumulates across calls within a session: `add_entity → get_graph_summary → verify entity count incremented`. The dogfooding plan (Scenarios 1-5) assumes this works but never verifies it.

The evidence review's "stateless per invocation" language is ambiguous:
> "Each `python -m semantica.mcp_server` spawns a new process with a fresh in-memory graph. Entities/decisions/relationships added in one call do NOT persist to the next."

If this means "each tool call spawns a new process," then the entire integration is broken — you can never build up graph state. But in standard MCP (stdio transport), the server process starts once and handles many requests. The evidence review likely means "each server process" not "each tool call."

**Fix:**
- Add a compound test to the dogfooding plan BEFORE Scenario 1: "Scenario 0: State accumulation — call `add_entity('test')` then `get_graph_summary`; verify node_count increases. If node_count stays at 0, the MCP server is truly per-call stateless and the entire integration approach must change."
- Run this test against the live server before committing any catalog files. If accumulation fails, the skill must recommend batching: do all graph operations in a single compound MCP call or switch to the CLI.
- Add this risk to the register: "State may not accumulate across MCP calls — unverified" (Likelihood: Low, Impact: Critical).

---

### Finding 4 — HIGH: Extraction degradation specifics are wrong

**Severity:** HIGH  
**Section:** 2.1 (skill gotchas), evidence review

The plan's gotcha says:
> "Entity extraction may require an LLM provider; check `semantica doctor` if extraction tools return errors."

The evidence review found the actual dependency is **torch/transformers**, not an LLM provider:
> "Without torch, transformers, and gensim (which fails to build on Python 3.14), the NER/relation extraction returns minimal labels."

- `extract_entities`: returns entity types (PERSON, ORG) without names
- `extract_relations`: returns empty

The gotcha's "LLM provider" language will send agents looking for API keys that don't exist. The real fix is `pip install torch transformers` — but gensim won't build on Python 3.14.

**Fix:**
- Reword: "`extract_entities` and `extract_relations` need torch and transformers for full NLP. Without them: `extract_entities` returns entity types without names; `extract_relations` returns empty. Install with `pip install torch transformers`. Note: gensim (a transitive dep) fails on Python 3.14 — extraction still works without it but may be further degraded."
- Add a risk: "Extraction tools degraded without torch/transformers; gensim fails on Python 3.14" (Likelihood: Medium, Impact: Medium).

---

### Finding 5 — MEDIUM: server.md likely exceeds 500-char budget

**Severity:** MEDIUM  
**Section:** 1.2 (server.md), acceptance criteria

The proposed server.md text is approximately 530-550 characters (including markup), but the acceptance criterion says "Under 500 chars." The code-review-graph server.md is 443 chars.

**Fix:**
- Either trim the text to fit 500 chars, or adjust the budget to 600 chars. Suggested trim: remove "The graph is in-memory — record decisions, entities, and relationships as you work; they persist for the session." (the in-memory limitation belongs in the skill gotchas, not the agent-facing instruction snippet).
- If trimmed, verify against the 17,500-char `agentDocs` budget in config.json.

---

### Finding 6 — MEDIUM: `add_relationship` parameter names don't match schema

**Severity:** MEDIUM  
**Section:** 2.1 (skill workflows), evidence review finding

The evidence review found:
> "`add_relationship` — Uses `source`/`target` not `source_id`/`target_id` as schema says"

The plan's tools.json uses curated intents (not raw descriptions), so this is fine for the catalog. But the SKILL.md workflows show example calls like `add_entity` without arguments — when they show arguments for `add_relationship`, they should use the real parameter names (`source`/`target`) so agents don't get runtime errors.

**Fix:**
- In the SKILL.md workflow section, when providing argument guidance for `add_relationship`, use `source`/`target` (the actual parameter names), not `source_id`/`target_id`. Add a gotcha: "`add_relationship` uses `source`/`target` parameter names, not `source_id`/`target_id` — contrary to what the schema may claim."
- Verify this with a live call during dogfooding.

---

### Finding 7 — MEDIUM: Lane A serialization is overly constrained

**Severity:** MEDIUM  
**Section:** 5 (Integration Order), Lane A description

The plan says:
> "Lane A (catalog entry) — serial: meta.json → tools.json → stack-mcp.json"

But `tools.json` does not depend on `meta.json` at write time — they're independent files in the same directory. `stack-mcp.json` does not depend on either — it just needs the directory name to match. All three can be written in parallel; only `index_build.py --check` needs them all present.

The plan's "must serialize" rationale says:
> "`tools.json` after `meta.json` within Lane A (the `server` field in tools.json references the server name)"

The `server` field in tools.json is `"semantica"` — a literal string, not derived from meta.json's `name`. No dependency exists.

**Fix:**
- Remove the serial constraint within Lane A. All three files can be written in any order or in parallel. Keep the Integration Gate serial after all lanes merge — that's where the real dependency is.
- This doesn't block execution but wastes parallelism.

---

### Finding 8 — LOW: Skill "When NOT to Use" guard is slightly imprecise

**Severity:** LOW  
**Section:** 2.1 (When NOT to Use)

> "A one-off lookup 'is this connected to that?' — use `memory_search` (AiRaccoon)"

AiRaccoon's `memory_search` does semantic recall over indexed documents — it won't answer "is X connected to Y" unless someone previously wrote that relationship fact to memory. The guard implies AiRaccoon can answer relationship questions it can't.

**Fix (suggested):**
> "A one-off lookup where the answer already exists in indexed docs — use `memory_search` (AiRaccoon) first. Don't build graph nodes for trivia or facts you won't query again. The graph is for active reasoning — entity extraction from new text, causal tracing of decisions, or recording structure you'll query later in the session."

---

### Finding 9 — LOW: `batch` tag placement is correct but worth documenting

**Severity:** LOW  
**Section:** 1.3 (tools.json tags)

`run_reasoning` is tagged `["run", "batch"]`. The `batch` tag is in the `meta` category of `mcp-tags.json` — it describes tools suitable for parallel/bulk dispatch ("non-functional characteristics that affect tool selection strategy"). This is correct: `run_reasoning` processes IF/THEN rules in bulk. The existing ai-raccoon tools.json uses `batch` the same way (e.g., `memory_ingest_file` → `["write", "files", "batch"]`). No fix needed — documenting for completeness.

---

## Statelessness Verdict

**The plan is honest about the in-memory limitation but understates its consequences.**

What the plan says correctly:
- The graph is in-memory and does not survive session restarts (skill gotchas)
- `export_graph` is recommended for persistence (skill workflow)
- The in-memory limitation is a registered risk (Risk #2)

What the plan misses:
- **No import mechanism exists** — export produces an artifact you can never re-load (Finding 2). This makes the persistence story hollow. Without import, the graph is genuinely ephemeral — useful within one session, useless across sessions. The skill should direct durable facts to AiRaccoon and position Semantica as a session-scoped reasoning tool.
- **State accumulation is unverified** — we don't know if state accumulates across MCP calls within a session (Finding 3). If it doesn't, the entire approach fails.
- **Impact underrated** — Risk #2 is rated Impact: Medium but should be High given the missing import mechanism.

**Bottom line:** The plan is honest about WHAT the limitation is, but soft-pedals what it MEANS. An agent reading the gotchas will think "I'll just export at the end" — not realizing the export is an archival dead end. The skill must clearly position Semantica as session-scoped only and direct durable state to AiRaccoon.

---

## Assessment against ai-badger conventions

| Convention | Status |
|---|---|
| Catalog entry pattern (meta.json, server.md, tools.json) | ✅ Follows code-review-graph pattern correctly |
| stack-mcp.json wiring | ✅ Schema-valid, correct `declare`/`command`/`availability` |
| SKILL.md structure | ✅ Matches ai-raccoon-memory pattern (frontmatter, When NOT to Use, workflows, gotchas, checklist) |
| TDD approach | ✅ RED-GREEN cycle documented, tests named before files exist |
| Tag vocabulary | ✅ All tags drawn from `mcp-tags.json` closed set |
| Schema validation | ✅ Both schemas referenced with correct relative paths |
| VERSION + changelog | ✅ Semver patch bump, changelog format matches convention |
| Integration gate | ✅ `index_build.py --check` → `pytest` → `pylint` in correct order |

---

## Summary

| # | Severity | Finding | Action |
|---|---|---|---|
| 1 | CRITICAL | `get_graph_analytics` is broken but presented as working | Remove from tools.json or document as known-broken |
| 2 | CRITICAL | Export has no import — persistence story is a dead end | Re-rate risk, reword gotcha, note as non-goal |
| 3 | HIGH | Compound state accumulation not verified | Add Scenario 0 to dogfooding before any file creation |
| 4 | HIGH | Extraction degradation specifics are wrong | Fix gotcha to name torch/transformers, not LLM provider |
| 5 | MEDIUM | server.md likely exceeds 500-char budget | Trim or adjust budget |
| 6 | MEDIUM | `add_relationship` param names differ from schema | Use real param names in SKILL.md guidance |
| 7 | MEDIUM | Lane A serialization is overly constrained | Allow parallel writes within Lane A |
| 8 | LOW | "When NOT to Use" guard slightly imprecise | Sharpen the guard language |
| 9 | LOW | `batch` tag placement correct (documentation note) | No action needed |

**Execution gate:** Fix findings 1-4 before creating catalog files. Findings 5-7 can be fixed during implementation. Findings 8-9 are optional polish.
