# Research: adding the pi harness to ai-badger

**Date:** 2026-08-28
**Question:** Can ai-badger's workflow be delivered inside the `pi` harness through pi extensions, what does that cost, and should it live in this repository?

**Investigated by:** six parallel research lanes plus an orchestrator spike, against pi 0.84.3
installed locally via bun, and ai-badger at commit `16db414f`. Every number below carries how it
is known. Where a lane's figure disagreed with a direct measurement, the measurement wins and the
correction is recorded.

```chart:matrix
title: the six asks against pi
ask, verdict, effort
task phases, extension - straightforward, low
subagent isolation, extension - straightforward, low-med
first-class memory, gate native / MCP absent, high
semantica audit, observation better / sink absent, high
prompt markers, extension - fixes known defect, low
event-bus comms, not possible via the bus, med
```

---

## Findings

### F1 — A pi extension runs ai-badger's existing Python hooks unmodified, and acts on their JSON [MEASURED]

This is the finding the whole integration rests on. It was established twice independently — once
by the orchestrator, once by the design lane — and both runs used *real* ai-badger hook scripts,
not stand-ins.

The consequence is large: ai-badger keeps **one** Python implementation across all four harnesses.
pi support becomes a TypeScript adapter that translates event shapes, not a reimplementation of
sixteen hooks.

**Evidence:** Orchestrator spike, `spike/.pi/extensions/badger-bridge.ts`, calling the unmodified
`features/common/skills/prompt-markers/scripts/user_prompt_hook.py` via
`execFileSync("python3", [HOOK], {input: JSON.stringify({prompt, cwd, session_id})})`:

```
$ pi -p --no-tools --approve -e ./.pi/extensions/badger-bridge.ts "q: run the tests later"
[SPIKE] text="q: run the tests later" source=interactive streamingBehavior=undefined markerExpanded=true
[SPIKE] injected="QUEUED TASK: The user has provided a task to queue for execution after completing your current work."

$ pi -p --no-tools --approve -e ./.pi/extensions/badger-bridge.ts "just a normal prompt"
[SPIKE] text="just a normal prompt" source=interactive streamingBehavior=undefined markerExpanded=false
```

The second run is the negative control: the bridge declines when it should. This check was seen to
produce both answers, not only the one wanted.

The design lane reproduced this against three further hooks, each both firing and staying silent:
`memory_first_gate_hook.py` (deny on `Grep`, silent on `Read`), `user_prompt_hook.py` (fires on
`f:`, silent on plain text), `dispatch_gate_hook.py` (deny on `Agent` with no `model`, silent with
`model:"sonnet"`). All exit `0`; the decision travels in stdout, never the exit code.

### F2 — The hooks dispatch on dialect, not on harness identity, so zero Python changes are needed [READ]

An adapter that speaks the *Claude* dialect gets Claude-shaped JSON back. No `pi` branch is needed
anywhere in Python; the translation to pi's return shapes happens in TypeScript, where it belongs.

**Evidence:** `features/common/skills/ai-raccoon-memory/scripts/memory_first_gate_hook.py:31-38`

```python
def _host(payload: Dict[str, Any]) -> str:
    """The transport, from the event name or the payload's spelling."""
    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    if event in ("PreToolUse", "PostToolUse"):
        return "claude"
    if event in ("preToolUse", "postToolUse"):
        return "copilot"
    return "copilot" if "toolName" in payload else "claude"
```

### F3 — All six Claude events ai-badger uses have a pi counterpart; coverage is 12 of 16 hooks day one [READ]

| ai-badger (Claude) | pi event | pi return shape |
|---|---|---|
| `UserPromptSubmit` | `input` | `{action:"transform", text}` |
| `PreToolUse` | `tool_call` | `{block:true, reason, terminate?}` |
| `PostToolUse` | `tool_result` | `{content?, details?, isError?}` |
| `SessionStart` | `session_start` | — (side effects) |
| `SessionEnd` | `session_shutdown` | — |
| `Stop` | `agent_settled` | — |

`agent_settled` is a *better* fit than Claude's `Stop`: it fires only when "Pi will not continue
running automatically", which is exactly what a task checkpoint wants.

12 of 16 hooks live day one, 2 conditional, 2 inert. The four that fail are all blocked on the
same thing — F5.

**Evidence:** `docs/extensions.md:569`, `:583-596`; `dist/core/extensions/types.d.ts`; mapping
built by the design lane against `features/common/hooks/hooks.json`.

### F4 — pi's extension surface is 34 events, a superset of Claude Code's [MEASURED]

Nine can block, cancel, mutate or replace: `project_trust`, `session_before_switch`/`_fork`/
`_compact`/`_tree`, `context` (rewrite the message list), `before_provider_request` (replace the
payload), `before_provider_headers`, `before_agent_start`, `message_end`, `tool_call` (a true
pre-execution veto, plus in-place argument mutation with no re-validation), `tool_result`,
`user_bash`, `input`.

**Evidence:** `$ grep -c 'on(event: "' $PI/dist/core/extensions/types.d.ts` → `34`
(orchestrator re-measurement, confirming the lane's figure exactly).

### F5 — pi has no MCP, deliberately. This is the largest gap in the integration [MEASURED]

ai-badger currently depends on MCP for **five** servers: ai-raccoon (memory), semantica (decision
graph), hermes (messaging), code-review-graph, playwright. Under pi, none of them exist. Each must
be re-exposed as extension-registered tools via `pi.registerTool()`, or reached another way.

This is the single biggest cost in the whole proposal, and it is not a gap pi intends to close.

**Evidence:**
```
$ find $PI/dist -iname "*mcp*" | wc -l
0
$ grep -rin "mcp\b" $PI/docs/*.md
docs/usage.md:308: "It intentionally does not include built-in MCP, sub-agents, permission
popups, plan mode, to-dos, or background bash. You can build or install those workflows as
extensions or packages, or use external tools such as containers and tmux."
```

### F6 — The event bus is in-process only. It cannot carry cross-agent communication [MEASURED]

Ask 6 asked for "correct event bus based agent communication tooling". pi's bus does not provide
it and cannot be made to. Two concurrently running pi sessions cannot talk through `pi.events`.

The whole implementation is 24 lines wrapping one `node:events` `EventEmitter` — channels are
`string`, payloads are `unknown`, nothing is persisted, there is no socket and no IPC.

The realistic transport is `--mode rpc` (pi's programmatic surface, 1595 lines of docs). The
existing answer in this project is the Hermes messaging bridge — but that is MCP-backed, so F5
applies to it too.

**Evidence:** `$ wc -l $PI/dist/core/event-bus.js` → `24`; full source read — `createEventBus()`
returns `{emit, on, clear}` over a single `EventEmitter`. The only shipped cross-process precedent
in the corpus is `examples/extensions/file-trigger.ts`, which `fs.watch`es `/tmp/agent-trigger.txt`
— an extension author's hack, not a feature.

### F7 — pi has no worktree isolation of any kind, but its subagent model is stronger than ai-badger's today [MEASURED]

A measured zero: `$ grep -ril "worktree" $PI/docs $PI/examples | wc -l` → `0`. `ctx.cwd` is a
read-only string with no `setCwd`.

That sounds worse than it is. pi's subagents are **real OS child processes** with their own `cwd`,
`--model` and `--tools`. The worktree path simply *becomes* the `cwd` argument — which is stronger
isolation than a same-process subagent, not weaker. Subagents are not native (pi says so at
`docs/usage.md:308`); the reference implementation is a ~1000-line extension that spawns
`pi --mode json -p --no-session --model X --tools Y` and parses JSONL from stdout, with model
routing via per-agent `.md` frontmatter.

**Evidence:** `$PI/examples/extensions/subagent/`; `docs/usage.md:308`; `dist/core/session-cwd.d.ts`.

### F8 — pi's `input` event carries `streamingBehavior`, which would fix ai-badger's documented mid-turn marker defect [READ]

ai-badger's own `CLAUDE.md` records the defect: a message queued **mid-turn** reaches the model as
an attachment, never passes the `UserPromptSubmit` hook, and its marker is never expanded. The
model is told to apply the behaviour manually — a workaround, not a fix.

pi's `input` event exposes `streamingBehavior: "steer" | "followUp" | undefined`, documented as
"`undefined` when idle, `steer` for mid-stream interrupts, `followUp` for messages queued until
the agent finishes". If `input` fires for queued messages, markers expand correctly in the case
that is broken today.

This is **READ, not MEASURED** — the spike only exercised the idle path
(`streamingBehavior=undefined`). Confirming it needs a live model turn to queue behind, which
needs provider credentials. It is the highest-value spike remaining.

**Evidence:** `$PI/docs/extensions.md`, `pi.on("input", …)` block; `CLAUDE.md` "Prompt markers".

### F9 — All four requested providers are already built into pi. No custom-provider extension is needed [MEASURED]

Enabling OpenRouter, DeepSeek, Anthropic and Copilot is configuration, not code.

**Evidence:**
```
$ pi auth check --provider <p> --json
anthropic       {"status":"not_ready","reason":"credentials_not_configured"}
openrouter      {"status":"not_ready","reason":"credentials_not_configured"}
deepseek        {"status":"not_ready","reason":"credentials_not_configured"}
github-copilot  {"status":"not_ready","reason":"credentials_not_configured"}
copilot         {"status":"not_ready","reason":"provider_not_found"}
```
`credentials_not_configured` means the provider is recognised and only lacks keys;
`provider_not_found` means the id is unknown. **The correct id is `github-copilot`; plain
`copilot` does not exist.**

Auth paths differ: Anthropic takes `ANTHROPIC_API_KEY` or `/login` with a Claude Pro/Max
subscription (billed as "extra usage", not free). OpenRouter takes `OPENROUTER_API_KEY` or an
OAuth-minted key. DeepSeek is API-key only. **Copilot is OAuth-subscription only — there is no
API-key path for it at all.**

### F10 — Catalog sizes are READ from shipped static JSON, not measured from a live run [READ]

| provider | models | api groups |
|---|---|---|
| OpenRouter | 351 | openai-completions |
| GitHub Copilot | 33 | anthropic-messages, openai-completions, openai-responses |
| Anthropic | 13 | anthropic-messages |
| DeepSeek | 2 | openai-completions |

39 providers ship in total. These counts are graded READ deliberately: `pi --list-models` returns
`No models available` until a provider is logged in, so no live catalog was observable. The
provider lane flagged this limitation of its own accord before being asked.

**Evidence:** `~/.bun/install/global/node_modules/@earendil-works/pi-ai/dist/providers/data/*.json`,
counted as `sum(len(v) for v in json.load(f).values())`; `$ ls $D/*.json | wc -l` → `39`;
`$ pi --list-models` → `No models available. Use /login to log into a provider…`.

### F11 — Credential handling already satisfies the no-hardcoded-secrets invariant [READ]

Resolution order is `--api-key` → `auth.json` (mode 0600, outside any repo) → env var →
`models.json` `apiKey`, and that last field supports `$ENV_VAR` interpolation or `!command`
shell-out. Committed config never needs a literal secret.

**Evidence:** `$PI/docs/providers.md`, `$PI/docs/models.md`, `$PI/docs/settings.md`.

### F12 — Claude Code's SKILL.md files load into pi unmodified [MEASURED]

pi implements the Agent Skills standard, reads `name` and `description`, and ignores unknown
frontmatter — so ai-badger's `scope:` field is silently dropped rather than rejected. pi is *more*
lenient than the standard (a skill's `name` need not match its directory). The docs explicitly
document pointing pi at `{"skills": ["~/.claude/skills"]}`.

**Evidence:** design lane loaded the catalog through pi's own loader — **79/79 skills, zero
diagnostics**. `$PI/docs/skills.md`; `$PI/examples/sdk/04-skills.ts`.

### F13 — Headless pi silently ignores project-local extensions. This is the biggest operational risk [READ]

At the default `defaultProjectTrust: "ask"`, a non-interactive pi run shows no trust prompt and
loads **none** of ai-badger's project-local extensions. It then runs to completion and reports
success while being completely ungoverned.

That is this project's recorded failure mode. Changelog 0.80.0 shipped four hermes hooks that were
dead on arrival — registered, never running. A green unattended run would be no evidence that any
hook fired.

Mitigations, in order of preference: install the adapter at **user scope** rather than
`.pi/extensions/`; or pass `--approve`; or set `defaultProjectTrust: "always"` — noting that pi
has **no built-in sandbox**, so extensions run with the full permissions of the pi process.

**Evidence:** `$PI/docs/security.md:29`, quoted verbatim:

> Non-interactive modes (`-p`, `--mode json`, and `--mode rpc`) do not show a trust prompt.
> Without an applicable saved trust decision, `defaultProjectTrust: "ask"` and `"never"` ignore
> such resources, while `"always"` trusts them. Use `--approve`/`-a` or `--no-approve`/`-na` to
> override project trust for one run.

And, from the same section: "Before trust is resolved, pi only loads context files, user/global
extensions, and CLI `-e` extensions." Context files (`AGENTS.override.md`, `AGENTS.md`,
`CLAUDE.md`) load regardless of trust — but note pi reads only **one** context file per directory,
so an `AGENTS.md` beside `CLAUDE.md` shadows it.

### F14 — A separate repository cannot register a harness with ai-badger at all [READ]

The in-repo/separate-repo question is largely settled by the engine: registration is in-repo
either way. The only genuinely open question is where the *TypeScript* lives.

Four enforcement points, three mechanical:
- `engine/badger_lib.py:192` — `AGENT_NAMES = ["claude", "copilot", "hermes"]`, a literal
- a closed `enum` in six schemas (`config`, `agents`, `manifest`, `stack-mcp`, `skills-source`,
  `support`), with `jsonschema` a required unguarded dependency, so it refuses
- `tooling/validate.py` `config_stack_gaps` rejects an agent name with no in-tree directory
- `tests/test_three_agent_scope.py` asserts the roster is exactly three

`ADR-0016:37` states it directly: "A project config naming `junie` fails schema validation — the
schemas are the enforcement point."

This is **not a wall**. The repo anticipated a fourth harness and left a checklist — that test's
own docstring says the pin exists "so a future re-addition has to be a deliberate decision that
updates this file, the schemas, and the catalog together."

**Evidence:** files and lines as cited; all four re-verified directly by the orchestrator.

### F15 — `AGENT_NAMES` is a hand-maintained twin list with no mechanical cross-check [READ]

The comment above it reads: "Canonical agent list — keep in sync with schemas/agents.schema.json
and schemas/config.schema.json agents enum." A comment is the enforcement.

This is exactly the failure the `derive-or-delete-the-list` invariant names, and this repo has
been bitten by it repeatedly. Adding a fourth harness adds a fourth entry to every copy of the
list. Whatever else is decided, **deriving this list rather than adding to it is the change that
pays for itself.**

**Evidence:** `engine/badger_lib.py:190-192`; `.ai-badger/invariants/derive-or-delete-the-list.md`.

### F16 — Renaming `agent` to `harness` is semantically right but has no migration path [READ]

pi's own tagline is "There are many agent harnesses, but this one is yours", so the vocabulary
matches the ecosystem. The cost is the problem.

`config.agents` is a **required, persisted, user-authored field** in every downstream repo's
`.ai-badger/config.json`, and there is no migration mechanism — `tooling/validate.py:221` states
"no migration by design, re-scaffold to upgrade."

Three options, costed:

| option | files touched | breakage |
|---|---|---|
| (a) full rename incl. config key | ≥73, plus migration code that does not exist | every downstream config fails validation until re-scaffolded |
| (b) prose/docs only, keep `agents` as the wire key | small | none — but every machine-readable artefact still says "agent", so it does not deliver the alignment |
| (c) additive `harness` alias, `agents` deprecated | ~6–10 vocabulary files + `badger_lib.py` | none downstream; carries two names until a later deprecation wave |

**Option (c) is the only one that changes the wire format without breaking consumers.**

A real hazard for any find-and-replace: "agent" collides with the persona sense
(`hermes-agent-author`, `.claude/agents/`, `personaRouting`) and with "Hermes Agent" as a product
name **inside the same files** (`CLAUDE.md`, `README.md`). A blind replace corrupts those.

**Evidence:** naming lane census; `.ai-badger/config.json`; `schemas/config.schema.json`;
`tooling/validate.py:221`. Correction applied: the lane reported "18 per-hook `agents` maps"; it is
**16**, measured two ways (`len(d['hooks'])` and `grep -c '"agents"'`). Per-harness coverage
measured at claude 16/16, copilot 9/16, hermes 8/16.

### F17 — `pi install` has no subdirectory syntax, so `features/pi/` can never be installed from this repo [READ]

In-repo TypeScript must ship by ai-badger's own file-copy scaffolding, not by `pi install`. This
constrains the distribution design regardless of which repo option is chosen.

**Evidence:** `$PI/docs/packages.md` — no documented subdirectory source form.

### F18 — ADR-0016 contains the strongest in-repo argument against this work, and half of it has expired [READ]

> "The owner does not use Junie, and there is no capacity to maintain a fourth agent surface."
> — `docs/adr/0016-junie-support-removed.md:16`

Two clauses. The first does not apply: the owner **does** use pi — he installed it and initiated
this work. The second stands, and no amount of research settles it. It is a capacity question,
and it is the owner's to answer.

The swap reframing matters here: if pi **replaces** hermes the roster stays at three and the
objection is answered outright. If pi is **added**, it is the fourth surface ADR-0016 argues
against.

**Evidence:** `docs/adr/0016-junie-support-removed.md:16`, quoted above verbatim; the owner's
use of pi is established by its local installation (`pi --version` → `0.84.3`, installed via bun)
and by his initiating this task.

### F19 — The owner uses hermes for two jobs only: unattended/scheduled runs, and local terminal coding [READ]

Stated directly by the owner when asked, 2026-08-28. He does **not** use it for remote/mobile
reachability or for notifications.

This substantially improves the swap case, because pi's largest capability gap versus hermes —
it has no messaging-platform integration whatsoever — lands on jobs he does not use. Of his two
actual jobs, local terminal coding is covered outright (and pi beats hermes on hook coverage,
12/16 versus 8/16), leaving unattended runs as the only real question.

That question collides head-on with F13: an unattended headless run is precisely the case where
project-local extensions are silently ignored.

**Evidence:** owner's answer, this session.

### F20 — The trust gap is real and reproducible: identical commands, one flag apart, one governed and one not [MEASURED]

F13 said this from the docs. It is now demonstrated. The swap lane ran seven configurations with a
control; the orchestrator independently reproduced the decisive pair and then sharpened it.

| run | config | extension loaded? |
|---|---|:--:|
| A | `.pi/extensions/`, default trust, `-p` | **no** |
| B | *control* — identical + `--approve` | yes |
| C | explicit `-e` | yes |
| D | identical to A + `--verbose` | **no** |
| E | `~/.pi/agent/extensions/`, no flag | **yes** |
| F | `.pi/` + `defaultProjectTrust:"always"` | yes |
| G | F + `--no-approve` | no |

Runs A and B are the same command against the same directory, one flag apart, and produce
**byte-identical terminal output**. One was governed; one was not. Nothing distinguishes them on
screen. Run D shows `--verbose` does not surface it either.

**Evidence:** orchestrator reproduction, probe extension writing a sentinel file at load:
```
$ cd trust/ && pi --offline -p --no-tools "hi"          # run A, default trust
probe: NOT-LOADED
$ cd trust/ && pi --offline -p --no-tools --approve "hi" # run B, control
probe: LOADED
```
Both runs terminated on the same "No API key found" message — which is what makes the test valid:
the model call is constant, trust is the only variable, and run B proves the probe is capable of
firing.

The sharpest form, one run with **both** extensions installed, default trust, no flag:
```
user-scope probe:    LOADED
project-local probe: NOT-LOADED
```
Same process, same instant, opposite outcomes — decided purely by install location.

### F21 — Under the trust gap, the agent reads ai-badger's instructions while running none of its enforcement [READ]

This is what makes F20 dangerous rather than merely inconvenient. Context files load *regardless*
of project trust, but project-local extensions do not. So in run A the agent had ai-badger's
`CLAUDE.md` in context — its invariants, its delegation rules, its prompt-marker vocabulary — and
none of the hooks that enforce any of it.

It talks like it is governed. It is not. A reviewer reading the transcript would see an agent
citing the right rules.

That is this project's recorded failure mode, twice over: changelog 0.80.0 shipped four hermes
hooks dead on arrival, and the standing note is that "shipped and running are different claims".

**Evidence:** `$PI/docs/security.md:27` — "Context files such as `AGENTS.override.md`, `AGENTS.md`,
and `CLAUDE.md` are loaded regardless of project trust unless context loading is disabled."
Combined with `:29` (F13) and the run A/B pair (F20).

### F22 — Install at user scope. It is the only mitigation that survives being forgotten [MEASURED]

Three mitigations work; only one is safe by default.

- **User scope (`~/.pi/agent/extensions/`)** — loads headless, default trust, no flag. Measured
  in run E and in the two-probe run above. **This is the recommendation.**
- **`--approve`** — works (run B), but run G shows a stray `--no-approve` silently re-breaks it,
  and every unattended invocation must remember the flag forever.
- **`defaultProjectTrust: "always"`** — works (run F), but it is global and turns "cloning a repo"
  into "running its code". pi has **no built-in sandbox**: extensions run with the full permissions
  of the pi process.

**Evidence:** runs E, B, G, F as tabulated; `$PI/docs/security.md:33,37` and its "No Built-in
Sandbox" section.

### F23 — Against the owner's two actual jobs, pi wins both; the loss is governance-by-default, not capability [READ]

Verdict: **swap with named losses.**

Local terminal coding is covered outright. For unattended runs, pi is an *upgrade* on paper —
four of the eight hooks hermes lacks today (`task-checkpoint`, `task-checkpoint-session-end`,
`dispatch-gate`, `blast-radius-kill-guard`) are precisely the ones unattended work needs — but
only **if extensions load**, which is F20.

Two real losses beyond that:
- **`no_agent=true` cron ticks.** Hermes supports scheduled work that runs no model at all. pi has
  no scheduler. The resolution is not to port these: they should drop the agent entirely and become
  plain `launchd` scripts.
- **The MCP stack** (F5) — ai-raccoon and semantica go with it.

**Evidence:** swap lane's hook-set comparison against `features/common/hooks/hooks-manifest.json`;
`$ grep '\bmcp\b' $PI/docs` → 1 hit, the line stating pi has none.

### F24 — Dropping hermes keeps the roster at three and answers ADR-0016 directly [INFERRED]

If pi replaces hermes rather than joining it, no schema enum widens, `AGENT_NAMES` stays three
long, and `tests/test_three_agent_scope.py` needs only its names swapped — not its assertion
loosened. The capacity objection in F18 is answered rather than argued with.

Removal cost is estimated at **75–110 files**. This is `INFERRED`, by analogy from ADR-0016's junie
removal (59 files, +227/−655) scaled by hermes's larger measured footprint (44 files, 5,882 lines).
It reasons from those two measurements and must not be quoted as a measured figure for hermes.

One thing that does **not** have to go: the hermes *MCP catalog entry* is independent of the
harness slot. The gateway can be kept without spending a roster place on it.

---

## What each of the six asks actually gets

1. **Task phases** — *extension, straightforward.* `session_start` / `turn_start` / `turn_end` /
   `agent_settled` / `session_shutdown`, with `ctx.getContextUsage()` and per-turn billing on
   `message_end.usage`. Note `getSessionStats()` lives on `AgentSession`, not `ExtensionContext`.
2. **Subagent + session isolation** — *extension, straightforward, and the cleanest win.* Real
   child processes with their own cwd; the worktree path becomes the `cwd` argument. Stronger than
   today. Risk is F13, not the mechanism.
3. **First-class memory** — *split.* The pre-tool veto that forces a memory search is **native**
   and measured working. The MCP transport underneath is **absent** (F5).
4. **Semantica decision audit** — *split, and one half is an upgrade.* The MCP sink is absent, but
   `pi.appendEntry()` is a zero-token session-persisted audit ledger that Claude Code has no
   equivalent for — decisions could be *observed* rather than relying on the model to record them.
5. **Prompt markers** — *extension, straightforward,* and it plausibly fixes the mid-turn defect
   (F8). Unmeasured; the top remaining spike.
6. **Event-bus comms** — *not possible via the bus* (F6). Needs `--mode rpc` or another transport.

---

## Recommendation

**Install at user scope, and treat that as non-negotiable.** F20–F22 turn this from a preference
into the single decision that determines whether any of the rest is real. `.pi/extensions/` is
silently inert in exactly the unattended case the owner cares about, and F21 makes that failure
invisible — the agent quotes ai-badger's rules while enforcing none of them.

**Do the declarative half first and prove it fires.** Before any TypeScript, ship what pi reads
without an extension — context files and skills (F12: 79/79 load unmodified) — and verify with an
assertion that a hook actually ran, not that a run succeeded. F20 shows a green run and an
ungoverned run are indistinguishable on screen.

**The acceptance test is specific:** have a hook write a sentinel, spawn a child run into a fresh
worktree — a path with no saved trust decision — and assert the sentinel exists. Not that the run
exited 0. That is exactly the run A/B pair, and it is the check that would have caught 0.80.0.

**Then build one adapter extension.** F1 and F2 mean it translates event shapes and shells out; it
reimplements nothing.

**Do not add a `"pi"` key to `hooks-manifest.json` on day one.** The design lane dissented from its
own brief here and the dissent is correct: the manifest's existing `claude` arm already names the
event and the script, so the adapter can read `hooks.json` at runtime and map the six event names.
Adding the key forces four hand-maintained harness lists (F15) plus 16 manifest arms with no
partial path through `validate.py`. Earn that later.

**Keep the TypeScript in-repo** unless it grows its own dependency tree or a build step. The fork
point is not file count — it is when `npm install` enters every Python-only PR's critical path.
Below that line: `features/pi/`, no runtime dependencies, no bundler. Above it: hybrid, with the
cross-repo drift check made mandatory, because two lists that must agree is exactly F15 again.

**Start in-repo regardless, because extraction is the cheaper reversal.** ADR-0016 is a worked
template for removing a harness in one commit. Merging back is worse on three counts: squash-merge
means history does not graft, a companion repo puts version literals outside `version_sync.py
--check`'s reach, and it means collapsing two release ledgers.

**On naming, take option (c)** — additive `harness`, `agents` kept as a deprecated alias. It is the
only option that changes the wire format without breaking every downstream config, and it is
bounded to ~6–10 files.

**On hermes: swap, don't add** (F23, F24). Against the owner's two stated jobs pi wins both, the
roster stays at three, and F18's capacity objection is answered instead of argued with. Keep the
hermes MCP catalog entry — it does not cost a roster slot. Convert `no_agent=true` cron ticks to
plain `launchd` scripts rather than porting them; they never needed an agent.

**The capacity question (F18) is yours and is not answerable from evidence** — but the swap
reframing shrinks it from "maintain a fourth surface" to "maintain a different third one".

---

## Still open

- **Does `input` fire for mid-turn queued messages?** (F8) The single highest-value unmeasured
  claim — it decides whether pi fixes a defect ai-badger currently documents as unfixable. Needs
  provider credentials and a live turn to queue behind.
- **How many of the owner's cron jobs are `no_agent=true` scripts versus jobs that need a model?**
  (F23) This decides the size of the migration. Mostly the former means most of it is `launchd`
  scripts and never touches pi at all. Only the owner can answer it.
- **What does removing hermes actually cost?** F24 estimates 75–110 files by analogy; nobody ran
  the removal. The junie figure (59 files, +227/−655) is for a *different* harness and must not be
  quoted as hermes's.
- **Live model catalogs** (F10) — every count is from static JSON. Re-run `pi --list-models` after
  a real `/login`; Copilot in particular gates individual models per account.
- **Does the MCP gap have a cheaper answer than re-fronting five servers?** (F5) Nobody costed
  writing a generic MCP-client extension for pi, which would restore all five at once. That is the
  obvious next question and it was not investigated.
- **Whether any of this should be built at all** (F18) — the capacity clause.
