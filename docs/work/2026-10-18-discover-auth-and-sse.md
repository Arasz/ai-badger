# Research: how `mcp-index --discover` should handle authorized servers, and whether it needs SSE

**Date:** 2026-10-18
**Question:** (1) Auth: how should `--discover` enumerate MCP servers that need authorization (HTTP 401) or a user login; (2) SSE: is any MCP server on this machine configured with the legacy HTTP+SSE transport?

## Questions (verbatim)

1. **Auth.** How should `--discover` enumerate MCP servers that need authorization (HTTP 401) or a user login? Today these report `needs authorization`: plugin:context7, plugin:figma, plugin:huggingface-skills, plugin:canva, tinyfish. The 8 `claude.ai *` connectors are named `host-managed connector (OAuth)` and skipped. Cover: (a) what the MCP authorization spec requires (2025-06-18 and any newer revision): OAuth 2.1 + PKCE, RFC 9728 protected-resource metadata via `WWW-Authenticate: resource_metadata`, RFC 8414 AS metadata, dynamic client registration RFC 7591, client ID metadata documents, the loopback redirect; (b) MEASURE what each 401 server actually returns: status, `WWW-Authenticate` header, `/.well-known/oauth-protected-resource` and AS metadata, whether DCR is offered — plain unauthenticated GET/POST only, never send credentials; (c) whether any of them accepts a static API key or header instead (context7 API key, tinyfish key, HF token), citing their docs; (d) where Claude Code keeps MCP OAuth tokens (keychain item names, `~/.claude/.credentials.json`, `mcpOAuth` keys) — existence and metadata only, never secret values — and whether reusing them is appropriate (default stance: do not); (e) how claude.ai connectors are reached (proxy, account auth), and whether a third-party client can enumerate them at all; (f) design options, ranked: our own interactive OAuth login (browser + loopback + PKCE + DCR, token storage via the OS keychain using platform APIs, refresh); static headers from env; skip and report — for each the cost, the security surface, and what it would unlock.
2. **SSE.** Is any MCP server configured on this machine with the legacy HTTP+SSE transport (`"type": "sse"`, or a URL ending `/sse`)? MEASURE by scanning every config source `server_configs.py` reads, plus `claude mcp list` from `/Users/arasz/RiderProjects/ai-raccoon`; report counts per source, name each SSE server, say whether supporting SSE would unlock anything here; READ the spec status of SSE to judge whether support is worth adding.

All probes ran once, 2026-10-18 ~14:20 UTC, on MacBook-Air-Arasz (Darwin 27.0.0), Claude Code 2.1.302, from a home network. Scripts and raw output live in the session scratchpad, not in the repo.

## Per-server 401 table

Unauthenticated `POST initialize` to the configured URL, no config headers, no credentials. "Static key" is from vendor docs (F7-F9).

| server | status | `resource_metadata` in 401 | PRM | AS | DCR (`registration_endpoint`) | CIMD | static-key option |
|---|---|---|---|---|---|---|---|
| plugin:context7 (`?client=claude-code-plugin`) | 401 | yes | 200 | clerk.context7.com, context7.com | yes | yes (clerk) | `Authorization: Bearer <API key>` |
| plugin:figma | 401 | yes, `scope="mcp:connect"` | 200 | api.figma.com | advertised; client_name allowlist | no | none (OAuth only) |
| plugin:huggingface-skills (`?login`) | 401 | yes | 200 | huggingface.co | yes | yes | `Authorization: Bearer hf_…` |
| plugin:canva | 401 | yes | 200 | mcp.canva.com | yes | yes | none |
| tinyfish | 401 | yes | 200 (path form only) | clerk.tinyfish.ai | yes | no | `Authorization: Bearer sk-tinyfish-…` |

```chart:matrix
title: 401 servers against discovery and key options (1 = yes)
server, 401, PRM, DCR, CIMD, statickey, anon
context7, 1, 1, 1, 1, 1, 1
figma, 1, 1, 1, 0, 0, 0
hf, 1, 1, 1, 1, 1, 1
canva, 1, 1, 1, 1, 0, 0
tinyfish, 1, 1, 1, 0, 1, 0
```

## SSE count per source

| source | entries | `type: sse` | URL ends `/sse` |
|---|---|---|---|
| `~/.claude.json` user scope | 3 | 0 | 0 |
| `~/.claude.json` project scopes | 1 | 0 | 0 |
| installed plugins (`.mcp.json` / `plugin.json`) | 14 | 0 | 2 (product-legal: Atlassian, Asana; plugin disabled) |
| synced plugins | 1 | 0 | 0 |
| `/Users/arasz/RiderProjects/*/.mcp.json` | 54 | 0 | 0 |
| `*/.claude/settings*.json`, `~/.claude/settings*.json` | 1 | 0 | 0 |
| `~/.hermes/config.yaml` | absent | — | — |
| `claude mcp list` (ai-raccoon) | 24 rows | 0 | 0 |

## Design options

```chart:matrix
title: options against cost (1 low - 3 high), servers unlocked here of 13 skipped, security surface (1 low - 3 high)
option, cost, unlocked, surface
host init names, 1, 8, 1
headers+helper, 1, 3, 2
skip and report, 1, 0, 1
own OAuth, 3, 4, 3
reuse CC tokens, 2, 4, 3
```

## Findings

### F1 — The 2025-06-18 spec makes PRM discovery, AS metadata, PKCE and `resource` mandatory, and DCR a SHOULD [READ]

Servers MUST serve RFC 9728 metadata and point to it from `WWW-Authenticate` on a 401. Clients MUST use PRM to find the authorization server and RFC 8414 metadata for its endpoints. They MUST use PKCE and send RFC 8707 `resource` on both authorization and token requests. Redirect URIs MUST be localhost or HTTPS. DCR (RFC 7591) is a SHOULD. Tokens go in `Authorization: Bearer`, never in the query string, and clients MUST store them securely.

**Evidence:** https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization — Overview items 1-4, "Authorization Server Location", "Resource Parameter Implementation", "Communication Security", "Authorization Code Protection".

### F2 — Later revisions rank client registration as pre-registration, then CIMD, then DCR; 2026-07-28 deprecates DCR [READ]

2025-11-25 adds Client ID Metadata Documents (SHOULD) and demotes DCR to MAY. Clients try pre-registered info, then CIMD when `client_id_metadata_document_supported` is true, then DCR, then ask the user. It requires S256 and says a client MUST refuse when `code_challenge_methods_supported` is absent. It requires a well-known PRM fallback when `WWW-Authenticate` has no `resource_metadata`, and both RFC 8414 and OIDC discovery. 2026-07-28 marks DCR deprecated and adds RFC 9207 `iss` validation. CIMD needs an HTTPS-hosted metadata document. The spec itself says CIMD cannot stop localhost impersonation, which is the case for a CLI.

**Evidence:** https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization ("Client Registration Approaches", "Authorization Code Protection", "Localhost Redirect URI Risks"); https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization (Overview item 3, "Authorization Response Validation").

### F3 — All five 401 servers publish spec-shaped PRM and AS metadata with S256 and a registration endpoint [MEASURED]

Every server answered 401 with `WWW-Authenticate: Bearer resource_metadata="…"`. Its PRM returned 200 JSON naming its authorization servers, and each AS metadata document listed `code_challenge_methods_supported` including `S256` plus a `registration_endpoint`. The AS documents of context7 (Clerk), HF and Canva also advertise `client_id_metadata_document_supported: true`; Figma and tinyfish do not. Figma's token endpoint lists no `none` auth method, so a public client gets a client secret back from DCR. For tinyfish, only the path-form PRM (`/.well-known/oauth-protected-resource/mcp`) exists; the root form is 404. See the per-server table.

**Evidence:** `python3 -I probe.py context7=… figma=… hf=… canva=… tinyfish=…` (scratchpad `probe.py`, urllib, no redirects followed, UA `ai-badger-probe/1`) → `probe.out`: five 401s; PRM 200 at each `resource_metadata` URL; AS metadata 200 at `<issuer>/.well-known/oauth-authorization-server`; fields as tabulated. Run once.

### F4 — context7 and HF answer anonymously on their bare URL; the 401 comes from the plugin's query string [MEASURED]

Run against the URLs as configured, `mcp_client.list_tools` gets 401 for `https://mcp.context7.com/mcp?client=claude-code-plugin` and `https://huggingface.co/mcp?login`. Run against the bare URLs it succeeds: context7 returns 2 tools (`query-docs`, `resolve-library-id`) in 1.3s and HF returns 4 (`hf_fs`, `hf_whoami`, `hub_repo_details`, `hub_repo_search`) in 0.8s. Signed in through Claude Code, the same HF plugin exposes 6 tools, so the anonymous HF list is incomplete. The context7 list matches.

**Evidence:** scratchpad heredoc calling `mcp_client.list_tools({"type":"http","url":u}, 20)` for six URLs → `anon.out`. The 6-tool HF count comes from the `claude -p` init event in F12.

### F5 — `mcp_client` reports 403 for Asana and Atlassian, where a probe with a different User-Agent gets 401 [MEASURED]

`probe.py` got 401 with `invalid_token` from both `/sse` endpoints. `mcp_client` got 403 from both and reported it as "needs authorization (HTTP 403)". Atlassian's 401 carries no `resource_metadata`, and its PRM is 404 at both well-known paths. That is non-conformant with 2025-06-18; only its AS metadata (origin-level) exists. Asana's PRM names `resource: https://mcp.asana.com` with no path.

**Evidence:** `probe.out` (atlassian, asana sections) against `anon.out` (last two lines). The two clients differ in User-Agent and Accept headers.

### F6 — `mcp_client` treats 401 and 403 alike and never reads `WWW-Authenticate` [READ]

`_Http._open` maps both codes to `Unauthorized("needs authorization (HTTP n)")` and discards the headers. Under 2025-11-25 a 403 means insufficient scope, not a missing token. The challenge's `resource_metadata` and `scope` are exactly what a report or a login flow would need.

**Evidence:** `features/common/skills/mcp-index/scripts/mcp_client.py:291-299`; `tool_discovery.py:29-34`.

### F7 — context7 and tinyfish document a static API key sent as a Bearer header [READ]

context7: "pass your API key via the `Authorization: Bearer YOUR_API_KEY` header" to `https://mcp.context7.com/mcp`. tinyfish documents a manual config with `"Authorization": "Bearer YOUR_API_KEY"` (`sk-tinyfish-…`) for clients without browser sign-in.

**Evidence:** https://github.com/upstash/context7 README, "Installation"; https://docs.tinyfish.ai/mcp-integration, "Command Code" section.

### F8 — Hugging Face accepts an HF user token as a Bearer header [READ]

The official server documents `claude mcp add hf-mcp-server -t http https://huggingface.co/mcp -H "Authorization: Bearer <YOUR_HF_TOKEN>"` as the alternative to `?login`.

**Evidence:** https://github.com/huggingface/hf-mcp-server README, "Install in Claude Code"; https://huggingface.co/docs/hub/en/agents-mcp.

### F9 — Figma and Canva offer no static-key path; Figma also gates DCR by `client_name` [READ]

Figma's remote server authenticates only through the OAuth browser flow and admits DCR clients by an allowlisted `client_name`. An unlisted client gets a bare 403. A new ai-badger client would be refused unless it impersonated a listed name, which we must not do. Canva's remote MCP is per-user OAuth with no API key.

**Evidence:** https://workos.com/blog/figma-mcp-403-forbidden-client-name (2026-10-05, quoting Figma staff); https://forum.figma.com/suggest-a-feature-11/remote-figma-mcp-server-let-a-static-token-authenticate-as-an-alternative-to-oauth-57343; https://www.scalekit.com/blog/canva-mcp-vs-api ("Both paths are OAuth per-user").

### F10 — Claude Code holds MCP OAuth tokens in a keychain item and in a plaintext 0600 file, keyed per server [MEASURED]

The login keychain has a generic-password item with service `Claude Code-credentials`, created 2026-07-08 and modified 2026-10-18. `~/.claude/.credentials.json` exists (mode 0600, 4342 bytes) with top-level keys `claudeAiOauth` and `mcpOAuth`. `mcpOAuth` has 11 entries, each keyed `<server name>|<hash>`. They cover 4 of the 5 servers (context7, figma ×2, HF, canva) plus tinyfish, openrouter and four product-legal servers. Entry fields are `accessToken`, `discoveryState`, `serverName`, `serverUrl` (openrouter adds `clientId` and `redirectUri`). No entry has a `refreshToken` or `expiresAt` field. `~/.claude.json` holds `mcpNeedsAuthNoticed`, a list of 21 server names. No secret value was read out or printed.

**Evidence:** `security find-generic-password -s "Claude Code-credentials"` without `-w`/`-g` (attributes only) → `creds.out`; a Python heredoc printing key names and counts only → `credkeys.out`; `ls -la ~/.claude/.credentials.json`.

### F11 — Reusing Claude Code's tokens from `--discover` is not appropriate [INFERRED]

From F1, F2 and F10: the tokens were issued to Claude Code's client registration, and `discoveryState` is Claude Code's. The file format is undocumented and can change in any release. Each token is audience-bound to one server (RFC 8707), and the spec puts secure custody on the client that obtained the token. Reading them would make ai-badger a second holder of the user's credentials without their consent. Refreshing them would rotate tokens under Claude Code, and spec F1 requires refresh rotation for public clients, which could log Claude Code out. Keep the default: do not read them.

### F12 — Claude Code's headless init event already lists every connected server's MCP tool names, connectors included [MEASURED]

`claude -p --output-format stream-json --verbose` emits a `system/init` event before any model turn. Its `tools` array carried `mcp__<server>__<tool>` names for 12 servers: context7 2, figma 42, huggingface-skills 6, tinyfish 29, four `claude_ai_*` connectors (Claude Docs 8, Exa 3, Hugging Face 5, Microsoft Learn 3), plus ai-raccoon, imessage, playwright and roslyn-navigator. Its `mcp_servers` array carried per-server status. It has names only, no descriptions. Canva (needs authentication) and the disabled or unauthenticated connectors are absent. The host does the authenticating, so ai-badger handles no credentials.

**Evidence:** `claude -p --output-format stream-json --verbose --max-turns 1 "reply ok"` run from an empty scratchpad dir, killed after the init line; per-server `mcp__` counts parsed from `init.jsonl`. Run once.

### F13 — claude.ai connectors reach Claude Code through Anthropic's proxy on the Claude account, which a third-party client cannot use [READ]

Claude Code fetches the connector list itself and connects through `https://mcp-proxy.anthropic.com/v1/mcp/<mcpsrv id>` (transport `claudeai-proxy`), authenticated by the claude.ai login. A probe with no credentials got 401 `authentication_error`. It had no `WWW-Authenticate`, and PRM and AS metadata were 404. There is no public OAuth surface, so only the Claude account credential (`claudeAiOauth`) could reach it, and F11 rules that out.

**Evidence:** https://github.com/anthropics/claude-code/issues/83044 (log lines "Using claude.ai proxy at https://mcp-proxy.anthropic.com/v1/mcp/…"); https://code.claude.com/docs/en/mcp ("the claude.ai connectors Claude Code fetches itself"); `python3 -I probe.py claudeai_proxy=https://mcp-proxy.anthropic.com/v1/mcp/mcpsrv_test` → `proxy.out`.

### F14 — Claude Code's own status for these servers: four connected, canva needs authentication [MEASURED]

`claude mcp list` shows context7, figma, huggingface-skills and tinyfish as `✔ Connected`, and canva as `! Needs authentication`. Microsoft 365, Calendly and Indeed connectors also need authentication. So `--discover`'s "needs authorization" means "ai-badger has no token", not "the user is signed out".

**Evidence:** `claude mcp list` from `/Users/arasz/RiderProjects/ai-raccoon` → `mcplist.out` (27 lines, 24 servers).

### F15 — `server_configs`/`mcp_client` ignore `headersHelper`, which Claude Code supports for http/sse/ws servers [READ]

Claude Code can generate headers at connect time from a `headersHelper` command and re-runs it on auth errors. ai-badger's scripts have no reference to it, so a server configured that way would get no Authorization header from `--discover`. No spec on this machine uses `headersHelper` today (MEASURED by a JSON walk: 0).

**Evidence:** https://code.claude.com/docs/en/mcp (WebSocket section and "Failed discovery requests"); `grep -c headersHelper features/common/skills/mcp-index/scripts/*.py` → 0 in every file.

### F16 — Recommended: names from the host's init event, plus `headersHelper`, plus a richer skip report; do not build our own OAuth [INFERRED]

From F3, F9, F11, F12 and F14, the options rank:
1. **Ask the authenticated host** (F12). Cost: small, one subprocess plus a parser. Unlocks the tool names of every server the host has connected: 8 of the 13 skipped here (4 of the 5 401 servers, not canva; 4 of the 8 connectors). Security surface: none new. Limits: no descriptions, and the init format is undocumented.
2. **Static headers from env, plus honour `headersHelper`.** `${VAR}` header expansion already works (`mcp_client.py:266-268`). Adding `headersHelper` is small. It unlocks context7, HF and tinyfish if the user configures a key (F7, F8). Security surface: running a user-configured command, and keys in env.
3. **Skip and report, better.** Cost: trivial. Report the `resource_metadata`/scope from the challenge, tell 401 from 403 (F6), and point at `claude mcp login`. Unlocks nothing.
4. **Our own OAuth** (browser, loopback, PKCE, CIMD/DCR, keychain via platform APIs, refresh, RFC 9207 `iss`). Cost: large and ongoing. It would need an HTTPS-hosted CIMD document, which the stdlib client has no home for. It unlocks canva and tinyfish, plus context7 and HF in full. Not figma (F9), and not connectors (F13). Security surface: a second token store and a localhost redirect that can be impersonated (F2).
5. **Reusing Claude Code's tokens** is rejected (F11).

### F17 — The F12 init event is a stable interface across Claude Code versions [UNVERIFIED]

Checked on 2.1.302 only. No documentation found that commits to the `tools` array's shape.

### F18 — No configured MCP server uses the legacy HTTP+SSE transport [MEASURED]

No entry in any config source has `"type": "sse"`. Two URLs end in `/sse`: product-legal's Atlassian (`https://mcp.atlassian.com/v1/sse`) and Asana (`https://mcp.asana.com/sse`). Both are typed `"http"`, sit in a plugin that `enabledPlugins` has set to `false`, and are absent from `claude mcp list`. `claude mcp list` shows no SSE transport; every remote server reads `(HTTP)`. There is no `~/.hermes/config.yaml`. Counts per source are in the SSE table.

**Evidence:** scratchpad `scan.py` (imports `server_configs`, applies `mcp_client.transport_of`, flags `type == "sse"` or a path ending `/sse`) → `scan.out`: 74 entries, 2 `/sse` URLs; a product-legal `.mcp.json` dump (type/url only) plus `enabledPlugins` → `legal.out`; `mcplist.out`.

### F19 — HTTP+SSE has been deprecated since 2025-03-26, Claude Code falls back to it itself, and 2026-07-28 drops it from the standard bindings [READ]

2025-03-26 says Streamable HTTP "replaces the HTTP+SSE transport", which it calls deprecated, and keeps only a backwards-compatibility probe. 2026-07-28 lists only stdio and Streamable HTTP. Claude Code's docs call SSE deprecated: an `http` entry tries HTTP and switches to SSE on its own (v2.1.265+).

**Evidence:** https://modelcontextprotocol.io/specification/2025-03-26/basic/transports ("Streamable HTTP", "Backwards Compatibility"); https://modelcontextprotocol.io/specification/2026-07-28/basic/transports; https://code.claude.com/docs/en/mcp ("Option 2: Add a remote SSE server").

### F20 — Adding SSE support to `mcp_client` would unlock nothing here [INFERRED]

From F18: the only `/sse` endpoints are in a disabled plugin. From F5: both return 401/403 without a token, so even an SSE client would stop at "needs authorization". From F19: the transport is on its way out of the spec. Not worth the code.

## Still open

- DCR was not exercised. Registering would create a client on each vendor's server, so "registration works" is advertised, not proven, for all five. Figma's allowlist (F9) says it would fail for an unlisted name. Settle it with an owner-approved test registration against a throwaway account.
- Why do Asana and Atlassian give `mcp_client` 403 but `probe.py` 401 (F5)? The suspect is the default `Python-urllib` User-Agent or the Accept header hitting a WAF. Settle it by re-running `mcp_client` with only the UA changed.
- Is the `claude -p` init event's `tools` list stable across Claude Code versions (F17)? Settle it by checking the changelog, or by watching it across two releases before building on it.
- Do Claude Code's `mcpOAuth` entries carry refresh tokens in the keychain copy, given that the file copy has none (F10)? It is not answerable without reading secrets, and it does not change F11.
- Does the anonymous context7 tool set match the authenticated one exactly, beyond the names (F4)? Descriptions were not compared.
