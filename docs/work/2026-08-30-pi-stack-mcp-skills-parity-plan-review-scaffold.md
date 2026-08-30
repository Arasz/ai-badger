# MoE plan review — lane 3/3, scaffold-adjustment surface (P3/P4): wiring, context plumbing, honesty

**Task:** aib-pi-stack-mcp-skills-parity · **Date:** 2026-08-30 · **Reviewer home ground:** how ai-badger adjustments get wired and fed context.
**Input attacked:** plan rev 2 (M5/M7, P3/P4), premortem §1-D3/D4, and the code: `features/pi/adjustments/{adjust_mcp.py,adjust_skills.py,pi_settings.py,adjustment.json}`, `features/hermes/adjustments/adjust_mcp.py`, `features/common/skills/welcome-ai-badger/scripts/scaffold.py`, live `~/.pi/agent/settings.json`, live `~/.pi/agent/extensions/`.

**Overall verdict: APPROVE-WITH-MUSTS.** The wiring itself is sound — the scaffold's adjustment context (`scaffold.py:631-648`) already carries every key the migration-only removers need (`mcp_declarations` :646, `mcp_declined` :647, `target_dir` :635, `install` :639), so P3 needs **no scaffold.py change**. But three claims on the adjustment surface are not yet pinned to a mechanism, and one package-file omission would leave P3 red with no lane assigned to fix it.

---

## Q1 — Version-gate feasibility (M5): mechanism exists, plan pins NONE → MUST-1, MUST-2

**Feasibility: verified feasible.** The installed extension is plain TypeScript source, readable from the scaffold's Python process: `~/.pi/agent/extensions/pi-mcp-tools/` holds `index.ts`, `ConfigLoader.ts`, `McpClient.ts`, … plus `package.json` (measured this session). No compiled dist to see through.

**But the plan names no detection mechanism** — M5 says only "detect the installed `~/.pi/agent/extensions/pi-mcp-tools` build". Three candidates, one eliminated by measurement:

- **package.json version — eliminated.** Installed `package.json` says `"version": "1.1.6"` under the upstream name `@zhafron/pi-mcp-tools`; the fork's own `package.json` also says `1.1.6` (`~/RiderProjects/pi-mcp-tools-fork/package.json:3`). A version read cannot discriminate fork-build-from-upstream-build, and upstream may bump independently. Not an honest gate.
- **Byte-marker in source — feasible.** Grepping installed `ConfigLoader.ts`/`index.ts` for a symbol only P1 introduces (e.g. `loadProjectMcpJson`) works, but is fragile against refactors and indirect (the marker's meaning lives in the reviewer's head).
- **Capability marker file shipped by P1 — recommended.** P1 adds e.g. `capabilities.json` (`{"projectMcpJson": true}`) to the extension tree; the adjustment reads it, absence ⇒ predates project-scope ⇒ skip removal + warn. Explicit, survives refactors, trivially fakeable in pytest with a tmp dir (mirroring the `pi_settings.SETTINGS_PATH` monkeypatch idiom already pinned by `tests/test_pi_adjustments.py:832`'s real-home guard).

**MUST-1:** plan §M5 must pin exactly ONE mechanism, and P1's Files list must ship it — P1 currently lists only `ConfigLoader.ts`, `claudeMcpConfig.ts`, `index.ts` (plan §P1); no marker artifact is in any package. Without the marker, the gate cannot exist as specified and P5 step 10 ("version-gate live proof") has nothing to prove.

**MUST-2 — the gate must be per-extension, and the plan gates the wrong one for skills.** `adjust_skills.py` removes the global skills path on the strength of the *adapter's* ungated `resources_discover` contribution (M4) — so its removal must be gated on the **`~/.pi/agent/extensions/ai-badger` adapter build**, not on pi-mcp-tools. Measured: the installed adapter's `index.ts` contains **zero** occurrences of `resources_discover` — every machine with the pre-P2 adapter that runs the P3 scaffold loses the project's only pi skills route, exactly the "strands the machine" failure M5's gate exists to prevent, on a second extension the plan never gates. M5's text names only the pi-mcp-tools build. P3 needs two gates: fork-marker for `adjust_mcp.py`, adapter-marker for `adjust_skills.py` (P2 must ship the adapter's marker; P2's Files list also has none).

## Q2 — Shape-aware removal (M5): concrete basis exists, definition missing → MUST-3

**"Legacy key drift" is not vibes — it has exactly one concrete historical form, measured:**
- Git history of `adjust_mcp.py`: `_server_entry`'s key set is unchanged since introduction; the single shape-relevant change is `command.split()` → `shlex.split()` (commit `c7d0d528`, the 0.144.0 review pass). So a legacy entry can differ from today's generation only in the command array when the declaration's command string carries quotes.
- Live check: all 5 global entries (`ai-raccoon`, `code-review-graph`, `hermes`, `playwright`, `semantica`) **deep-match today's regenerated shapes exactly** (verified by re-running `_server_entry` logic against `features/common/stack-mcp.json` and diffing against `~/.pi/agent/settings.json`). Keys in the wild: `{enabled, toolPrefix, type, command, env?}` — no `cwd`, no `url`, no quoted commands.

**MUST-3:** the plan must define the matcher so the test can pin it. Recommended concrete definition:
> Regenerate the entry with `_server_entry(name, declaration)` from the context's `mcp_declarations` (same key the old writer used). Remove iff: name is declared (minus declined) AND `type`/`url`/`env`/`cwd` are deep-equal AND the entry's `command` equals the shlex-split **or** the plain-split list of the same command string (the one legacy allowance). `enabled`/`toolPrefix` drift is tolerated (scaffold-owned decoration). Anything else ⇒ warn-and-leave, naming the entry.

Two corollaries the plan must absorb:
1. **Plan §4.3's claim is matcher-dependent.** "User-owned entries survive by construction (shape-match requirement makes this true for values, not just keys)" is only true under content-strict matching as above. Under the plan's own looser parenthetical ("name + command"), a user's `env` edit on a same-named entry is destroyed — contradicting §4.3. Pin the strict matcher.
2. **Scope §4.2's claim.** "This repo's scaffold run removes all 5 servers" is verified true *today* (all 5 deep-match), but a catalog change since a project's last scaffold ⇒ regenerated shape ≠ stored entry ⇒ warn-and-leave forever. That stale-but-honest outcome is acceptable; say so, so the P5 byte-diff treats the warning as the expected signal, not a failure.

## Q3 — adjustment.json: no mechanical breakage; descriptions must be updated → SHOULD

`features/pi/adjustments/adjustment.json` descriptions become lies after P3 ("Map .mcp.json to pi-mcp-tools settings.json format", "Merge project .ai-badger/skills/ path into pi's user-global settings skills array" — both describe write behavior the scripts will no longer perform). Consumers, all verified:
- `schemas/adjustment.schema.json`: `description` optional, unconstrained; `tooling/validate.py:45` validates structure only. No breakage.
- `scaffold.py:651-663` embeds `result['notes']` **verbatim** into scaffold notes; nothing parses the notes format. The `files` list stays `[]` for user-global writes (current behavior, `adjust_mcp.py:118`); removal should keep that (nothing inside the project changes).
- `tests/test_support_scaffolded_by.py` consumes only `script` names (`SCRIPT_PATTERN` over support.json's scaffoldedBy/wiredBy vs `adjustment.json` arms, :14-40) — stays green as long as the scripts keep their names.

**SHOULD:** update both descriptions in P3 (they are the honesty surface a future reader consults first), and rewrite `pi_settings.py`'s module docstring, which currently *argues for* user-global writes with the headless-trust rationale (`pi_settings.py:3-10`) — after P3 that rationale is historical and contradicts ADR-0023 if left standing.

## Q4 — support.json honesty rows: currently written by NOBODY → MUST-4

Plan §3 defines the rows, P3's AC demands "support.json pi rows match MUST-4 exactly", and P3's `test_support_json_honesty.py` asserts the substrings — **but neither P3's nor P4's Files list contains `features/common/support.json`.** As written, P3 goes red with no package assigned to green it. The rows that become lies are measured in the file today:
- `agents.pi.capabilities.mcpServers.scaffoldedBy` = "pi/adjustments/adjust_mcp.py — merges into ~/.pi/agent/settings.json's mcp key (install=True) or prints the snippet (--no-install)" — false after P3.
- `agents.pi.capabilities.skills.mechanism`/`scaffoldedBy` — describes the merge route the plan retires.

**MUST-4:** add `features/common/support.json` **and** `features/pi/adjustments/adjustment.json` to P3's Files list. Shared-file discipline: `features/common/` is consumed by every stack, and within this task **P3 is the only lane that may touch it** — state that explicitly so P4 (ADR/changelog/README only) doesn't reach for the same file.

## Q5 — Migration sequencing (M7): no repo-B coupling to repo-A edits — verified, no finding

`tests/test_framework_copies.py` is entirely synthetic: every test builds framework roots from `tmp_path` via `_make_root` (predicate: `schemas/`+`features/`+`engine/badger_lib.py`), and discovers/prunes only `~/.ai-badger/framework`-shaped trees. It reads neither repo A (`pi-badger-integration`) nor any vendored project copy — `grep -rn "pi-badger-integration" tests/ engine/` returns zero hits. P2 editing the canonical adapter in the other repo cannot break repo B's suite; M7's "P3 merges after pbi-move's repo-B surgery" is correctly characterized as rebase-churn hygiene only, with runtime safety carried by the version gate (which, per MUST-1/2, must first exist). The real-home guard machinery the plan promises to extend (`:832`) exists (`test_pi_settings_write_does_not_touch_real_home`, conftest `REAL_HOME`/`REAL_WRITE_LOG`).

## Q6 — ADR numbering: 0023 free — verified

`docs/adr/` tops out at `0022-pi-arms-hooks-dynamically.md`; `0023-pi-project-scoped-mcp-and-skills.md` is unclaimed. `CHANGELOG.md` exists at repo root for P4.

---

## Findings

| # | Sev | Finding |
|---|-----|---------|
| MUST-1 | MUST | M5's version gate has no pinned mechanism. Pin ONE: a capability marker file shipped by P1 (recommended) — and add it to P1's Files list. package.json version is ruled out (installed 1.1.6 == fork 1.1.6, upstream-owned). |
| MUST-2 | MUST | The gate is per-extension: `adjust_skills.py`'s removal must gate on the **ai-badger adapter** build having `resources_discover` (installed adapter today: 0 hits), not on pi-mcp-tools. P2 must ship the adapter marker. Plan M5 names only the fork. |
| MUST-3 | MUST | Define the shape-aware matcher concretely (regenerate-from-declaration + deep-equal type/url/env/cwd + shlex-or-plain command allowance + warn-and-leave), or "tolerate legacy key drift" is untestable and plan §4.3's "survive for values" claim is unearned. Scope §4.2's "removes all 5" to "verified today; catalog drift ⇒ warn-and-leave". |
| MUST-4 | MUST | Add `features/common/support.json` + `features/pi/adjustments/adjustment.json` to P3's Files list; declare P3 the sole lane for `features/common/support.json`. Otherwise P3's honesty test is red by construction. |
| SHOULD-1 | SHOULD | Rewrite `pi_settings.py:3-10` module docstring (currently argues for user-global writes) in P3; update both adjustment.json descriptions. |
| SHOULD-2 | SHOULD | Pin the test seam: extensions dir as a monkeypatchable module constant in `pi_settings.py` (mirror `SETTINGS_PATH`, :26), guarded by the :832 real-home extension. |
| SHOULD-3 | SHOULD | Pin the empty-key end state (drop `mcp`/`skills` key when emptied vs leave `[]`/`{}`) — P5 step 3's "user keys byte-identical" needs the answer. |
| NIT-1 | NIT | Removal set = declared-minus-declined mirrors the writer, so an entry written long ago for a since-declined/retired server is never matched; warn-and-leave covers it — note it in the ADR residual. |
| NIT-2 | NIT | `--no-install` removal proposal should list the exact entry names (like today's PROPOSAL_HEADER + JSON), not a generic sentence. |

## Verified vs hypothesis

**Verified (read/ran this session):**
- Adjustment context keys: `scaffold.py:631-648` — `framework_root, config, feature_dir, target_dir, target, install(:639), skills, prune, personas, index, mcp_servers(:645), mcp_declarations(:646), mcp_declined(:647)`; `install = not --no-install` (`:822`). P3 needs no scaffold.py change.
- `_server_entry` shape history: one shape-relevant change ever (`split`→`shlex.split`, `c7d0d528`); all 5 live global entries deep-match today's regenerated shapes; live skills array = this repo's path only.
- Installed pi-mcp-tools = plain TS source + `package.json` 1.1.6 (upstream name); fork `package.json` also 1.1.6; installed adapter `index.ts` has zero `resources_discover`.
- `test_framework_copies.py`: fully tmp_path-synthetic; zero references to repo A anywhere in `tests/`/`engine/`.
- `schemas/adjustment.schema.json` (description optional) + `tooling/validate.py:45`; `scaffold.py:651-663` notes verbatim; `test_support_scaffolded_by.py` script-name-only coupling.
- Plan's cited test lines exist: `test_adjust_mcp_proposes_servers` :92, `test_adjust_skills_install_true_merges_skills_path` :537, `test_adjust_mcp_install_true_merges_into_settings` :566, real-home guard :832.
- ADR 0023 free; Hermes sibling `adjust_mcp.py` is propose-never-write (correct precedent shape for "never write global again", though removal-write is a new contract — the notes must name the mutated path as MERGED_HEADER does today).
