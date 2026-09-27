# Plan review round 2: feasibility and simplicity (rev 3 additions)

Plan: `.ai-badger/worktrees/aib-ai-raccoon-prompt-rag-hook/docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-plan.md` (rev 3). Source read at main `4abf5ade`. The owner rulings table is treated as binding. Nothing below reopens O-1..O-7 or the Budget row.

**Result: 1 MUST, 5 SHOULD, 4 NOTE.**

---

## MUST

### F1. Copilot branch A cannot ship `timeoutSec` 100: the adjuster hard-codes 10
- **Plan section:** §1.4 Copilot branch A says "`timeoutSec` 100 | manifest only". §1.2, W2b/I5 and the P4 Files list do not name `features/copilot/adjustments/adjust_hooks.py`.
- **Evidence:** READ. `features/copilot/adjustments/adjust_hooks.py:145-149` builds every Copilot entry that has a source command as `{"type":"command","bash":…,"timeoutSec": 10}`. It never reads the source hook's `timeout`. The discovery path uses a literal `5` at `:176`. With a manifest-only change, the generated `.github/hooks/ai-badger-hooks.json` carries `timeoutSec: 10`. W2b/I5 (`timeoutSec` > 90.5) then fails on correct plan steps, or ships a Copilot hook that the host kills after 10 s, well before the 90 s pipeline finishes.
- **Fix:** In branch A, add an adjuster edit to P4. Carry the source hook's `timeout` into `timeoutSec`, for example `"timeoutSec": h.get("timeout", 10)`. That derives the value instead of adding a second literal. The existing entries all say `timeout: 10` (MEASURED: every `timeout` in `features/common/hooks/hooks.json` is 10), so their output does not change. Put the adjuster in the P4 Files list and in §1.4. Name `tests/test_adjust_hooks_copilot.py` in P4's gate and add a row that pins the carried value. P1.2 already edits this file, so keep the order P1 before P4.

---

## SHOULD

### F2. Parallel lanes cannot be "pushed per package" and still be green on pre-push
- **Plan section:** §4 intro ("pushed per package"; "every package boundary is green on pre-push"), §4 "Generated outputs are serialized", Q1 ("Closing step" inside the lane; acceptance "pre-push green"), P1.7/P2.5 closing step inside lanes that run in parallel.
- **Evidence:** READ. `.ai-badger/manifest.json:481-495` stores one directory `hash` and a `file_count` for `.ai-badger/skills/ai-raccoon-memory`. Every lane that adds a file under that skill (P2, Q1, Q2a, Q2b, Q2c) rewrites the same line, so two lanes' closing steps always conflict there. P1's VERSION bump also rewrites `frameworkVersion` in every manifest entry. If a lane skips the closing step, `sync_plugin_skills --check` and the scaffold-freshness lane of pre-push fail, so the lane cannot push.
- **Fix:** Say it once in §4: parallel lanes commit locally and never push. Only the integrating session runs the closing step and pushes, once per merge. Remove "Closing step" from Q1's lane steps and "pre-push green" from each lane's acceptance. Put both in a per-merge integration checklist instead. Everything else in §5 is file-disjoint as claimed (READ).

### F3. The sibling-load derive test does not see the pipeline modules or `model_groups.py`
- **Plan section:** §7 (Hermes rows: "+6 rows each"), P3 acceptance ("the sibling-load derive test … passes").
- **Evidence:** READ. `tests/test_hermes_plugin_install.py:400-436` builds `wanted` only from `_load_sibling_module(…, "x.py")` calls in `ai_badger_hooks.py`. The plan loads the four pipeline siblings and `model_groups.py` from `memory_context.py` with its own loader. That loader fails open to single-search (§9.2, B13). So a missing `SHARED_SKILL_MODULES` row would silently turn Hermes into single-search. The derive test cannot catch it, and W8, I9 and I11 are hand-enumerated rows. This is the "registered with no agent" shape.
- **Fix:** Extend the derive test to also scan `memory_context.py` for its by-path sibling names. For example, one module constant `SIBLINGS = ("openrouter_client.py", …, "model_groups.py")` that both the loader and the test read. Then assert every name is in the shipped set. This removes the need to trust the hand-written six rows.

### F4. Four pipeline modules plus a second ADR is more than the port needs
- **Plan section:** §1 module table, §9.1, §12 "One pipeline file instead of four", Q0.1.
- **Evidence:** INFERRED from the plan's own numbers (~120 + 250 + 250 + 220 lines). The binding rulings table does not require parallel Q2a/Q2b/Q2c lanes; §12 cites "the owner expects" without a ruling. `openrouter_client.py` is a real boundary: S1's static rule keys on it. The planner, Jev and runner modules are all effect-free consumers of injected callables. Each extra file costs a Hermes row, a twin row, a mirror file, a `sys.modules` key and a B13 parametrization.
- **Fix:** Use three modules: `memory_context.py`, `openrouter_client.py`, and `query_pipeline.py` (planner, Jev, dedupe, merge, run; about 700 lines, one Q2 lane). The contracts in §5 stay the same and the tests stay per concern (separate test files can target one module). Hermes rows drop from 6 to 4. If the owner does want three parallel lanes, keep four modules but record that as a ruling rather than as a §12 inference.

### F5. Claude and Hermes behave differently when `task` is declined
- **Plan section:** §9.7 Consequences; §1.3 Hermes decline check.
- **Evidence:** READ. `task` is `scope: default` (`features/common/skills/task/SKILL.md`) and can be declined via `config.exclude`. On Claude the resolver is `.ai-badger/skills/task/scripts/model_groups.py` (the path arithmetic `Path(__file__).parents[1].parent/"task"/"scripts"` is correct: MEASURED against the scaffolded tree, where the file is byte-identical to the catalog). So declining `task` gives `no-model`, which falls back to single-search. On Hermes, `adjust_hooks.py:158-163,214-219` copies `SHARED_SKILL_MODULES` from the catalog unconditionally, so the same config runs the full pipeline and sends data to OpenRouter. The registry is always delivered (`model_registry.deliver` has no skill condition, READ), so only the resolver code differs.
- **Fix:** Pick one behaviour and pin it with a row. The simplest is to accept the difference and state it in SKILL.md for both agents: "Claude: declining `task` disables the planner unless the override is set; Hermes: unaffected". The alternative is to have the Hermes arm also require `<project>/.ai-badger/skills/task/` before choosing the pipeline. Add one I-row for whichever you choose.

### F6. `ENV_NAMES` is added in Q3, but P2's scrub fixture (G2) already depends on it
- **Plan section:** §7 env-switch row ("Scrub list is a module constant imported by the fixtures from `memory_context.py` (`ENV_NAMES`)"), Q3.2 ("add … `ENV_NAMES`"), Q1 ("extend the env scrub"), G2 (P2, scrubs `OPENROUTER_API_KEY` and the pipeline vars).
- **Evidence:** READ within the plan. In P2 the fixture has nothing to import. Q1 then "extends" the scrub by hand, which creates the twin §7 claims cannot exist.
- **Fix:** Define `ENV_NAMES` with all six names (`AI_BADGER_PROJECT_ID`, `AI_BADGER_MEMORY_CONTEXT`, `…_PIPELINE`, `…_PLANNER_MODEL`, `…_TEST_OPENROUTER_BASE`, `OPENROUTER_API_KEY`) in P2 as a constant. Q1 and Q3 then add nothing to the scrub. Proxy variables stay a separate fixture constant.

---

## NOTE

### F7. Claude `timeout: 100` is accepted and needed
- **Plan section:** §1.2, R-h, Q0.3/Q3.1.
- **Evidence:** READ, current Claude Code hooks doc (code.claude.com/docs/en/hooks), `timeout` row: "Seconds before canceling … Defaults: 600 for `command` … Claude Code lowers the `command` … default to 30 on `UserPromptSubmit`". No maximum is stated. A value of 100 is valid. The explicit value is required: without it, UserPromptSubmit cancels the hook at 30 s, which is below the 90 s pipeline. `hook_wiring.py:306-331` copies the hook dict (`dict(h)`), so `timeout` survives the rewrite (READ).
- **Fix:** Record this citation in Q0.3 now and downgrade R-h to resolved. Q3.1's stop condition cannot trigger. Add the "default 30 on UserPromptSubmit" fact to W2a's docstring so nobody deletes the explicit value as redundant.

### F8. The Hermes fallback path for the resolver points outside the plugin
- **Plan section:** §9.7 Mechanics of C.
- **Evidence:** INFERRED from the path arithmetic. In the plugin dir, `__file__ = ~/.hermes/plugins/ai-badger/memory_context.py`, so the second candidate is `~/.hermes/task/scripts/model_groups.py`. That path is harmless when absent, but it is outside the dir that W10 asserts on.
- **Fix:** Try the second candidate only when `Path(__file__).parent.name == "scripts"` (the Claude and catalog layouts). Otherwise a missing sibling means `no-model`.

### F9. The edit-sequence line disagrees with §9.8 on Q2c
- **Plan section:** §4.0 "Edit sequence" (`Q1 ∥ Q2c → Q2a ∥ Q2b`) versus §9.8 headings (`Q2a (∥ Q2b, Q2c)`, `Q2c (∥ Q1, Q2a, Q2b)`) and the §5 diagram.
- **Fix:** Use one statement: Q2c may run from P2+Q0 until Q3; Q2a ∥ Q2b after Q1.

### F10. ADR-0032 could be a second decision inside ADR-0031
- **Plan section:** C13, Q0.1.
- **Evidence:** INFERRED. Both ADRs cover the same hook and are written in parallel lanes that both touch `docs/adr/README.md` (§5 shared-file table). ADR-0031's consequences already have to mention planned-query search-log rows.
- **Fix:** Optional. Write one ADR with two numbered decisions (transport, pipeline). That removes one README row and the rebase hotspot. Keep two only if the proxy decision should be supersedable on its own.

---

## Checked and found sound
- **Where the Claude hook lands:** `.ai-badger/skills/ai-raccoon-memory/scripts/memory_context_hook.py` via the `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` → `${CLAUDE_PROJECT_DIR}/.ai-badger/skills/` rewrite (`hook_wiring.py:309-312`). Skill `scripts/` directories are copied whole. The scaffolded `task/scripts/model_groups.py` is byte-identical to the catalog (MEASURED `cmp`).
- **Loading `model_groups.py` by path:** it imports only stdlib (`datetime`, `json`, `re`, `warnings`, `pathlib`, `typing`), and `load_groups(path)`, `resolve(level=, groups=)` and `_emit_id` match the plan's references (READ `model_groups.py:14-21,289-358`).
- **`badger_store`:** `_nearest_project_id_file` exists in the sibling `badger_store.py`, which is identical to the hooks copy (MEASURED md5). In Hermes, `badger_store.py` is in `USER_PLUGINS`.
- **Plugin mirror and index:** `sync_plugin_skills` copies whole skill directories. `SKILL_EXCLUDE_PATTERNS` would not drop any of the new names. `index.json` lists skills, not scripts. None of these is a hand-kept twin.
- **Plugin-level hooks:** repo-root `hooks/hooks.json` holds only the drift notice, so the P3a command added before the P4 manifest row stays inert.
