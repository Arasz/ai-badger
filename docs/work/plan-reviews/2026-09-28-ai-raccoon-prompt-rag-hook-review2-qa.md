# QA plan review, round 2: rev-3 test design (aib-ai-raccoon-prompt-rag-hook)

This review covers §6 rows G, O1–O9, PL1–PL7, J1–J9, MG1–MG2, R1–R8, B9–B14, the rev-3 rows H12,
W10, T24 and T25, the fake OpenRouter server, the fake ai-raccoon proxy modes, the bun goldens (Q0.2)
and the §6.1 map of pi's 115 tests. The owner rulings on rev 3 are treated as binding.

Out of scope: rows P1 (V*), P2 core (C*) and P3/P4 (except where a pipeline row depends on them),
production design, and security beyond what a test can observe.

Probes are in `scratchpad/probe/` (p1–p5). Each one was run with `.venv/bin/python3` (CPython 3.11.15, macOS).

**Result: 5 MUST, 8 SHOULD, 4 NOTE.**

| id | row(s) | severity | evidence | finding |
|---|---|---|---|---|
| F1 | G1, G4, O8, G2, every in-process pipeline row | MUST | MEASURED (p2) | The in-process guards raise an ordinary exception inside code that catches every exception. Nothing fails. |
| F2 | O2 (also J4, PL6 307 cases) | MUST | MEASURED (p5) | A POST answered with 307 is never followed, even by the default redirect handler, so O2's mutation stays green. |
| F3 | T12, T13, T14, O4, O5, H8, W9, B14 | MUST | MEASURED (no timeout plugin); INFERRED (hang) | No per-test watchdog exists. A mutant that removes a deadline hangs the suite instead of going red. |
| F4 | O4, B14, W10, W9 | MUST | MEASURED (p1) | `threading.active_count()` counts the fake server's own handler threads. B14 goes red on correct code. |
| F5 | O4 (the HTTPS path) | MUST | MEASURED (p3, p3b) | Every drip row runs over plain HTTP, and production is HTTPS only. One plausible HTTPS watchdog does nothing, and every row stays green. |
| F6 | T25 | SHOULD | READ + INFERRED | Under `nostdin` and `crash`, "fake line count unchanged" cannot observe a write. Only the flaky 0.05 s bound can go red. |
| F7 | J5 | SHOULD | READ | `elapsed < 0.5 s` is a wall-clock assertion standing in for "never sleeps". |
| F8 | J6 | SHOULD | READ | The row puts a fake-clock budget on a real socket, so the `hang` attempt waits up to 15 s of real time. |
| F9 | B11, W9 | SHOULD | READ | B11 spends 5 s of real time. W9 has no stated budget, so it waits 15 s or more on the pipeline path. |
| F10 | T24 / G3 `latereply` | SHOULD | READ | "Holds reply 1" is not tied to an event. If the fake uses a sleep, the order of the two replies is up to the scheduler. |
| F11 | O5 | SHOULD | INFERRED | O5's mutation (`timeout=None`) stays green because the watchdog also bounds a hang. |
| F12 | PL4–PL6, J2–J7 | SHOULD | READ | The planner and Jev tests use the real fake server even though `post` is injectable. That costs real time and threads without adding a failure mode beyond Q1. |
| F13 | G2 | SHOULD | READ | The key and proxy half of G2 cannot go red today. It becomes real once F1 is fixed. |
| F14 | §6.1 map | NOTE | MEASURED (pi test counts) | The per-file counts match. The cross-references are wrong in two places. |
| F15 | Q0.2 goldens | NOTE | READ | Nothing mechanical proves an output came from bun. |
| F16 | C11, T6, T11, I12, W5, R4 | NOTE | READ | These are cuts that lose no failure mode (see "Proportion"). |
| F17 | network guard | NOTE | INFERRED | DNS is never reached, as long as the guard wraps `socket.create_connection` before resolution. |

---

## MUST

### F1 — A guard that raises into a catch-all cannot fail a test

**Rows:** the shared network guard (§6, "Network guard"), the real-executable guard, G1, G4, and O8's
mutation "fall back to production on refusal". Every in-process pipeline row relies on these guards.

**What happens.** §9.5 maps "any other exception → `transport`" in `post_json`, and T20 maps any
spawn exception to `None`. The planned guards raise an ordinary exception at connect or `Popen`
time. Production code catches that exception and turns it into an expected fallback, so the test
stays green.

- **O8 cannot go red for "fall back to production on refusal".** The mutant posts to
  `https://openrouter.ai`. The guard raises, `post_json` returns `transport`, and the planner
  reports `transport`, which is exactly what O8 expects. The fake and the capture server both record
  0 requests. The row is green.
- **The same applies to every row that could reach the network.** Only the subprocess guard writes a
  marker (H12, I6, I12). The in-process guard writes none.

**Evidence (MEASURED, p2).** A guard raising `Exception` inside a stand-in that catches everything
returned `transport` and was recorded once. A guard raising a `BaseException` subclass escaped.

**Fix.**
1. Both guards append every refusal to a per-test list.
2. An autouse teardown asserts that list is empty. That is the failure path, and it cannot be caught
   by production code.
3. The guards also raise a `BaseException` subclass so the call stops at once. `pytest.fail` is itself
   a `BaseException`: `Failed → OutcomeException → BaseException`, MEASURED.
4. G1 and G4 each get a companion row. The row calls a stand-in that wraps the call in
   `except Exception`, and its teardown must report red. That proves the teardown, not only the raise.
5. S1 (static) should also forbid `except BaseException` in the six modules, so the guard's
   `BaseException` cannot be swallowed either.

Once this is in place, I12 is subsumed (see Proportion).

### F2 — O2's 307 cannot go red under its own mutation

**Row:** O2, "fake answers 307 … mutation: default `HTTPRedirectHandler`".

**Evidence (MEASURED, p5).** With `ProxyHandler({})` and the *default* redirect handler, which is the
mutant, a POST answered with:

- **307 or 308:** `HTTPError`. The capture server saw nothing.
- **301, 302 or 303:** followed as a `GET`. The capture server saw `Authorization: Bearer sk-test`.

CPython's handler refuses to follow a POST on 307/308, so O2 is green with or without `NoRedirect`.
The key-forwarding defect the row exists for shows only on 301/302/303.

**Fix.**
- Parametrize O2 over `301, 302, 303, 307, 308`. Each case asserts `Reply.status == code` and that the
  capture server recorded 0 requests.
- The 302 case is the one that goes red under the named mutation.
- Apply the same change to the 3xx rows in J4 (`→ server`) and PL6 (`→ transport`).

### F3 — Mutants that remove a deadline hang instead of going red

**Rows:** T12 (`hang` never replies), T13, T14 (`nostdin` never reads), O4, O5, H8, W9 and B14.
§6 says "Timing rows assert upper bounds under a watchdog", but no watchdog is defined.

**Evidence (MEASURED).** The venv has no `pytest-timeout` and no `faulthandler` timer. A grep of
`tests/conftest.py` and the pytest config for `faulthandler` or a timeout found nothing relevant.

**What happens.** Under the named mutations ("drop the deadline", "blocking `readline()`", "blocking
`stdin.write`", "`timeout=None`", "remove the watchdog"), the call blocks for as long as the fake keeps
blocking. G3 defines `hang` as "never replies". The suite then stalls. It does not go red, and on
pre-push that ends as the known SIGKILL with no output.

**Fix.** Give every blocking fake behaviour a finite ceiling, and state it in G3 and in the fake
OpenRouter spec. For example:
- `hang` exits, or closes the connection, after 20 s.
- `drip` and `body-drip` stop after 20 s.
- `nostdin` exits after 20 s.

Keep each row's bound far below that ceiling (for example, a 3 s bound against a 20 s ceiling). A
mutant then returns late and fails the bound assertion, and correct code has a 6× margin under load.
Add one G3 case asserting that each blocking mode does end by its ceiling.

### F4 — The thread-count assertion counts the fake server's threads

**Rows:** O4 ("`threading.active_count()` back to baseline"), B14, W10 and W9 ("thread count unchanged").

**Evidence (MEASURED, p1).**
- **Handler that hangs:** after a 0.3 s client deadline, the count went from baseline 2 to 3. It was
  still 3 half a second later, because the handler lives as long as its sleep.
- **`body-drip`:** the count went from 3 to 4 at return and back to 3 half a second later.

**What happens.**
- **B14:** "Jev `hang` … thread count back to baseline" fails on correct code for as long as the fake's
  hang lasts.
- **O4 and W10 (`body-drip`):** the result depends on a race.

The baseline "taken after the servers start" does not help. The fake server starts its handler
threads per request, after the baseline is taken.

**Fix.**
- Name the watchdog thread (for example, `ai-badger-openrouter-watchdog`).
- Assert that no live thread carries that name, plus no live `threading.Timer`. Do not assert a global
  count.
- For the proxy side (T17, W9), pass or fail on reaped pids. Those rows start no in-process server,
  so their count is clean.
- Alternative: run the fake OpenRouter in a subprocess. That costs more, and naming the thread is enough.

### F5 — The production (HTTPS) watchdog path is never exercised

**Rows:** O4 and every other drip or hang row. The fakes are plain HTTP on `127.0.0.1`, and O8
correctly refuses an `https` test base.

**What the gap is.** Only `DeadlineHTTPHandler` is ever driven. `DeadlineHTTPSHandler`, the only
handler production uses, is not. §9.5 says the connection subclass "hands its socket to the watchdog
right after `connect()`". For HTTPS there are two sockets.

**Evidence (MEASURED, p3 and p3b).**
- **The pre-wrap raw socket is held:** `wrap_socket` detaches it. The timer's
  `socket.socket.shutdown(raw)` raised `OSError: [Errno 9] Bad file descriptor` inside the Timer
  thread, printed only to stderr. The TLS read ran to its 5 s socket deadline. The watchdog was
  0.5 s, and the drip would have run for 20 s.
- **A `dup()` of the socket is held:** the read ended at 0.51 s with `SSLEOFError`.

So one plausible implementation leaves HTTPS unbounded while every O-row stays green.

**Fix.** Add O4b, a TLS drip:
1. Start a TLS fake on `127.0.0.1` with a throwaway self-signed certificate. Give it an IP SAN of
   `127.0.0.1` and generate it per session with
   `openssl req -x509 -newkey ec … -addext subjectAltName=IP:127.0.0.1`. If `openssl` is missing, skip
   with the reason stated.
2. Trust it through `SSL_CERT_FILE`. `ssl.create_default_context()` honours that variable, so O3's
   "default context" pin stays intact. The environment-variable route is INFERRED; confirm it when the
   row is written.
3. Call `post_json` directly with the `https://127.0.0.1:<port>` URL. Unit tests pass the URL as a
   parameter, so the base-URL refusal does not apply.
4. Have the fake send the headers and then drip the body at 1 byte every 0.05 s, with a 0.3 s share.
   Assert the call returns `timeout`, well inside the bound.
5. Mutation: attach the pre-wrap socket. The row must go red.

A handshake-only drip does not work without a certificate. CPython applies the socket timeout as a
deadline for the whole handshake, so the watchdog's effect cannot be told apart (MEASURED, p3: the
handshake timed out at exactly the socket timeout).

---

## SHOULD

**F6 — T25 can only go red on its timing bound.** In `nostdin` the fake never reads stdin, and in
`crash` it is dead. In both modes "fake line count unchanged" is true even under the mutant "keep
writing after a partial write". Only `< 0.05 s` can go red, and that is the tightest bound in the plan.

Fix: wrap the session's write path (`os.write`, or the session's `_write`) with a spy and assert 0
write calls after poisoning. Add an assertion that `select` is not entered. Drop the timing bound, or
widen it to about 1 s.

**F7 — J5 asserts `elapsed < 0.5 s` to prove there is no Retry-After sleep.**
- Make the fake send `Retry-After: 30`.
- Monkeypatch `time.sleep` in `jev_scoring` (and `time.sleep` globally for this test) to record calls.
  Assert 0 calls.
- Drop the elapsed-time bound.

**F8 — J6 mixes a fake clock with a real socket.** "Attempt 1 `hang`" goes through the fake server,
but the attempt share `min(15, deadline − now)` comes from a fake clock that real time does not move.
The real `post_json` then arms a 15 s Timer and a 15 s socket timeout.

Fix: split the row.
- **J6a (fake clock):** an injected `post` records `budget.remaining()` for each attempt. It also
  covers "remaining ≤ 0 → 0 calls" and the missing key.
- **J6b (real clock):** a scaled real budget of about 0.5 s. `hang` then `ok`, and assert that the
  first socket is closed. With F3's ceiling in place, the mutant fails late rather than hanging.

**F9 — Real waits B11 and W9.**
- **B11:** observing `SINGLE_BUDGET_SECONDS` through a real 5 s `hang` costs 5 s or more per run.
  Instead, monkeypatch `SINGLE_BUDGET_SECONDS=0.3` and `PIPELINE_TOTAL_SECONDS=30`, then assert the
  return within 2 s. The mutant then waits the 15 s open share and goes red. Or spy on the `Budget`
  constructor's argument.
- **W9:** "within budget + 1 s" names no budget. With the pipeline on and no key, the session open
  (`child(15)`) and the fallback search each take 15 s against `hang`. State the patch, for example
  `PIPELINE_TOTAL_SECONDS=0.5` through a module-constant patch, and the bound.

**F10 — The `latereply` mode needs an event-driven specification.** For T24, the fake must hold
reply 1 until it has *read* request 2, then write reply 1 and reply 2 in that order. Driving the
ordering with a sleep makes the result depend on the scheduler. The two searches must also return
different hits. Otherwise the mutant "accept the first reply" is indistinguishable.

**F11 — O5 is vacuous under its mutation.** The watchdog bounds the whole exchange, so `timeout=None`
still returns `timeout` in bound. Fold `hang` into O4's table as a third mode, and drop the
`timeout=None` claim or state it as "watchdog removed". F3 still applies.

**F12 — Route PL and J through an injected `post`.** Real sockets add threads (F4), real time (F8)
and a larger flake surface. Beyond Q1 they add no failure mode, because `plan()` and `score()` take
`post`. Two exceptions:
- Keep one row per module through the fake server as the wiring proof: PL4 and J2.
- Keep J9's leak row on real `Reply` objects.

Drive PL5, PL6 and J4–J8 with a scripted `post` that returns `Reply` or timeout values.

**F13 — G2's "0 HTTP requests" is vacuous today.** With the scrub removed, and `OPENROUTER_API_KEY=k`
and `https_proxy` exported, the request goes to production. The guard then swallows the attempt (F1)
and the fake counts 0 either way. G2 currently goes red only through `AI_BADGER_MEMORY_CONTEXT=0`.
After F1, add "the guard recorded 0 refusals" to G2's assertions. That half then has a real red.

---

## NOTE

**F14 — §6.1 map errata.** MEASURED: the per-file test counts in pi's files are 9, 24, 5, 18, 13, 20
and 26, which matches the plan.

- **The merge row** says M15–M19 are not ported, "dedupe is `prune_hits` itself (… C21)". C21 is the
  rank-format table; the dedupe rows are C15, C16 and C20. R8 then claims pi M15 (droppables) and
  M18 (mem/code independent) as ported.
- **The parity row** repeats "C21".

Fix: move M15 and M18 to "ported → R8", list only M16, M17 and M19 as covered by C15/C16/C20, and
correct the reference.

**F15 — Nothing proves a golden came from bun.** Q0.2's gate runs by hand, and nothing stops a Python
script from writing `pipeline_goldens.json`. Add a CI-run row asserting:
- the file's `generator` equals `gen_pipeline_goldens.ts` and `bun` is non-empty;
- `pi_commit` equals the plan's SHA;
- every key in `pipeline_golden_inputs.json` has an output.

Also forbid any `tests/**/*.py` that writes `pipeline_goldens.json` (a grep row). This cannot prove
provenance, but it removes the easy path to Python-generated goldens.

**F16 — Cuts** are listed under Proportion below.

**F17 — Network egress.** DNS is not reached as long as the in-process guard wraps
`socket.create_connection` and refuses on the host string before resolution. `http.client` looks up
`socket.create_connection` at instance init, so patching the module attribute works. Nothing in the
design reads the real HOME: the real-executable guard reads the pwd home read-only, at import. There
is no real key, because the scrub removes it (G2).

Remaining exposure: before F1, a violation is silent rather than blocked. Egress itself is blocked,
because the guard's raise prevents the connect even when the exception is swallowed. What is lost is
the red.

---

## Proportion (157 rows)

Most of the 46 new rows each carry a distinct failure mode. These cuts lose none:

| cut | why no failure mode is lost |
|---|---|
| **O5** | Fold it into O4's table as the `hang` mode (F11); its own mutation cannot go red. |
| **C11** | C10's bun golden of the whole block already fails on any trust-header edit, including softened or hardened wording. |
| **T6** | Merge it into the T10 payload table. "Empty lists → empty" is one more parametrized case. |
| **T11** | "`crash` → `None`" is T16's parametrized case, and the reaping is T17's `crash` runs. |
| **I12** | With F1's autouse teardown on both guards, every test in every module already asserts it. |
| **W5** | The gate lives inside `build()`, which the Hermes arm calls, so W5's mutation "bypass gate" is B5's. Keep W6, because the decline check is Hermes-only. |
| **R4** | Merge it with PL7 into one vocabulary row: `PLANNER_REASONS ∪ RUN_REASONS` equals the golden list minus `aborted`. R3's goldens already pin the reason each scenario returns. |

Net: 150 rows. F2 turns O2 into a parametrized table without adding a row, and F5 adds O4b, so the
total is 151. I would not cut further. The remaining pipeline rows (MG1/MG2, R1–R3 and R5–R8, J1–J9,
PL1–PL6, B9–B14) each pin a distinct pi behaviour or a budget share.

## Answers to the four questions

1. **Can each row go red for the failure it names?** No for O2 (F2), O5 (F11), the O8 fallback-to-
   production mutation (F1), G2's key half (F13), and T25's line-count clause (F6). Every
   deadline-removal mutant stalls the suite rather than going red (F3). The HTTPS watchdog has no row
   at all (F5). The rest are credible: O1 (MEASURED red under `ProxyHandler()`, p4), PL, J and R.
2. **Are the budget and watchdog tests deterministic?** R5 and J6's share arithmetic use a fake clock
   and are sound. Not deterministic or proportionate: the thread-count assertions (F4, MEASURED), the
   0.05 s and 0.5 s bounds in T25 and J5 (F6, F7), the fake clock on a real socket in J6 (F8), the
   real 5–15 s waits in B11 and W9 (F9), and `latereply` ordering (F10).
3. **Do any tests touch the real network, a real key, the real ai-raccoon or the real HOME?** Not by
   design: the scrub, temp HOME and PATH, and the guards are all in place. But a violation would be
   silent in-process (F1), so "no test reaches it" is currently unprovable.
4. **Are 157 rows proportionate?** Mostly. Seven cuts lose no failure mode, and two additions (O4b and
   the widened O2) close real gaps.
