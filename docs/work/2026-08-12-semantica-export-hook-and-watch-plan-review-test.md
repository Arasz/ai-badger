# Semantica Export Hook & Watch Plan — Test-Engineer Quality Gate Review

**Date:** 2026-08-12  
**Task:** `semantica-integration-part2`  
**Reviewer:** Test Engineer subagent (delegated review)  
**Target Document:** `docs/work/2026-08-12-semantica-export-hook-and-watch-plan.md`  
**Verdict:** `APPROVE-WITH-FIXES`  

---

## Executive Summary

This review evaluates the testability, TDD RED-GREEN discipline, sensitivity coverage (`prove-the-check-fails`), gate chain requirements (`validate.py --all`, `pylint`, `pytest`), and failure mode edge cases in `docs/work/2026-08-12-semantica-export-hook-and-watch-plan.md`.

The overall architectural direction (exporting Semantica graph snapshots to JSON, seeding a template file, and registering an AiRaccoon `memory_watch_add` watcher per ADR-0019) is sound. However, the implementation plan contains **7 specific findings** (1 Critical, 4 High, 2 Medium) spanning factual inaccuracies regarding repository files, untestable process assumptions, reversed TDD execution ordering, and gaps in test isolation and failure mode coverage.

The plan is **APPROVED WITH FIXES**, pending incorporation of the required remediations outlined in Section 4.

---

## Evaluation Dimensions

### 1. Component & Integration Testability
- **Scaffolding Integration (WP A)**: The plan specifies updating `features/common/scaffolding.json`. However, `features/common/scaffolding.json` **does not exist** in the repository. Scaffolding manifests are stack-specific (e.g. `features/hermes/scaffolding.json`). Testing a non-existent file path will invalidate scaffolding tests.
- **Hook Execution Model (WP B)**: The plan claims `export_semantica_graph.py` will "connect to running Semantica stdio" when triggered on session stop or pre-commit. Standalone python hook scripts running in a git/session subshell cannot attach to an active stdio process owned by an agent harness without an explicit IPC channel or export buffer. The script can only be tested reliably via CLI arguments (`--json`) or data structures passed to `export_graph()`.
- **AiRaccoon Watch Integration (WP C)**: Registration of `.ai-raccoon/semantica-graph.json` via `memory_watch_add` is testable either by mocking `memory_watch_add` or asserting entry creation in `.ai-raccoon/watches.json`.

### 2. TDD RED-GREEN Cycle & Witnessing
- **Sequence Error**: Work Package D (TDD Test Suite) is listed *after* Work Packages A, B, and C. Per repo invariant `tdd-mandatory` and `prove-the-check-fails`, tests must be authored and witnessed in a RED state *before* implementing templates, hook scripts, or scaffolding declarations.
- **Witnessing Protocol**: The plan lacks explicit instructions or criteria for witnessing RED test failures before code implementation.

### 3. Sensitivity Test Coverage (`prove-the-check-fails`)
- **Vague Requirements**: WP D mentions "Sensitivity checks proving every assertion can fail" in a single bullet point without naming specific test cases or failure assertions.
- **Missing Negative Cases**: The plan does not specify sensitivity tests for corrupt JSON payloads, missing parent directories, atomic replace failures, or scaffolding omission.

### 4. Quality Gate Chain Requirements (`validate.py --all`, `pylint`, `pytest`)
- **Gate Integration**: `validate.py --all` executes schema validation, `skills_lint`, and scaffolding checks. Pylint enforces 10.00/10 clean code scores on non-test python scripts. Pytest runs unit and sensitivity suites.
- **CWD Pollution Risk**: `export_semantica_graph.py` defaults to `Path.cwd() / ".ai-raccoon/semantica-graph.json"`. Unbound unit test runs calling `main([])` without explicit `--target` or `monkeypatch.chdir(tmp_path)` risk polluting the repository working directory.

### 5. Failure Mode & Edge Case Resilience
- **Missing Edge Cases**: The plan omits key edge cases including read-only filesystem permissions, malformed/truncated raw JSON inputs, atomic rename tempfile collisions across concurrent processes (`os.getpid()`), and missing parent directory creation.

---

## Numbered Findings & Severities

### Finding 1 (HIGH): Incorrect Scaffolding Target Path (`features/common/scaffolding.json`)
- **Severity:** HIGH
- **Description:** WP A specifies updating `features/common/scaffolding.json` to seed `.ai-raccoon/semantica-graph.json`. `features/common/scaffolding.json` does not exist in `ai-badger`. Scaffolding manifests exist under stack-specific directories (`features/hermes/scaffolding.json`, `features/claude/scaffolding.json`, `features/copilot/scaffolding.json`).
- **Impact:** Any test asserting that `features/common/scaffolding.json` seeds the graph file will fail or target an invalid path.
- **Remediation:** Update WP A to target `features/common/templates/semantica-graph.json.tmpl` for the template body and update stack-specific scaffolding manifests (e.g. `features/hermes/scaffolding.json`) for project seeding.

### Finding 2 (CRITICAL): Disconnect Between Hook Specification and Script Execution Model
- **Severity:** CRITICAL
- **Description:** Section 1 (Item 2) and WP B state that `export_semantica_graph.py` "executes `export_graph(format='json')` via Semantica stdio or client" and "connects to running Semantica stdio". Standalone Python scripts invoked from OS hooks (session stop, pre-commit) have no mechanism to attach to an active stdio pipe owned by an external agent harness (Hermes or Claude Code). The script relies on receiving raw JSON via `--json` or re-reading an existing disk file.
- **Impact:** The specified runtime execution model is impossible as described and untestable.
- **Remediation:** Clarify the runtime contract in Section 1 and WP B: the agent harness or post-tool hook exports the JSON string and invokes `export_semantica_graph.py --json '<payload>' --target .ai-raccoon/semantica-graph.json`, or writes to a buffer file.

### Finding 3 (HIGH): TDD Execution Order Reversal & Lack of RED Witnessing Protocol
- **Severity:** HIGH
- **Description:** WP D (TDD Test Suite) is placed after WP A, B, and C in the plan sequence. Repo invariant `tdd-mandatory` requires writing failing tests *before* writing production code.
- **Impact:** Developers following the plan in order will write production code before tests, violating TDD discipline and risking unverified GREEN tests.
- **Remediation:** Move WP D to be Work Package 0 (or Step 1 in every Work Package). Require explicit RED test runs to be witnessed before creating templates or scripts.

### Finding 4 (HIGH): Sensitivity Test Requirements Lack Concrete Definitions
- **Severity:** HIGH
- **Description:** WP D includes only a single generic bullet point for sensitivity checks. It defines no concrete sensitivity test methods or failure assertions.
- **Impact:** Tests may pass without proving that they can catch real defects (`prove-the-check-fails` violation).
- **Remediation:** Explicitly define sensitivity test methods in `TestExportHookChecksCanFail` (e.g. `test_missing_file_check_can_fail`, `test_corrupted_metadata_check_can_fail`, `test_invalid_json_fallback_can_fail`).

### Finding 5 (HIGH): Test Suite Pollution Risk via Default Relative Target
- **Severity:** HIGH
- **Description:** The default target in `export_semantica_graph.py` is `.ai-raccoon/semantica-graph.json` relative to `Path.cwd()`. Unit tests invoking `main([])` without `--target` or without `monkeypatch.chdir(tmp_path)` will write directly into the host repo root during `pytest` runs.
- **Impact:** Test suite execution contaminates working directory state and causes non-isolated test behavior.
- **Remediation:** Specify in WP D that all unit tests must execute within `tmp_path` or pass explicit `--target str(tmp_path / "...")` parameters.

### Finding 6 (MEDIUM): Unhandled Failure Mode Edge Cases
- **Severity:** MEDIUM
- **Description:** The plan omits explicit error handling and test coverage for:
  1. Invalid or malformed JSON strings passed to `--json` (falling back to seed payload with `raw_unparsed`).
  2. Missing parent `.ai-raccoon` directory (requiring `target_path.parent.mkdir(parents=True, exist_ok=True)`).
  3. OS write/permission failures gracefully exiting 0 with a stderr warning to avoid blocking git hooks.
- **Impact:** Unhandled runtime exceptions in git hooks could block user git commits or session termination.
- **Remediation:** Expand WP B and WP D to include explicit error resilience and fallback tests for these edge cases.

### Finding 7 (MEDIUM): Missing Quality Gate Integration Details
- **Severity:** MEDIUM
- **Description:** The plan mentions `validate.py --all`, `pylint`, and `pytest` in Section 3, but does not detail how new artifacts are validated against existing repo gates (e.g. `skills_lint` rules for `SKILL.md`, `pylint` 10.00/10 for `export_semantica_graph.py`).
- **Impact:** New scripts or skills may fail pipeline quality gates if not verified locally.
- **Remediation:** Add explicit gate verification steps to the acceptance criteria of each Work Package (`validate.py --all`, `pylint`, `pytest`).

---

## Required Plan Fixes (Actionable Remediation Checklist)

To move this plan from `APPROVE-WITH-FIXES` to `APPROVED`, update `docs/work/2026-08-12-semantica-export-hook-and-watch-plan.md` with the following changes:

- [ ] **Fix Scaffolding Path (WP A)**: Change `features/common/scaffolding.json` to `features/common/templates/semantica-graph.json.tmpl` and reference stack-specific manifests (e.g. `features/hermes/scaffolding.json`).
- [ ] **Clarify Hook Execution Contract (Section 1 & WP B)**: Document that `export_semantica_graph.py` receives exported JSON via `--json` CLI argument or buffer file, rather than attempting direct stdio process attachment.
- [ ] **Re-order TDD Work Package (WP D -> WP 0)**: Move test creation to Step 1, mandating RED witnessing before implementing templates or hook scripts.
- [ ] **Specify Concrete Sensitivity Tests (WP D)**: List explicit test methods under `TestExportHookChecksCanFail` and `TestSkillChecksCanFail` to satisfy `prove-the-check-fails`.
- [ ] **Enforce Test Isolation (WP D)**: Require all unit tests to use `tmp_path` fixtures or `monkeypatch` to prevent `CWD` directory pollution.
- [ ] **Add Edge Case Resilience Specs (WP B & WP D)**: Include explicit requirements and tests for malformed JSON fallback, missing parent directory creation, and non-blocking exit 0 on OS errors.
- [ ] **Detail Quality Gate Execution**: Explicitly list `python3 tooling/validate.py --all`, `python3 -m pylint <script>`, and `python3 -m pytest tests/` as required verification steps in the plan.
