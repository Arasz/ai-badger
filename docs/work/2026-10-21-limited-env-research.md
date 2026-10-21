# Research: limited-env as an instruction-only operating mode

**Date:** 2026-10-21
**Question:** Can a `limited-env` stack deliver ai-badger's memory-first and workflow directions in enterprise environments without installing or executing agent hooks?

This investigates a proposal. It does not introduce the stack or change runtime behavior.
The completion gate is a source-backed record, explicit gaps, and a clean HTML render.

## Findings

### F1 — Existing limited mode replays hook commands [READ]

The current Claude-specific `limited_mode.py on` writes directions into `CLAUDE.local.md`.
Its `checkin` reads hook registrations and executes their commands through the shell.
It already tells the agent to search memory before repository text search. This is useful
prior work, but a mode that prohibits hook execution should not direct agents to this check-in.

**Evidence:** `skills/task/scripts/limited_mode.py:26-38`, `:107-119`, `:148-153`, `:169-199`;
`docs/how-to/run-without-hooks.md`, sections “Know what you are opting into” and “Check in”.

### F2 — Stacks can deliver invariants and conditionally include skill directions [READ]

The scaffolder copies and summarizes invariants from the resolved stacks. Skill extension
descriptors carry requirements; extensions whose requirements fail are removed before delivery.
`requires: ["stacks=limited-env"]` can select such an extension. The config schema accepts
hyphenated stack names and requires catalog membership. Therefore the
name `limited-env` fits the existing syntax; catalog content and index generation are still needed.

**Evidence:** `features/common/skills/welcome-ai-badger/scripts/scaffold.py:436-447`;
`features/common/skills/welcome-ai-badger/scripts/extensions.py:198-228`;
`features/common/skills/welcome-ai-badger/scripts/_shared.py:147-176`;
`schemas/config.schema.json:60-67`.

### F3 — Claude hook wiring is separate from stack invariant delivery [READ]

`HookWiring.wire` activates for configured Claude projects, then reads the common hook manifest.
The inspected entry path has no `limited-env` condition. The scaffolder also runs agent-specific
adjustments, selected by agent name rather than arbitrary stacks. A new stack-local
`adjustments/` directory would not be dispatched. Adding invariant files alone does not
establish a no-hook installation contract.

**Evidence:** `features/common/skills/welcome-ai-badger/scripts/hook_wiring.py:221-262`;
`features/common/skills/welcome-ai-badger/scripts/scaffold.py:565-586`, `:730`.

### F4 — Memory-first prose already exists, while raw-result retrieval depends on hook capture [READ]

The ai-raccoon MCP instruction block already requires memory search before web/code search or
asking the user, with projectId, scope=all and multiple query formulations. Reuse this policy
rather than create a conflicting memory workflow. The raw-text-search skill expects a gate-provided
pattern/hash and captured output; instruction-only sessions should read their direct search
results instead of waiting for those hook artifacts.

**Evidence:** `features/common/mcp/ai-raccoon/server.md:4-13`;
`features/common/skills/get-raw-text-search/SKILL.md:19-33`, `:41-43`.

### F5 — Written instructions cannot promise the enforcement that hooks provide [READ]

Claude's current documentation describes instruction files as context rather than enforced
configuration. Its hook reference also distinguishes managed-hook restrictions from disabling
hooks, and explains that hook registrations can come from settings, plugins and frontmatter.
Consequently, inspect the target policy and delivery channels; a project-local stack cannot
control independently installed plugins or administrator-owned hooks.

**Evidence:** [Claude memory documentation](https://code.claude.com/docs/en/memory),
“CLAUDE.md vs auto memory” and “Write effective instructions”, accessed 2026-10-21;
[Claude hook reference](https://code.claude.com/docs/en/hooks), “Hook locations” and
“Disable or remove hooks”, accessed 2026-10-21.

### F6 — A stack plus one resolved no-hook policy is the smallest complete proposal [INFERRED]

From F1-F5: keep `limited-env` as the explicit opt-in. Add its invariant content and targeted
skill extensions, and resolve its presence into a shared policy used by hook-producing paths.
Start without a second user-facing switch that could contradict the stack. An independent
per-agent mode can follow if mixed environments need it.

Proposed scope:

| Surface | Required outcome |
| --- | --- |
| Root instructions | Summarize that memory-first and workflow checks are performed by the agent |
| Memory invariant | Require relevant memory searches for each new investigation topic before code/web search; inspect cited sources; use direct search only for gaps |
| Missing memory tool | State the limitation once, then use available approved sources; do not claim a memory check occurred |
| Task and research skills | Put manual context retrieval and progress/checkpoint steps at their natural workflow boundaries |
| Hook writers | Skip ai-badger registrations; remove existing registrations only where ownership is proven; preserve unrelated settings |
| Hook-dependent skills | Replace or omit steps that depend on injected context, capture hashes, markers or automatic observers |
| Plugin and user scope | Detect or document remaining ai-badger hook sources; do not claim project cleanup disables independently installed hooks |
| Telemetry and interrupted sessions | Declare automatic observations and interruption checkpoints unavailable unless separately implemented |

Suggested invariant wording (proposal):

> Before a new investigation, search available project memory with the canonical projectId,
> scope=all, and two or three focused query formulations. Inspect relevant source references.
> If memory leaves a gap, search the available code or external sources for that gap.
> If memory is unavailable, say so once and proceed using approved sources. Repeat when the
> topic changes. This procedure is followed by the agent; no hook enforces it.

Acceptance criteria for implementation: fresh scaffold has no ai-badger agent-hook registrations;
re-scaffolding removes owned registrations and preserves third-party entries; selecting the stack
delivers the invariant and applicable extensions; deselecting it restores normal delivery;
memory-first examples work without hook-produced artifacts. Exercise each supported agent and
scope before claiming support. Mutations should reintroduce a registration, remove the invariant,
and leave a capture-only step in the limited workflow; each must fail its corresponding check.

### F7 — Agent adherence and the target enterprise's permitted channels remain untested [UNVERIFIED]

No instruction-only sessions were run. No enterprise policy was supplied. MCP, repository
instructions, skills and ordinary scripts may each have separate restrictions. Test the memory
procedure on a small fixed task set, including topic changes and an unavailable memory server,
before quoting a reliability claim. Compare observed tool order with the required sequence.

## Still open

- Is the target restriction “no automatic hooks”, “no hook registration”, or “no repository code execution”? This proposal assumes no ai-badger agent hooks; it does not enable prohibited scripts.
- Is this repository-wide or local to an affected employee? A committed stack changes the team's scaffold; a local override may be necessary for mixed teams.
- Audit every host adapter, tool integration and installed plugin for hook registration and cleanup, including user scope. This record inspected the shared Claude path, not every writer.
- Which manual context/checkpoint tools work without hook initialization? Validate those before naming exact commands in skill extensions.
- How reliably do supported agents follow the invariant? Instruction delivery and observed adherence require separate checks.
- Simpler alternative: ship only the invariant and a short manual-workflow section when enterprise policy already disables all hooks. That reduces implementation cost, but does not meet a promise that ai-badger itself installs no hooks.
