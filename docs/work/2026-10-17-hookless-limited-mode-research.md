# Research: an ai-badger limited mode for Claude Code sessions whose hooks an enterprise policy blocks

**Date:** 2026-10-17
**Question:** When an enterprise's managed settings block Claude Code hooks, how much of what ai-badger's hooks do can still be delivered, and by which non-hook mechanism?

```chart:bars
title: ai-badger Claude hook arms by what they do (26 total)
context injection (SessionStart / UserPromptSubmit): 8
tool guards (PreToolUse deny or warn): 6
post-tool nudges and capture (PostToolUse*): 8
lifecycle (Stop / SessionEnd): 4
```

## Findings

### F1 — "Hooks are blocked" means one of three managed keys, and each blocks a different set [READ]

`allowManagedHooksOnly: true` blocks user, project and local hooks, hooks from installed plugins that are not force-enabled, and hooks in agent frontmatter. It still runs managed hooks, Agent SDK hooks, and **hooks from plugins that managed `enabledPlugins` force-enables**, matched on the full `plugin@marketplace` ID. The custom status line also falls back to managed settings only. `strictPluginOnlyCustomization: ["hooks"]` is looser: it stops hooks from every `settings.json` scope but keeps **all** plugin hooks. `disableAllHooks: true`, when set in managed settings, turns off every hook (managed hooks, plugin hooks, the status line and the file-suggestion command) and leaves only in-process Agent SDK hooks running.

So the first thing a limited mode has to establish is which of the three is in force. Under the first two, the plugin path still exists. Under the third, no hook path exists at all.

**Evidence:** code.claude.com/docs/en/settings-reference, sections `allowManagedHooksOnly` → "What runs under allowManagedHooksOnly", `strictPluginOnlyCustomization.hooks`, `disableAllHooks` (raw `.md` fetched 2026-10-17, lines 4054-4110 and 4653-4665 of that file).

### F2 — ai-badger delivers 25 of its 26 Claude hook arms through project settings, the one channel every one of those policies blocks [READ]

Each manifest entry with a Claude arm is of type `hooks-json`, which gets wired into the consumer's `.claude/settings.json`. The single exception is `drift-notice` (`plugin-hooks-json`), the only hook in the plugin's own `hooks/hooks.json`. As a result, an enterprise that allowlists the ai-badger plugin and force-enables it still loses 25 of the 26 hooks under both `allowManagedHooksOnly` and `strictPluginOnlyCustomization.hooks`. That outcome is a packaging decision in ai-badger, not a limit set by the policy.

**Evidence:** `features/common/hooks/hooks-manifest.json` (every entry's `agents.claude.type`); `hooks/hooks.json` (SessionStart → `drift_notice_hook.py` only); `.claude/settings.json` `hooks` block in this repo (the other arms, each `if [ -f "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/..." ]`).

### F3 — Moving the Claude arms into the plugin's hooks.json restores full behaviour under two of the three policies [INFERRED]

This follows from F1 and F2. If the arms ship in the plugin's `hooks/hooks.json`, an organisation can host ai-badger in its own marketplace (`strictKnownMarketplaces` allows that), force-enable it in managed `enabledPlugins`, and every hook runs under `allowManagedHooksOnly`. Under `strictPluginOnlyCustomization.hooks`, simply having the plugin installed is enough. This is the cheapest high-value change, and it gives the enterprise what such policies are for: one vetted, versioned hook bundle in place of arbitrary per-repo hooks.

Two follow-on costs. (1) A repo that has both the project-settings copy and the plugin copy would fire each hook twice, so the scaffolder has to choose one channel per repo, or the scripts need an idempotence guard. (2) The plugin copy's commands still point at `${CLAUDE_PROJECT_DIR}/.ai-badger/skills/...`, see F9.

### F4 — Several hookless channels survive a hook block, and each has its own policy kill-switch [READ]

| Channel | What it can replace | Its own managed kill-switch |
|---|---|---|
| `CLAUDE.md` / `.claude/rules/*.md` (incl. `paths:` rules) | Standing instructions, the prose twin of any guard or nudge | "Project instructions" set to `managed-only` |
| Skills (model- or `/`-invoked) | Pull-mode versions of injection hooks | `strictPluginOnlyCustomization.skills` (plugin skills still load) |
| Skill inline shell `` !`cmd` `` | Live context injected at skill load (unread mail, unfinished tasks) | `disableSkillShellExecution` |
| MCP server `instructions` + tools | Session-start context in the system prompt; on-demand checks | `allowManagedMcpServersOnly`, `strictPluginOnlyCustomization.mcp` (plugin MCP still loads) |
| Permission `deny` rules | Pattern-expressible PreToolUse guards | `allowManagedPermissionRulesOnly` |
| git hooks (lefthook) | Commit/push-time gates; Claude settings do not reach them | none in Claude Code |

**Evidence:** settings-reference sections `disableSkillShellExecution`, `strictPluginOnlyCustomization.skills` / `.mcp`, `allowManagedPermissionRulesOnly`; docs/en/memory "Managed policy" row and the `managed-only` Project instructions setting (memory.md lines 59, 359); docs/en/skills "Inject dynamic context".

### F5 — The hook scripts work as standalone commands, so their logic can be reused in pull mode [MEASURED]

When piped a synthetic payload, `prompt-markers/scripts/user_prompt_hook.py` returned the FEEDBACK `additionalContext` for an `f:` prompt, and `task/scripts/dispatch_gate_hook.py` returned `permissionDecision: deny` for an Agent call with no model. A CLI or MCP tool wrapper ("check this dispatch", "what is my unread mail", "expand this marker") can therefore call the same code with no rewrite. Ran once each, so this shows the logic is reachable. It says nothing about speed or robustness.

**Evidence:** `echo '{"prompt":"f: stop using tabs",...}' | python3 .ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py` and `echo '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose",...}}' | python3 .ai-badger/skills/task/scripts/dispatch_gate_hook.py`, macOS, main checkout at 476b7b2b, system python3, 2026-10-17, one run each.

### F6 — With no hooks at all, the 26 arms fall into four classes, and only some survive [INFERRED]

This reasons from the hook descriptions in `hooks-manifest.json` and the channel table in F4:

- **Context injection (8)**: message delivery at session start and per turn, session-start tracking, context enrichment, prompt markers, memory context, git-config health, drift notice. *Substitute:* one pull entry point, a `badger-checkin` skill whose body uses `` !`...` `` to inline unread mail, unfinished tasks, drift and git health, or an MCP tool doing the same, which a `CLAUDE.md` line tells the agent to run first. Prompt markers already have a prose twin ("apply it yourself", `CLAUDE.md:54`). *Lost:* the per-turn, automatic part. Delivery becomes something the model does once, at its own discretion.
- **Guards (6)**: dispatch gate, generated-file guard, memory-first gate, blast-radius kill guard, git-internals guard, cross-worktree warning. *Substitute:* permission `deny` rules where the rule is a path or command pattern (`Edit(.git/**)`, edits to the generated-file list, `Bash(pkill:*)`), plus git-hook gates (`scaffold_freshness_guard` already catches generated-file drift at pre-push). *Lost:* the dispatch gate and the memory-first gate depend on session state and arguments, which no permission pattern can express, so they become advisory prose only.
- **Post-tool nudges and capture (8)**: commit reminder, test economy ×2, grounded feedback ×2, memory follow-through, memory-first marker, Semantica autosave. *Substitute:* prose invariants that already exist (`small-commits-early-draft-pr`, `test-run-economy`, `grounded-feedback`). Semantica autosave becomes a step in the skill. *Lost:* the memory follow-through telemetry, with no replacement and no prose twin. The retrieval eval would silently lose that input.
- **Lifecycle (4)**: task checkpoint on Stop/SessionEnd and message cursor drop. *Substitute:* an explicit "checkpoint" step at the `task` skill's finish, which reads the transcript after the fact. *Lost:* checkpoints for interrupted turns. Bus cursors are left behind until something reaps them.

Roughly: injection degrades to pull, about half the guards become deny rules and the rest prose, the nudges become prose, and the lifecycle work becomes an explicit skill step. The grade is INFERRED because no substitute has been built or tried.

### F7 — Limited mode has to be declared, because a blocked hook cannot report its own absence [INFERRED]

A hook that never runs leaves no trace. The only in-session evidence is negative: the `[ai-badger] ...` lines that UserPromptSubmit normally injects, which this session shows, do not appear. A model cannot reliably notice something missing. A deterministic switch is better: a `.ai-badger/config.json` key (for example `"claude": {"hooks": "plugin" | "project" | "off"}`) that the scaffolder reads to decide where it wires the arms (F3) and whether to emit the limited-mode `CLAUDE.md` block, deny rules and check-in skill (F6). A canary line can stay as a secondary, advisory signal. This reasons from F2's wiring and from how `user_prompt_hook.py` output shows up in context.

### F8 — Skill-frontmatter hooks are not a safe fallback [UNVERIFIED]

The `allowManagedHooksOnly` entry names agent-frontmatter hooks as blocked but does not mention skill-frontmatter hooks either way. Whether they run under that key was not tested. A managed-settings file is needed to test it, and writing one to `/Library/Application Support/ClaudeCode/` on this machine would change policy for every session. Until someone tests it, a design should treat them as blocked.

### F9 — `${CLAUDE_PROJECT_DIR}` resolves inside plugin hooks.json commands [UNVERIFIED]

F3 depends on this. Project memory records that it is set for hooks only. Whether that includes plugin-sourced hooks was not run.

### F10 — Which of the three keys real enterprise users actually set [UNVERIFIED]

Nobody asked. The answer decides whether F3 alone, which covers two keys, is enough, or whether F6's full limited mode is needed.

## Still open

- **Which key the target enterprise sets** (F10). One `/status` → "Setting sources" from an affected user, or the managed JSON itself, decides between "plugin-host the hooks" and "build limited mode".
- **Skill-frontmatter hooks under `allowManagedHooksOnly`** (F8). Settle it in a throwaway VM or container with a managed-settings file. Do not use this machine.
- **`${CLAUDE_PROJECT_DIR}` in plugin hooks** (F9). Add one plugin hook that echoes it and run `claude -p` once.
- **Double-firing during migration** (F3). Pick one: scaffold-time channel choice or a script-side idempotence guard.
- **Is the full limited mode over-engineered?** The simpler version is F3 plus one `CLAUDE.md` paragraph listing what to do by hand when hooks are off. Build F6's check-in skill and deny rules only if F10 shows `disableAllHooks` in managed settings, the one case F3 cannot cover.
- **The memory follow-through signal has no hookless twin** (F6). Accept losing it in limited mode, or move it server-side into ai-raccoon itself.
