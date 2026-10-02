# Data access

This page covers every way ai-badger's own scripts, hooks, skills and declared MCP servers can
send project data off the machine. For each one it gives the default and the switch.

The rule ai-badger follows is that only the agent host's own model provider receives project
data. That is Anthropic for Claude Code and GitHub for Copilot. For Hermes and pi it is whatever
provider the operator configured. Since 0.185.0 ai-badger's own scripts and hooks send nothing else
prompts, plans, memory or code unless someone opts in, and a project can make that refusal
permanent. pi delegation is the exception (see the table and the last section).

The evidence for each row is in the research record
[`docs/work/2026-10-02-aib-local-only-data-access-hardening-research.md`](../work/2026-10-02-aib-local-only-data-access-hardening-research.md);
the design is in [ADR-0034](../adr/0034-third-party-egress-is-opt-in-and-lockable.md).

## Surfaces

| Surface | What leaves | Destination | Default | Control |
|---|---|---|---|---|
| Per-prompt memory context, pipeline mode (`ai-raccoon-memory`) | the gated prompt; up to 48 memory **and source-code** excerpts (500 chars each) with their paths | OpenRouter chat completions (planner) and `/api/alpha/decisions` (`typesafe/jev-1.13`) | **off** | `AI_BADGER_ALLOW_THIRD_PARTY=1` + `OPENROUTER_API_KEY`, no `dataPolicy` lock |
| Per-prompt memory context, single search | nothing beyond the machine (stdio to the local `ai-raccoon` proxy) | local | on | `AI_BADGER_MEMORY_CONTEXT=0` turns the hook off |
| Jev advisory (`task-decomposition/scripts/jev_choice.py`) | plan step goals, instructions, acceptance criteria, files, verifier | OpenRouter decisions, or `AI_BADGER_JEV_ENDPOINT` | **off** | `AI_BADGER_JEV=1` + `_TIER=1`/`_WAVES=1`; a non-loopback endpoint also needs the opt-in and no lock |
| pi subagents by `level:` | the whole delegated task | the model `.ai-badger/model-groups.json` resolves (all `openrouter/*` ids) | on for pi projects | pi's own provider config; **not governed by the opt-in** |
| archify update check | an HTTPS GET (IP and headers, no content) | `tt-a1i.github.io` | on when the skill runs it | `ARCHIFY_UPDATE_CHECK_DISABLED=1` |
| archify brand capture | the URL the author names | that site | on demand | private addresses refused unless `ARCHIFY_BRAND_ALLOW_PRIVATE=1` |
| archify rendered HTML | the viewer's IP when the page is opened | Google Fonts | on open | none |
| feed-badger `open_pr.py` | files the agent generalised from the project | `git push` + `gh pr create` to the **public** `Arasz/ai-badger` | on demand | scans for credential-shaped strings only; review the diff before running it |
| Playwright MCP | npm package fetch (`@playwright/mcp@latest`), then any site the agent browses | npm, the web | declared when `npx` exists | `config.mcp.decline: ["playwright"]` |
| Hermes MCP | messages the agent writes | the chat platforms Hermes is connected to | declared when `hermes` exists | `config.mcp.decline: ["hermes"]` |
| ai-raccoon `memory_sync` | memory snapshots | the cloud storage configured in ai-raccoon | off unless configured | ai-raccoon config |

Everything else is local:
- the message bus, task tracking and the task-graph server (SQLite, stdio);
- the BM25 MCP recommender;
- the drift notice and the debug and audit logs;
- archify preview, which serves on loopback.

Git pushes and `gh` calls from the task and PR flows go only to the project's own `origin`.

## Opting in: `AI_BADGER_ALLOW_THIRD_PARTY`

Third-party egress needs `AI_BADGER_ALLOW_THIRD_PARTY=1`. The value must be the exact string
`1`, so `true`, ` 1` and `01` do not count.

An `OPENROUTER_API_KEY` in the environment does nothing on its own. Before 0.185.0 the key alone
switched the memory pipeline on.

The check sits in `openrouter_client.post_json`, the one function that opens a socket for these
features, so every call through `post_json` is checked. A loopback destination is always allowed:
`127.0.0.1`, `localhost` or `::1`, matched exactly, with no userinfo. Every other destination must
use `https://`: a non-loopback `http://` URL is refused even when opted in. A URL whose host
`urllib` would dial differs from the host it parses to (whitespace, control characters, `\`) is
refused too, so the checks below always judge the host that is actually dialled.

## Locking a project: `dataPolicy`

To make a repository local-only for every developer, whatever their shell sets, commit this to
`.ai-badger/config.json`:

```json
{ "dataPolicy": "local-only" }
```

The lock is checked by walking up from the session's working directory. Egress is locked when
any ancestor's `.ai-badger/config.json` matches any of these:
- it carries a `dataPolicy` key (any value);
- it is not a regular file (a directory, a FIFO, a dangling symlink);
- it cannot be reached or read (for example an unsearchable `.ai-badger/` folder), is larger
  than 1 MiB, or is not a JSON object.

The walk follows the symlink-resolved path, the path as given, and `$PWD` when it names the same
directory, so a host that reports the physical working directory still sees a lock above a
symlinked checkout. A nested project or an in-tree worktree under a locked directory stays
locked. A config without `dataPolicy` leaves the decision to `AI_BADGER_ALLOW_THIRD_PARTY`.

When you opted in and a lock refuses egress, the memory hook writes one line per process to
`~/.ai-badger/hook-errors.log` (a Hermes warning under Hermes) naming the locking config, never
the prompt: `memory_context.egress-refused <path>: dataPolicy`. Without the opt-in a refusal is
the normal default and is not logged.

Re-running `welcome-ai-badger` keeps an existing `dataPolicy`. Scaffolders older than 0.185.0
reject a config containing it, so upgrade ai-badger before committing it.

### Allowing named hosts in a locked project: `allowHosts`

A locked project can still reach an approved company endpoint, such as a decider deployed in the
company cloud:

```json
{ "dataPolicy": { "mode": "local-only", "allowHosts": ["decider.corp.example"] } }
```

The allowlist relaxes the lock; it never replaces the opt-in. A non-loopback POST from a locked
project needs `AI_BADGER_ALLOW_THIRD_PARTY=1` **and** a host in the allowlist. A committed config
cannot switch egress on by itself, so a cloned repository that lists `openrouter.ai` gains nothing
without the developer's opt-in.

- Entries are exact host names: case-insensitive, with a trailing dot ignored and any URL port
  accepted. `decider.corp.example` does not admit `evil-decider.corp.example` or
  `decider.corp.example.evil.example`.
- An entry must contain a dot and cannot be an IP address or end in an all-digit label. A
  wildcard, a port, a URL or a non-string entry, an unknown key, or a `mode` other than
  `"local-only"` voids the whole list; the project stays locked with nothing allowed.
- When several ancestors lock, only hosts listed by **all** of them pass: a nested project can
  narrow its parent's allowlist, never widen it. A string-form lock (`"local-only"`) anywhere
  above contributes an empty list, so it allows nothing.
- Re-running `welcome-ai-badger` keeps a valid object verbatim and writes an invalid one back as
  `"local-only"`, with a note that the allowlist was dropped. Scaffolders older than 0.186.0
  reject the object form; the 0.185.0 runtime reads it as a full lock.

### `AI_BADGER_PROJECT_ID` must match the working directory

When `AI_BADGER_PROJECT_ID` is set (and not blank), the memory pipeline runs only if it equals
the project id found by walking up from the working directory (`.ai-badger/project-id`). A
mismatch, or no id on the walk, leaves the single local search. This stops an exported id from
pulling a locked project's memory into a third-party request made from an unlocked directory.
When you opted in, the refusal is logged once, without the ids or the prompt.

## Jev endpoints

`jev_choice.py` picks its endpoint in three ways:

- **Default.** OpenRouter's decisions endpoint, authenticated with `OPENROUTER_API_KEY`. It needs
  the opt-in and no lock.
- **`AI_BADGER_JEV_ENDPOINT` on loopback.** Allowed even in a locked project. This is the slot
  for a local classifier (see below).
- **`AI_BADGER_JEV_ENDPOINT` anywhere else.** It must use `https://` and needs the opt-in. In a
  locked project its host must also be in `allowHosts`. This covers a company-cloud deployment.

A custom endpoint authenticates with `AI_BADGER_JEV_ENDPOINT_KEY`, and sends no `Authorization`
header when that is unset or empty. It never receives `OPENROUTER_API_KEY`.

When the advisory is enabled but no endpoint is permitted, `jev_choice.py` reports
`status: off` with a `refusal` code and a reason naming the cause: `not-opted-in`, `locked`
(naming the config and that the host is not in its `allowHosts`), `plaintext`, `no-key`,
`bad-endpoint`, `bad-endpoint-key` or `bad-test-base`.

## Local classifiers instead of Jev

| Option | Model | Where it runs | Fits |
|---|---|---|---|
| A: developer machine | `Mapika/decider-2b` (Apache-2.0, 1.9B), or `-4b` for more accuracy | `decider.serve` on Apple-Silicon MPS, or a Q4_K_M GGUF through llama.cpp on CPU | Jev's wire format on `/v1/systemone`: point `AI_BADGER_JEV_ENDPOINT` at it |
| A: relevance and re-rank | `ibm-granite/granite-embedding-reranker-english-r2` (Apache-2.0, 150M) | Text Embeddings Inference CPU image | memory scoring, MCP tool re-rank (not wired yet) |
| B: company cloud | `Mapika/decider-4b` on one small GPU; `pplx-decider-v1-27b` when near-Jev quality is needed | container in the VNet (AKS, Azure ML online endpoint, SageMaker, Vertex), behind the platform gateway (the decider server has no auth) | the same endpoint slot, over `https://` |

Three findings shape these options:
- **Accuracy.** On the community *Jev Decision Index 0.2.1*, decider-2b and decider-4b are close
  to Jev on tool retrieval (ToolRet 0.631 and 0.650, against Jev's 0.653) but well below it
  overall (28.97 and 40.70, against 57.91).
- **Calibration.** A stock small instruct model with a JSON schema is poorly calibrated for
  confidence-gated decisions (ECE 0.37).
- **Thresholds.** The thresholds tuned for Jev (0.6 for a tier, 0.7 for a wave) have to be
  refitted for each model.

Wire compatibility with `jev_choice.py` has not been run yet. The research record's "Still open"
list gives the evaluation that settles it.

## Not governed by `AI_BADGER_ALLOW_THIRD_PARTY`

- **Proxy bypass.** Once opted in, the OpenRouter client still ignores `HTTPS_PROXY`, so its
  calls bypass a corporate proxy or DLP inspection. Honouring it is the next planned change.
- **pi delegation.** The model registry accepts only `openrouter/*` ids, and pi's own memory and
  RAG extensions run outside ai-badger's hooks.
- **ai-raccoon embeddings.** The embedding engine stays local only when ai-raccoon is configured
  with a local engine (`ai-raccoon model embedding set local`).
- **Third-party MCP binaries.** The internal network behaviour of ai-raccoon, semantica and
  code-review-graph has not been audited.
- **External search in agent text.** The instruction "search externally when memory has no hit"
  makes the host agent use its own web search tool.
- **Loopback forwarders.** Loopback is not the same as on-machine. A local proxy on
  `127.0.0.1` (LiteLLM, an `ssh -L` tunnel) receives data even in a locked project, by design.
- **Process cwd.** The `jev_choice.py` CLI checks the lock at the process's cwd, not at the
  plan file's project. Run it from inside the project.
- **Refresh lag.** A consumer keeps the old behaviour until `den-refresh` re-scaffolds its
  `.ai-badger/` copies. Hermes picks it up when any project refreshes, because it shares one
  user plugin.
