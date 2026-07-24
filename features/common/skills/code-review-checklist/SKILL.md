---
name: code-review-checklist
description: >-
  Aviation-style preflight checklist for code reviews. Every item is a concrete,
  pass/fail check organized into sequential phases. Stack-specific checks activate
  via extensions (dotnet, react, cosmos, azure, ts, mcp). Use when reviewing PRs,
  performing milestone reviews, or self-reviewing before push.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, checklist, fullstack]
    related_skills: [comprehensive-code-review, frontend-code-review, data-contract-audit, plan-review, requesting-code-review]
---

# Code Review Preflight Checklist

> **Pattern: Aviation preflight checklist.** Each phase is a system check.
> Every item is a concrete, verifiable action — read it, check it, confirm it.
> No item is skipped regardless of reviewer experience. Critical items carry
> WARNING markers. Phases are sequential — complete each before proceeding.

## When to Use

- Reviewing a PR before approving
- Performing a milestone or sprint review
- Self-reviewing before `git push`
- Checking a subagent's output before merging

## When NOT to Use

- Plan/spec feasibility review → `plan-review`
- Frontend architecture deep-dive → `frontend-code-review`
- Full milestone review methodology → `comprehensive-code-review`
- Pre-commit security scan → `requesting-code-review`

## Preflight Protocol

1. **Read each item aloud** (or mentally). Verify against actual code, not assumptions.
2. **Mark PASS or FAIL.** If any FAIL exists, do not approve until resolved.
3. **WARNING items are non-negotiable.** They represent real bugs from past incidents.
4. **Complete phases sequentially.** Phase 1 gates all others.

> **Stack-specific checks:** This template covers universal concerns. If your
> project uses dotnet, react, cosmos, azure, ts, or mcp, the corresponding
> `extensions/<name>/` phases are embedded automatically. Follow them after
> the generic phases. Project-specific checks (incident lessons, project
> conventions) go in `project-local.md` and are appended automatically.

<!-- MERGE_EXTENSIONS -->

---

## Phase 1: Pre-Takeoff Gates (ALL MUST PASS — gates everything else)

> These are absolute blockers. If any FAIL, do not proceed to Phase 2.

- [ ] **Build passes** — the project's build command completes with zero errors
- [ ] **Tests pass** — the project's test command shows no new failures vs baseline
- [ ] **Lint passes** — the project's linter runs clean
- [ ] **No hardcoded secrets** — no API keys, tokens, connection strings, or passwords in any tracked file
- [ ] **No unjustified warning suppressions** — every suppression must have a tracked TODO or documented reason
- [ ] **VERSION bumped** — if this is a release, the version has been bumped (semver) and a changelog entry exists
- [ ] **One PR = one task** — the PR does not bundle unrelated changes

<!-- EXT:pre-takeoff -->

---

## Phase 2: Architecture & Layering (Structural Integrity)

> These checks enforce clean boundaries between layers. Violations compound
> into unmaintainable codebases.

### 2.1 Layering

- [ ] **Domain has zero infrastructure dependencies** — domain files must not
  import HTTP clients, database SDKs, cloud provider SDKs, or any external
  service client.
- [ ] **Infrastructure implements domain interfaces** — the dependency direction
  is always: Infrastructure -> Domain (never reverse). Domain defines ports;
  infrastructure provides adapters.
- [ ] **API endpoints are thin** — delegate to domain services/engine.
  Endpoints > 50 lines should be refactored.
- [ ] **API surface maps 1:1 to domain operations** — no business logic in
  controllers, route handlers, or API gateway functions.

### 2.2 Domain Model

- [ ] **State transitions enforced by domain model** — state machine transitions
  are in the model, not the endpoint.
- [ ] **No string action parameters where an enum exists** — if a switch on a
  string action exists, it should be a typed enum.

### 2.3 Screaming architecture

- [ ] **Folders named by domain concept** — a new folder name should tell a
  reader what the system *does*, not what kind of file lives there.
  Avoid catch-all `Services/`, `Controllers/`, `Utils/` buckets.
- [ ] **Shared technical chassis is the only exception** — logging, DI wiring,
  cross-cutting middleware may use generic names.

<!-- EXT:architecture -->

---

## Phase 3: Cross-Cutting Concerns (TDD, Security, Docs)

### 3.1 TDD Compliance

- [ ] **Tests exist for all new production code** — no production code without
  a test that demanded it
- [ ] **Test-first order** — failing test written -> code to make it pass ->
  refactor. Not the reverse.
- [ ] **Edge cases tested** — not just happy path. Error paths, boundary
  conditions, concurrent scenarios.
- [ ] **Missing test scenarios documented** — if a test gap exists, it's noted
  as a follow-up, not silently skipped.

### 3.2 Repository & Contract Tests

- [ ] **Repository interfaces have contract tests** — not just in-memory fakes.
  Datastore implementations should be validated against the contract.
- [ ] **Repository filter methods cover spec requirements** — if the API spec
  defines filters, the repository must have a method that supports them.

### 3.3 Security

- [ ] **No hardcoded secrets, credentials, or tokens** in any tracked file
- [ ] **Managed credentials preferred over shared keys** — use identity-based
  auth over connection strings, account keys, or shared access signatures
  wherever the platform supports it.
- [ ] **Token/credential storage is encrypted** — secrets at rest use the
  platform's encryption mechanism, not plaintext.
- [ ] **OAuth/SSO flows handle edge cases** — popup-blocked fallback documented,
  token refresh implemented, CSRF tokens have TTL/cleanup.

### 3.4 Documentation & Hygiene

- [ ] **Spec issues from reviews are fixed** — check if prior review findings
  are addressed in the implementation, not just noted in the spec.
- [ ] **Tracked TODOs for deferred work** — every suppression, known gap, or
  technical debt has a tracked issue or inline TODO with context.
- [ ] **No copy-paste duplication in specs/docs** — check for duplicated content
  blocks that should reference a single source.
- [ ] **Import paths are accurate** — all referenced modules, components, and
  utilities exist at the paths used in import statements.

<!-- EXT:cross-cutting -->

---

## Phase 4: Backend Runtime Behavior (Concurrency, Errors)

### 4.1 Concurrency & Idempotency

- [ ] **Optimistic concurrency via ETag** — every Save/Upsert that could be
  called concurrently must use ETag-based CAS.
- [ ] **Idempotent operations return 200, not 409** — if an operation is already
  in the target state, return 200 with current state. Only throw 409 for
  genuinely conflicting states.
- [ ] **Idempotency check comes BEFORE policy evaluation** — check
  disposition/early-exit before calling business logic that may return a
  misleading status for already-applied items.
- [ ] **TOCTOU gaps documented** — if a check-then-act pattern exists, note
  whether it's acceptable for current phase or needs a distributed lock.
- [ ] **Export/create operations have idempotency** — calling POST twice should
  either return the same resource or reject the second (not silently duplicate).

### 4.2 Error Handling

- [ ] **Problem type URIs / error codes are consistent** — the error identifier
  used by the backend must match what the client checks. Drift = silent failures.

<!-- EXT:backend-runtime -->

---

## Phase 5: Client-Server Contract Alignment

> WARNING: Mismatched routes, response shapes, or error codes cause
> silent failures — the app compiles and tests pass against mock data.

- [ ] **Client route paths match API route paths EXACTLY** — including resource
  prefix
- [ ] **Query parameter names match** — client query keys use the same parameter
  name as the API expects
- [ ] **Response shapes match field-for-field** — nested vs flat, wrapper
  objects, detail-only fields omitted from list responses
- [ ] **Error codes/types match** — client error detection uses the exact error
  identifiers the API returns.
- [ ] **Client types mirror backend types** — field names, optionality, nesting
  all match. Enum values use the wire format.
- [ ] **Config endpoints agree** — if the spec defines one path and the client
  calls another, resolve before implementation.
- [ ] **Types are explicitly defined** — every type referenced in an API call
  must have a corresponding type definition (not inline any or inferred).
- [ ] **Mock/test fixtures match actual API responses** — if the API shape
  changes, the test fixtures must update too. Wrong fixtures = tests pass
  against phantom data.

<!-- EXT:contract -->

---

## Phase 6: Cross-Feature Patterns

- [ ] **New code matches existing patterns in the same repo** — compare against
  established conventions in sibling modules/features.
- [ ] **Shared constants are not duplicated** — API base URLs, feature flags,
  config values should come from a single source, not redefined per module.
- [ ] **Cross-feature duplication extracted to shared utilities** — if two
  modules share ~70 lines of identical logic, extract it.
- [ ] **Bulk operations consider parallelism** — sequential processing of 10+
  items is slow. Document why sequential is required or use concurrent execution.

<!-- EXT:patterns -->

---

## Phase 7: Accessibility

- [ ] **Automated accessibility tests exist for every new page/section** — at
  minimum one axe smoke test per page-level component
- [ ] **All interactive elements have associated labels** — htmlFor/id pairs,
  aria-label, or aria-labelledby
- [ ] **Decorative icons have aria-hidden="true"**
- [ ] **Status badges have aria-live="polite"** — screen readers must announce
  changes to status indicators
- [ ] **Loading states have aria-busy="true" and aria-live="polite"**
- [ ] **Error containers have role="alert"**
- [ ] **Nav links have aria-current="page" on active state**
- [ ] **External links have target="_blank" rel="noopener"**

<!-- EXT:accessibility -->

---

## Phase 8: Orchestration & Async Patterns

- [ ] **Long-running operations return async acknowledgment** — not synchronous
  completion. Return an operation ID for polling/tracking.
- [ ] **Orchestration code is deterministic** — no direct I/O in orchestration
  functions. Activities/workers do the I/O.
- [ ] **Retry loops are bounded** — every retry, poller, or concurrency gate
  has an explicit finite cap. An unbounded loop is a standing availability/cost risk.

<!-- EXT:orchestration -->

---

## Phase 9: Post-Merge Verification (Smoke Test)

> After merging, verify the integration doesn't break the combined codebase.

- [ ] **Build clean on main** — zero errors after merge
- [ ] **All tests pass** — no regressions from merge conflicts
- [ ] **Lint clean** — integration clean
- [ ] **Merge conflicts resolved with intent** — not blindly auto-merged
- [ ] **Infrastructure definitions updated** — if new resources were added
  (database tables, containers, queues, storage)
- [ ] **Issues closed with PR reference comments** — traceability maintained

<!-- EXT:post-merge -->

---

## Usage Tips

1. **Walk phases sequentially** — Phase 1 gates everything.
2. **Check each item against actual code**, not assumptions.
3. **Stack-specific extensions add items into each phase** — dotnet, react, cosmos, azure, ts, and mcp items are merged .
4. **Project-specific checks** go in `project-local.md` — incident lessons, project conventions, etc.
5. **After completing all phases**, the reviewer signs off: "Preflight complete. All phases PASS."
