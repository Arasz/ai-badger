# Plan review — API/structure lane (MoE) — aib-bus-followups-independence

2026-09-01 · Reviewer: api/structure (non-author). Basis: the join plan + architect/test/harness
appendices + research-a/b/c, verified against worktree HEAD c7424c6f. Method: read the four plan
files, then verified every finding's load-bearing claim in the repo (files/lines cited below).
The memory-first-gate hook notice on repo text search is expected and non-fatal (no memory_search
in this toolset); reads proceeded under that exception, same as research-c.

## MUST (fix before dispatch)

**M1 — P2's bank-fixture conversion list is incomplete; P2's own full-pytest gate cannot pass as scoped.**
Plan ref: join P2 file list (`tests/test_project_registry.py`, `test_send_message_skill.py:382`,
`test_message_bus_manifest.py :33/:68/:140-150`, `test_message_bus_hermes.py:345/:362`).
Wrong: the raccoon surface (`RACCOON_BANK_ENV`, `_make_bank`/`_register_bank` fixtures) is used by
test files the list never names. Evidence: `tests/test_message_delivery_hook.py:106-115`
(`_register_bank`) feeds `test_copilot_event_spellings_deliver`, `test_standalone_invocation_via_subprocess`
(env list at :662-671 also sets `env[RACCOON_BANK_ENV]`), and the Rule 8 owner
`test_subdirectory_cwd_resolves_to_the_project_via_the_resolver`; `tests/test_message_bus_hermes.py`
has a THIRD bank test, `test_project_delivery_resolves_the_process_cwd_through_the_registry` (~:330,
uses `_make_bank`), beside the two named; `tests/test_message_bus_manifest.py:405-417` sets
`env[RACCOON_BANK_ENV]` directly outside :140-150. Once P2 deletes the surface, all of these go red.
Fix: re-spec P2's conversion scope by symbol, not line pins — every `_make_bank`/`_register_bank`
definition and use site repo-wide (derive-or-delete), including the delivery-hook file and the
manifest subprocess test; add the now-inert `AI_BADGER_RACCOON_DB` entry in
`tests/js/pi_message_bus_adapter.test.mjs:228` (`e2eEnv`) to a lane's cleanup list.

**M2 — The Rule 8 owner-map repoint must move from P8 into P2, or the branch is red the moment P2 lands.**
Plan ref: join P8 ("Rule 8 titles + mutation-flag repoint :576/:579-581"); P2 AC (rename
`test_sender_project_resolves_from_the_raccoon_registry`).
Wrong: the sweep `test_every_non_deferred_spec_scenario_has_an_owner`
(tests/test_message_bus_integration.py:625-632) asserts `def <member>(` in each owner file — P2's
rename and rewrites of the Rule 8 owners (send CLI :382; hermes registry test; hook resolver test)
break the sweep on the integrated branch between P2 and P8, violating "green at every commit".
Evidence: owners block at tests/test_message_bus_integration.py:552-566 embeds the exact old names.
Fix: P2's commit repoints the Rule 8 owner entries it orphans; P8's duty shrinks to verifying the
map against the final spec wording. (P4's AC calling :576/:579-581 "Rule 7 mutation flags" is a
mislabel — they are Rule 8's; correct it while editing.)

**M3 — P2/P5 "disjoint regions" in test_message_bus_hermes.py is false at the semantic level.**
Plan ref: join P5 "Merge after P2 (shared test file, disjoint regions)"; plan-tests §3.
Wrong: P2's converted :345/:362 tests keep the `_start(hooks)` → `_turn(hooks)` shape and assert the
mail arrives in `_turn`'s context ("same 1:1 fail-open shape, kept"). P5 redefines `_start`
(:90-91) into the first-`pre_llm_call` delivery — the consuming call. Post-merge, `_start` consumes
and `_turn` is a second, empty live read: P2's fresh assertions fail. Evidence:
tests/test_message_bus_hermes.py:89-91 (`_start` = `on_session_start_message_delivery`), :330-385
(all three tests call `_start` then assert on `_context(_turn(hooks))`); harness §2 edit 3.
Fix: name the reconciliation — P5's scope explicitly includes re-timing P2's converted resolver
tests to the first-`pre_llm_call` sequence (or give one lane whole-file ownership of
test_message_bus_hermes.py). Also reconcile plan-tests §3's :362 mechanism ("nested-`.ai-badger`
refusal") with the join's retired-refusal ruling (see S1).

## SHOULD

**S1 — Appendices contradict the authoritative join on two ⚑-adjacent rulings.**
Plan ref: join decision register (walk policy: nearest wins, **no ancestor refusal**,
`ProjectIdAmbiguous` retires; arm env `AI_BADGER_TEST_HOLD_ARMED`).
Wrong: plan-architect still specifies "ancestor → raise `ProjectIdAmbiguous`" and
`AI_BADGER_TEST_HOLD_ARM`; plan-tests §3 R3b keeps both refusal shapes and derives :362's
conversion as a refusal mechanism. An implementer working from an appendix ships retired semantics.
Evidence: plan-architect decision table rows 4/9; plan-tests §3 R3b + :362 row vs join register.
Fix: stamp both appendices "superseded by the join on walk policy + arm-env name" at the top, and
delete R3b's refusal arm (keep R3a/R3c/R3d) so the test list matches the ruling.

**S2 — Nobody owns the consumer-facing docs that describe the deleted registry.**
Plan ref: join P6 (exact sentences: D5/D6 only), P8 (new changelog entry, content unspecified).
Wrong: `skills/send-message/SKILL.full.md:56-59` instructs users that projectId comes from "the cwd
resolver's read of the ai-raccoon registry" with refuse-on-multiple — false after P2, in the very
section P6 edits. The 0.156.0 changelog's P2/P3 bullets (:20-28) describe the registry mechanism,
and the NEW release entry has no assigned content for: registry removal, `AI_BADGER_RACCOON_DB`
disappearing (a consumer-visible env seam), the id-less-fleet state, the worktree note (R4).
Evidence: SKILL.full.md read; changelog read; P6/P8 scope lines. mcp-tools.json and
hooks-manifest.json intents need nothing (verified — the raccoon MCP server is a different surface;
hermes manifest arm removal is already P5's).
Fix: add to P6 the SKILL sender-identity paragraph rewrite (registry → `.ai-badger/project-id`
walk, nearest-wins) through the harness §5 mirror chain; give P8's changelog entry a required
content list (D2 consumer impact included).

**S3 — P3's budget line undercounts what "in-orchestrator" means for a store commit.**
Plan ref: join "Parallelism & order" ("In-orchestrator — P3 (one branch + strip lists)").
Wrong: P3 is a full store-lane commit: `_hold_at` gate + ~33-copy re-land + `sync_plugin_skills` +
vendored gate + six strip lists + two arming sites + NEW leak-witness test + full pytest — the same
ceremony as P1/P2, which are subagent lanes. Its strip-list line pins (manifest :83/:411, hook
:85/:671) also go stale because P2 rewrites those exact hunks first (verified:
test_message_bus_manifest.py:405-417, test_message_delivery_hook.py:662-671 carry both the bank env
P2 removes and the HOLD env P3 amends).
Fix: either dispatch P3 as a subagent lane like P1/P2, or correct the budget line and note the
strip-list sites must be re-located post-P2 by pattern, not line number.

**S4 — P8's lifecycle test is feasible but the plan omits the invocation contract it depends on.**
Plan ref: join P8 (test_project_id_lifecycle.py; "strip id → den-refresh backfill").
Wrong: nothing states how the test drives scaffold/den-refresh in a sandbox; research-a frames
den-refresh as running "from the framework at `$AI_BADGER`", which is the SKILL flow, not the
script contract. Evidence (verified): scaffold.py main takes `--config/--target/--root` +
`--no-install` (:784-800); refresh.py main takes `--root/--target` and autodetects only as fallback
(:309-330) — no `$AI_BADGER` dependency, `re_scaffold` runs with `install=False`. A throwaway-repo
lifecycle test works, but needs a crafted schema-valid config.json (frameworkVersion/project/
stacks/agents required) and explicit `--root` pointing at the repo.
Fix: one sentence in P8 naming the invocation shape (`scaffold.py --target <tmp> --config <crafted>
--root <repo> --no-install`; `refresh.py --root <repo> --target <tmp>`) so the lane doesn't
rediscover it or reach for env redirection.

## NOTE

- **N1 (verified safe):** P4/P3 shared-file claim holds. P3 edits test_message_bus_integration.py
  strip lists/_child_env (:75, :194-197); P4 edits the Rule 7 owner entry (:466-472) — disjoint
  hunks, P4's python gate passes pre-P3 (it does not exercise the arm gate), combined file green.
- **N2 (verified safe):** P4's adapter is decoupled from P2's resolver. The JS E2E resolves via
  `AI_BADGER_PROJECT_ID` override (tests/js/pi_message_bus_adapter.test.mjs:225-231), which P2
  keeps as highest precedence; no bank dependency, no hidden cwd coupling (hook probes
  `$CLAUDE_PROJECT_DIR` else payload cwd, event-independent).
- **N3:** P4 retiming the :266 E2E may change its test title; the Rule 7 owner entry embeds the
  title string verbatim (integration :466-472, `.mjs` owners matched by `member in text`). P4 owns
  :466-471, but the plan should say explicitly: keep title and map string in one edit.
- **N4:** `ProjectIdAmbiguous` retirement leaves a dead refusal branch in send_message.py:148-151
  (ambiguous → exit 1). P2 rewrites the send CLI tests; fold the dead-branch removal into P2's AC
  so the surface and its contract retire together.
- **N5:** P1/P2/P5/P7 sizing claims check out against the cited files; P5's manifest hermes-arm
  removal (:178-179) is real (hooks-manifest.json message-delivery-session-start row verified).

## VERDICT

DISPATCH-READY-WITH-CHANGES

Must-fix before dispatch, all plan-text edits (no code change needed to decide them):
1. M1 — re-spec P2's conversion scope by fixture symbol (delivery-hook + hermes-:330 +
   manifest-subprocess + JS e2eEnv litter); P2's full-pytest gate depends on it.
2. M2 — move the Rule 8 owner-map repoint from P8 into P2's commit.
3. M3 — give P5 explicit ownership of re-timing P2's converted hermes resolver tests (or
   whole-file ownership of test_message_bus_hermes.py).

With those three amendments (plus the SHOULD stampings S1/S2), the package boundaries, merge
order, and budget are sound: the serial store lane is correctly ordered, the parallel lanes are
genuinely disjoint after M3, P8's integration package is feasible as verified, and no external
surface outside the named docs imports the retiring resolver API.
