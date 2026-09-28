# Plan review: testability lens (QA)

Target: `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-plan.md` in the task worktree (read in full, including the binding orchestrator rulings).
Question for every row: can it go red for the failure it names? Nothing was implemented, so no mutation could be applied to production code. Where a claim could be settled, I settled it with a probe script in the scratchpad (MEASURED). Everything else is READ against source or INFERRED.

Out of scope: production security, layering and performance (code-reviewer's lens), the design itself, and the Copilot capability question (P0 decides that).

**Count: 5 MUST, 11 SHOULD, 8 NOTE.**

| id | plan section | severity | the gap | grade |
|---|---|---|---|---|
| M1 | §1 transport, P3 T26 | MUST | The deadline tests only drip the body. The "chunked reads + deadline check" option passes T26 but hangs when the headers drip. | MEASURED |
| M2 | Rulings Q1 vs C7/P4.3/H13/I2/I7 | MUST | The port-override ruling has no test rows. Five rows still describe the rejected sitecustomize shim. The I7 guard cannot catch the new way a test would leak to the live serve. | MEASURED (7721 is listening) + READ |
| M3 | P6 I1 + P6 acceptance | MUST | "No pi surface names memory_context" fails on correct code in the composed claude+copilot+hermes+pi scaffold. | READ |
| M4 | P5 W8, P6 I6 | MUST | The Hermes sibling loader caches in `sys.modules`. I6 ("installed inert") can pass on the source-tree module, and W8 depends on test order. | READ |
| M5 | P2 C22/C35/C36 | MUST | The "golden" oracle is TypeScript code, not a string. C35 leaves real parity divergences untested (ranking 0 or null, JS exponent formatting, lineStart 0). | MEASURED + READ |
| S1 | P1 V15 | SHOULD | The mutation "key the dedupe on literal command" is not real. The discovery and explicit commands are byte-identical. | READ |
| S2 | P3 T28 | SHOULD | The mutation is real only when `no_proxy`/`NO_PROXY` are cleared. The row does not say to clear them. | MEASURED |
| S3 | all new test modules | SHOULD | No env scrub for `AI_BADGER_PROJECT_ID`, `AI_BADGER_MEMORY_CONTEXT`, `AI_BADGER_MEMORY_CONTEXT_PORT` or the proxy vars. conftest scrubs none of them. | READ |
| S4 | P5 W14 (and S1 wording) | SHOULD | Patching spawn to raise, then checking the block is present, cannot see "tried to spawn, caught it, fell back to HTTP". | INFERRED |
| S5 | P4 | SHOULD | Nothing tests that the hook *process* exits within its bound. A worker-thread deadline can return from `search()` while interpreter shutdown still waits. | INFERRED |
| S6 | P3 T6 | SHOULD | As written, the "hoist `Path.home()`" mutation survives on CI, where there is no real token. The row must check the positive direction. | READ (conftest) + INFERRED |
| S7 | P0, P6 I3 | SHOULD | The spike has no positive control for the model's answer. The branch A I3 row has no captured Copilot payload to use as its fixture. | INFERRED |
| S8 | P3 T23 | SHOULD | The wall-clock `< 0.5 s` assertion is the flaky way to catch "retry loop". Count connect attempts instead. | INFERRED |
| S9 | P6 I2 | SHOULD | The `guarded()` fallback to `elif [ -f relative ]` can hide a broken path rewrite. | READ |
| S10 | P3/P4/P6 fixtures | SHOULD | A token written into the session-scoped HOME leaks to every later test. | READ |
| S11 | P4 S3, H6 in subprocess form | SHOULD | "Serve down = dead port" cannot prove the child was routed at all. A mis-set port env sends the child to the live serve, where it gets a 401, stays silent and passes. | INFERRED |
| N1 | §1.3 / F2 | NOTE | For `memory-context` the Hermes F2 rule is vacuous, because `pre_llm_call` is already registered. W7/I6 are the real guards. | READ |
| N2 | §1.2 / I4 | NOTE | The pi exclusion holds, but its proof is static. §1.2(3) "the sibling is absent there" is false in a hermes+pi scaffold. | READ |
| N3 | §1.3, C3, V1 | NOTE | The plan's F2 data claims hold on real data: 12 Hermes arms, and prompt-markers claude+copilot are the only gaps. | MEASURED |
| N4 | P4 S1–S3 | NOTE | The no-spawn proofs are genuine as a set, not singly. | READ |
| N5 | P2 C30/C32 | NOTE | JS `length` counts UTF-16 units, Python counts code points. `\s` differs on U+FEFF. | INFERRED |
| N6 | P4 H15 | NOTE | Change detector. It adds nothing that W2a does not already give. | READ |
| N7 | P5 M1–M5 | NOTE | The memo is module-level state. Every M row needs a reset fixture. | INFERRED |
| N8 | P3 B4 | NOTE | "Before any file read" names no observable. | READ |

---

## MUST

### M1: T26 cannot tell a whole-call deadline from a body-only one

§1 lets the implementer choose "chunked reads with a deadline check, or a worker thread joined on the deadline". The claim to prove is "one wall-clock deadline over connect+headers+body". T26 drips only the body ("headers then 1 byte / 0.1 s").

**Evidence (MEASURED).** `scratchpad/drip_probe.py` implements the chunked-read option: a no-proxy opener, per-op `timeout=BUDGET`, and a deadline check between `read1(64)` calls. Result:

```
body returned after 0.33 s
headers STILL RUNNING after 5.0 s
```

`http.client` reads the status line and headers through `readline` under the per-op timeout, so a peer that drips headers holds the call for (header bytes × interval). The option passes T26 and still blocks the prompt up to the host timeout.

**Fix.**
- Add fake mode `drip-headers`: status line, then one header byte every 0.05 s. Add a row T26b (`budget=0.3` → returns within the watchdog bound).
- Make its mutation "deadline checked only in the body loop".
- Or drop the chunked option from §1 and mandate the worker thread. S5 then applies.

### M2: the port-override ruling (Q1) has no rows, and the live-serve guard is aimed at the wrong leak

The binding ruling replaces the sitecustomize shim with `AI_BADGER_MEMORY_CONTEXT_PORT` (integer 1–65535; garbage falls back to 7721; host hard-coded). The plan body still says otherwise in five places:
- C7 and P4.3: the shim file.
- H13: `PYTHONPATH=<sitecustomize shim>`.
- I2: "sitecustomize shim".
- I7: "7721 appears only in T24 and the sitecustomize shim's redirect table".

No row covers any part of the new variable. The live serve is up on this machine: `lsof -iTCP:7721` shows `AiRaccoon 27353 … 127.0.0.1:7721 (LISTEN)` (MEASURED).

The obvious "garbage port falls back to 7721" test, written against the real transport, therefore connects to the live bank. It sends the tmp token, gets a 401, returns `None`, and passes. The I7 guard is a text grep for the literal `7721`, and a test that sets the env to `"abc"` never spells 7721. So I7 cannot go red on the leak route this ruling creates. The brief's criterion "tests never touch live serve" has no test that can fail.

**Fix.**
- Replace every shim reference with the env var.
- Add rows:
  - P1 valid port → the request reaches `127.0.0.1:<port>` (fake count 1).
  - P2 `""`, `"abc"`, `"0"`, `"65536"`, `"-1"`, `" 8080 "` → resolved port per the ruling. Test this through a pure `_port(env)` or the injected opener, never a socket.
  - P3 any value containing a host (`"evil:80"`, `"1234@evil"`) → the host is still `127.0.0.1`.
- Replace I7's grep with an autouse fixture in the new test modules. It wraps `socket.socket.connect`/`socket.create_connection` and fails the test on `("127.0.0.1", 7721)` or `("localhost", 7721)`. That fixture can go red; the grep cannot.
- Every subprocess test sets the port env explicitly (see S11).

### M3: I1 and the P6 acceptance line fail on correct code

I1 and the P6 acceptance line say nothing under "pi-owned `.ai-badger/hooks/` copies … names `memory_context`". In a `claude, copilot, hermes, pi` scaffold that directory is shared:
- Hermes copies every `SHARED_SKILL_MODULES` file to `target_dir / "hooks" / filename` (`features/hermes/adjustments/adjust_hooks.py:214-217`, READ).
- W6 *requires* `memory_context.py` there.
- pi copies `ai_badger_hooks.py` into the same dir (`features/pi/adjustments/adjust_hooks.py:83-91`, READ). After P5 that file contains `_load_memory_context`.

So on the correct implementation the assertion fails, and the implementer will weaken it ad hoc.

**Fix.** Scope the pi assertion to what pi executes:
- `.pi/**` and the tmp-HOME pi extension dir contain no `memory_context`.
- `index.ts` spawns only `DELIVERY_SCRIPT` on `before_agent_start` (I4b).
- Add a pi-only scaffold (`agents: [pi]`) where `.ai-badger/hooks/memory_context.py` must be **absent**.
- Also correct §1.2(3): the sibling *is* present when Hermes is configured. Exclusion rests on pi never calling `pre_llm_inject_context`.

### M4: the Hermes sibling cache defeats I6 and makes W8 depend on order

`_load_sibling_module` returns `sys.modules.get(module_name)` before looking at the file (`ai_badger_hooks.py:72-74`, READ). It keeps `_missing_siblings` and `_broken_siblings` per process.

If W7 (source tree) runs before I6 in the same process, the installed plugin's `_load_memory_context()` returns the cached *source-tree* module. I6 then passes even when the sibling was never copied, which is exactly the "installed inert" failure it exists to catch. W8 ("sibling missing → logged once") depends on test order the same way. A reset pattern already exists: `tests/test_sibling_module_loading.py:34-55` and `test_memory_first_gate_hermes.py:28`.

**Fix.**
- Add a fixture that pops the memory-context module key and clears `_missing_siblings`/`_broken_siblings` around every P5/P6 Hermes test.
- I6 additionally asserts that `sys.modules[key].__file__` resolves under the tmp-HOME plugin dir.
- Mutation to prove it: drop the `SHARED_SKILL_MODULES` row, then run I6 *after* W7 in one process. It must go red.

### M5: the "golden" is code, and C35 leaves real parity divergences untested

C22 says the golden block is the "whole string from `rag-core.ts:412-435`". Those lines are the body of `toMemoryContext`, not a string (READ). So the expected value is a person's reading of the same TypeScript the port is transcribed from, and a misreading lands in both (T0-04).

Default-mode rank rendering is `const rank = hit.ranking ?? "?"`, then `` `(rank ${rank})` `` (`rag-core.ts:260,266`, READ). There is no rounding; the `Math.round(n*1e4)/1e4` is the TUI card path, not this one. The C35 inputs (1.0, 0.8123, missing) miss the actual divergences:

| Input | JS | Python naive | Row that would kill it |
|---|---|---|---|
| `ranking: 0` | `(rank 0)` | `or "?"` → `(rank ?)` | none |
| `ranking: null` | `(rank ?)` | `.get(k,"?")` → `(rank None)` | none |
| `5e-05` | `0.00005` | `5e-05` | none (MEASURED: `node`/`python3` side by side) |
| `1e-7` | `1e-7` | `1e-07` | none (MEASURED) |
| `lineStart: 0, lineEnd: 5` | `:0-5` | truthiness drops it | none |
| `lineEnd: null` | `:10-null` (`!== undefined`) | `is not None` drops it | none |

**Fix.**
- Generate the goldens by *running* pi: `bun` is at `/opt/homebrew/bin/bun`, MEASURED. Use a small script under `tests/fixtures/` that imports `rag-core.ts` and prints `toMemoryContext` for a committed input JSON. Commit the output together with the pi commit SHA, so the oracle does not come from the port's author.
- Add the six inputs above to C36's intersection fixture.
- Add C35 mutations `or "?"` and `str(x)` for float.
- Decide explicitly whether `lineEnd: null` → `:10-null` is ported or is an accepted divergence.

## SHOULD

**S1 (P1 V15): the mutation cannot go red.**
- Discovery wiring produces `guarded('python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py"')` (`hook_wiring.py:296`, `PROJECT_DIR_VAR = "${CLAUDE_PROJECT_DIR}"` at `:17`).
- The explicit path rewrites `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` to the same string and guards it. The current `.claude/settings.json:64` shows that exact form (READ).
- A literal-command dedupe therefore also leaves one entry. `_prune` additionally drops superseded entries by `script_id` regardless of `_hook_key`.
- **Fix.** Seed a *literally different* pre-existing entry for the same script, e.g. an absolute path from another checkout or the unguarded form. Assert one entry survives. Apply the mutation to `_hook_key` **and** to `_prune`'s superseded set separately.

**S2 (T28): works only with `no_proxy` cleared.**
- With `no_proxy`/`NO_PROXY` cleared, default `urlopen` sends a `127.0.0.1` request to `http_proxy`, and `ProxyHandler({})` goes direct. `scratchpad/proxy_probe.py`: `default urlopen: {'real': 0, 'proxy': 1}`, `no-proxy opener: {'real': 1, …}` (MEASURED, 3.11.15).
- A CI or dev env with `NO_PROXY=127.0.0.1,localhost` makes the default-`urlopen` mutation survive.
- **Fix.** T28 must `monkeypatch.delenv` both spellings and set both `http_proxy` spellings.

**S3: scrub the environment.**
- conftest scrubs only `HERMES_HOME` (`tests/conftest.py:188`, READ).
- An exported `AI_BADGER_PROJECT_ID` makes T3/T4/T5/H10 red on one machine. It is loud, but machine-dependent.
- An exported `AI_BADGER_MEMORY_CONTEXT=0` reddens every happy row.
- **Fix.** Add an autouse fixture in the new modules that deletes `AI_BADGER_PROJECT_ID`, `AI_BADGER_MEMORY_CONTEXT`, `AI_BADGER_MEMORY_CONTEXT_PORT`, `http(s)_proxy`, `HTTP(S)_PROXY`, `no_proxy`, `NO_PROXY`. Subprocess tests build `env` from that scrubbed state.

**S4 (W14, and S1's wording): raising cannot see a caught spawn attempt.**
- A patch that raises plus "block present" cannot see code that tries `Popen`, catches the error and falls back to HTTP. The block is still present.
- S1 says "no patched callable reached", which is right. W14 says only "block present, no spawn".
- **Fix.** Use record-then-raise patches in both, and assert the call log is empty. W14 also needs no "inside the memory arm only" scoping: patch globally for the duration of the `pre_llm_inject_context` call, and assert on the log.

**S5 (P4): no test that the hook process exits.**
- T25/T26 run in-process: `search()` returns. With the worker-thread design, a non-daemon thread keeps the interpreter alive at exit, and the Claude prompt stays blocked until the host's 10 s kill.
- **Fix.** Add H13b: subprocess run against `hang` and `drip-headers` with port env set. Assert rc 0, empty stdout, and `proc.wait` returning inside a generous watchdog (e.g. 4 s with a 0.3 s budget via a test-only parameter, or the real 5 s budget with a 9 s watchdog). Mutation: `daemon=False`.

**S6 (T6): check the positive direction.**
- Test modules import during collection, *before* the session `_home_off_limits` fixture runs (`tests/conftest.py:176-189`, READ). A hoisted `Path.home()` therefore captures the REAL home.
- If T6 asserts silence (tmp HOME without a token), the mutation survives on CI, which has no real token.
- **Fix.** Seed a token `"tok-T6"` in a per-test tmp HOME set after import. Assert exactly one request with header `X-AiRaccoon-Token: tok-T6`.

**S7 (P0 / I3): the spike oracle is a model answer.**
- A NONE can come from the model ignoring context as well as from the host dropping output, and branch B files an issue claiming three existing arms are inert.
- **Fix.**
  - Add a positive control: the same code word placed in `.github/copilot-instructions.md` must yield PERIWINKLE.
  - Run each arm at least 3 times.
  - Have the marker hook dump its stdin. Commit that captured Copilot payload as the fixture I3 feeds to the generated `bash` string, instead of a Claude-shaped payload.

**S8 (T23): count connections instead of timing them.**
- The failure is "retry loop". Count connect attempts with a patched `socket.create_connection` (== 1) instead of asserting `< 0.5 s`, which flakes on a loaded runner.
- Keep only a generous watchdog.

**S9 (I2): the `guarded()` fallback can mask a broken rewrite.**
- `guarded()` falls back to `elif [ -f "<relative>" ]` (`hook_wiring.py:60-74`, READ). If I2 runs `sh -c` with cwd = the tmp scaffold, a rewrite that yields a wrong `${CLAUDE_PROJECT_DIR}` path still finds the script relatively and prints the block.
- **Fix.** Run with cwd = an empty tmp dir. Assert stdout has no `systemMessage` and that the first-branch path exists.

**S10: token files leak through the session HOME.**
- `_home_off_limits` is **session**-scoped (READ). A token written to `Path.home()/.ai-raccoon/mcp-token` by one test stays for the rest of the run.
- After that, any existing test that fires the wired UserPromptSubmit chain in a cwd with a project id (e.g. `monkeypatch.chdir(ROOT)`, and the real repo has a project id) makes a request to 7721.
- **Fix.** Tokens only ever go in `tmp_path` HOMEs set with `monkeypatch.setenv("HOME", …)` or passed as `home=`. Add a module teardown that asserts the session HOME has no `.ai-raccoon/mcp-token`.

**S11: a dead port proves nothing about routing.**
- "Serve down" simulated as a dead port leaves a zero-request outcome that also holds when the child ignored the port env. A child that ignores the env lands on the live serve, gets a 401, stays silent, and passes.
- **Fix.** For subprocess expected-silent runs, use a fake that *accepts and records* the connection, then returns 500 or resets. Assert fake count == 1 and silent output. Reserve the dead port for in-process T23 only.

## NOTE

**N1 (§1.3 F2).** The manifest arm `memory-context.hermes.method = "pre_llm_call"` resolves because `register_hook("pre_llm_call", pre_llm_inject_context)` already exists (`ai_badger_hooks.py:1179`). Deleting the memory call from `pre_llm_inject_context` leaves F2 green. The plan should say that F2 proves only event registration for Hermes, and that W7/I6 are the wiring guards.

**N2 (§1.2 / I4).**
- (a) and (c) are list-membership checks. (b) is a regex over `index.ts`.
- `loadGates` reads only Pre/PostToolUse (`index.ts:101-114`), and the only `before_agent_start` spawn is `DELIVERY_SCRIPT` (`:68,729`) (READ). So the exclusion is true today.
- I4 cannot see a pi extension outside this repo (e.g. `pi-badger-integration` ships `mem-based-rag` itself, which is the double-injection risk).
- **Strengthen (b):** assert that no adapter `.ts` reads a `UserPromptSubmit` key from `HOOKS_CONFIG`. A future generic replay is the plausible regression, and it would not name `memory_context`.

**N3 (MEASURED; the plan's claims hold).** `scratchpad/f2_probe.py` implements §1.3 over the real data:
- `hermes arms: 12`.
- Gaps are exactly `prompt-markers` claude (`UserPromptSubmit`) and copilot (`userPromptSubmitted`).
- Deleting the `context_enrichment_hook.py` command yields 2 gaps (V1), because its Hermes arm resolves on `pre_llm_call`.

**N4 (the no-spawn proofs are genuine as a set).**
- S1 does not intercept `multiprocessing`'s spawn start method (`_posixsubprocess.fork_exec` directly). S2's static import scan covers that.
- `badger_store.py` imports no `subprocess` (grep, READ), so S2 will not start red on the sibling.
- S3 (PATH markers) covers the out-of-process runs only against spawns by name. That is fine as a third layer, but it is not a proof alone.

**N5 (oneLine).** JS `flat.length`/`slice` count UTF-16 units, while Python counts code points. A snippet with astral characters (emoji) truncates at a different position, and JS can split a surrogate pair. JS `\s` includes U+FEFF; Python `\s` does not. Either add one astral-char row to the bun-generated goldens (M5) or record this as an accepted divergence.

**N6 (H15).** `BUDGET_SECONDS <= 5` restates a literal. W2a (`timeout > BUDGET_SECONDS`) is the real invariant. H15's mutation `= 9` would pass W2a against timeout 10, which is the only argument for keeping H15. Either keep it, labelled as a product-decision pin, or drop it.

**N7 (M rows).** The memo dict is module state in `ai_badger_hooks`. M1–M5, W7–W10 and I6 need a fixture that clears it. Otherwise M4 ("on_session_start clears") can pass because an earlier test left it empty.

**N8 (B4).** "Kill switch checked before any file read" needs an observable. Pass `home=` pointing at a path whose token read is recorded (patch `Path.read_text` for that path only), and assert no recorded read when the switch is `"0"`. Otherwise the "reorder" mutation survives whenever the token is simply absent.

---

Probes (scratchpad, not repo): `proxy_probe.py`, `drip_probe.py`, `f2_probe.py`. No repo file was edited.
