# ADR-0034: Third-party egress is opt-in and lockable per project

**Date:** 2026-10-02
**Status:** Accepted (2026-10-02, targeting 0.185.0; see `docs/changelog/0.185.0-local-only-data-policy.md`).
**Author:** Rafał Araszkiewicz (Arasz) with Claude (task `aib-local-only-data-access-hardening`)
**Scope:** `features/common/skills/{ai-raccoon-memory,task-decomposition}/scripts/openrouter_client.py`,
`features/common/skills/ai-raccoon-memory/scripts/memory_context.py`,
`features/common/skills/task-decomposition/scripts/jev_choice.py`, `schemas/config.schema.json`.
**Supersedes:** ADR-0031 D2.2 (the pipeline runs whenever a key is present).

## Context

ai-badger has to work in corporate repositories that hold client data. The rule there is that
only the agent host's approved model provider may receive project data: Anthropic for Claude
Code, GitHub for Copilot, and whatever the operator has approved for Hermes or pi.

The egress inventory found one surface that broke the rule by default (research record
`docs/work/2026-10-02-aib-local-only-data-access-hardening-research.md`):

- **F1. The per-prompt memory-context pipeline.** ADR-0031 D2.2 turns it on whenever
  `OPENROUTER_API_KEY` is set. Every qualifying prompt then goes to an OpenRouter chat model, and
  up to 48 memory and source-code excerpts go to `typesafe/jev-1.13`. Many developers export that
  key for unrelated tools, so a corporate checkout leaked without anyone opting in.
- **F2. Measured on the owner's machine.** The key was set, and the hook also fires on
  harness-injected turns.
- **F3. The opt-in Jev advisory forwarded the OpenRouter key.** It sent the key as the Bearer
  token to whatever host `AI_BADGER_JEV_ENDPOINT` named.

## Decision

### D1: one egress rule, enforced in the client

`openrouter_client.py` is the only module that opens a socket for these features (ADR-0031 D2.1).
It now owns a single predicate:

```
egress_allowed(url, env, cwd) = is_loopback(url) or third_party_allowed(env, cwd)
third_party_allowed(env, cwd) = env["AI_BADGER_ALLOW_THIRD_PARTY"] == "1" and not project_locked(cwd)
```

`post_json` checks this predicate before DNS resolution or connect. A caller that passes no `env`
is refused for every non-loopback host, so a future caller fails closed. `is_loopback` compares
the parsed hostname exactly against `127.0.0.1`, `localhost` and `::1`, and refuses userinfo.

### D2: a project locks egress with `dataPolicy`

`project_locked(cwd)` walks every ancestor of the cwd, through the path as given, the
symlink-resolved path, and `$PWD` when it names the same directory (hosts report the physical
cwd). Egress is locked if any ancestor's `.ai-badger/config.json` meets one of
these conditions:

- it carries a `dataPolicy` key (the schema accepts only `"local-only"`; any other value also
  locks);
- it is not a regular file (directory, FIFO, dangling symlink — never opened);
- it cannot be reached or read, is larger than 1 MiB, or is not a JSON object.

A config without `dataPolicy` defers to the environment. The reasons for this shape:

- **Any ancestor, not the nearest.** A nested scaffold, such as a monorepo package or an in-tree
  worktree branched before the lock landed, cannot override its parent's lock.
- **Fail closed.** A broken file cannot prove the project opted in.

### D3: the memory pipeline needs the egress rule, not just a key

`pipeline_for` returns no pipeline unless `egress_allowed(base, env, cwd)` holds. A session that
is not opted in, or is locked, gets ADR-0031's single local ai-raccoon search: a 5 s budget and
no HTTP. This replaces D2.2's "key present ⇒ pipeline".

### D4: Jev endpoints never borrow the OpenRouter key

`jev_choice.endpoint_target` resolves `(url, key)` in three ways:

- **Loopback test seam.** Unchanged.
- **Custom `AI_BADGER_JEV_ENDPOINT`.** It must use `https://`, or loopback `http://`. Its key is
  the optional `AI_BADGER_JEV_ENDPOINT_KEY`; when that is unset or empty, no `Authorization`
  header is sent. The OpenRouter key is never used here.
- **Default.** The OpenRouter production endpoint, with the OpenRouter key.

Every resolved url must still pass D1. A loopback decider, such as the Apache-2.0
`Mapika/decider` server on `/v1/systemone`, therefore works in a locked project. A company-cloud
endpoint needs the opt-in and an unlocked project.

### D5: a refusal the user asked to avoid is visible, without prompt content

`lock_reason(cwd)` names the locking config and its cause. When `AI_BADGER_ALLOW_THIRD_PARTY=1`
and a key are set but a lock refuses the pipeline, the memory hook reports one line per process
to `~/.ai-badger/hook-errors.log` (a warning under Hermes). A refusal without the opt-in is the
default and stays silent. `jev_choice.py`'s off envelope carries a `refusal` code and a reason
naming the cause.

## Consequences

**Positive**

- A key in the environment no longer sends client data anywhere.
- A repository can commit `"dataPolicy": "local-only"` and know that no developer's shell setting
  overrides it.
- Every current and future caller of the client is covered by construction.

**Negative**

- Existing key holders silently lose the OpenRouter pipeline until they set
  `AI_BADGER_ALLOW_THIRD_PARTY=1`. The changelog's upgrade note carries this.
- Consumers keep the old behaviour until `den-refresh` re-scaffolds their copies. Hermes shares
  one user plugin, so it picks up the new behaviour when any project refreshes.
- Scaffolders older than 0.185.0 reject a config that contains `dataPolicy`, because
  `additionalProperties` is false.
- A company-cloud decider cannot run inside a locked project. That needs a host allowlist, which
  is a follow-up.

**Neutral**

The rule governs only the OpenRouter client. `docs/reference/data-access.md` lists what it does
not govern:

- proxy bypass;
- pi's `openrouter/` model pins and pi's own memory pipeline;
- ai-raccoon's embedding engine configuration;
- the archify update check and fonts;
- feed-badger's PR to the public framework repository.

## Alternatives considered

- **Env-only opt-in.** A project could not lock it, and one developer's global opt-in would reach
  client repositories.
- **Config-only opt-in.** Every developer would have to edit a tracked file to opt in.
- **Keep key presence and add a `local-only` lock.** The default would stay open, which is the
  defect this ADR fixes.
- **Per-surface switches only.** The memory pipeline and Jev each have their own switches, but
  nothing covers a future caller. The client-level check covers it.
- **A host allowlist in config.** This is the right shape for company-cloud endpoints, but it is
  more than the default flip needs. It is deferred.
- **Nearest config wins.** A nested config could then quietly override its parent's lock.
