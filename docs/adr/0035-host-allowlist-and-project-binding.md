# ADR-0035: A locked project can allow named hosts, an exported project id must match the cwd, and plaintext egress is refused

**Date:** 2026-10-03
**Status:** Accepted (2026-10-03, targeting 0.186.0; see `docs/changelog/0.186.0-egress-allowlist-project-binding.md`).
**Author:** Rafał Araszkiewicz (Arasz) with Claude (task `aib-egress-proxy-allowlist-project-binding`)
**Scope:** `features/common/skills/{ai-raccoon-memory,task-decomposition}/scripts/openrouter_client.py`,
`features/common/skills/ai-raccoon-memory/scripts/memory_context.py`,
`features/common/skills/task-decomposition/scripts/jev_choice.py`,
`features/common/skills/welcome-ai-badger/scripts/config_writer.py`, `schemas/config.schema.json`.
**Amends:** ADR-0034, decisions D1, D2 and D4. ADR-0034's other decisions stand.

## Context

ADR-0034 made third-party egress opt-in (`AI_BADGER_ALLOW_THIRD_PARTY=1`) and lockable
(`dataPolicy` in any ancestor `.ai-badger/config.json`). Its follow-up list names three gaps this
ADR closes. The research record is
`docs/work/2026-10-03-aib-egress-proxy-allowlist-project-binding-research.md`.

1. **A locked client repository could not reach an approved company endpoint.** An example is a
   decider in the company cloud. The only way out was to remove the lock.
2. **An exported `AI_BADGER_PROJECT_ID` made the memory pipeline read a project other than the
   one whose lock was checked.** The lock was checked against the session's cwd, and there is no
   mapping from a project id to a path (F13).
3. **Plain `http://` was allowed to any opted-in, unlocked host.**

The plan review found two further problems.

- **First draft: an allowlist that needed no opt-in.** A committed config, including one in an
  untrusted clone, could then switch egress on with a developer's ambient key. That is the
  defect ADR-0034 removed.
- **The checked host can differ from the dialled host.** `urlsplit` and `urllib.request.Request`
  disagree on some inputs, for example `https://decider.corp.example\@evil.com`.

## Decision

### D1: one predicate, now with an allowlist and a plaintext refusal

This decision amends ADR-0034 D1.

```
egress_allowed(url, env, cwd) =
    is_loopback(url)
    or ( url is https and dialled_host(url) is well-formed and opted_in(env)
         and ( not project_locked(cwd) or dialled_host(url) in allowed_hosts(cwd) ) )
```

- **Plaintext:** every non-loopback `http` URL is refused.
- **The dialled host:** `dialled_host` is the host `urllib.request.Request` will dial, with the
  port stripped, lower-cased and the trailing dot stripped. It must equal the `urlsplit`
  hostname normalised the same way. A URL that contains whitespace, a control character or `\` is
  refused. The allowlist therefore judges the host that is actually dialled.
- **Where it is enforced:** `post_json` evaluates this on every POST and caches nothing. The
  checks in `pipeline_for` and Jev's `_resolve` only produce early, readable refusals.

### D2: `allowHosts` relaxes a lock but never replaces the opt-in

This decision amends ADR-0034 D2.

`dataPolicy` may be either `"local-only"` or `{"mode": "local-only", "allowHosts": [...]}`.

**Matching.** An allowlisted host passes only when the session has opted in.

- `allowed_hosts` is the intersection of the lists of every locking ancestor. A nested project
  can narrow its parent's list but never widen it, which keeps ADR-0034 D2's rule that a nested
  config cannot override its parent's lock.
- A locking config with no valid list contributes the empty set.

**Entries.** Each entry is an exact host matching `HOST_PATTERN`:

- LDH labels, with at least one dot;
- the last label starts with a letter, which excludes dotted IPv4, IPv6 and numeric shorthand such as `0x7f.0x1`;
- an optional trailing dot;
- matched case-insensitively, ignoring the URL's port.

A single bad entry, a wrong `mode`, an unknown key or a list that is not a list voids the whole
allowlist. The config still locks.

`HOST_PATTERN` is pinned against the schema's pattern by a test.

**Carry-over.** On a re-scaffold, a valid object is kept verbatim. An invalid one is written back
as `"local-only"`, and the scaffold notes that the allowlist was dropped.

### D4: Jev resolves through the predicate

This decision amends ADR-0034 D4.

`_resolve` asks `egress_allowed` first. When it refuses, it reports one of these codes:

- `not-opted-in`;
- `locked`, naming the config and noting that the host is not in its `allowHosts`;
- `plaintext`.

A custom endpoint still never receives `OPENROUTER_API_KEY`.

### D7: an exported project id must match the cwd's

When `AI_BADGER_PROJECT_ID` is set, and is not blank after stripping, `pipeline_for` compares it
with the id read from the nearest `.ai-badger/project-id` above the cwd. It does not use
`resolve_project_id`, which would return the override itself.

A mismatch, or a missing walked id, means no pipeline. The single local search still runs. When
the session opted in, the refusal is reported once, with no ids or prompt text. No id-to-root
registry is added.

## Consequences

**Positive**

- A client repository can stay locked and still use an approved company endpoint.
- An untrusted repository's config cannot switch egress on.
- An exported project id can no longer route a locked project's memory out from an unlocked
  directory.
- No plaintext egress.

**Negative**

- Scaffolders older than 0.186.0 reject the object form. The 0.185.0 runtime reads it as a full
  lock, which fails closed.
- An operator whose `AI_BADGER_PROJECT_ID` deliberately points elsewhere loses the pipeline.
- A company endpoint inside a locked project still needs the developer's global opt-in. That
  opt-in also enables OpenRouter in unlocked repositories.

**Neutral**

`HTTPS_PROXY` is still ignored. Honouring it is connectivity, not policy: without it, egress fails
closed as `transport`. It is its own follow-up change.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Allowlisted host needs no opt-in | A committed config, including an untrusted clone's, would switch egress on with the developer's key (security plan review, MUST-1) |
| Union across locking ancestors | A nested config could widen its parent's lock, contradicting ADR-0034 D2 |
| A sibling key `dataPolicyAllowHosts` | Two keys to carry over, and an orphaned list could exist without a lock |
| Suffix or wildcard matching | `evil-decider.corp.example`-style bypasses |
| Dropping only a bad entry | A typo would silently widen nothing but hide the mistake; voiding fails visibly |
| An id-to-root registry for `AI_BADGER_PROJECT_ID` | None exists (ADR-0025); a mismatch refusal closes the gap without one |
| Refusing plaintext only when a proxy is set | Leaves plaintext delivery to opted-in unlocked hosts |
