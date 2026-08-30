# Refinement feedback — pi stack parity — 5 design decisions

<!-- refinement-form: owner-gate:aib-pi-stack-mcp-skills-parity:v1 · saved 2026-08-30T18:52:25.908Z · answered 5/5 -->

Source document: `docs/work/2026-08-30-pi-stack-mcp-skills-parity-plan.md (+ premortem + test strategy in the same directory)`

## D1 — Keep the <code>isProjectTrusted()</code>-only MCP trust gate — with the measured semantics, not the plan's original story

**Verdict:** APPROVE

**Notes:**

_(none)_

---

## D2 — The adapter's <code>resources_discover</code> skills contribution stays <strong>ungated</strong> (unconditional)

**Verdict:** APPROVE

**Notes:**

_(none)_

---

## D3 — Repurpose <code>adjust_mcp.py</code>/<code>adjust_skills.py</code> as migration-only removers — <strong>shape-aware</strong> and <strong>version-gated</strong>

**Verdict:** APPROVE

**Notes:**

_(none)_

---

## D4 — <code>mcpDisabledTools</code> stays global; the fork's non-atomic save gets fixed as a drive-by

**Verdict:** APPROVE

**Notes:**

_(none)_

---

## D5 — Map remote servers: claude <code>type:"http"/"sse"</code> → fork <code>type:"remote"</code>

**Verdict:** APPROVE

**Notes:**

_(none)_

---

## Not answered

_(none — every item has a verdict)_

<!-- end refinement feedback -->

<!-- provenance: the reviewer's browser save did not reach this path; the reviewer pasted the
     complete feedback block into the orchestrating session at 2026-08-30, and the orchestrator
     persisted it here verbatim (end marker verified before ingest). -->
