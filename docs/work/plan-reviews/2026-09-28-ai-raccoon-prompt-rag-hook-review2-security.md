# Plan review round 2 (security/correctness) — aib-ai-raccoon-prompt-rag-hook rev 3

Scope: §0 deltas only — §9 pipeline, proxy transport deltas (T24/T25), landing of O-2..O-7.
Totals: **MUST 3, SHOULD 3, NOTE 5.**

Verified baseline: pi HEAD `161673c0`; `git log ee5f1c6e..HEAD -- extensions/query-pipeline extensions/mem-based-rag` is empty (MEASURED), so goldens pinned at `ee5f1c6e` are current. Cited pi lines READ and match: `pipeline.ts:267` (left<1000), `:286-287` (original reason kept), `:298` (planner cap), `:319-338` (search loop, continue on failure), `:351-379` (Jev failure → null scores → mergeSelect), `:387-391` (budget-exhausted); `mem-based-rag/index.ts:806-821` (switch, prune, [:5]). O-1, O-3, O-6 land correctly (T18/T19, T23, R7/B12).

---

## MUST-1 — Watchdog does not bound the connect phase (and possibly not the TLS handshake)
- **Section:** §9.5 "Deadline"; non-negotiable #3 ("a watchdog holds every call inside its stage share").
- **Evidence:** READ stdlib `socket.create_connection` (py 3.11.15): iterates every `getaddrinfo` result and gives *each* `sock.settimeout(timeout)` + `connect`. MEASURED `getaddrinfo("openrouter.ai",443)` → 4 addresses (2×A, 2×AAAA). The plan hands the socket to the watchdog "right after `connect()`", so a black-holed route (broken IPv6, SYN-dropping firewall, captive portal) costs up to 4 × `remaining()`: planner 15 s share → 60 s; Jev 8 s → 32 s. READ `HTTPSConnection.connect`: `super().connect()` then `wrap_socket` (handshake). If "after connect()" means after the HTTPS override returns, a handshake drip is also outside the watchdog. O4/O5 run on loopback, where connect is instant, so no row can go red for this.
- **Failure scenario:** IPv6-preferring host with dead v6 route: planner call takes 2×15 s before the v4 connect; the 90 s total plus proxy open exceeds Claude's 100 s timeout; on Hermes (no host timeout, O-5) the turn blocks past the budget.
- **Fix:** In the connection subclass override the *plain* `HTTPConnection.connect` (the one HTTPS's `super().connect()` calls): resolve once, then for each address create the socket, **attach it to the watchdog before `sock.connect`**, `settimeout(budget.remaining())` recomputed per attempt, stop when `remaining() <= 0`. The TLS wrap then runs on an attached socket. Add rows: O10 — patched `getaddrinfo` returning 4 entries and a `connect` that blocks until shutdown → `timeout` within share + 0.5 s; O11 — plain-TCP loopback server that accepts and drips bytes, driven through the HTTPS connection class directly → `timeout` within share + 0.5 s. Reword non-negotiable #3 to "except DNS (R-i)".

## MUST-2 — Keyless runs take the pipeline path and 90 s budget, contrary to O-7
- **Section:** §1.3 "Default-on detection", §9.2 `pipeline = …`, §12 bullet 4, row B10.
- **Evidence:** O-7 ruling (binding): "The pipeline is on by default when `OPENROUTER_API_KEY` exists". §9.2 sets `pipeline = env PIPELINE != "0" and all four siblings loaded` — the key is not part of the decision; a keyless run gets `Budget(90)`, a session open share of 15 s, planner `no-model`, then a fallback search share `min(15, left−8)` = 15 s. READ pi: the planner in pi uses the session model registry (`planner-call.ts` `createRegistryPlanner`), and `OPENROUTER_API_KEY` is only the Jev key (`types.ts:113`), so "pi parity" does not justify keying the hook's mode this way.
- **Failure scenario:** a user without an OpenRouter key (the default user) and a hung proxy: worst case ~30 s per gated prompt instead of rev 2's 5 s; B10 pins that behaviour as correct.
- **Fix:** `pipeline = env PIPELINE != "0" and openrouter_client.api_key(env) is not None and siblings loaded`. Rewrite B10: missing key → 0 HTTP, 1 search, run budget `SINGLE_BUDGET_SECONDS` (observed via `hang` returning within 5 s + 1 s), block identical to pipeline-off. Drop §12 bullet 4 or restate it as "missing key → pipeline off", matching O-7.

## MUST-3 — O-5 (CLI only, gateway skipped) lands fail-open
- **Section:** §10 O-5 row ("default CLI-only *if a kwarg exists*"), P3b.0, W7 ("policy per P3b.0 and O-5").
- **Evidence:** READ plan lines 1265, 531, 872 vs ruling line 1359 ("Hermes: CLI sessions only; gateway-originated sessions are skipped"). The plan never says what happens when P3b.0 finds no platform/gateway kwarg; the implied default is to run. With rev 3 that run sends the prompt and up to 48 memory/code excerpts to OpenRouter on the user's key, triggered by remote chat users.
- **Fix:** Make it fail closed: `build()` is called only on a positive CLI signal that P3b.0 identifies (cite the Hermes source line); no signal → the Hermes arm is inert and P3b returns to the owner before shipping. W7 as a table: gateway platform → 0 spawns, 0 HTTP; kwarg absent/unknown → 0 spawns, 0 HTTP; CLI → 1 spawn. Mutation: default to "run" when the kwarg is missing. Update the §10 O-5 row to the ruling text.

---

## SHOULD-1 — `parse_plan` CPU sits outside every budget; adversarial model output costs ~5–10 s
- **Section:** §9.3 Parser; §1 non-negotiable #2 ("one wall-clock Budget bounds the whole run").
- **Evidence:** MEASURED (port of pi's `collectObjectSpans` + last→first `json.loads(text[s:e+1])`): 1 MB of nested `{…}` → 5.52 s; 1.2 MB of `{"a":`-nested → 9.41 s (199 005 `RecursionError`s). The 1 MiB body cap allows this; the planner sends no `max_tokens`, and the prompt (user-pasted, untrusted) is the planner input, so prompt injection can steer output length/shape. The parse runs after `post_json` returns, and nothing checks the budget.
- **Fix:** Cap the extracted planner text (e.g. 64 KiB — a maximal valid plan is < 3 KB) → `invalid-shape`/`no-json-object` above it, recorded as an accepted divergence; use `json.JSONDecoder().raw_decode(text, start)` (no slice copy) and require `end == span_end+1`; catch `RecursionError` explicitly. Add a PL3 corpus row: 1 MiB nested braces returns in < 0.5 s.

## SHOULD-2 — Resolver fallback probe is layout-blind
- **Section:** §9.7 "Mechanics of C", W10.
- **Evidence:** READ `ai_badger_hooks._load_sibling_module` (`:77`, `Path(__file__).resolve().parent`), so Hermes loads from the plugin dir today. But candidate 2, `Path(__file__).parents[1].parent/"task"/"scripts"/"model_groups.py"`, resolves to `~/.hermes/task/scripts/model_groups.py` from the plugin dir. From the project copy `<project>/.ai-badger/hooks/memory_context.py`, which the Hermes adjuster also writes (READ `adjust_hooks.py` `adjust()` SHARED_SKILL_MODULES loop, §1.6(3)), it resolves to `<project>/task/scripts/model_groups.py`, a repo-controlled path. Any future loader of that project copy (or a missing plugin-dir `model_groups.py`) executes repo code in the gateway. INFERRED: not reachable today.
- **Fix:** Try candidate 2 only when `Path(__file__).resolve().parent.name == "scripts"` and `parents[1].name == "ai-raccoon-memory"`; resolve both candidates. W10 adds: plugin-dir `model_groups.py` deleted, and a planted `~/.hermes/task/scripts/model_groups.py` and `<project>/task/scripts/model_groups.py` that write a marker on import → planner `no-model`, no marker.

## SHOULD-3 — O-2 promise "byte-identical to pi for every hit without such characters" is broken for rank strings and path spacing
- **Section:** §1.5 accepted divergences; C19, C21.
- **Evidence:** READ pi `rag-core.ts:176-177` (path is `trim()` only) and `:260-272` (`hit.ranking ?? "?"` interpolated raw). The plan renders a non-numeric rank as `?` (C21 `"x"`→`?`) and runs the path through `one_line`, which collapses every whitespace run. A rank `"high"` or a path `docs/My  Notes.md` has none of the O-2 characters, yet the output differs from pi's.
- **Fix:** Add `sanitize_field(s)` that replaces only the ruling's set (`\r \n \t \v \f`, U+0085, U+2028, U+2029) and leaves everything else raw. Path = `sanitize_field(trimmed path)`; rank = `js_number` for numbers, `sanitize_field(str)` for strings, `?` for null/absent. C21: `"x"` → `x`; add path `"a  b"` preserved; add bun goldens for both.

---

## NOTE-1 — Watchdog thread and FD hygiene (§9.5)
`socket.shutdown` on an already-closed or reset socket raises `OSError` inside the `Timer` thread, and `threading.excepthook` then prints a traceback to stderr (and into the Hermes log). Wrap the callback in `except OSError`. Also close the response and any `HTTPError` (it holds the fp) in `finally`, so the long-lived Hermes process never waits on GC for FDs. INFERRED.

## NOTE-2 — Key header hardening (§9.5, O9)
READ `http.client.putheader`: `raise ValueError('Invalid header value %r' % (values[i],))`. An env key with an embedded CR/LF puts the full `Bearer <key>` into the exception text. §9.5 catches it (→ `transport`), so nothing leaks today, but O9 should add an embedded-`\n` key case, and `api_key` should reject keys that are not printable-ASCII with no whitespace (→ `None`). Use `add_unredirected_header` for `Authorization` as a second guard next to `NoRedirect`. Say explicitly that `DeadlineHTTPSHandler`/`DeadlineHTTPHandler` subclass `HTTPSHandler`/`HTTPHandler`: otherwise `build_opener` adds the default handler, which bypasses the watchdog.

## NOTE-3 — O-7 disclosure is narrower than the egress (§1.3, ADR-0032)
J2 sends each candidate's `path` and `kind`, and the pool includes code hits. SKILL.md and the changelog should say "the prompt, file paths, and memory *and source-code* excerpts (≤48 × 500 chars)", not only "matched excerpts".

## NOTE-4 — Close R-j instead of documenting it (§9.6)
Accept `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE` only when the key also carries a test sentinel prefix (H12 already uses `sk-test-`). A user's real key can then never reach a loopback listener. Add a row to O8.

## NOTE-5 — Injection surface of planner and Jev output (§9.2–9.4)
Planner output only chooses query text; `projectId`, `scope:"project"` and `limit` are fixed by the hook (T3), so it cannot widen retrieval. Jev output is clamped numbers that only reorder already-retrieved hits. A malicious memory snippet can still steer its own Jev score (bounded to ranking). Add a B9 assertion that no `query`/`concept` annotation and no planner text appears in the block.
