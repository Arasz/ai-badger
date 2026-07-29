# ADR-0014 — MCP support is configuration, not retrieval

**Date:** 2026-07-29
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude
**Supersedes:** [ADR-0013](0013-what-the-mcp-tool-index-is-for.md) in part. Its three purposes
stand. Its central premise — that tool definitions are already resident in the model's context —
is **false on current Claude Code**, and the ordering it derived from that premise is reversed
below. [ADR-0012](0012-bm25-retrieval-with-a-falsifiable-eval.md) is untouched: BM25 remains the
matcher for the per-turn path, which survives.

> **Correction (2026-07-29, same day).** Context §5 below describes `mcp-tags.json` as documenting
> "the closed taxonomy ADR-0012 reversed". That is wrong. [ADR-0012](0012-bm25-retrieval-with-a-falsifiable-eval.md)
> line 63 exempts it in as many words — *"`mcp-tags.json` is unaffected"* — and the file is live in
> `_auto_tags`, `cmd_validate` and `cmd_tag`. Only its own `description` field is stale. Decision
> point 4 stands unchanged; the reason given for it did not. Recorded here rather than edited into
> the text above, per `README.md`: the value of the record is that it says what was believed at the
> time. See [`docs/changelog/0.50.0-mcp-support-is-configuration-not-retrieval.md`](../changelog/0.50.0-mcp-support-is-configuration-not-retrieval.md).

## Context

ADR-0013 scoped this feature to three purposes and ranked ranking quality last. It reasoned from
a premise stated plainly in its own text: *"On a host that loads MCP tool definitions itself —
Claude Code does — ai-badger's hint does not replace them, it is appended to them."*

That premise no longer holds, and two further facts discovered since change what is buildable.

### 1. The definitions are not resident — the model sees names without descriptions

Claude Code defers tool definitions through ToolSearch once deferrable definitions reach a
fraction of the context window (`ENABLE_TOOL_SEARCH`, default 10%). **Confirmed first-hand**: the
session in which this ADR was written is running deferred, and its own system messages say so —

> Some tools are deferred and not listed above. […] Until fetched, only the name is known — there
> is no parameter schema, so the tool cannot be invoked.

So on a machine with enough servers connected, the model is working from **~275 tool names with
no descriptions and no schemas**. Hermes behaves comparably.

This inverts ADR-0013's ordering. Supplying curated intent for a tool the model can see only as
`rider:apply_patch` is not redundant with a description the model already has — **there is no
description**. Purpose 1 (curation the model cannot derive) is the strongest of the three, not a
consolation prize.

It does not invalidate the measurement that produced ADR-0013: the LLM-versus-matcher experiment
supplied the full list *explicitly in its prompt*, so its finding — that a model reading
descriptions beats our matcher 0.846 to 0.442 — stands on its own terms. What no longer follows
is the inference to production, which assumed those descriptions were there.

### 2. Pruning is real, and on one host it is ours to write

Both target hosts can remove tools rather than merely rank them.

- **Hermes**: `mcp_servers.<server>.tools` takes `include` / `exclude`, exact names or fnmatch
  globs, applied at *registration* — a filtered tool never enters the tool definitions and its
  name never reaches the model. Fully declarative YAML; the interactive `hermes mcp configure` is
  a front-end over the same key. **But it lives in `~/.hermes/config.yaml`, user-global, with no
  project override.**
- **Claude Code**: agent definitions accept `disallowedTools`, and server-level specs
  (`mcp__server`, `mcp__server__*`) are documented as *removing* every tool from that server.
  Agent definitions live in `.claude/agents/*.md` — **project-scoped and committable**, a file a
  scaffolding framework legitimately owns. *Reported from the 2.1.220 schema by research; not
  verified on this machine, which has no agent definitions. Verify before building on it.*

### 3. A scaffolder owns two of seven arrival routes

MCP servers reach Claude Code by at least seven routes: project `.mcp.json`, user-global
`~/.claude.json`, user config per project, plugin-provided `.mcp.json` (user scope),
extension-provided, auto-fetched cloud connectors, and CLI-added. ai-badger can write **two**.
Hermes has one, and it is user-global.

This is why the index sees tools from servers ai-badger never declared and cannot declare, and it
is the constraint any design must state rather than assume away.

### 4. ai-badger was committing the overreach it warns against

`.mcp.json` is tracked, ships in the plugin payload, and carries absolute paths from the
maintainer's machine. Claude Code loads a plugin's `.mcp.json` at **user** scope, so installing
ai-badger configures two permanently-broken user-global servers for every installer
([#173](https://github.com/Arasz/ai-badger/issues/173)).

### 5. The definitions are scattered across three registries

`features/common/external-tools.json` (where servers actually live),
`features/common/mcp-servers.json` (empty), `features/common/mcp-tags.json` (documents the closed
taxonomy ADR-0012 reversed), plus `features/mcp/` — a *stack for authoring MCP servers*, sharing a
name with none of it.

## Decision

**MCP support is a configuration concern, wired like skills. Retrieval is a secondary path over
whatever configuration produces.**

1. **MCP tools become a first-class catalog feature**, mirroring how skills already work: a
   per-stack `mcp/` directory and a `stack-mcp.json` declaring configuration, resolved by the
   same stack-aware scaffolding that already filters skills correctly at install time (ADR-0010).
2. **`external-tools.json` is removed.** Its one real entry (`code-review-graph`) carries an
   `instructions` blob and `generate_mcp_json`; a skill with an `mcp-tool` field subsumes both,
   and lets the hand-written instructions be maintained where instructions belong.
3. **`mcp-servers.json` is deleted** unless a reader is found. It is empty and schema'd, the same
   shape as `mcp-tools.yaml.tmpl`, which was registered in `index.json`, copied by nothing, and
   removed in #145 once someone checked.
4. **`mcp-tags.json` survives only if it earns it** — as vocabulary for grouping, display and
   stack inference, never as a matching key. Its description, which still claims tags drive
   recommendation, is corrected. ADR-0012 is not edited.
5. **Per-agent adjustment is where server configuration happens**, in `features/<agent>/
   adjustments/`, the existing mechanism. What each agent supports is a researched fact per
   agent, not an assumption.
6. **ai-badger proposes user-global configuration; it never writes it.** It may write
   project-scoped files it owns. `.mcp.json` stops shipping.
7. **The index records server *status*, not just tools.** Dropping zero-tool servers (#145)
   collapsed `enabled: false` and enabled-but-not-running into one silence with opposite
   remedies — the fourth instance of that failure in this repository.

## Consequences

### Positive

- Curation is now justified by a measured fact about what the model can see, rather than hoped
  to be useful.
- Pruning becomes buildable on at least one host in a file ai-badger owns, which is the first
  mechanism found that does more than describe.
- One concern, one home, one name — replacing three registries and a name collision.
- #173 stops shipping broken configuration to every installer.

### Negative

- ADR-0013's ordering is reversed one day after acceptance. The three purposes were right; the
  premise underneath them was not. Recorded rather than quietly amended.
- The `disallowedTools` capability is unverified locally. If it does not behave as reported,
  Claude-side pruning has no mechanism and only Hermes does.
- A rebuild is more work than a consolidation, and the per-turn hint keeps running throughout.

### Neutral

- The per-turn retrieval path survives unchanged. It was measured as having no detectable effect
  where descriptions are resident — but that condition is now known to be uncommon, so the
  measurement's applicability is narrower than it appeared.
- Two claims in earlier documents are wrong and are corrected wherever they appear: skill listings
  are **shortened to fit** a budget rather than dropped least-invoked-first, and tool schemas are
  not universally resident.

## Alternatives considered

- **Keep consolidating rather than rebuilding.** Rejected: three registries disagreeing about one
  concern is not a layout problem, and the empty one and the superseded one both read as current.
- **Prune by stack.** Measured and rejected as the primary axis: no mechanical tool→stack path
  exists (7 of 98 tools with a hand-written alias table; none of four servers named after any
  ai-badger stack), and under shipped defaults a stack-scoped listing filters nothing on three of
  six real project profiles. The useful axis is **server relevance**, which a human states once.
- **Ship an embedding model.** Rejected in ADR-0013 on distribution grounds; unchanged.
