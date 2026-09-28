# Plan review R3 — integration seams & user intent

Reviewed: `docs/work/2026-09-28-task-decomposition-plan.md` (rev 1), against `plan-sections/p{1,2,3}`, the research record, `task/SKILL.md`, `quick-task/SKILL.md`, `status-report`, `scaffold.py`/`skills_argv.py`, `scaffold_freshness_guard.py`, `verify.sh`, `badger_lib.py`.

---

**1. MUST — S13's re-scaffold command never delivers the new skill and guarantees a red scaffold gate.**
Plan: §3 S13 release ritual (`AI_BADGER_MCP_AVAILABILITY=all … --no-install --skills ''`), AC(4).
Evidence: a true-empty `--skills` recovers the previously scaffolded set from the target manifest (`features/common/skills/welcome-ai-badger/scripts/skills_argv.py:17-19,52`); this repo's manifest records 46 skill rows and **not** `task-decomposition`. `gates/scaffold_freshness_guard.py:14-20,103-104,362-382` fails fast when the manifest is a proper subset of `badger_lib.expected_skill_names(config)` and its remediation explicitly says to run the config-derived list, never `--skills ''`; `welcome-ai-badger/SKILL.md:133` states the same prohibition. So the new mirror `.ai-badger/skills/task-decomposition/**` is never written, AC(4) is unreachable, and because `scaffold` is an always-run local lane (`verify.sh:61,241,444-458` selects `LOCAL_LANES` wholesale), every push between S9 and S13 fails the gate — S9's own gate list does not contain the re-scaffold.
Edit: run the self-scaffold in S9 (after the skill + index land) with the guard-printed config-derived `--skills` list — or omit `--skills` so catalog defaults apply — and keep S13's rerun for version/config stamps; add an S9/S13 AC asserting `.ai-badger/skills/task-decomposition/SKILL.md` is in the re-scaffold diff.

**2. MUST — the Jev seam is contradictory: P2's in-server `steps_ready{advisory}` stands where DR9 puts Jev skill-side, and no interface carries wave hints across.**
Plan: DR9 ("never in the server — the server is offline by contract") vs §4 `p2-api-contract.md` B1 tool #11 (`steps_ready` input `advisory:"off"|"tier"|"waves"|"both"`, output `advisory` block, `openWorldHint` "only for steps_ready when advisory enabled") and B4 ("called only by `steps_ready`") — P2 stands "as written" wherever the merged plan has not restated it, and the plan never mentions `advisory` at all. DR7 computes waves server-side; DR9 computes hints skill-side; nothing names how a hint reaches the packing (post-processing `waves`? an input parameter?). S5's test list, S7's twelve-tool contract, and S9's `mcp-plan-tools.md` would each freeze a different shape.
Edit: amend §2's interface freeze with the exact `steps_ready` signature — drop `advisory`/`openWorldHint` conditional, or add an explicit read-side hints input (e.g. `force_serialize[[a,b]]`) and state that the skill post-processes waves — and add one S5 or S7 test that a hint can only add serialization.

**3. MUST — the hand-rolled MCP protocol and launch-cwd hypothesis are never verified against a host; R-A's flip can never fire.**
Plan: DR3 command (`uv run --script .ai-badger/...`), S7 ACs (real subprocess pipes + `uv run --script … --check`), S8 ACs (catalog/scaffold files), R-A.
Evidence: P2-B3 labels "hosts spawn project-scoped MCP servers with cwd = project root" a HYPOTHESIS and demands a verification AC — "launch under Claude Code and pi, call initialize + tools/list + one tools/call" with a named flip. The merged plan dropped that gate and has no host-level test anywhere, so the requested "MCP server as the API" can ship as a server no host launches, degrading silently to CLI.
Edit: add to S7 or S13 an AC: launch under Claude Code and pi (Copilot if available), call `initialize`/`tools/list`/one `tools/call`, paste output; on protocol-shape failure apply R-A's flip (or P2-B3's `~/.local/bin` shim). If it cannot be automated, record it as an owner-performed acceptance check.

**4. SHOULD — `quick-task` is silently exempted from a request that explicitly names it.**
Plan: S10 only adds `quick-task/SKILL.md:54-56` = "Do not call `task-decomposition`…"; no §1 ruling. The request: "a new skill `task-decomposition`, used by the quick-task and task skills". P3/P2 justify the exemption (no plan artifact, six-bullet cap), but the plan's decisions table never records it and no owner-visible line states it.
Edit: add a DR ("quick-task stays decomposition-free; a change needing decomposition escalates") and one line in the owner-visible summary — or wire quick-task's minimal plan through a lightweight decomposition so the request is met literally.

**5. SHOULD — Jev's demotion to default-off advisory is hidden from the owner-visible trade-off summary.**
Plan: DR9 vs the summary paragraph ("the one real trade-off" = pydantic/uv). The request asks Jev to make model/parallel choices; the ruling makes both deterministic and Jev an opt-in, upgrade-only proposer. DR9 says the request is honoured because Jev is "kept, not cut", but a reader of the summary would not see that shipped defaults never call Jev.
Edit: add Jev to the owner-visible summary and require an explicit owner acknowledgement in the plan before dispatch (or default the advisory on with the serialize-safe gating).

**6. SHOULD — `plan_state` in DR8 is not one of the frozen twelve tools.**
Plan: DR8 ("`plan_state`/`progress_checklist` flag `integration_ok`") vs DR5's frozen names. `plan_state` is P1-A4's four-tool surface (with `plan_put`/`step_update`), deleted by DR5; §2 says every lane brief quotes the twelve.
Edit: replace with `progress_checklist` and/or `plan_get(include:"state")` in DR8; sweep the plan for any other surviving P1 tool names before lane briefs are written.

**7. SHOULD — the progress seam has two shapes and no pinned mapping.**
Plan: DR10 (progress_checklist primary; `status_report.py` fallback; `packages/checked/total` frozen) and S11's "tool-first wording" vs standing P2-B1 #12 (`progress_checklist` → `{task_id, plan_id, revision, complete, total, steps[{marker}], next[], blocked[], text?}`) and the script's `{plan_file, matched, packages[], checked, total}` plus four-section render.
Evidence: S11 AC(3) freezes the script's keys but nothing pins how an agent renders the tool output into the "Progress checklist" section — the two paths can render differently, and `next`/`blocked` have no home in the four sections.
Edit: freeze the mapping in S11 — e.g., tool `format:"text"` is the section verbatim, script output is the fallback — and add a test asserting the SKILL's mapping against a fixture.

**8. SHOULD — the degraded/in-flight story is asserted, not tested, and missing the resume case.**
Plan: DR12 (no-server consumers hand-write the plan file + manual checkboxes; in-flight `**P<N>**` plans keep reporting), S9/S10/S11 ACs; S13's integration test exercises the server path only.
Evidence: no gate exercises a hand-written fallback file parsing under `STEP_RE`, and nothing states what manual semantics replace failed/forced/blocked/join-enforcement. The standing P2 caller map says `task` calls `plan_get` on entry; for a resumed pre-rollout task there is no row, and neither S9's reference nor S10's rewrite says `not-found → legacy plan file, never `plan_create` over an in-flight task`.
Edit: add one fallback fixture (skill-written plan file → `status_report` renders it; multi-sink without join flagged) to S9/S11, and an S10 sentence + pin-test row for "no plan row → legacy file, manual checkboxes".

**9. SHOULD — the CLI contract is never frozen, though it is the load-bearing transport.**
Plan: DR3 freezes the server command and §2 freezes tool names, but the CLI's invocation form and subcommands appear nowhere; S7 tests "CLI ≡ MCP" without a named CLI surface, and S9's `mcp-plan-tools.md` is what a fresh agent uses in worktree sessions where no `.mcp.json` exists (P1 measured).
Edit: freeze in §2: `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_cli.py <tool-name> --json`, twelve verbs matching the tool names, and assert the reference documents all twelve.

**10. SHOULD — `effort` collides between the task loop and the step field, and S10's rewrite map doesn't touch the affected lines.**
Plan: DR6 (`loop` low|high on `TaskPlan`; `Step.effort` low|medium|high) vs `task/SKILL.md:6,41-45,134,166,169,366`, which still say "effort (low/high) picks the loop". S10's line list rewrites `:67-68` and `:206` but not `:44,134,166,169,366`; line 134's "`effort` (low/high) picks the loop; `level` picks the model tier" now reads as a direct contradiction of the step schema.
Edit: extend S10's rewrite map and pin test to require the disambiguation ("task `loop` (low|high) vs step `effort` (low|medium|high) → model tier"), including the Model tier contract section.

**11. NIT — S9's contract test is content-blind and blind to the `spec.json` seam.**
Plan: S9 AC(1) asserts "the five contract sections" (undefined; P3-C1's skeleton has ~8 headings and a five-rule method), and P3's D8 side-by-side `spec.json` input appears nowhere in the merged plan, its freeze, or any AC.
Edit: enumerate the exact headings/rules the contract test pins (or pin the five rule names), and restate D8 (`spec.json` stays requirements; the plan consumes it) in §1 or S9 with one coverage rule: every non-deferred spec scenario maps to ≥1 step AC.

**12. NIT — S5 leaves the module name open (`task_plan_model.py` "or `task_graph.py` sibling") in a step S7 imports from and S9 documents.**
Edit: pick the sibling name now; S5's Files line and S7's imports/docs depend on it.

**13. NIT — gate commands mix bare `pytest`/`python3` with the repo's `.venv/bin/python3` invariant (`invariants/local/venv-python.md`).**
Edit: normalize every Gate/AC command in §3 to `.venv/bin/python3 -m pytest …` (or the verify.sh lane), so a lane brief copies a working command.

**14. NIT — R-B overstates offline usability: the CLI shares the pydantic import, so a cold uv cache/network blocks it too.**
Plan: R-B ("CLI+degraded file path keeps `task` usable offline"); DR2's PEP 723 fetch is the first-run requirement for both transports.
Edit: correct R-B to "warm uv cache; one networked first run, or the hand-written file path", and say that in S9's fallback reference.

**15. NIT — `declare: true` with an unmet `uv` prerequisite ships a dead server into every consumer's MCP config, and S8 AC(3)'s "(or the unmet-prerequisite note)" doesn't say which behavior is expected.**
Plan: DR3 (`declare: true`), S8 AC(3); `features/common/dependencies.json` entries are reported, never installed.
Edit: pin the expected scaffold behavior in the AC (declare regardless + prerequisite note, or availability-gated omission) and test it on a scratch fixture with `uv` absent from PATH.

## Still open

- Does the owner accept (a) quick-task's exemption, (b) Jev as default-off advisory rather than the chooser? Both are request deltas that only the requester can ratify.
- Which host(s) can actually run the manual MCP smoke here (Claude Code / pi / Copilot), and what is the fallback if none can be automated?
- Should the S9 self-scaffold land in S9 (my recommendation, to keep pushes green) or should the plan instead accept a `VERIFY_SKIP=scaffold` window until S13? The plan currently implies neither.

Verdict: **PROCEED AFTER MUSTS** — fix F1 (re-scaffold argv/order), F2 (Jev transport signature), F3 (host smoke); the rest are SHOULD/NIT and can be folded before lane briefs.