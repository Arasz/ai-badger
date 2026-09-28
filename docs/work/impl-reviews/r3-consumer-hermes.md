# Implementation review — R3 (fresh-eyes consumer)

I walked the branch as a scaffolded consumer: read the skill and its three references, ran the declared CLI launch in a scratch project (warm cache, cold cache, forced-offline, no `uv`), ran every usage/error mode, rendered the Hermes proposal, and re-ran the delivery gates (`sync_plugin_skills.py --check`, `index_build.py --check`, `gates/skills_lint.py`, `gates/scaffold_freshness_guard.py` — all pass). Findings are about what a consumer actually experiences.

## Findings

**1. MUST — The skill points at `mcp-plan-tools.md` for "the exact input shape"; the reference contains no shape at all.**
`features/common/skills/task-decomposition/SKILL.md:31` and `:62` both say the exact input shape is in `references/mcp-plan-tools.md`. That file (`references/mcp-plan-tools.md:9-22`) is a "reach for it when" table plus error codes — no argument names, no example. The only JSON example anywhere in the shipped skill is none; the CLI form at `SKILL.md:142` / `mcp-plan-tools.md:29` is `<tool-name> --json <args>`.
What a consumer experiences on the CLI path (the only path for a Hermes user before merging the YAML proposal, and any host where the server isn't listed): error-driven discovery. Spot-run evidence in a scratch project:

```
$ task_graph_cli.py plan_create --json '{}'
findings: task_id, task_description_ref, steps, loop — "Field required"
$ ... '{"steps":[{}]}'      → steps.0.id/goal/instructions/effort — "Field required"
$ ... '{"steps":[{... "status":"pending"}]}'
findings: steps.0.status — "Extra inputs are not permitted"
```

Four round trips to learn the step shape; deriving it from `schemas/task-plan.schema.json` actively misleads (the stored `Step.required` includes `status`/`completed_at`, which the input model rejects). Under an MCP host the tool schema exists, so the promise is merely redundant; on the fallback path it is the one missing artifact.
Fix: add one worked `plan_create` JSON (two steps plus a join) and a per-tool argument-key list to `mcp-plan-tools.md`; or drop the "exact input shape" claim and say "the MCP schema, or iterate on `invalid-arguments` findings".

**2. SHOULD — `integration_ok` is claimed to be surfaced by `progress_checklist`; it is not.**
`SKILL.md:116` says `integration_ok` is surfaced by `progress_checklist` and `plan_get(include:"state")`. `progress_checklist_data()` (`scripts/task_graph.py:428-452`) never computes it, and the handler (`task_graph_server.py:679-696`) doesn't add it. I ran it: payload keys are `blocked/complete/next/revision/steps/task_id/text/total`. Only `plan_get(include:"state")` returns it (`task_graph_server.py:636-638`).
A consumer verifying the join rule from the status view (the obvious place to look) finds no signal. Fix: add `integration_ok`/`integration_sink` to the checklist payload (and text header), or correct the sentence.

**3. SHOULD — Plan-quality findings are computed but no tool surfaces them; `plan_create` accepts a step with zero ACs.**
`task_plan_model.py:300-307` builds `step_without_acs` findings and `task_graph.py:416-424` adds `integration_missing` — nothing in the 12 tools returns them. Spot-run:

```
$ plan_create --json '{"...","steps":[{"id":"s1","goal":"g","instructions":"i","effort":"low","acceptance_criteria":[]}]}'
{ "created": true, "revision": 0, "steps": 1, ... }   exit 0
```

The skill says "there is no step without a check" (`SKILL.md:72-74`) and stop rule 5 makes it a stop condition (`:104-106`), but the server stores the plan and the rendered file shows `**S1 — g (pending)**` with no criteria. The one place (`plan_create` payload) where a finding would land says nothing.
Fix: return `findings` from `plan_create`/`plan_replace` (and expose them via `plan_get`), or state in the skill that the server does not enforce the quality rules and the plan review is the only gate.

**4. SHOULD — The rendered plan file drops every `check`.**
`task_graph_server.py:921-934` renders only `- [ ] <ac id>: <statement>`. My smoke plan's AC with `"check": "pytest tests/test_thing.py"` rendered as `- [ ] ac1: it works`. The skill says the AC's `check` is the thing that can go red; the human-facing plan artifact — and the shape the degraded path copies — does not carry it. `plan_export` carries it, so this is view fidelity, not data loss, but a consumer reviewing the file (or working graph-off from a hand-written file that copies the shape) cannot see what to run.
Fix: render the check (e.g. `- [ ] ac1: it works — check: pytest …`) and say so in the degraded-path instructions.

**5. SHOULD — `server.md` gives a Hermes operator false advice about the fallback.**
`features/common/mcp/task-graph/server.md:12-14` (verbatim in `HERMES.md:146-155`): "Without a project `.mcp.json`, the CLI twin takes the same tool names". Two problems:
- A scaffolded project *always* gets `.mcp.json` (`mcp_tools.py:100` — `requires_reader=False`), so the stated condition is rarely true; the actual condition is "your host doesn't read `.mcp.json`", which is exactly Hermes (`~/.hermes/config.yaml` is its only route, per `features/hermes/adjustments/adjust_mcp.py` docstring).
- A Hermes agent reading HERMES.md therefore sees the file exists, assumes the server is configured, and never learns the CLI is its fallback — until it tries `mcp__task-graph__*` and gets nothing.
Fix: phrase the fallback host-neutrally: "If your host does not show the `task-graph` tools, use the CLI twin: `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_cli.py <tool> --json`."

**6. SHOULD — The Hermes `~/.hermes/config.yaml` proposal uses a project-relative path in a user-global file, with no anchor.**
`features/common/stack-mcp.json:45-59` declares `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_server.py`; there is a `claude` override using `${CLAUDE_PROJECT_DIR}` but no `hermes` override. I rendered the actual proposal (`adjust_mcp.adjust` with the catalog declaration):

```
mcp_servers:
  task-graph:
    command: "uv"
    args: ["run", "--script", ".ai-badger/skills/task-decomposition/scripts/task_graph_server.py"]
    enabled: true
```

`~/.hermes/config.yaml` is user-global; `.ai-badger/skills/...` resolves against whatever cwd Hermes spawns the server with. If that is the session's project dir, one entry works for every project (elegant); if not, the server fails to launch with a path error and the config is silently wrong for all projects. Nothing in the proposal or `meta.json` states the assumption. Fix: document the cwd requirement in the proposal note, or provide a `hermes` override anchored the way Claude's is.

**7. SHOULD — Claude's override makes Copilot's server entry vanish; a Copilot consumer gets no usable `task-graph` config.**
`stack-mcp.json:48-59` gives a Claude-only override; `.mcp.json` renders for its first configured reader, Claude (`mcp_tools.py:100`, readers `("claude","copilot")`), so it contains `uv run --script ${CLAUDE_PROJECT_DIR}/…`. The Copilot CLI reads `.mcp.json` too (module docstring `mcp_tools.py:11`), but `${CLAUDE_PROJECT_DIR}` is a Claude variable. `_declared_differently_in_mcp_json` (`mcp_tools.py:644-664`) therefore drops task-graph from `.github/mcp.json` by design (#193). Result in this repo: `.github/mcp.json` (tracked) has no task-graph, `.mcp.json` has the Claude-only form. The operator gets a note naming the server; the Copilot agent gets the CLI or nothing. With `copilot` alone configured, both files get the neutral form and it works — the break is the common claude+copilot combination.
Fix: make the `.mcp.json` entry host-neutral (relative path works for both readers if the client's cwd is the project root), or add a `copilot` override and a rule that lets `.github/mcp.json` keep the server when the surviving `.mcp.json` entry is host-specific.

**8. SHOULD — Exit code 1 collides between "closed error envelope" and "uv could not launch".**
`mcp-plan-tools.md:32-34` and `task_graph_cli.py:12-14` promise exit 0 = payload, exit 1 = the closed error envelope. Cold cache overrides: with a fresh `UV_CACHE_DIR` and `UV_OFFLINE=1`, `uv` itself exits 1 with `No solution found … network was disabled` on stderr and no envelope. A wrapper that treats exit 1 as a tool-domain failure parses empty stdout as JSON and breaks; a consumer can't tell a plan error from a launch failure.
Fix: document that a launch/dependency failure is also non-zero without the envelope, or give launch failures a distinct code (e.g. 3) in the CLI wrapper.

**9. SHOULD — The Jev advisory is advertised but undiscoverable from the product.**
`docs/changelog/0.179.0-task-decomposition-graph.md` announces "An opt-in Jev advisory … at plan time (`AI_BADGER_JEV=1`)". Nothing in `SKILL.md` or the three references mentions Jev, `AI_BADGER_JEV`, or `scripts/jev_choice.py`; no other shipped code imports it (grep across `features/` finds only the script itself). A consumer reading the skill can never enable it. Fix: document the env switch and what it changes in the skill (or drop the scripts from the shipped skill).

**10. NIT — The agent-doc budget passes with 49 characters to spare.**
`.ai-badger/config.json` `agentDocs: {maxChars: 19200, maxLines: 282}`; `.hermes.md`/`HERMES.md` are 19151 chars / 277 lines, `.ai-badger/HERMES.md` 19003 (the 148-byte delta is just the managed banner). The branch raised maxChars 18700→19200 for the task-graph injection. Honest, but the next invariant added to any Hermes project trips the stop-hook compaction reminder. Worth a deliberate note or a small compaction pass.

**11. NIT — `platforms: [linux, macos]` on a cross-platform skill.**
`features/common/skills/task-decomposition/SKILL.md:8`. The server/CLI are stdlib + pydantic Python launched by `uv`; no OS-specific code (`task` also omits windows, pre-existing). 44 of 48 common skills declare windows. If any host or doc reads `platforms` as a filter, Windows Hermes users lose the planning half of `task`. Add windows or confirm the field is inert.

**12. NIT — Consumer docs carry internal plan identifiers.**
`SKILL.md:124` ("Degraded path (DR12)") and `references/plan-vocabulary.md` (P3-C2, SK4, "§2", `WPn` dispositions) are framework-internal rename bookkeeping. The one consumer-relevant sentence is the bottom "Reading rule". A fresh consumer in their own project gains nothing from the disposition map and may wonder whether P3-C2 is something they must do. Keep the IDs out of the consumer path or expand each once.

**13. NIT — `mcp-index` will not surface the 12 tools until someone re-runs it.**
`features/common/mcp/task-graph/tools.json` is well-formed and genuinely useful: all 12 names, every intent <200 chars, tags all drawn from `features/common/mcp-tags.json`, and the intents discriminate well (`plan_get` "first read after a gap" vs `progress_checklist` "status report"; `step_complete` vs `ac_check` by lifecycle stage). But the tracked `.ai-badger/mcp-tools.json` is dated 2026-08-23 and contains no `task-graph` source at all, `tooling/index_build.py --check` does not cover it, and nothing in the scaffold regenerates it. A consumer's index only gains the entries after `mcp-index update` while the server is registered and reachable. Fix: one line in the skill/changelog ("run `mcp-index update` after den-refresh to add the task-graph intents").

## Still open

- **Hermes spawn cwd (F6).** I could not test Hermes here (not installed) or find documented cwd semantics for `mcp_servers:` entries; if Hermes spawns servers with the session project cwd, F6 downgrades to a documentation nit. Worth confirming against Hermes source before changing the declaration.
- **Copilot and `${CLAUDE_PROJECT_DIR}` (F7).** I verified the file contents and the #193 drop logic, not Copilot CLI's variable expansion. If Copilot CLI happens to expand `${...}` from `.mcp.json`, F7 downgrades to a clarity issue; the tracked `.github/mcp.json` still lacks the server.
- **Retirement has no home (related to F3).** The method requires "every request point … recorded retired with a reason" (`SKILL.md:96`, `decomposition-method.md:11`), but neither the model nor the schema has a retirement field and the skill never says where to put it. It likely belongs in `task_context`, but that is a guess; as written, the completeness stop rule is unverifiable from the artifacts.
- **Verified-good, for the record:** the method in `decomposition-method.md` is teachable (split/merge tests, candidate table, lane-brief fill test, state/escape rules, MoE handoff); the degraded path is findable exactly where needed (`SKILL.md:149-162`, repeated in the reference); all four frontmatter `related_skills` exist; the plugin pointer matches `sync_plugin_skills._POINTER_BODY`; `docs/skills.md` row/section and the `index.json` entry are accurate; the 12 names match across `tools.json`, server `ToolSpec`s and the skill; the prerequisite note is truthful and printed at scaffold (with the install command duplicated three times); warm and cold-with-network launches work (`Installed 5 packages`, cold run 0.87 s), and the fresh-offline and no-`uv` failures are clear on their own terms.

**Verdict: MERGEABLE AFTER MUSTS** — fix finding 1 (one worked example and per-tool argument keys in `mcp-plan-tools.md`); findings 2–9 are cheap follow-ups that a consumer will hit tonight on the Hermes/Copilot and graph-off paths.