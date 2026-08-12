# Semantica Integration — MoE Review Synthesis

**Date:** 2026-08-12
**Reviewers:** Architect + Test-engineer (parallel MoE)
**Combined verdict:** APPROVE-WITH-FIXES

## Combined findings: 11 actionable, 7 informational

### Pre-execution blockers (must fix before creating files):

| # | Finding | Source | Action |
|---|---|---|---|
| 1 | `get_graph_analytics` is BROKEN in v0.6.5 | Arch F1 | Remove from tools.json; present 11 honest tools, not 12 with one broken |
| 2 | Export has no import — persistence dead-end | Arch F2 | Rewrite gotcha: graph is session-scoped only; export is archival snapshot; durable facts → AiRaccoon |
| 3 | State accumulation unverified (Scenario 0) | Arch F3 | Run compound test BEFORE catalog creation: add_entity → get_graph_summary → verify count increments |
| 4 | Extraction degradation misattributed | Arch F4 | Gotcha: "torch/transformers" not "LLM provider" |
| 5 | RED-GREEN cycle unenforceable | Test 2.1 | Commit test files first (witnessed RED), then production files (GREEN) |
| 6 | No "can fail" sensitivity tests | Test 3.1 | Add at least one sensitivity test per test file |
| 7 | No `validate.py --all` in gate chain | Test 3.2 | Add to integration gate and as a test |
| 8 | Dogfooding Scenario 2 impossible (stateless) | Test 5.1 | Replace with: "record chained decisions in single MCP call, query causal chain, then verify empty in new session" |
| 9 | `add_relationship` param names differ | Arch F6 | Use `source`/`target` in skill guidance, add gotcha |

### During-implementation fixes:

| # | Finding | Action |
|---|---|---|
| 10 | server.md likely over 500 chars | Trim to fit; remove in-memory sentence (belongs in skill gotchas) |
| 11 | Lane A serialization is artificial | meta.json, tools.json, server.md can be written in parallel |

### Informational (no action required / deferred):

| # | Finding |
|---|---|
| 12 | Skills_lint duplication (Test 1.1) — split tests into "gate-proven" (skip) and "author intent" (keep) |
| 13 | Manual acceptance criteria unmarked (Test 1.3) — note which are manual vs automated |
| 14 | Index discovery tests don't assert entry shape (Test 3.3) |
| 15 | No error-recovery dogfooding scenario (Test 5.2) |
| 16 | Dogfooding success criteria vague (Test 5.3) |
| 17 | Tool-name reference test fragile (Test 6.2) |

## Adjusted plan outline

The original plan (Section 1-8) remains valid with these adjustments:

### Section 1 (Catalog Entry) changes:
- **tools.json**: 11 tools, not 12. Remove `get_graph_analytics`.
- **server.md**: Trim to ≤500 chars. Remove in-memory sentence.
- **stack-mcp.json**: No changes.

### Section 2 (Skill) changes:
- Gotcha 1: "Graph is session-scoped and ephemeral — no import mechanism. Export produces archival snapshot only. Durable facts → AiRaccoon memory_write."
- Gotcha 2: "extract_entities/relations need torch and transformers for full NLP. Without them: entities return types without names; relations return empty."
- Gotcha 3 (new): "add_relationship uses source/target parameter names, not source_id/target_id."
- When NOT to Use: Sharpen — don't claim AiRaccoon answers relationship questions.

### Section 3 (Testing) changes:
- Add `test_catalog_can_fail` class with 2+ sensitivity tests
- Add `test_skill_can_fail` class with 2+ sensitivity tests
- Add `test_semantica_catalog_validation_remains_green` (runs validate.py --all)
- Document which tests are "gate-proven" (delegate to existing gates) vs "author intent"
- Gate chain: index_build --check → validate.py --all → pytest -q → pylint

### Section 5 (Integration Order) changes:
- Lane A files can be written in parallel (no serial dependency)
- Lane C (tests) committed and RED-witnessed before Lanes A+B

### Section 6 (Dogfooding) changes:
- ADD Scenario 0: "State accumulation — add_entity then get_graph_summary, verify count increases."
- REPLACE Scenario 2: "Record 2+ chained decisions in single MCP call, query causal chain, verify — then start new session and verify graph is empty."
- ADD Scenario 6: "Error recovery — call get_graph_analytics (if kept) or a missing tool, verify skill guides recovery."

### Section 7 (Risk Register) additions:
- "get_graph_analytics throws PageRank error on 0.6.5" — Likelihood: Certain, Impact: Low
- "No graph import mechanism" — Likelihood: Certain, Impact: Medium
- "State accumulation unverified" — Likelihood: Low, Impact: Critical
- "Extraction degraded without torch/transformers" — Likelihood: Medium, Impact: Medium
- "gensim fails on Python 3.14" — Likelihood: Medium, Impact: Low

## Execution order (adjusted)

1. **Scenario 0**: Test state accumulation against live MCP (Arch F3)
2. **Lane C RED**: Commit test files, witness failures
3. **Lane A**: Create catalog files (parallel within) — 11 tools, trimmed server.md
4. **Lane B**: Create SKILL.md with corrected gotchas
5. **Lane C GREEN**: Tests pass
6. **Integration gate**: index_build --check → validate.py --all → pytest -q → pylint
7. **Lane D**: VERSION + changelog
8. **Dogfooding**: 6 scenarios (0-5)
