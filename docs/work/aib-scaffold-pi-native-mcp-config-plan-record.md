# Plan record — aib-scaffold-pi-native-mcp-config

**Provenance.** The plan below is the orchestrator's reconstruction of delegation d-32's
(architect) returned plan JSON: the harness cache truncated the answer head (30,756 chars,
including the JSON) and it is not recoverable from disk. The reconstruction combines the
brief's mandated shape with the architect's **verbatim rationale tail** (reproduced below),
which encodes every decision the JSON carried (step split, rejected alternatives, H1/H2
verdicts, MUST risks). Deviations from the architect's exact payload are possible in
instruction wording only — the plan-review lane's brief explicitly attacks this reconstruction.
The plan was recorded via `plan_create` (validated by the same `PlanCreateInput` model the
architect validated against).

## The plan (recorded as revision 0)

```json
{
  "task_id": "aib-scaffold-pi-native-mcp-config",
  "task_description_ref": "docs/work/aib-scaffold-pi-native-mcp-config-research.md",
  "research_ref": "docs/work/aib-scaffold-pi-native-mcp-config-research.md",
  "loop": "low",
  "task_context": "Scaffold pi-native .pi/mcp.json (write where pi 0.99.1 actually reads MCP config) with F10/F11/F11a merge semantics; stop claiming the retired pi-mcp-tools fork reads .mcp.json; harden mcp-plan-tools.md to pi's exact call form. Top-level criterion: all steps' ACs are checked and met. Evidence: docs/work/aib-scaffold-pi-native-mcp-config-research.md (F1-F11a); plan provenance and the architect's rationale: docs/work/aib-scaffold-pi-native-mcp-config-plan-record.md. Version 0.183.0 is assigned to this task (s4 owns the bump). Orchestrator dispatches lanes; each lane reports per-AC evidence (command + output) and pastes TDD RED output.",
  "source_refs": [
    "features/common/stack-mcp.json",
    "skills/welcome-ai-badger/scripts/mcp_tools.py",
    "/Users/arasz/.bun/install/global/node_modules/@earendil-works/pi-coding-agent/docs/mcp.md",
    "docs/work/aib-scaffold-pi-native-mcp-config-research.md"
  ],
  "steps": [
    {
      "id": "s1",
      "goal": "Scaffold pi-native .pi/mcp.json with F10/F11/F11a merge semantics, and retire the fork-era .mcp.json reader claim",
      "instructions": "TDD end to end (failing test first, paste RED output). You own the scaffolder's MCP write path. Context you must verify before fixing: research record docs/work/aib-scaffold-pi-native-mcp-config-research.md (F1-F11a) in the repo root you were given.\n\nWhat to build, in features/common/skills/welcome-ai-badger/scripts/mcp_tools.py + scripts/scaffold.py (call site scaffold.py:744-749):\n1. A new McpDestination writing .pi/mcp.json (label '.pi/mcp.json', readers=('pi',), requires_reader=True: written only when 'pi' is in config.agents; only project-scoped servers, exactly like generate_mcp.json splits scope). Merge into the 'mcpServers' mapping via the existing _merge_mcp_servers_json machinery where compatible, but the pi destination's merge semantics are F10/F11/F11a (below) and override the usual section.update(entries) rewrite.\n2. New-entry template shape (F4/F8): base declarations are SHELL STRINGS ('uv run --script ...', 'code-review-graph serve', 'npx -y @playwright/mcp@latest') — pi requires a single executable + args, so split with the existing split_on_whitespace/_render_entry path (it already splits when 'args' is absent — pin this for the pi destination with a named test). User-tool-dir executables render in ~/-form (~/... prefix — pi expands ~ in command/args/cwd only; ${HOME} stays literal and must never be emitted). The AI_BADGER_MCP_AVAILABILITY determinism override must gate the ~ rewrite exactly as it gates the ${HOME} one (_home_relative_command). Drop the fork 'tools' array (all_tools=False). Add \"exposure\": \"direct\" on every NEW entry (hardcoded destination default — schema forbids a per-server exposure key). Never carry the claude agentOverride's ${CLAUDE_PROJECT_DIR} anchor: resolve agentOverrides for the destination's own reader ('pi') so the base, unanchored declaration renders.\n3. Merge semantics (F10/F11/F11a — the acceptance contract): (a) an entry already present in .pi/mcp.json survives re-scaffold BYTE-IDENTICAL (whole entry, command/args/env/cwd included — template shape governs new entries only; when today's template would render differently, emit a note, never rewrite); (b) new declared servers are appended with the template; (c) entries the scaffold does not recognize (user-added servers) survive untouched — merge is a union, never a drop; (d) config.mcp.decline still removes its named servers with a note (#186); (e) the unavailable-removal path keeps its shape gate, where shape = template identity (command/args/env/cwd as rendered) and decorations (exposure/toolExposure/enabled) neither shield a template-identical entry from removal nor count toward identity — a tuned-but-dead server is removed with a note; (f) a hand-edited launch (not template-identical) is a user edit: kept with a warn-and-leave note, never destroyed. Build the removal comparison template through the SAME home-rewrite path the write uses, or ~-form entries never match and linger (architect MUST-risk 1).\n4. Retire the fork-era claim (F2): remove 'pi' from MCP_JSON.readers and the EXPANDS_HOME_ONLY fork carve-out (or leave the mechanism inert if removing it churns more than it cleans — your call, say which). Consequence (documented behavior change, report it for s4's changelog): with claude+pi configured, .mcp.json goes back to Claude's ${CLAUDE_PROJECT_DIR} anchor and the fork-era 'dropped for pi' note disappears. Replace the fork-era tests (test_mcp_json_carries_the_project_relative_launch_when_pi_is_configured and siblings) with test_mcp_json_keeps_claudes_anchor_with_pi_configured.\n5. Record every .pi/mcp.json write through ctx.record_generated_config (generatedConfig manifest, #194) and note the trust gate once per run (pi reads .pi/mcp.json only in trusted projects; headless with defaultProjectTrust ask|never skips it).\n\nTest list (tests/test_stack_mcp_servers.py, names may improve): test_pi_mcp_json_written_for_pi_agent; test_pi_mcp_json_not_created_without_pi_agent; test_pi_mcp_json_splits_shell_string_command; test_pi_mcp_json_uses_tilde_home_form_not_dollar_home (incl. AI_BADGER_MCP_AVAILABILITY=all override); test_pi_mcp_json_carries_no_tools_array; test_pi_mcp_json_new_entries_default_to_direct_exposure; test_pi_mcp_json_inherits_no_claude_anchor; test_mcp_json_keeps_claudes_anchor_with_pi_configured; the F11a fixtures: test_pi_native_existing_entry_survives_scaffold_byte_identical, test_pi_native_new_entry_gets_template, test_pi_native_unknown_entry_survives, test_pi_native_declined_server_removed, test_pi_native_unavailable_tuned_entry_removed, test_pi_native_unavailable_hand_edited_entry_kept_with_note; test_pi_native_second_render_leaves_file_bytes_unchanged (entry-level identity + idempotent bytes — architect MUST-risk 3: F11 is entry-level deep equality; the writer's re-serialization is accepted, pinned here); test_pi_mcp_json_records_generated_config.\n\nFiles you own: features/common/skills/welcome-ai-badger/scripts/mcp_tools.py, features/common/skills/welcome-ai-badger/scripts/scaffold.py, tests/test_stack_mcp_servers.py, and their plugin mirrors skills/welcome-ai-badger/scripts/{mcp_tools.py,scaffold.py} (regenerate with python3 tooling/sync_plugin_skills.py — never hand-edit skills/). Do NOT touch: features/common/support.json, features/pi/instructions/, features/common/skills/task-decomposition/, VERSION, docs/changelog/ (other steps own these). Commit as you go (small commits); run the pre-push gate set before pushing and treat a red gate as step work. Report per-AC evidence, the pasted RED output, what you rejected and why, and the .mcp.json behavior-change sentence for the changelog.",
      "effort": "medium",
      "persona": "api-engineer",
      "depends_on": [],
      "files": [
        "features/common/skills/welcome-ai-badger/scripts/mcp_tools.py",
        "features/common/skills/welcome-ai-badger/scripts/scaffold.py",
        "tests/test_stack_mcp_servers.py",
        "skills/welcome-ai-badger/scripts/mcp_tools.py",
        "skills/welcome-ai-badger/scripts/scaffold.py"
      ],
      "acceptance_criteria": [
        {
          "id": "ac1",
          "statement": "A pi-configured project gets .pi/mcp.json whose NEW entries are template-shaped: shell-string commands split into command+args, user-tool-dir executables in ~/ form (never ${HOME}), no tools array, \"exposure\":\"direct\", no ${CLAUDE_PROJECT_DIR} anchor; not written when pi is not configured",
          "check": "python3 -m pytest -q tests/test_stack_mcp_servers.py -k 'pi_mcp_json'"
        },
        {
          "id": "ac2",
          "statement": "F11a merge fixtures pass: existing entries survive byte-identical (entry deep-equal, second render idempotent), new entries get the template, unknown entries survive untouched, declined servers removed, unavailable+template-identical removed despite tuned decorations, unavailable+hand-edited-launch kept with a note",
          "check": "python3 -m pytest -q tests/test_stack_mcp_servers.py -k 'pi_native'"
        },
        {
          "id": "ac3",
          "statement": "The whole test file plus the Claude adjustment tests are green, and no code claims the retired fork reads .mcp.json (readers/EXPANDS_HOME_ONLY fork carve-out retired or inert)",
          "check": "python3 -m pytest -q tests/test_stack_mcp_servers.py tests/test_adjust_mcp_claude.py"
        },
        {
          "id": "ac4",
          "statement": "Plugin mirror synced from features/ so the pre-push plugin-skills-sync gate passes",
          "check": "python3 tooling/sync_plugin_skills.py --check"
        }
      ]
    },
    {
      "id": "s2",
      "goal": "Make the framework's pi MCP mechanism claims honest (support.json + pi instructions)",
      "instructions": "Rewrite-first TDD: tests/test_support_json_honesty.py currently pins the RETIRED fork claims (e.g. 'session_start', '${HOME} expanded' in the pi mechanism text) — update the test expectations to the native contract first, run it, paste the RED output, then rewrite the source text. Changes: (1) features/common/support.json — the pi entry's mechanism/scaffoldedBy strings must state the native contract: config in ~/.pi/agent/mcp.json (global) and .pi/mcp.json (project, trust-gated), scaffold-written by this framework's pi destination with merge semantics (existing entries preserved byte-identical, new entries templated with \"exposure\":\"direct\", tuning survives re-scaffold); .mcp.json is Claude Code's / Copilot CLI's and is not read by native pi; tools are named mcp__<server>__<tool> with the codemode|codemode-deferred|deferred|direct|hidden exposure model. No 'pi-mcp-tools fork reads .mcp.json' claim anywhere in support.json. (2) features/pi/instructions/pi.instructions.md — the MCP bullet gains one sentence: ai-badger scaffolds .pi/mcp.json (preserving existing entries and their exposure/toolExposure tuning across re-scaffold); keep the 'Measured against pi 0.99.1' provenance line accurate (do not broaden its claims). Evidence source: docs/work/aib-scaffold-pi-native-mcp-config-research.md F1/F4/F10/F11. Files you own: features/common/support.json, features/pi/instructions/pi.instructions.md, tests/test_support_json_honesty.py. Do NOT touch anything else (mcp_tools.py, skills/, docs/changelog are other steps'). Report per-AC evidence, the pasted RED output, and a one-line summary of wording changes for s4's changelog.",
      "effort": "low",
      "depends_on": [],
      "files": [
        "features/common/support.json",
        "features/pi/instructions/pi.instructions.md",
        "tests/test_support_json_honesty.py"
      ],
      "acceptance_criteria": [
        {
          "id": "ac1",
          "statement": "test_support_json_honesty.py pins the NATIVE claims and is green (rewrite-first discipline: RED output pasted before the rewrite)",
          "check": "python3 -m pytest -q tests/test_support_json_honesty.py tests/test_support_catalog.py"
        },
        {
          "id": "ac2",
          "statement": "No fork-era claim survives in support.json's pi strings",
          "check": "! grep -q 'fork reads' features/common/support.json"
        }
      ]
    },
    {
      "id": "s3",
      "goal": "Harden mcp-plan-tools.md's call example to pi's exact call form",
      "instructions": "In features/common/skills/task-decomposition/references/mcp-plan-tools.md the 'A worked example, both ways' MCP block shows raw JSON-RPC tools/call lines with bare tool names ({\"name\":\"step_start\",...}) — a wire form no host exposes and the exact surface that invites invented names like mcp_task_graph_step_start. Rewrite that block to pi's exact call form: the declared tool mcp__task-graph__step_start called with the same JSON arguments, all six example calls spelled mcp__task-graph__<tool>. State the precondition in one line: tools reach the model under that name only when the server entry carries \"exposure\":\"direct\" (the codemode default leaves them undeclared — reachable from codemode scripts or via tool_search). Keep at most one clearly-labelled generic JSON-RPC line for non-pi MCP hosts if it still earns its place; the bare-name JSON-RPC block goes. Mirror: after editing, run python3 tooling/sync_plugin_skills.py (the file ships to skills/task-decomposition/references/). Evidence: research record F9. Files you own: features/common/skills/task-decomposition/references/mcp-plan-tools.md and its mirror skills/task-decomposition/references/mcp-plan-tools.md (regenerated, never hand-edited). Do NOT touch other files. Docs gates (validate) must pass. Report per-AC evidence and any wording you deliberately kept.",
      "effort": "low",
      "depends_on": [],
      "files": [
        "features/common/skills/task-decomposition/references/mcp-plan-tools.md",
        "skills/task-decomposition/references/mcp-plan-tools.md"
      ],
      "acceptance_criteria": [
        {
          "id": "ac1",
          "statement": "The six example calls show pi's exact form mcp__task-graph__<tool> and the exposure:\"direct\" precondition is stated",
          "check": "grep -q 'mcp__task-graph__step_start' features/common/skills/task-decomposition/references/mcp-plan-tools.md"
        },
        {
          "id": "ac2",
          "statement": "Plugin mirror synced and the docs/validation gates pass",
          "check": "python3 tooling/sync_plugin_skills.py --check && python3 tooling/validate.py --all"
        }
      ]
    },
    {
      "id": "s4",
      "goal": "Join: mirrors + self-scaffold, track this repo's .pi/mcp.json, release 0.183.0, run the gates on the combined tree",
      "instructions": "This is the join step — s1, s2 and s3 each ran against their own tree; the COMBINATION is untested until here (review the join, not just the parts). On the merged tree: (1) re-run python3 tooling/sync_plugin_skills.py and the self-scaffold refresh so skills/ and .ai-badger/ mirror the features sources (pre-push scaffold-freshness-guard and plugin-skills-sync must pass); (2) materialize this repo's .pi/mcp.json from the new destination and TRACK it (H1 decision: portable content — split commands, ~/ form, project-relative args; if you find a reason to gitignore instead, stop and report, do not decide silently); (3) release ritual: set VERSION to 0.183.0 (assigned at dispatch), write docs/changelog/0.183.0-scaffold-pi-native-mcp-config.md — it must state the F10/F11/F11a merge semantics (existing .pi/mcp.json entries and their exposure/toolExposure tuning survive re-scaffold; user-added servers never dropped), the .mcp.json behavior change (claude's ${CLAUDE_PROJECT_DIR} anchor restored when pi is configured; fork-era 'dropped for pi' notes gone), and the sibling-reported motivation (a tuned consumer cut 55 of 106 declarations from every prompt; a flattening scaffold would have restored them all) — then run python3 tooling/changelog_index.py and python3 tooling/version_sync.py; no BREAKING_VERSIONS entry (architect SHOULD-7). (4) Cross-step gate runs on the merged tree, each as evidence: full pytest, validate --all, index_build --check. Report per-AC evidence with commands and outputs, plus anything the join exposed that the per-step runs could not see.",
      "effort": "low",
      "persona": "api-engineer",
      "depends_on": ["s1", "s2", "s3"],
      "files": [
        "VERSION",
        "docs/changelog/0.183.0-scaffold-pi-native-mcp-config.md",
        "docs/changelog/README.md",
        ".pi/mcp.json",
        "skills/",
        ".ai-badger/",
        "plugin.json",
        "marketplace.json"
      ],
      "acceptance_criteria": [
        {
          "id": "ac1",
          "statement": "Mirrors and self-scaffold are fresh on the merged tree",
          "check": "python3 tooling/sync_plugin_skills.py --check && python3 tooling/index_build.py --check"
        },
        {
          "id": "ac2",
          "statement": "Release artifacts are consistent at 0.183.0 with the changelog present",
          "check": "test \"$(cat VERSION)\" = \"0.183.0\" && test -f docs/changelog/0.183.0-scaffold-pi-native-mcp-config.md && python3 tooling/version_sync.py --check"
        },
        {
          "id": "ac3",
          "statement": "The merged tree passes every gate — the cross-step tests (full suite) and validate are green together, which no per-step run measured",
          "check": "python3 -m pytest -q && python3 tooling/validate.py --all"
        },
        {
          "id": "ac4",
          "statement": "This repo's .pi/mcp.json is materialized, valid JSON and tracked",
          "check": "git ls-files .pi/mcp.json && python3 -m json.tool .pi/mcp.json >/dev/null"
        }
      ]
    }
  ]
}
```

## The architect's rationale tail (verbatim from d-32's cached answer)

> plan itself already carries the full failing-test list (this task's requirement); the red
> state is transient inside TDD, and splitting would force `tests/test_stack_mcp_servers.py`
> to serialise across two lanes for no independent verification — the second lane would just
> run the first's tests. One lane, `api-engineer`, TDD end to end.
> - **Rejected: a separate "run the gates" step.** The decomposition contract: a step whose
>   only content is running a gate is an acceptance criterion, not a step. The gates are s4's
>   ACs.
> - **Cheap lanes** are encoded as `effort: "low"` (per the task skill, effort resolves to the
>   level tier when no `level`/`model` pin is present), so no explicit model pin was added.
>
> ## H1 / H2 verdicts
>
> - **H2 — settled: no schema change.** `stack-mcp.schema.json` rejects unknown per-server keys
>   (`additionalProperties: false` on the server item and on `agentOverride`), so a per-server
>   `exposure` plumbed through declarations would fail `tooling/validate.py --all`. The tuning
>   path F10 actually needs is the *file plus merge preservation*, not a declaration key.
>   **Decision: hardcode `"exposure": "direct"` on the pi render for new entries.**
> - **F11's H2 (the shape gate) — confirmed and kept.** `_drop_unavailable` already exists and
>   is shape-gated; F11a pins "shape" as template identity (`command/args/cwd/env`), with
>   `exposure/toolExposure/enabled` as decorations that survive rewrites but do not shield a
>   template-identical entry from the explicit unavailable-removal path. The plan's two F11a
>   fixture tests pin both directions (e-tuned → removed; hand-edited launch → kept with a
>   note).
> - **H1 — confirmed, with a decided outcome.** `.pi/mcp.json` *will* be materialized by the
>   next self-scaffold here: `.ai-badger/config.json` lists the `pi` agent, and the guard
>   re-scaffolds with `AI_BADGER_MCP_AVAILABILITY=all`. `.pi/` is not in
>   `tooling/release_paths.py`'s `SHIPPED_PATHS`, so it is scaffold output, not shipped
>   surface. `.gitignore` currently ignores only `.mcp.json`/`.mcp.json.bak-*`
>   (machine-specific `cwd`, #173); `git check-ignore .pi/mcp.json` says *not ignored*, and
>   `.pi/agents/*.md` are already tracked. The guard's `ignored_in` exemption means either
>   choice keeps it green; **decision: track/commit it**, because the destination renders
>   portable content (no cwd, `~` commands, project-relative args) and the consumer precedent
>   (pi-badger-integration) is a tracked `.pi/mcp.json`. If the implementer disagrees, it must
>   stop and report, not silently gitignore.
>
> ## MUST-level risks a reviewer should attack
>
> 1. **MUST — removal identity math.** If the unavailable path compares whole entries, a
>    tuned-but-dead entry lingers (fails F11a fixture e); if it compares too loosely (e.g.
>    command only, or ignores `args`), a hand-edited launch is destroyed (fails fixture f). It
>    must also build the comparison template through the *same* home-rewrite path the write
>    uses, or `~`-form entries never match and linger. The two named tests are the gate.
> 2. **MUST — `.mcp.json` behavior change.** With `claude`+`pi`, `.mcp.json` goes back to
>    Claude's `${CLAUDE_PROJECT_DIR}` anchor, and the fork-era "dropped for pi" note
>    disappears. Intended (the fork is retired) and covered by the replaced
>    `test_mcp_json_keeps_claudes_anchor_with_pi_configured`, but the changelog must state it;
>    the reviewer should confirm no consumer other than the sibling relies on the old file
>    content.
> 3. **MUST — "byte-identical" vs the writer.** `cg.write_json_with_backup` re-serializes
>    `indent=2` without `sort_keys` and only skips the write on exact-text equality
>    (`config_guard.py:70-81,113`). F11 is satisfied at *entry* level (deep-equality
>    assertion); a hand-formatted file will still be reformatted. The named tests pin entry
>    identity plus a second same-writer render leaving file bytes unchanged. Reviewer decides
>    whether F11 demands literal file bytes.
> 4. **SHOULD — pinned honest test was not in the proposed file list.**
>    `tests/test_support_json_honesty.py` currently pins the *fork* claims (`session_start`,
>    `${HOME} expanded`) and would go red the moment s2 rewrites `support.json`. The plan gives
>    it to s2 with a rewrite-first TDD order. Likewise `test_support_catalog.py` forces
>    `configPath` (not `scaffoldedFile`) so no `features/pi/scaffolding.json` edit is needed.
> 5. **SHOULD — user-scope pi servers.** No catalog server is `scope: user` today, so no pi
>    user proposal path is added; if a future catalog adds one it becomes a silent no-op
>    (ADR-0014 decision 6 respected). Flagged, deliberately not in scope.
> 6. **SHOULD — default `exposure: direct` for new entries** declares every tool on first
>    render; F11a fixture (b) pins it and F10 tuning happens in the file afterwards (which the
>    merge then protects). Changing the default contradicts the record.
> 7. **SHOULD — release classification.** Minor bump 0.183.0, no `BREAKING_VERSIONS` entry:
>    existing consumers keep working, the fix reaches them on the next `den-refresh`. If the
>    reviewer rules the `.mcp.json` content change a required re-scan, the bump/
>    `BREAKING_VERSIONS` decision changes.
>
> ## Hypotheses left labelled (not verified)
>
> - The exact flag plumbing (a new `exposure` column + replacing `expand_home: bool` with a
>   home-prefix value) is a *suggested* implementation shape; the requirement is the emitted
>   behavior. An implementer may choose an equivalent column arrangement.
> - `~` expansion in pi also covers an *argument* per pi docs; the plan rewrites only the
>   executable (no declaration carries a `~/` argument), and leaves argument rewriting as
>   unnecessary scope.
> - H3 (`features/pi/adjustments/adjust_mcp.py` / `pi_settings.py` fork machinery) is
>   untouched, as the record requires.

## Review inputs beyond the plan

- Sibling review of the record (bus #1601, folded as commits): **MUST** — base declarations
  are shell strings; the pi render must split `command`+`args` (`split_on_whitespace`), emit
  `~/`-form, and never inherit the claude `${CLAUDE_PROJECT_DIR}` anchor (F8 corrected).
- F11a shape definition (bus #1597/#1599, adopted): template identity
  (`command/args/cwd/env`) vs decorations (`exposure/toolExposure/enabled`); fixtures (a)–(f).
- Sibling's split-tuning reference state (bus #1593): 3 direct + 2 deferred — the merge must
  preserve it across re-scaffold.
