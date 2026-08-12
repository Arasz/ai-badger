# Semantica Integration — Test-Engineer Review

**Date:** 2026-08-12
**Reviewer:** test-engineer (delegated review)
**Verdict:** `APPROVE-WITH-FIXES`

The plan is well-structured and the test catalogue is thorough for what it covers. However, seven
gaps need attention — three are blockers for the TDD contract, two bear on acceptance-criteria
honesty, and two are coverage gaps the existing test infrastructure would catch by default if the
new tests matched its conventions.

---

## 1. ACCEPTANCE-CRITERIA HONESTY

### 1.1 The plan's test suite duplicates the skills_lint gate without delegating to it (MEDIUM)

The plan proposes 10 skill-structure tests:

- `test_skill_md_has_valid_yaml_frontmatter`
- `test_skill_scope_is_default`
- `test_skill_has_when_not_to_use_section`
- `test_skill_has_gotchas_section`
- `test_skill_has_verification_checklist`
- `test_skill_references_specific_tools`
- `test_skill_under_120_lines`

All seven map directly to rules already enforced by `gates/skills_lint.py` — specifically:

| Plan test | skills_lint rule |
|---|---|
| Frontmatter validity | Rule 10 (parse + required keys) |
| Scope is `default` | Rule 12 (scope key, common-stack) |
| "When NOT to Use" | Not directly; Rule 5 checks description starts with "Use when", but the body's guard heading is not linted |
| Gotchas section | Rule 9 (`## Gotchas` required) |
| Verification checklist | Not linted (prose convention, not mechanical) |
| References specific tools | Not linted (prose convention) |
| Under 120 lines | Rule 6 (500-line cap — so this is a stricter bound not checked by the gate) |

The plan should explicitly acknowledge this overlap and either (a) delegate to `skills_lint` for
the rules it already covers, keeping only the prose-oriented tests the linter cannot enforce, or
(b) explain why each test is additive. Duplicating a gate inside a unit test is the shape of the
`derive-or-delete-the-list` invariant — a second source of truth that drifts silently.

**Remediation:** Split the skill tests into two categories: "gate-proven" (delegate to
`skills_lint`, no test needed) and "author intent" (prose patterns the linter can't check).
The prose-oriented tests (When NOT to Use, verification checklist, tool name references) are
valid; the mechanically-checked ones (frontmatter, scope, gotchas, line count) are ceremony
unless they assert a stricter bound than the gate (e.g. 120 lines vs 500).

### 1.2 Server.md uses a 500-char budget; the existing gate uses a 15-line budget (LOW)

The plan sets "Under 500 chars" as the `server.md` budget. The existing `test_every_shipped_server_md_stays_within_the_line_budget`
in `tests/test_mcp_catalog_instructions.py` enforces a **15-line** cap. The plan doesn't mention
this existing test or reconcile the two limits. The framework already checks this; the plan's
test is additive only if it asserts a stricter bound. Otherwise it is a duplicate.

**Remediation:** Either fold the 500-char check into the existing test's parametrized budget
or note that the existing 15-line gate is sufficient and drop the duplicate test.

### 1.3 Acceptance criteria that cannot be tested (LOW)

Several acceptance criteria in the plan are not mapped to any test:

- 1.2 AC: "Under 500 chars (agent instruction budget…)" — no test for this beyond manual review
- 1.2 AC: "Names the complementarity with AiRaccoon" — no automated test listed
- 1.2 AC: "Gives entry-point tool guidance" — prose review, not automated
- 2.1 AC: "Under 120 lines" — no test against the `skills_lint` gate cap; the plan's own test
  `test_skill_under_120_lines` covers it but the gate does not, so a future skill author who only
  runs `validate.py --all` will not see this violation

These are not dishonest — they are honest about being manual. But the plan labels them as
acceptance criteria under numbered quality gates. A criterion without an automated gate is a
`prove-the-check-fails` gap: no check has ever been seen to fail on it. At minimum, note which
are manual and which are automated.

---

## 2. TDD DISCIPLINE

### 2.1 The RED-GREEN cycle is described but not gated (HIGH — BLOCKER)

The plan states:

> "TDD approach: Write the test RED first (before creating the catalog files), then write the
> catalog files to make it GREEN."

And lists as a blocker:

> "TDD RED-GREEN cycle witnessed for both test files"

But the plan offers no mechanism to prove this — no commit ordering requirement, no CI gate that
demands the test files carry an earlier timestamp than the catalog files, no hook that prevents
committing catalog files without their tests. The `prove-the-check-fails` invariant (CLAUDE.md
line 47) reads:

> "Put the defect a gate, test or acceptance criterion exists to catch in front of it, watch it
> go red, take the defect away and watch it go green — a check that has only ever passed is
> indistinguishable from one whose comparison can produce a single answer that looks like
> success."

A test file committed alongside its implementation never proves it can fail. The plan's 22 tests
are a good catalogue, but without a witnessed RED run they are indistinguishable from
post-hoc tests that happen to pass.

**Remediation:** The plan needs a concrete TDD gate. The simplest: Lane C commits first
(test files only, witnessed RED), then Lane A and Lane B commits make them GREEN. A CI lane
that runs the test commit in isolation and expects failure would automate this. Alternatively,
the local workflow must produce a terminal log of the RED run. The "RED-GREEN cycle witnessed"
blocker is currently unenforceable — it is a human promise, not a gate.

### 2.2 The integration-order diagram shows Lane C as parallel, not precedent (MEDIUM)

Section 5's diagram shows Lane C (tests) running "parallel with Lane A+B". True TDD means tests
are written and seen to fail **before** the production code. The text acknowledges "can write
tests before files exist" but the parallelism notation ("three parallel boxes") suggests they
happen concurrently. A concurrent lane that writes tests while the other lane writes catalog
files is not TDD — it is test-together development.

**Remediation:** The diagram should show Lane C completing (or at least starting and reaching a
confirmed RED state) before Lane A+B begin. The existing text already says this in prose;
the diagram should match.

---

## 3. TEST COVERAGE GAPS

### 3.1 No "can fail" sensitivity tests (HIGH — BLOCKER)

The existing test infrastructure requires every check to include a companion test that proves
the check can detect a violation. This is explicit in the codebase:

- `test_the_byte_identity_check_can_fail` in `test_mcp_declared_servers.py` (line 145)
- `test_the_byte_identity_check_can_fail` in `test_mcp_catalog_instructions.py` (line 80)
- `test_the_guard_could_fail` class in `test_skill_bodies_carry_procedure_not_evidence.py`
- `test_the_check_actually_sees_something` in `test_skill_docs.py` (line 90)

The plan's 22 tests include **zero** "can fail" sensitivity tests. Without them, these tests
have never been observed to fail — which under the `prove-the-check-fails` invariant means they
are not checks.

**Remediation:** Add at least one sensitivity test per test file. Examples:
- In catalog tests: monkeypatch one tool name to be blank and assert `test_tool_names_are_unique`
  still catches it (purposefully identical names).
- In skill tests: monkeypatch the SKILL.md to remove the "When NOT to Use" heading and assert
  `test_skill_has_when_not_to_use_section` fails.
- Add a `test_each_check_can_fail` class that perturbs each assertion to confirm it goes RED.

### 3.2 No test runs `validate.py --all` against the full tree (HIGH)

The plan's integration gate (Section 3.3) runs `pytest`, `pylint`, and `index_build --check`.
It does **not** run `python3 tooling/validate.py --all`, which includes:

- Schema validation for all catalog files (including the new semantica ones)
- `skills_lint` (G4 gate — all 12 rules)
- Cross-stack reference checks
- Inlined body relative-link checks
- Feature JSON schema coverage
- Catalog stack membership

The existing ai-raccoon test suite includes `test_catalog_validation_remains_green` which runs
`validate.py --all` and asserts exit code 0. The plan's new test suite has no equivalent. This
means a broken `server.md` relative link or a skills_lint rule-8 violation in the new
`semantica-knowledge-graph` SKILL.md would pass the plan's gate chain.

**Remediation:** Add `test_semantica_catalog_validation_remains_green` that runs
`validate.py --all` and asserts exit code 0 against the full tree. The gate chain must also
include `validate.py --all` as a quality gate in Section 3.3.

### 3.3 No test for `index_build.py --check` discovery (MEDIUM)

The plan lists `test_index_build_discovers_semantica_mcp` and
`test_index_build_discovers_semantica_skill` as catalog tests 11 and 12. These are good, but
they only check that the entry exists — they don't verify the entry is **correct**. The
existing `test_the_index_lists_the_server` in `test_mcp_catalog_instructions.py` checks the
index entry shape: `{"name": "...", "path": "..."}`.

The plan's test 11 ("includes semantica in the mcp feature") and test 12 ("includes
semantica-knowledge-graph in the skills feature") should also assert the full index entry
shape matches the existing convention: name, path, and (for skills) scope.

### 3.4 No test for the evidence review's live findings (HIGH)

The evidence review (`2026-08-12-semantica-integration-review.md`) documents critical findings
that the plan's tests ignore:

- **`get_graph_analytics` is BROKEN** (PageRank calculation error). The plan includes it in
  `tools.json` with two tags (`diagnostic`, `read`) and intent prose, but the test suite has
  no guard that the documented tools actually work. Any agent reading the skill will discover
  this tool exists and try to use it — and it will fail.
- **`add_relationship` param names differ from schema** — uses `source`/`target` not
  `source_id`/`target_id`. The skill body's workflow section 2 tells the agent to call
  `add_relationship` — if the param names in the skill guidance don't match the actual
  MCP tool signature, the agent will get errors.
- **The MCP server is stateless per invocation** — each spawn creates a fresh in-memory graph.
  The plan's dogfooding Scenario 2 (causal archaeology with two chained decisions) is
  **impossible** without batching all graph construction + query into a single MCP call, because
  decisions recorded in one call won't be visible in the next.

The plan acknowledges the statelessness limitation in the skill's gotchas section ("The graph
store is in-memory — decisions and entities do not survive a session restart") but doesn't test
that the skill's workflows account for this. No dogfooding scenario explicitly tests
cross-invocation state loss.

**Remediation:**
- Add a test that the `tools.json` entries match the evidence review's live test results
  (mark broken tools as such in the catalog or add a `degraded` tag).
- Add a test that the skill body's tool usage matches the actual tool signatures — at minimum,
  a static check that parameter names in the skill prose match the `tools.json` entries.
- Add a dogfooding scenario that explicitly tests the statelessness pitfall: "Record a decision,
  start a new MCP session, and try to query it — observe that the graph is empty."

### 3.5 The server.md line/char budget is not tested within the plan's test suite (LOW)

The plan's `test_server_md_exists_and_under_500_chars` checks for ≤500 characters. The existing
framework test (`test_every_shipped_server_md_stays_within_the_line_budget`) checks ≤15 lines.
These are different metrics and neither implies the other. A 14-line file with 600 chars passes
the framework gate but fails the plan's test. A 16-line file with 400 chars fails the framework
gate but passes the plan's test. Reconciliation is needed.

---

## 4. QUALITY GATE CHAIN

### 4.1 The integration gate is missing `validate.py --all` (HIGH)

See finding 3.2 above. The gate chain should read:

```
index_build --check  →  validate.py --all  →  pytest -q  →  pylint
```

Currently it reads `index_build --check → pylint → pytest -q`, which validates JSON schemas
only in production (through `index_build`'s own validation) but not the declarations the
framework already checks through `validate.py --all` (skills_lint, cross-stack references,
inlined body links, etc.).

### 4.2 The gate chain order buries schema validation inside index_build (LOW)

`index_build.py --check` validates JSON as part of its build step, so the plan's gate chain
does get schema validation — but it's coupled to index building rather than being an independent
step. If `index_build` is refactored to skip schema validation, this gate silently weakens.
`validate.py --all` is the framework's explicit "check everything" step and should be the
gate, not a side effect of building.

### 4.3 No pre-commit hook or CI lane specified (LOW)

The plan specifies local quality gates only. The existing framework has pre-commit hooks
(generated-file-guard) and CI lanes. A new catalog entry should be no different — the plan
should confirm that the existing hooks and lanes automatically pick up the new test files
and catalog entries without configuration changes.

---

## 5. DOGFOODING PLAN

### 5.1 Scenario 2 is impossible under stateless MCP (HIGH)

Scenario 2 requires "at least 2 recorded decisions where one depends on another" and then
using `get_causal_chain` to trace ancestry. Since each MCP invocation spawns a fresh graph,
decisions recorded in the first call are invisible to the second. The only way to make this work
is to batch all construction + queries into a **single** MCP tool call — which the plan doesn't
describe.

The plan's risk register acknowledges "In-memory graph store limits utility" (Risk #2) but the
dogfooding plan doesn't test the actual severity of this limitation. A more honest scenario
would be:

**Revised Scenario 2:** "Record two chained decisions in a single session (one MCP invocation),
then query `get_causal_chain` within the same invocation — verify the chain is complete.
Then start a new session — verify the graph is empty and the decisions are gone."

### 5.2 No dogfooding scenario tests the agent's error recovery (MEDIUM)

The 5 scenarios all assume success. None tests what happens when:
- The agent tries `get_graph_analytics` (which is BROKEN) — does the skill guide recovery?
- The agent tries `extract_entities` without torch/transformers (which is DEGRADED) — does
  the skill note the dependency?
- The graph is empty — does the `escalation by result` section (skill section 6) actually
  guide the agent to population rather than an error loop?

### 5.3 The dogfooding success criteria are vague (LOW)

Criterion "Agent correctly chooses Semantica tools over AiRaccoon tools for decision/causal
queries" — there is no baseline to measure against. What counts as "correctly"? One session
where the agent made the right choice? A statistical measurement over N sessions? Without
a defined threshold, this criterion is always "pass from a single supportive example."

---

## 6. ADDITIONAL OBSERVATIONS

### 6.1 The plan tests schema validation but the harder problem is content correctness

All 12 catalog tests + 10 skill tests are structural: Does the JSON parse? Do schema keys
match? Are tags valid? None of these tests verify semantic correctness — that the tool intents
accurately describe the tool, that the skill's workflow logic produces correct agent behavior,
that the stack-mcp entry's command actually launches the server.

This is a known tradeoff (the evidence review did live testing of the server). The plan should
be explicit about the boundary: "structural validation is automated; semantic validation is
manual (evidence review + dogfooding)."

### 6.2 The `test_skill_references_specific_tools` test (test 8) is fragile

Checking that the SKILL.md body contains "at least 6 of the 12 semantica tool names" can
produce false positives (a tool name appearing in prose unrelated to usage instructions)
and false negatives (a tool referenced by a slightly different name). A more robust check
would use a controlled vocabulary approach — e.g., the skill's frontmatter `metadata.hermes.tags`
already names the tool group, and a `tools_used` key could explicitly list the referenced tools.

### 6.3 The plan doesn't test against the ai-raccoon-memory reference pattern

The plan claims the skill "follows the same structure" as `ai-raccoon-memory/SKILL.md`
but the tests don't verify structural equivalence — no test compares the heading structure,
section count, or presence of specific sections (When NOT to Use, numbered workflows,
Gotchas, Verification Checklist) against the reference. The structure is tested for
presence, not for faithfulness to the reference.

---

## 7. VERDICT AND REMEDIATION SUMMARY

### Verdict: `APPROVE-WITH-FIXES`

### Required before execution (blockers):

| # | Finding | Severity |
|---|---|---|
| 2.1 | RED-GREEN cycle is unenforceable — needs a concrete gate | HIGH |
| 3.1 | No "can fail" sensitivity tests — violates `prove-the-check-fails` | HIGH |
| 3.2 | No `validate.py --all` in test suite or gate chain | HIGH |
| 3.4 | Evidence review findings (broken tools, param mismatches, statelessness) untested | HIGH |
| 5.1 | Dogfooding Scenario 2 is impossible under stateless MCP | HIGH |
| 1.1 | Skills_lint duplication — tests should delegate, not duplicate | MEDIUM |
| 2.2 | Integration diagram shows parallel lanes, not test-precedent TDD | MEDIUM |

### Recommended (before merge, not blocking):

| # | Finding | Severity |
|---|---|---|
| 5.2 | No error-recovery dogfooding scenario | MEDIUM |
| 3.3 | Index discovery tests don't assert entry shape | MEDIUM |
| 1.2 | Server.md budget conflicts with existing 15-line gate | LOW |
| 1.3 | Manual-only acceptance criteria are unmarked | LOW |
| 3.5 | Line/char budget tests are unreconciled | LOW |
| 4.1-4.3 | Gate chain ordering and CI/hook gaps | LOW |
| 5.3 | Dogfooding success criteria lack defined thresholds | LOW |
| 6.2 | Tool-name reference test is fragile | LOW |
| 6.3 | No structural equivalence test against reference pattern | LOW |
