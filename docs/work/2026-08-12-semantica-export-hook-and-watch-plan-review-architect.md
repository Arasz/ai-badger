# Semantica Export Hook & Watch Plan — Architecture Review

**Date:** 2026-08-12  
**Reviewer:** Architect subagent (delegated review)  
**Target:** `docs/work/2026-08-12-semantica-export-hook-and-watch-plan.md`  
**Verdict:** `APPROVE-WITH-FIXES`  

## Overview

The implementation plan for the Semantica export hook and AiRaccoon watch bridge accurately reflects ADR-0019. It solves Semantica's session-scoped process isolation without introducing complex graph import logic or hand-rolled network IPC.

## Key Findings

### F-01 (MEDIUM) — Atomic Write Tempfile Naming
- **Finding**: Using a fixed `.tmp` extension for atomic writes can cause collisions if concurrent hooks fire.
- **Remediation**: Use process ID suffix `.tmp.{os.getpid()}` for the tempfile before `os.replace`. (Implemented in `export_semantica_graph.py`).

### F-02 (LOW) — Graceful Fallback Exits 0
- **Finding**: When the Semantica process is unattached or absent during session end, the hook must fail soft and exit 0 to avoid blocking git or session teardown.
- **Remediation**: Wrap `export_graph` call in `try...except` in `main()`, print warning to stderr, and exit 0. (Implemented in `export_semantica_graph.py`).

### F-03 (LOW) — Seeding Template Validation
- **Finding**: The seed file template `.ai-raccoon/semantica-graph.json` must be valid JSON matching the export shape (`nodes`, `edges`, `decisions`, `metadata`).
- **Remediation**: Validate seed file structure in `test_semantica_export_hook.py`.

## Verdict
`APPROVE-WITH-FIXES` — All architectural findings are remediated and verified.
