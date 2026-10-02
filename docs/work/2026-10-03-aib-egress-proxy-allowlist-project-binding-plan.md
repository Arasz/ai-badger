# Plan: host allowlist, project-id binding and plaintext refusal (T1a), proxy tunnel (T1b)

**Task:** `aib-egress-proxy-allowlist-project-binding`, loop **high**.
**Research:** [`2026-10-03-aib-egress-proxy-allowlist-project-binding-research.md`](2026-10-03-aib-egress-proxy-allowlist-project-binding-research.md).
**Status:** the architect lane drafted the plan, then a security and a testability review ran
(2026-10-03). This revision folds in both reviews. The two most important changes:

- The security review moved the opt-in requirement. An allowlist only **relaxes** a lock; it
  never replaces the opt-in.
- The `https`-proxy tunnel moved to its own PR (T1b, below). It is connectivity, not policy.
  Without it, egress through a corporate proxy fails closed as `transport`, and nothing leaks.

## Rule (T1a)

```
egress_allowed(url, env, cwd) =
    is_loopback(url)
    or ( url is https
         and dialled_host(url) is well-formed
         and opted_in(env)
         and ( not project_locked(cwd) or dialled_host(url) in allowed_hosts(cwd) ) )
```

**The URL being sent to**

- **Every non-loopback `http` URL is refused** (`egress-refused`), with or without a proxy. This
  closes plaintext delivery: MITM or DNS spoofing to a host nobody approved.
- **`dialled_host`** is `urllib.request.Request(url).host`, with the port stripped, lower-cased and
  any trailing dot removed. It must equal `urlsplit(url).hostname` normalised the same way.
  Refuse any URL that contains whitespace, a control character or `\`. The allowlist then
  compares exactly the host that gets dialled.
- **Matching ignores the URL's port.** Any port on an allowlisted host passes.

**The `allowHosts` list**

- **Where it lives:** `dataPolicy` is either `"local-only"` or
  `{"mode": "local-only", "allowHosts": [...]}`.
- **Combining configs:** `allowed_hosts` is the intersection of every locking config's list.
  - A config that locks but has no valid list contributes the empty set.
  - When no config locks, the allowlist is not consulted.
- **Malformed lists:** if any entry is malformed, the whole list is void and the config still
  locks. Each of these voids the list:
  - a wildcard, a port, a URL, or a non-string entry;
  - `mode` other than `"local-only"`;
  - an unknown key;
  - `allowHosts` that is not a list.
- **What a valid entry looks like:** it is checked against `HOST_PATTERN`. The entry needs at
  least one dot, and its last label must not be all digits, which rules out IPv4 and numeric
  hosts. Entries are lower-cased and a trailing dot is stripped.
- **Twin check:** `HOST_PATTERN` equals the pattern in the schema's `oneOf` object branch.
- **Carry-over:** on a re-run, a valid object is kept verbatim. An invalid one is written back as
  `"local-only"`, with a note saying the allowlist was dropped.

**Enforcement**

- **Enforcement point.** `post_json` re-evaluates the rule on every POST and never caches it. The
  checks in `pipeline_for` and Jev `_resolve` are advisory.
- **Project id.**
  - **When it applies:** only when `AI_BADGER_PROJECT_ID` is set and not blank. A blank or
    whitespace value counts as unset.
  - **The walked id:** comes from `store._nearest_project_id_file(cwd)`, never from
    `resolve_project_id`, which returns the override itself.
  - **The comparison:** `override.strip()` must equal the walked id. A missing walked id counts as
    a mismatch, so a nested override that names a parent's id refuses.
  - **On a mismatch:** `pipeline_for` returns `None`. If the session opted in, the refusal is
    reported once.
  - **The threat it closes:** an unlocked cwd plus an override that names a locked project's id
    would otherwise pull that project's memory into an OpenRouter POST.
- **Jev.** `_resolve` asks `egress_allowed` first. When it refuses, the reason is one of:
  - `not-opted-in`;
  - `locked`, naming the config and saying that the host is not in `allowHosts`;
  - `plaintext`, for a non-loopback `http` URL.

## Steps (T1a, PR #550)

| Step | Goal | Depends on | Files |
|---|---|---|---|
| `allowlist-object-form` | The rule above (minus project id), `HOST_PATTERN`, `allowed_hosts`, `dialled_host`, plaintext refusal, schema `oneOf`, `config_writer` carry-over; `scaffold.py` stays at ≤850 lines | — | both `openrouter_client.py`, `schemas/config.schema.json`, `config_writer.py`, `scaffold.py` (only the call line if needed), `test_memory_context_egress.py`, `test_config_data_policy.py`, `test_scaffold_config_version.py` |
| `jev-routes-through-egress` | `_resolve` uses `egress_allowed` first, with refusal codes | allowlist-object-form | `jev_choice.py`, `test_jev_choice.py` |
| `project-id-binding` | Refuse on an id mismatch | allowlist-object-form | `memory_context.py`, `test_memory_context_pipeline_wiring.py` |
| `adr-docs-release` | ADR-0035, `data-access.md`, skill docs, changelog 0.186.0, `VERSION` | allowlist-object-form | docs, `VERSION` |
| `join` | Regen chain, gates, review-tests by a non-author, key-shape scan | all | — |

## Witnesses and mutations

Each witness is red on 0.185.0 for the stated reason. New names are stubbed first, so a witness
fails on its assertion, not on an `AttributeError`. End-to-end `post_json` witnesses are
preferred.

### `allowlist-object-form`

**Witnesses**

| ID | Setup | Expected |
|---|---|---|
| A1 | Locked project with `{allowHosts: ["decider.corp.example"]}`, opt-in on | `post_json` to `https://decider.corp.example/v1` reaches the recording opener |
| A2 | Same project, **no opt-in** | `egress-refused`, zero requests (security M1) |
| A3 | Same project | `https://openrouter.ai` refused, even with the opt-in |
| A4 | Same project, opt-in on | `evil-decider.corp.example` and `decider.corp.example.evil.example` refused |
| A5 | `https://decider.corp.example:/x`, `https://evil.com\t.decider.corp.example/`, `https://decider.corp.example\@evil.com` | Refused (security M2) |
| A6 | Opted in, unlocked, `http://decider.corp.example/` | Refused; a loopback `http` control still passes (security S1) |
| A7 | Entry `Decider.Corp.Example.` | Matches `https://DECIDER.corp.example.:8443/x` |
| A8 | Entries containing a wildcard, a port, a URL, an IPv4 address, a single label or a non-string; or `mode` other than `"local-only"`, an unknown key, a non-list `allowHosts` | Each voids the whole list, even next to a good entry |
| A9 | Intersection cases | Parent `[a, b]` with child `[b, c]` allows `b` only. A string-form parent with an object child allows nothing |
| A10 | Shared entry matrix | Schema and client agree, and the patterns are equal |
| A11 | Re-run carry-over | A valid object is kept verbatim. An invalid one is written back as `"local-only"`, and the note mentions the dropped list |

**Mutations**

- Opt-in skipped for allowlisted hosts.
- Allowlist ignored.
- `endswith` used for matching.
- Union instead of intersection.
- Only the bad entry dropped.
- Scheme check removed.
- Match on `urlsplit` only.
- Carry-over always writes `"local-only"`.

### `jev-routes-through-egress`

**Witnesses**

| ID | Setup | Expected |
|---|---|---|
| J1 | Locked project with an allowlisted custom endpoint, opted in | Resolves |
| J2 | Same, no opt-in | `not-opted-in` |
| J3 | Same project, default OpenRouter endpoint, opted in | `locked`, with the reason naming the config |
| J4 | `https://evil-decider.corp.example` | Refused |

**Mutations**

- Allowlist bypassed.
- Old refusal order.

### `project-id-binding`

**Witnesses**

| ID | Setup | Expected |
|---|---|---|
| B1 | Unlocked cwd with id `open-id`; override `locked-id`, passed in `env` with `os.environ` clean; opted in | `pipeline_for` is `None`; the single search still runs |
| B1b | Same override supplied through `os.environ`, with `env` empty | Same as B1 |
| B2 | Override equal to the file id, space-padded | Builds |
| B3 | No file id plus an override | `None` |
| B4 | Blank override | Treated as unset |
| B5 | Refusal reporting | Reported once when opted in; silent otherwise |
| B6 | Nested: override equals the parent's id | `None` |

**Mutations**

- Binding removed.
- `resolve_project_id` used for the walked id (the tautology).
- A `None` walked id counts as a match.
- No `strip`.

### Existing tests that stay green

- `tests/test_memory_context_transport.py:675-679`: a padded override against a file id. The
  block is still non-`None`.
- The `ENV_NAMES` AST scan.
- `test_g2_scrub_holds_against_outer_env`.

## Rewritten tests (named in the PR)

- `test_the_schema_enum_is_the_client_local_only_value`: now checks the `oneOf` shape, the `mode`
  const, and the twin `HOST_PATTERN`.
- Any Jev refusal-reason test whose text changes.

## T1b: `aib-egress-https-proxy-tunnel` (next PR, after #550)

**Behaviour**

- A non-loopback `https` POST goes through an `http://host:port[/]` proxy taken from the passed
  env, using the constants `https_proxy` / `HTTPS_PROXY`.
  - When the lowercase variable is present, it wins, even if blank. A blank value means no proxy.
  - `no_proxy` / `NO_PROXY` follow the same lowercase-present-wins rule, through
    `proxy_bypass_environment`. Never `proxy_bypass`, which on macOS reads system settings and
    leaks a DNS lookup.
- `Request.set_proxy` is called per request. `_tunnel()` goes inside `_DeadlineHTTPSConnection.connect`,
  with `server_hostname=_tunnel_host`.
- The `Host` header on the tunnelled request must be the target's (testability M1).
- A malformed proxy value gives `transport`, with zero dials.
- Loopback is never proxied, and `ProxyHandler({})` stays.
- `ENV_NAMES` gains the four names, and so does Jev's env-name list.

**Tests**

- A `CaptureProxy` fake:
  - it dials upstream at call time, through the net guard;
  - handlers catch `BaseException`;
  - it relays on raw sockets;
  - it has `refuse` and `hang` modes, with a 3 s ceiling.
- The certificate gains `DNS:decider.test` and keeps `IP:127.0.0.1`.
- Timing uses a 0.3 s share and asserts under 1.5 s.

**Mutations:** P1–P8.

**Docs:** the proxy routes traffic but is not a policy control:
- ai-badger never forces it;
- `NO_PROXY=*` dials direct;
- a TLS-inspecting proxy sees the payload;
- `SSL_CERT_FILE` handling is INFERRED.

## Out of scope (listed as "not governed" in data-access.md)

- `HTTP_PROXY` and `ALL_PROXY`.
- System and PAC proxies.
- Proxy authentication.
- An allowlist for unlocked projects.
- A registry mapping project ids to roots.
