# Research: prune catalog-retired MCP servers and hooks on re-scaffold

Task `aib-prune-retired-catalog-scaffold-entries` · 2026-11-11 · worktree at origin/main 8a5ff5c0 (0.218.1).
Grades: READ (I read the source at the cited line), MEASURED (I ran it and saw the output),
INFERRED (follows from READ facts but I did not run it), UNVERIFIED (not checked).
Paths are relative to the worktree. `S` = `features/common/skills/welcome-ai-badger/scripts`.

Probes (throwaway, scratchpad, HOME redirected):
`/private/tmp/claude-501/-Users-arasz-RiderProjects-ai-badger/c3cabaf3-90b1-4705-ba4d-7cae180b8f79/scratchpad/probe/probe.py`,
`.../probe/probe2.py`, `.../probe/probe3.py`.

---

## Q1. Merge points: what each adds, what it removes, how it decides ownership

| # | File written | Function | Adds | Removes | Ownership test | Retired name survives? |
|---|---|---|---|---|---|---|
| 1 | `.claude/settings.json` `enabledMcpjsonServers`, `permissions.allow`, `disabledMcpjsonServers`, `permissions.deny` | `features/claude/adjustments/adjust_mcp.py` `adjust` 20-67, `_extend` 75-90 | missing names / `mcp__<n>__*` (54-59) | **nothing** — `_extend` only appends (88-89) | none; "merged into, never owned — so never recorded" (65) | **yes** (MEASURED, probe2: `['semantica','code-review-graph']`, `['mcp__semantica__*', ...]`) |
| 2 | `.mcp.json` | `S/mcp_tools.py` `generate_mcp_json` 932-955 → `_merge_mcp_servers_json` 605-644 | `section.update(entries)` (637) — catalog wins on refresh | declined (638, by name), declared-elsewhere (639), unavailable (640, **shape-matched**), user-scoped (641, by name) | name in current catalog; for unavailable, rendered-shape equality `_drop_unavailable` 756-773 | **yes** (MEASURED, probe) |
| 3 | `.github/mcp.json` | `generate_copilot_mcp_json` 846-877 → same `_merge_mcp_servers_json` | as #2 | as #2 | as #2 | **yes** (MEASURED) |
| 4 | `.pi/mcp.json` | `generate_pi_mcp_json` 957-985 → `_merge_pi_mcp_json` 646-688 | union: only names absent from file (673-676) | declined (683), unavailable if launch == template (684, `_drop_pi_unavailable` 775-825), user-scoped (685) | template-launch identity `_launch_of` 104-106 | **yes** (MEASURED) |
| 5 | `.claude/settings.json` `hooks` | `S/hook_wiring.py` `wire` 221-384, `merge_hooks` 180-212, `_prune` 125-151, `drop_declined` 88-112 | incoming hooks, dedup by (matcher, script id) | (a) framework hooks whose script id an incoming hook **re-registers** (`superseded`, 188-195); (b) hooks of skills in `config.exclude` (373); (c) all owned hooks under `limited-env` (386-421) | `skill_script_id` 29-43: command contains `/.ai-badger/skills/` etc. — a path-derived ownership signal that already exists | **yes** (MEASURED, probe2: `['semantica-knowledge-graph','commit-reminder']`). Note `merge_hooks` only visits events present in the incoming set (187), so a whole retired event is never even looked at (READ) |
| 6 | `.ai-badger/hooks/hooks.json` | `hook_wiring.py` 361-364 `bl.dump_json` | whole file | whole file rewritten | owned file | no (READ) |
| 7 | `.github/hooks/ai-badger-hooks.json` | `features/copilot/adjustments/adjust_hooks.py` 199-205 (`open(..., "w")`) | whole file | whole file rewritten | owned file | no (READ; 0.218.0 diff removed the semantica hook from it without the commit message listing it as hand-removed) |
| 8 | `.codex/config.toml` | `features/codex/adjustments/adjust_mcp.py` `adjust` 49-92 | managed block between `# ai-badger:mcp-start`/`-end` (21-22) rebuilt from current declarations (75-83) | everything previously inside the markers (64-67 split it out; only `base + suffix` survive) | the **markers** are the ownership boundary; a name already defined outside the block is skipped (76) | **no** (MEASURED, probe3: block went `semantica` → `task-graph`, operator `mine` kept) |
| 9 | `~/.hermes/config.yaml` `mcp_servers` | `features/hermes/adjustments/adjust_mcp.py` `adjust` 23-53 | nothing — returns a note (`files: []`, 53) | nothing | n/a | n/a — see Q5 |
| 10 | `.ai-badger/hooks/<flat copies>` | `S/superseded_prune.py` `_prune_retired_hook_copies` 67-74 | — | the hand-kept `RETIRED_HOOK_COPIES` (18) | name list | n/a |
| 11 | `.ai-badger/**` manifest entries (skills, personas, …) | `superseded_prune.py` `prune` 28-65, `_reason` 80-91 | — | entries whose catalog `source` is gone (89-90) or stack left (87-88), unless edited (`_edited_here` 93-128, needs `outputHash`) | manifest `entries` + hash | removes the semantica **skill dir** if unedited (INFERRED from 89-90) |
| 12 | `~/.pi/agent/settings.json` (legacy) | `features/pi/adjustments/pi_settings.py` + `features/pi/adjustments/adjust_mcp.py` 132-172 | — (migration-only, docstring 10-13) | shape-matched entries for **current** declarations (`remove_mcp_servers`, call 172) | shape | INFERRED yes: matching is keyed on `mcp_declarations` (151), which no longer contain a retired name |

Out of scope but same defect class: `.ai-badger/mcp-tools.json` is maintained by the `mcp-index` skill (`update` "marks removed ones", `features/common/skills/mcp-index/scripts/mcp_index.py:15`, 670), not by the scaffold; 0.218.0 cleaned it by hand (commit 769d94fb message). READ.

Why Codex is safe (READ, MEASURED): ownership is a **region**, not a name. Everything between the markers was written by ai-badger by definition, so the block can be thrown away and rebuilt from the current declaration set; the operator's servers live outside it and a name collision is resolved in the operator's favour (76). JSON (`.mcp.json` etc.) has no comment syntax, and `permissions.allow` is a flat string array, so there is no place to put a region marker — this design does not transfer to rows 1-5.

Live second instance (MEASURED): this repo's `.claude/settings.json` still lists `ai-raccoon` in `enabledMcpjsonServers` and `mcp__ai-raccoon__*` in `permissions.allow`, while `ai-raccoon` is `scope: user` in `features/common/stack-mcp.json` and is in none of `.github/mcp.json`, `.pi/mcp.json`, `.codex/config.toml` (`.ai-badger/config.json` has no `mcp` key). The append-only `_extend` kept them after the scope change. **That allow rule is load-bearing** (it approves the user-global ai-raccoon's tools), which is why "not in this run's declared set" must never mean "remove" — see Q5.

## Q2. Ownership signals that already exist

- `.ai-badger/manifest.json` `generatedConfig` (READ, this repo): five records of the shape
  `{"path": ".mcp.json", "destination": ".mcp.json", "frameworkVersion": "0.218.1"}` (also `.claude/settings.json`, `.github/mcp.json`, `.pi/mcp.json`, `.gitignore`). **No server names, no permission rules, no hook entries.**
- The record is explicitly *not* ownership: `S/generated_config.py:1-6` ("bookkeeping, never ownership: nothing reads a record back to overwrite, delete or drift-check the file"); `schemas/manifest.schema.json` `generatedConfig.description` says the same; `items.additionalProperties: false` with exactly `path/destination/frameworkVersion` (READ). Pinned by `tests/test_manifest_generated_config.py:211` `test_the_schema_pins_the_record_shape` and the philosophy by `:157` `test_a_recorded_config_the_project_edited_is_still_the_projects` ("A record licenses nothing").
- Manifest `entries` record owned files with `hash`/`outputHash` — files only (READ, `superseded_prune.py:93-128`).
- Hook commands: `skill_script_id` (`hook_wiring.py:29-43`) and `tool_hooks.is_ours` (used 176, 413) — a path/marker signal on every framework hook. READ.
- Codex markers `# ai-badger:mcp-start/-end` (`features/codex/adjustments/adjust_mcp.py:21-22`). READ.
- Rendered-shape identity for MCP entries: `_drop_unavailable` 756-773 / `_drop_pi_unavailable` 775-825 / `_template_candidates` 734-754 already prove "ai-badger wrote this entry" by re-rendering the catalog declaration (incl. every `~`/`${HOME}` spelling). It needs the **declaration**, which is exactly what retirement deletes (`catalog.get(name) is None → continue`, 764-765). READ — this is the precise gap.
- `only_generated_entries` (`mcp_tools.py:57-74`) — key-shape guess, kept for one migration. READ.
- Existing hand-kept removal lists (precedent, READ): `RETIRED_HOOK_COPIES` (`superseded_prune.py:18`), `REMOVED_MODULES` incl. `"export_semantica_graph.py"` (`features/hermes/adjustments/adjust_hooks.py:52`, used 177-178), `LEGACY_COPILOT_MCP_CONFIG` (`mcp_tools.py:49`), `RETIRED_DECLARATION_FILES` (`mcp_tools.py:54`). `tests/test_semantica_removed.py:37-39` has a `TOMBSTONES` exemption for exactly such a list.

## Q3. Candidate designs

Semantica's last declaration (READ, `git show 769d94fb -- features/common/stack-mcp.json`): `{"name":"semantica","command":"semantica-mcp","declare":true,"env":{"SEMANTICA_DISABLE_PROGRESS":"1"},"availability":{"command":"semantica-mcp"}}`. Its hook: PostToolUse, matcher `^(mcp__.+__|.+-)?export_graph$`, script `.ai-badger/skills/semantica-knowledge-graph/scripts/semantica_export_autosave_hook.py` (READ, 0.218.0 diff of `.claude/settings.json`). Git history shows exactly one deleted `features/*/mcp/*/meta.json`: semantica, 769d94fb (MEASURED, `git log --diff-filter=D`).

### (a) Retired-names list
- *Derived from git history*: works only in the framework repo. A consumer's `frameworkRoot` is the plugin cache; whether it is a git checkout with history is UNVERIFIED, and a shallow clone would lose it. Not usable at scaffold time. INFERRED.
- *Tombstone that keeps the last declaration* — a top-level `"retired": [ {…last declaration…} ]` in the same `stack-mcp.json`: retiring a server is **moving** its object from `servers` to `retired` (one edit, not a second list). The scaffold feeds `retired` into the existing shape-matched drop path, so only an entry identical to what ai-badger rendered is removed; a hand-edited one is kept with the existing "kept … hand edit" note (823-825).
  - Semantica prune: `.mcp.json`, `.github/mcp.json`, `.pi/mcp.json` entries removed if still template-shaped; `enabledMcpjsonServers` `semantica` and `permissions.allow` `mcp__semantica__*` removed by name (no shape exists for a string rule).
  - User collision risk: MCP files ≈ nil (must equal the rendered launch). Permission rules: name-only — a user who hand-added `mcp__semantica__*` for a user-global semantica loses it and gets a permission prompt (annoyance, not breakage). INFERRED.
  - Migration: **works on the first refresh for every existing consumer** — no prior record needed. This is the only option that fixes the motivating case for already-scaffolded repos. INFERRED.
  - Invariant fit: the list is the catalog's own history in the catalog's own file; the invariant's second clause ("write the check that compares them and prove it fails") is met by a framework-side test that every name ever deleted from a `features/*/stack-mcp.json` `servers` array (git log) appears in that file's `retired`. INFERRED.
  - Files: `features/common/stack-mcp.json`, `schemas/stack-mcp.schema.json` (top-level `additionalProperties: false`, line 8 — needs the new key), `S/mcp_tools.py`, `features/claude/adjustments/adjust_mcp.py` (+ `S/adjustment_policy.py` 25-34 to pass `mcp_retired`), `features/hermes/adjustments/adjust_mcp.py` (note only), `tests/test_semantica_removed.py` (`TOMBSTONES` exemption + `test_source_stack_mcp_declares_no_semantica_server` :106 reads `servers` only, so it stays green). ~6-7 files.
  - Readers of `stack-mcp.json` that must ignore `retired`: `collect_catalog_mcp_servers` reads `data.get("servers")` only (206) and `tooling/validate.py:49` validates the schema — a new top-level key leaves all 5 call sites (268, 315, 389, 760, 795) unaffected. READ.

### (b) "Previous scaffold output minus current output" from a recorded owned set
- Add per-destination owned names to `generatedConfig` (e.g. `servers: [...]`, and for settings.json the approved names). Next run: `prior_owned − names(collect_catalog_mcp_servers())` = retired (availability-, decline- and scope-independent, see Q5).
- Semantica prune: **nothing** for any consumer whose manifest predates the change — semantica left the catalog in 0.218.0, so no run after the change ever records it. Consumers who refreshed before upgrading are permanently outside its reach. INFERRED (follows from all_records 34-47 carrying only what a run wrote).
- User collision: low going forward (name was recorded as written by ai-badger), but a user who later hand-edits a recorded entry loses it unless shape is also checked.
- Reverses the documented contract of #194 (Q2) → needs an ADR; rewrites `test_the_schema_pins_the_record_shape` (:211). `GeneratedConfigRecords.record(path, destination)` (24-32) and `record_generated_config` callback (`scaffold_context.py:56`) need a names argument; adjustments get no record callback today (`adjustment_policy.py:25-34`), so `.claude/settings.json` approvals need new plumbing. Files: `generated_config.py`, `scaffold_context.py`, `scaffold.py`, `mcp_tools.py`, `adjustment_policy.py`, `features/claude/adjustments/adjust_mcp.py`, `schemas/manifest.schema.json`, tests. ~8 files.
- Benefit over (a): no list at all, and it also catches future "silent" removals without an author remembering to tombstone. INFERRED.

### (c) Managed-block rebuild like Codex
- Not available for JSON arrays/objects without a marker key per entry. A marker key inside an MCP entry (e.g. `_aiBadger`) risks host schema rejection — Copilot treats unknown keys as someone else's config (`mcp_tools.py:60-62`); whether Claude/Copilot/pi tolerate an unknown entry key is UNVERIFIED. `permissions.allow` is `string[]` — no place for a marker at all. Rejected. INFERRED.
- Already in place for `.codex/config.toml` (row 8), `.ai-badger/hooks/hooks.json` (row 6), `.github/hooks/ai-badger-hooks.json` (row 7).

### Hooks (any design)
Derive, do not list: after `superseded.prune` (runs first, `scaffold.py:710`) removes an unedited retired skill directory, a framework hook (`skill_script_id` not None) whose `project_script(cmd)` (`hook_wiring.py:46-55`) no longer exists under the target is dead — `guarded()` (62-76) already turns it into a "hook skipped" message at runtime. Prune those across **all** events, not only the events `merge_hooks` visits (187). No list; the disk is the source. If the user edited the skill dir, `superseded_prune` keeps it (59), the script exists, the hook stays — consistent. INFERRED.
Semantica: the hook is removed iff the skill dir was removed. MEASURED that it currently survives (probe2).

## Q4. Tests that pin the additive behaviour (would be rewritten or must stay green)

Must stay green (they define the user-preservation contract; a correct prune leaves them unchanged — READ):
- `tests/test_stack_mcp_servers.py:290` `test_mcp_json_merge_preserves_existing` (`my-server` survives)
- `tests/test_stack_mcp_servers.py:481` `test_copilot_mcp_json_merge_preserves_existing`
- `tests/test_copilot_mcp_json.py:106` `test_an_existing_hand_added_server_survives_the_merge`
- `tests/test_stack_mcp_servers.py:1135` `test_pi_native_unknown_entry_survives` ("the merge is a union — a user-added server is never dropped")
- `tests/test_stack_mcp_servers.py:1250` `test_pi_native_unavailable_hand_edited_entry_kept_with_note`
- `tests/test_adjust_mcp_claude.py:72` `test_existing_settings_content_survives_and_is_backed_up` (asserts `allow == ["Bash(git status)", "mcp__code-review-graph__*"]` exactly)
- `tests/test_adjust_mcp_claude.py:61` `test_nothing_is_recorded_as_an_ai_badger_owned_file`
- `tests/test_scaffold_hook_wiring.py:255` `test_merge_leaves_third_party_hook_entries_untouched`
- `tests/test_hook_wiring_claude.py:102` `test_a_wired_command_survives_the_script_missing_at_runtime` — **conflicts with the hook-prune design** if that test scaffolds and the script is missing at scaffold time; read before building (UNVERIFIED which side of the line it sits on).
- `tests/test_codex.py:174` `test_mcp_preserves_config_and_scope`
- `tests/test_adjust_mcp_hermes.py:127` `test_an_existing_config_is_neither_read_nor_rewritten`; `tests/test_settings_preservation.py:93` `test_the_hermes_user_config_is_neither_read_nor_written`; `tests/test_stack_mcp_servers.py:361` `test_no_scaffold_step_writes_the_hermes_user_config`

Would be rewritten:
- Design (b): `tests/test_manifest_generated_config.py:211` `test_the_schema_pins_the_record_shape`; probably `:157` `test_a_recorded_config_the_project_edited_is_still_the_projects` (its docstring states the opposite contract).
- Design (a): `tests/test_semantica_removed.py` `TOMBSTONES` (37-39) gains a `features/common/stack-mcp.json` exemption; `:191`/`:237` `test_*tree_names_no_semantica_outside_history` otherwise go red. `test_source_stack_mcp_declares_no_semantica_server` (:106) reads only `servers`, stays green.
- No test pins "a name not in the catalog survives in settings.json" directly (searched test names in the files above, READ); the pin is indirect via exact-list asserts like `test_adjust_mcp_claude.py:72`.

## Q5. Hermes and availability

- The scaffold never writes `~/.hermes/config.yaml`: `features/hermes/adjustments/adjust_mcp.py:1,24` ("Print … write nothing"), `files: []` (53); ADR-0014 decision 6 (`docs/adr/0014-…md:110-112`). `git grep "config.yaml"` over `*.py` finds no writer (MEASURED). So a Hermes prune can only be a **note** ("remove `mcp_servers.semantica`"), the same channel the decline uses (`DECLINE_HEADER` 17-20). READ.
- Availability: `declared_servers` drops servers whose `availability.command` is not on PATH (`mcp_tools.py:391-392`); `AI_BADGER_MCP_AVAILABILITY=all|none` overrides (249-264). Every adjustment's `mcp_servers`/`mcp_declarations` is built from that filtered set (`project_server_names` 419-422, `declarations_for_agent` 407-417). Therefore **"previous minus this run's declared set" would treat an uninstalled `hermes`/`playwright` as retired** and strip its approvals. INFERRED from READ.
- But `collect_catalog_mcp_servers` (187-209) is pre-availability, pre-decline, pre-scope. Retired must be defined against **it** (or against the tombstone), never against `declared_servers`. Under that definition an unavailable server is never "retired". INFERRED.
- Note that files 2-4 already **do** remove an unavailable server's template-shaped entry (640, 684), and Codex drops it from its block (row 8) — so "unavailable → removed from the project MCP file" is existing, intended behaviour; what must not happen is removal of its `.claude/settings.json` approval or of a hand-edited entry. READ/INFERRED.
- Catalog is per active stack (196): a server whose stack left `config.stacks` is also absent from `collect_catalog_mcp_servers`. Design (b) would prune it (arguably correct, mirrors `superseded_prune` reason "stack no longer in config.stacks", 87-88); design (a) would not (its tombstone lives in a different stack's file). INFERRED.

## Q6. ADRs on merge contracts / ownership

- `docs/adr/0048-ai-raccoon-decisions-replace-semantica.md:57-62` — states the defect and defers it: "The scaffold merges MCP servers, permission rules and hooks additively. A re-scaffold does not remove the semantica entries from `.claude/settings.json`, `.mcp.json`, `.github/mcp.json` or `.pi/mcp.json`, nor the export hook entry …, nor a Hermes operator's `~/.hermes/config.yaml` … A scaffold prune for catalog-retired servers and hooks is a follow-up issue, not built here." READ.
- `docs/adr/0014-mcp-support-is-configuration-not-retrieval.md:65-73` (§3 "A scaffolder owns two of seven arrival routes"), `:110-112` (decision 6: propose user-global, never write it; may write project-scoped files it owns), `:122-123` (pruning buildable "in a file ai-badger owns"). READ.
- `docs/adr/0039-tools-feature-type.md:126` — owned files are "owned, marked and removable". READ.
- `docs/adr/0024-sqlite-runtime-store.md:55` — "Harness settings (`hooks.json`, `.claude/settings.json`, `package.json`) | Owned by the agent host, not by ai-badger." READ.
- `docs/adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md:86` — "Never `rmtree` the namespace — remove only what ai-badger owns". READ.
- `docs/adr/0044-project-scope-decision-for-an-mcp-server.md` — user-scoped servers removed from project files (cited at `mcp_tools.py:718-731`). READ (via code citation).
- No ADR defines a general merge/ownership contract for the generated JSON configs; #194's `generatedConfig` contract lives in code/schema text (Q2), not an ADR. READ (grep of `docs/adr/*.md` for additive/owned/prune/retire/merge).

---

## Recommendation

**(a) Tombstone in the catalog + disk-derived hook prune.**

1. `stack-mcp.json` gets a top-level `retired` array; retiring a server moves its last declaration there. The scaffold adds retired names to the *existing* shape-matched removal paths (`_drop_unavailable`, `_drop_pi_unavailable`), so `.mcp.json`, `.github/mcp.json` and `.pi/mcp.json` lose only template-identical entries; hand edits are kept with the existing note.
2. `features/claude/adjustments/adjust_mcp.py` gets `mcp_retired` and removes `enabledMcpjsonServers` and `permissions.allow` `mcp__<n>__*` for those names only, with a note.
3. `hook_wiring` prunes framework hooks (`skill_script_id` set) whose project script no longer exists on disk, across all events.
4. The Hermes adjustment prints a "remove these `mcp_servers` entries" note. Codex needs nothing.
5. A framework-side test compares `retired` to the git history of `servers` deletions, and you watch it fail once. This meets clause 2 of the derive-or-delete invariant.

It fixes semantica on every existing consumer's first refresh. Design (b) cannot do this.

**Simpler alternative considered:** no prune code. Keep the upgrade-note "remove by hand" (the status quo from ADR-0048) and add only step 3 (the hook prune, which needs no list). That is the smallest change, but the MCP and permission residue stays a per-release manual chore. **Larger alternative:** (b), recorded owned names. It is better long-term because no author has to remember to tombstone. But it does nothing for semantica, reverses the #194 contract, and needs an ADR and new adjustment plumbing. It can be added later on top of (a).

## Top risks

1. **Retired defined against the wrong set.** If "retired" is computed from `declared_servers()` or an adjustment's `mcp_servers`, which are filtered by availability, decline and scope, the change strips approvals that are in use. This repo's `mcp__ai-raccoon__*` rule (scope:user) and an uninstalled `hermes`/`playwright` are live examples. Define retired only from the tombstone, or from the pre-filter `collect_catalog_mcp_servers`.
2. **Permission rules are name-only.** No shape exists for `mcp__semantica__*`, so a user's own identical rule for a user-global server is removed. Cost: a permission prompt. Report each removal in a note.
3. **Hook prune vs the worktree/missing-script contract.** `guarded()` exists because a script can be missing in one checkout and present in another (`hook_wiring.py:62-68`), and `test_a_wired_command_survives_the_script_missing_at_runtime` (`tests/test_hook_wiring_claude.py:102`) pins survival. The prune must check the scaffold target only, run after `superseded.prune`, and not fire when a scaffold is partial. Read that test before building.
