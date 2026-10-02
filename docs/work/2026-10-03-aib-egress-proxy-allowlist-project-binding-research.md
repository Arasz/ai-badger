# Research: egress proxy, host allowlist and project-id binding

**Date:** 2026-10-02 (lane), recorded 2026-10-03
**Task:** `aib-egress-proxy-allowlist-project-binding`, which is T1 of
[`2026-10-02-data-access-follow-ups-plan.md`](2026-10-02-data-access-follow-ups-plan.md)
**Tree read:** 0.185.0 (`195b55db`). `OC` means
`features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py`; `MC` means
`memory_context.py` in the same directory. CPython citations are from 3.10. MEASURED results come
from a scratch script that loads the real client under 3.10.21 against loopback fakes.

## Proxy

**F1. The client ignores the proxy, and the target name is resolved directly.** MEASURED.
- **Test.** `HTTPS_PROXY` was set to a loopback capture proxy, then an opted-in POST went to
  `https://decider.test/…`.
- **Result.** The POST returned `transport`. The capture proxy saw nothing, and
  `getaddrinfo('decider.test')` ran.
- **Cause.** `make_opener` passes `ProxyHandler({})` to `build_opener`, which suppresses the
  default handler that would have read the proxy from the environment.

**F2. `ProxyHandler(dict)` cannot honour an explicitly passed env.** READ.
- `ProxyHandler.proxy_open` calls the module-global `proxy_bypass`.
- On darwin, `proxy_bypass` reads `os.environ`, and with no env proxy it falls back to the macOS
  SystemConfiguration proxy (`_scproxy`).
- So the decision belongs in our code, applied per request with `Request.set_proxy`.

**F3. Our custom `connect` skips the tunnel.** READ and MEASURED.
- `Request.set_proxy` swaps the request's host to the proxy and keeps the target as the tunnel
  host.
- `do_open` then calls `set_tunnel(target)`.
- The stock `HTTPSConnection.connect` runs `_tunnel()` and wraps TLS with
  `server_hostname=_tunnel_host`.
- `_DeadlineHTTPSConnection.connect` replaces the stock one. It never sends `CONNECT`, and does
  TLS straight to the proxy with SNI set to the proxy's name.

**F4. With `_tunnel()` added to our `connect`, the deadline and DNS behave correctly.** MEASURED.
- The proxy received `CONNECT decider.test:443`.
- Only the proxy host was resolved.
- `Proxy-Authorization` would go to the `CONNECT`; `Authorization: Bearer` stayed with the
  tunnelled request.
- Against a hanging proxy with a 0.5 s budget, the call ended at 0.50 s. The watchdog's socket is
  the one `_tunnel` reads from.
- From Python 3.12 the request line reads `HTTP/1.1`, so tests assert only the
  `CONNECT host:443 ` prefix.

**F5. `proxy_bypass_environment(host, {"no": value})` gives stdlib `NO_PROXY` semantics from a
passed value.** MEASURED.
- Domain suffix matching works: `a.corp.example` matches, `evil-corp.example` does not.
- An empty value bypasses nothing.
- CPython drops empty `*_proxy` values, and ours does the same.

**F6. Credential leak paths.** READ.
- `_parse_proxy` echoes the proxy URL in an exception message, so we parse the URL with
  `urlsplit` instead.
- `post_json` reports failures as bare `transport`, so a proxy URL never reaches a log.

**F7. The existing loopback-proxy test cannot catch a wrong design.** READ.
`test_o1_environment_proxy_is_ignored` sets `os.environ`. Under an env-parameter design it stays
green without testing anything, so it must pass `env=` explicitly.

## Allowlist

**F8. The lock lives in one place.** READ.
- `_config_lock` treats any `dataPolicy` key as a lock.
- `lock_reason` returns the first locking config found on the walk.
- `opted_in`, `third_party_allowed` and `egress_allowed` sit beside it.
- The schema is a string enum, `["local-only"]`.

**F9. `jev_choice` does not route through `egress_allowed`.** READ. `_resolve` checks
`opted_in`, then `lock_reason`. An allowlisted host would be refused before `post_json`, so
`_resolve` must ask `egress_allowed` first and derive its refusal codes afterwards.

**F10. The welcome carry-over writes the string `"local-only"`, which would drop an allowlist.**
READ (`config_writer._keep_data_policy`).

**F11. Object form or sibling key: both break 0.185.0 the same way.** READ.
- A 0.185.0 client reads either one as a full lock, because the key's presence is what locks.
- A 0.185.0 scaffolder rejects both.

The object form is preferred: there is one key to carry over, and the lock stays bound to its
allowlist.

**F12. Union across nested locks would contradict ADR-0034 D2.** READ. D2 says a nested config
cannot widen a parent's lock. Intersection keeps that promise.

## Project id

**F13. There is no mapping from a project id to a path.** READ.
- `badger_store` resolves the id from the cwd to the nearest `.ai-badger/project-id`, and its
  registry is never consulted.
- `MC._project_id` takes the env override first.

**F14. Nothing in the harness sets `AI_BADGER_PROJECT_ID` automatically.** INFERRED. Only
operators who export it by hand are affected by a strict rule.

## Decisions (logged in the auto-wm audit trail on 2026-10-02)

- **Proxy.** `https` targets only, through an `http://host:port` proxy read from
  `https_proxy`/`HTTPS_PROXY`, minus `no_proxy`/`NO_PROXY`.
  - A blank value means no proxy.
  - Loopback is never proxied.
  - Userinfo, another scheme, a path or a missing port gives `transport` with zero dials: fail
    closed, never a direct dial.
  - `ProxyHandler({})` stays.
- **Allowlist.** `dataPolicy` becomes either `"local-only"` or
  `{"mode": "local-only", "allowHosts": [...]}`.
  - Matching is on the exact https host: case-insensitive, with a trailing dot stripped.
  - A wildcard, a port or a URL in an entry is malformed and locks.
  - When several configs lock, only hosts in all of their lists pass (intersection).
  - An allowlisted host needs no opt-in.
  - The carry-over keeps a valid object verbatim.
- **Project id.** When `AI_BADGER_PROJECT_ID` is set and differs from the id walked up from the
  cwd, the pipeline is refused. No id-to-root lookup is added.
- **Out of scope.**
  - `HTTP_PROXY`, `ALL_PROXY`, system and PAC proxies, and proxy auth.
  - A lock-less `allowHosts`: an unlocked repository still needs the global opt-in.
  - TLS-inspecting proxies need their CA trusted. This is documented as INFERRED, via
    `SSL_CERT_FILE`.
