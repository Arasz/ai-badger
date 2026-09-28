# R1 — ai-badger integration-surface map: new skill + new local stdio MCP server

**Scope:** read-only inventory of every registration point a new skill (`task-decomposition`) and a new local stdio MCP server (Python, `task-graph`) must occupy. All paths are repo-relative in this worktree. Every claim carries `path:line`; deviations from the task's premise are called out in §0; the only HYPOTHESIS labels are on the two items nothing in the tree can verify (§2.4, §3.4).

**Evidence base (commands actually executed, no writes):** `ls -R features/common/mcp`, `cat features/common/stack-mcp.json`, `cat schemas/stack-mcp.schema.json`, `cat schemas/mcp-server.schema.json`, `cat schemas/mcp-tags.schema.json`, `grep -n` over `gates/skills_lint.py`/`tooling/validate.py`/`tooling/index_build.py`/`tooling/sync_plugin_skills.py`, `python3 - <<EOF` reads of `index.json` and `schemas/index.schema.json`, `cat engine/requirements.txt`, `cat features/common/dependencies.json`, `grep -rn` for the stdlib-only claim, `.lefthook/pre-push/verify.sh` (LANES + lane_cmd), `git ls-files .mcp.json.example`, `sed` reads of `CONTRIBUTING.md`, `RELEASING.md`, `docs/authoring-a-feature.md`, `docs/changelog/README.md`, `tests/*`.

---

## 0. Verdict on the premise — what is true, what is not

| Premise | Verdict |
|---|---|
| Skill sources canonical in `features/common/skills/<name>/`, mirrored to plugin `skills/` and self-scaffold `.ai-badger/skills/` | **True**, with two mechanisms and two regenerators (§1) |
| MCP declared in `features/common/stack-mcp.json`, schema `schemas/stack-mcp.schema.json` | **True** (`features/common/stack-mcp.json:1-45`, `tooling/validate.py` `SCHEMA_INSTANCES["stack-mcp.schema.json"]`) |
| Descriptor dirs under `features/common/mcp/<name>/`; `features/common/mcp-tags.json` | **True** (`features/common/mcp/{ai-raccoon,code-review-graph,hermes,playwright,semantica}/`; `index_build.py:89-92`) |
| Python deps declared in `engine/requirements.txt` behind a guard | **True** (`engine/requirements.txt:4-10`; `gates/deps_guard.py:55` `REQUIREMENTS`), but there is a **second** dependency surface for consumer projects (`features/common/dependencies.json` + `dependency_check.py`, §3) |
| Gate names "skills-shape, skills-lint" | **`skills-shape` does not exist.** The real gate is `gates/skills_lint.py` — 13 rules. `index_build.py --check` and `validate.py --all` are real lanes/checks. |
| "the ADR-0009 duplication discipline" | ADR-0009 is *One Framework Root*; the **vendored-verbatim discipline** is named in **ADR-0024** (which says it *extends ADR-0009*, `docs/adr/0024-sqlite-runtime-store.md:6,15,25`) and tested by `tests/test_badger_store_vendored.py`. Cite ADR-0024, not 0009, for vendoring. |

---

## 1. A new skill: exact layout, mirrors, regenerators, gates

### 1.1 Layout

Canonical (write here): `features/common/skills/task-decomposition/` containing `SKILL.md` plus optional `scripts/`, `references/`, `extensions/<agent>/`, `evals/`, `tests/`. Discovery is *any subdir with a `SKILL.md`* (`tooling/index_build.py:55-66`, `docs/authoring-a-feature.md:34`); delivery is a denylist — the whole dir is copytree'd (`features/common/skills/welcome-ai-badger/scripts/skill_delivery.py:275-290`).

Required frontmatter (rule 10): `name`, `description`, `version`, `author`, `license`, `platforms`, `metadata.hermes.tags`, `metadata.hermes.related_skills` (`gates/skills_lint.py:80-81`). Common-stack skills must additionally declare `scope: default` or `scope: optIn` in their own frontmatter — no fallback (`gates/skills_lint.py:128-131,310`; ADR-0018). `scope: default` = ships unasked and into the plugin copy; `optIn` = skeletons stay in the catalog, not copied into `skills/` (`docs/authoring-a-feature.md:216-235`, `tooling/sync_plugin_skills.py:34-35`).

Files **excluded** from every delivered/scaffolded copy and from the plugin mirror: `tests/`, `test_*.py`, `*_test.py`, `evals/`, `__pycache__`, `*.pyc`, `.DS_Store` (`engine/badger_lib.py:685-691`).

Two mirrors:

1. **Plugin root `skills/<name>/`** — the *only* path Claude Code scans for plugin skills (ADR-0008, `tooling/sync_plugin_skills.py:1-13`). Ships common `scope: default` + `features/claude/skills/` stack-local (`tooling/sync_plugin_skills.py:34-35,82-90`). For `welcome-ai-badger`/`den-refresh`/`feed-badger` only, the SKILL.md body is replaced by a pointer and the full body saved as `SKILL.full.md` (`tooling/sync_plugin_skills.py:52,66-79,116-135`).
2. **Self-scaffold `.ai-badger/skills/<name>/`** — produced by re-running the scaffolder against this repo; also relinked into `~/.hermes/skills/<project>/` (`features/common/skills/welcome-ai-badger/scripts/skill_delivery.py:36,57-100,275-290`).

`index.json` gets one item per skill: `{name, path, scope}` derived from the directory + frontmatter (`tooling/index_build.py:55-66`; `schemas/index.schema.json` `$defs.featureList`).

### 1.2 Who regenerates the mirrors (the ritual)

```bash
# plugin mirror (Claude Code's copy)
python3 tooling/sync_plugin_skills.py            # writes skills/
# index.json
python3 tooling/index_build.py                   # writes index.json
# self-scaffold: .ai-badger/{skills,manifest.json,CLAUDE.md,...} — run LAST (reads index.json)
AI_BADGER_MCP_AVAILABILITY=all python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py \
    --config .ai-badger/config.json --target . --root .
# release stamp variant used by CONTRIBUTING step 6: append --no-install --skills ''
```

Cited: `CONTRIBUTING.md:176-190` ("Re-scaffold if you touched the scaffolder"), `CONTRIBUTING.md:216-227`, `RELEASING.md:27-38`, `gates/scaffold_freshness_guard.py:54-55,78` (`RESCAFFOLD_ENV`).

### 1.3 Gates that check skills (real check ids)

| Gate / check id | What it reads | Test that proves it |
|---|---|---|
| `gates/skills_lint.py` **rules 1–12** (lines 266,270,273,277,279,282,286,289,293,297-303,306,310): name grammar; name==dir; description present/≤1024/`Use when`; body ≤500 lines / ≤5000 chars-÷4; conditioned `references/` mentions; `## Gotchas`; parseable+complete frontmatter; no duplicate keys; common-stack `scope:` | every `features/*/skills/*/SKILL.md` | `tests/test_skills_lint.py`, `tests/test_skills_lint_gateways.py` |
| `gates/skills_lint.py` **rule 13** (lines 145-240): gateway `manifest.json` — kind, member dirs, non-orphan, purpose byte-equal to member description | `features/*/skills/*/manifest.json` | `tests/test_skills_lint_gateways.py` |
| `tooling/index_build.py --check` (lane `index`; `tooling/index_build.py:183-196`) + `schemas/index.schema.json` | `index.json` vs tree | `tests/test_index_build.py` |
| `tooling/validate.py --all` (`validate_all` at 816; reports "skills lint" 843, "feature json schema coverage" 837, "catalog stack membership" 836, "cross-stack references" 839) | schema coverage + `skills_lint` | `tests/test_validate.py`, `tests/test_catalog_claims_checkable.py` |
| `tooling/sync_plugin_skills.py --check` (lane `plugin-skills`) | `skills/` vs a fresh render incl. shape | `tests/test_sync_plugin_skills.py`, `tests/test_plugin_copy_points_at_the_tailored_one.py` |
| `gates/scaffold_freshness_guard.py` (lane `scaffold`; `SKILLS_MIRROR=".ai-badger/skills"` :55) — re-scaffolds a throwaway copy and diffs, stamp-churn exempt; fails on a manifest recording a proper subset (`expected_skill_names` oracle :211) | `.ai-badger/**` incl. skills mirror | `tests/test_scaffold_freshness_guard.py` |
| `tests/test_docs_match_the_catalog.py:123-186` — `docs/skills.md` must have an at-a-glance row per common+claude-stack skill, correct `Ships` cell, and **five derived numerals** (catalog total, common total, `default` count, `optIn` count, tree glob `features/*/skills/*/SKILL.md`, and "These N") | `docs/skills.md:1-40` | itself |
| `tests/test_plugin_manifest.py:37-50` — every `scope: default` common skill must exist at `skills/<name>/SKILL.md` | plugin mirror | itself |
| `tests/test_expected_skill_names.py:53-57` — derived delivered set == manifest rows (currently 46 = 42 default common + 4 stack-local; 3 excluded) | `.ai-badger/manifest.json` | itself |
| `tests/test_scaffold_no_test_leak.py` — `tests/`/`evals/` never reach a scaffold | delivery | itself |
| `gates/release_guard.py` — `features/` and `skills/` are SHIPPED_PATHS (`tooling/release_paths.py:12-22`), so a new skill forces a `VERSION` bump | git tag diff | `tests/test_release_guard.py` |
| `gates/tdd_guard.py` (lane `tdd`) — Python changed under `features/` implies a test change | `git merge-base` diff | `tests/test_tdd_guard.py` |

Note: `.ai-badger/manifest.json` is **generated** (never hand-added to); `features/common/skills.json`/`skills-source.json` are for **external marketplace** skills and are not where an internal catalog skill is registered (`docs/authoring-a-feature.md:112-153`).

---

## 2. Registering a new MCP server

### 2.1 Catalog directory — `features/common/mcp/task-graph/`

`index_build` treats **any subdir containing `meta.json`** as one server (`tooling/index_build.py:89-92`), so the dir is the registration. Contents, using `semantica` as the worked example (`features/common/mcp/semantica/`):

| File | Contract |
|---|---|
| `meta.json` | `schemas/mcp-server.schema.json`: required `name`; optional `package`, `description`, `homepage`, `prerequisite{summary required; check, install, local{summary,check,install,uv,command}, global{...}}`. `name` must match dir + stack declaration |
| `server.md` | prose injected verbatim into every agent file; **≤15 lines** (`tests/test_mcp_catalog_instructions.py:187`); `content` is read by `mcp_tools._server_instructions` |
| `tools.json` | `schemas/mcp-server-tools.schema.json`: `{server, tools:[{name, intent ≤200 chars, tags[]}]}`; tags must come from the closed vocabulary in `features/common/mcp-tags.json` (`tests/test_mcp_catalog_instructions.py:198-207`) |
| `scripts/` (optional) | precedent: `features/common/mcp/semantica/scripts/{check.py,install.py,semantica_mcp_wrapper.py}`, `features/common/mcp/code-review-graph/scripts/{check,install}.py`; tested centrally (`tests/test_semantica_mcp_scripts.py`, `tests/test_code_review_graph_mcp_scripts.py`) |
| `prerequisite.check` | surfaced as a scaffold note; **declared servers must carry a prerequisite or explicitly none** (`tests/test_mcp_prerequisites.py:63-80`) |

### 2.2 Declaration — `features/common/stack-mcp.json`

Add to `servers[]` (`features/common/stack-mcp.json:1-45`); fields from `schemas/stack-mcp.schema.json`: `name` (must name the catalog dir), `command` (required when `declare: true`), `declare` (default false = describe-only), `scope` (`project`|`user`), `env` (`${VAR}` refs, never secrets), `availability.command` (PATH gate), `agentOverrides.{claude,hermes,copilot,pi}` (`command`/`args`). Example shape in `docs/authoring-a-feature.md:168-183`. This file is **not indexed** ("Read at scaffold time and NOT indexed", schema description; `docs/authoring-a-feature.md:50-58`).

### 2.3 How scaffolded projects get it wired

Read at scaffold time by `McpTools` (`features/common/skills/welcome-ai-badger/scripts/mcp_tools.py:126 collect_catalog_mcp_servers`, `:294 declared_servers`, `:326 split_servers_by_scope`) and written by `Scaffolder.run` (`scaffold.py:724 generate_mcp_json`, `:729 generate_copilot_mcp_json`):

- Claude Code: `.mcp.json` + approvals/denials in `.claude/settings.json` (`features/claude/adjustments/adjust_mcp.py:1-62`).
- Copilot CLI: `.github/mcp.json` and `.mcp.json` (`mcp_tools.py:615`).
- Hermes: **proposes** a `mcp_servers:` YAML block, never writes user-global config (`features/hermes/adjustments/adjust_mcp.py`; ADR-0014 decision 6).
- pi: migration-only removal of legacy global entries; the pi fork reads project `.mcp.json` directly (ADR-0023; `features/pi/adjustments/adjust_mcp.py:1-16`).
- `config.mcp.decline` removes a server from both owned files.

`.mcp.json.example` (repo root, tracked: `git ls-files .mcp.json.example` → matched) is **this repo's own dev convenience** — `cp .mcp.json.example .mcp.json` (CONTRIBUTING.md:88-95) — containing only `code-review-graph` + `hermes`; it is **not** generated from `stack-mcp.json` and **no test or gate reads it** (repo-wide matches: only `CONTRIBUTING.md:88`, `.gitignore:36`, changelog entries). Updating it for a new local server is optional/manual.

`.ai-badger/mcp-tools.json` is not scaffold output either: it is seeded/updated by the `mcp-index` skill from `features/<stack>/mcp/<server>/tools.json` when a host listing carries no tool detail (`features/common/skills/mcp-index/scripts/mcp_index.py`; `tests/test_mcp_index_catalog_seed.py:1-20`).

### 2.4 Schemas/checks policing it

`tooling/validate.py --all` validates `features/*/stack-mcp.json` → `stack-mcp.schema.json`, `features/*/mcp/*/meta.json` → `mcp-server.schema.json`, `features/*/mcp/*/tools.json` → `mcp-server-tools.schema.json`, `features/*/mcp-tags.json` → `mcp-tags.schema.json` (`tooling/validate.py:42-61`); plus `tests/test_catalog_claims_checkable.py:183-210` (every JSON under `features/` schema'd or exempt by name). Cross-behavior: `tests/test_mcp_feature_type.py`, `tests/test_stack_mcp_servers.py`, `tests/test_mcp_declared_servers.py`, `tests/test_mcp_prerequisites.py`, `tests/test_mcp_catalog_instructions.py`, `tests/test_mcp_tools_notes.py` (unparseable declaration must note, never go silent), `tests/test_mcp_legacy_files_removed.py`. `index_build.py --check` covers the `index.json` item. New tags are added by PR to `features/common/mcp-tags.json` (ADR-0004:45). HYPOTHESIS: there is no generic gate that a *new* server has a per-server catalog test file (semantica has one by convention, `tests/test_mcp_semantica_catalog.py`); the generic gates above are what would actually fail.

---

## 3. The dependency contract

### 3.1 Where a new dependency must be declared

| Surface | Use | Enforcer |
|---|---|---|
| `engine/requirements.txt` | framework-owned import under `engine/`, `tooling/`, `features/`, `gates/`. Current: `jsonschema` (required), `pyyaml` (optional), `semantica` (optional wrapper) — `engine/requirements.txt:4-10` | `gates/deps_guard.py` — AST-walks those four roots (`CODE_ROOTS`:55), classifies every import stdlib/first-party/third-party, and fails any third-party not declared in `engine/requirements.txt` (`collect`; lane `deps`); distribution→module aliases when metadata is absent (`ALIASES`:63) |
| `features/common/dependencies.json` | consumer-project installs (venv/npm/system): e.g. `code-review-graph`, archify's Node — `features/common/dependencies.json:1-40`, schema `schemas/dependencies.schema.json` | `features/common/skills/welcome-ai-badger/scripts/dependency_check.py` (runs inside `Scaffolder._check_dependencies`, `scaffold.py:532-545,720`; reports before installing, `SECURITY.md:79`); `tests/test_dependency_check.py` |
| `engine/requirements-dev.txt` | contributor tools (pylint, pytest) — **under a SHIPPED_PATH** (`engine/`), so touching it forces a VERSION bump (comment in `requirements-mutation.txt:5-8`) | CI install loads it (`pylint.yml`); no dedicated gate |
| `requirements-mutation.txt` (repo root) | dev-only `mutmut`, deliberately outside SHIPPED_PATHS (`requirements-mutation.txt:1-18`) | none; by design |
| **Vendoring** | a module that must run inside a consumer project with no framework access: maintain in `engine/`, copy verbatim into each skill `scripts/` | `engine/badger_store.py:319-335` `vendored_copies_report()` globs `features/**/badger_store.py` + `skills/**/badger_store.py` and reports byte-differences; `tests/test_badger_store_vendored.py:30-45` runs it on the real tree. Whole third-party packet precedent: archify with `vendor.json` + `tooling/vendor_archify.py --check` (ADR-0030; `tests/test_archify_vendor.py`) |

Nuance the task should not get wrong: `deps_guard` only checks that `engine/requirements.txt` *declares* the import; it does **not** check that a scaffolded consumer can import it. Consumer reachability is discipline — stdlib-only, a `dependencies.json` entry, or vendoring (ADR-0024:15-25). HYPOTHESIS: no general gate enforces stdlib-only in skill scripts; I found only module-specific vendoring tests.

### 3.2 Dependent claims that must change if a third dependency lands

Source of truth is `.ai-badger/config.json` → `project.summary` (line 6), rendered by the scaffolder into **7 generated files**:

- `.ai-badger/CLAUDE.md:3`, `.ai-badger/HERMES.md:3`, `.ai-badger/copilot-instructions.md:3` (source copies)
- `CLAUDE.md:5`, `HERMES.md:5`, `.hermes.md:5`, `.github/copilot-instructions.md:5` (discovery copies)

The claim text ("Stdlib-only except two declared dependencies (engine/requirements.txt): jsonschema is required … pyyaml is optional …") appears verbatim in all eight (7 + config). `tests/test_dependency_honesty.py` pins the summary: it must name jsonschema as required and must not claim every import is guarded (`test_the_summary_names_jsonschema_as_required`, `OVERCLAIM`), and the rendered copies must match.

Other prose that becomes stale and is **not** machine-checked for this fact: `README.md:392-396`, `docs/getting-started.md:159` ("Two packages: jsonschema and pyyaml"), `docs/authoring-a-feature.md:26` (`# jsonschema`), `engine/requirements.txt:1-3`. `gates/docs_guard.py` checks links/backticked paths/changelog rows, not counts of dependencies.

---

## 4. Tests and the release ritual

### 4.1 Test organization

- All Python tests live in the top-level `tests/` dir: `pyproject.toml:82-85` (`testpaths=["tests"]`); never under `features/` — only `features/pi/tests/` exists in-tree (the TS suite for the pi adapter) and is not collected by pytest. Convention stated at `docs/scripts.md:129-136`.
- Fixtures: `tests/conftest.py` supplies `load_script(relpath)` (import a script by repo-relative path; the docstring warns renaming breaks mutmut), `root` (real repo root), `make_scaffolder` (tmp target + config factory from `tests/scaffold_helpers.py`). Session fixtures redirect `$HOME`, `CLAUDE_PROJECT_DIR`, cwd, and the debug sink so no test writes into a real checkout (`tests/conftest.py:1-160`).
- Fixture data: `tests/fixtures/{memory_context,test_ruleset_min}` only; most fixtures are built in `tmp_path`.
- Vendoring/duplication tests: `tests/test_badger_store_vendored.py` (byte-equality + glob inventory, with mutations proving the check can fail), `tests/test_archify_vendor.py` (vendor.json manifest).
- A `load_script`-style path hook plus `tests/test_every_check_can_fail.py` makes every gate's failure provocation a test; a gate reachable from no lane fails that meta-test.

### 4.2 Release ritual (files a feature release touches)

1. `VERSION` (currently `0.178.0`).
2. `docs/changelog/{version}-{slug}.md` — one file per release; classification + headings (`docs/changelog/README.md:3-16`).
3. `python3 tooling/changelog_index.py` — regenerates the table region of `docs/changelog/README.md` (only between the markers; `tooling/changelog_index.py:1-28`).
4. `python3 tooling/version_sync.py` — stamps `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `index.json` (delegates to `index_build`), and every other shipped JSON carrying top-level `frameworkVersion` (today `features/common/data/model-groups.json`) (`tooling/version_sync.py:1-24`).
5. Re-scaffold this repo against itself **last**, with `AI_BADGER_MCP_AVAILABILITY=all … --no-install --skills ''`, so `.ai-badger/manifest.json` and every `Scaffolded by ai-badger <v>` line are stamped with the new version (`CONTRIBUTING.md:216-227`; `RELEASING.md:27-38`).
6. `BREAKING_VERSIONS` only when a re-scaffold is *required* (`RELEASING.md:10-14`).
7. Checks: `version_sync.py --check`, `changelog_index.py --check`, `gates/release_guard.py`, `gates/docs_guard.py` (lane `docs`), `gates/scaffold_freshness_guard.py`; all wired in `.lefthook/pre-push/verify.sh:64,232-246` and CI (`.github/workflows/pylint.yml` reads `$LANES` from that same script).

---

## 5. Where each new artifact goes

| Artifact | Exact path | Gate / check that polices it |
|---|---|---|
| Skill source | `features/common/skills/task-decomposition/{SKILL.md,scripts/*,references/*}` | `skills_lint` rules 1–12 (`validate.py --all` reports "skills lint"); `index_build.py --check` |
| `scope:` declaration | inside that `SKILL.md` frontmatter (`default`/`optIn`) | `skills_lint` rule 12; `tests/test_skill_scope_declarations.py` |
| Plugin mirror | `skills/task-decomposition/**` (default scope only) | `sync_plugin_skills.py --check` (lane `plugin-skills`); `tests/test_plugin_manifest.py`; `tests/test_plugin_copy_points_at_the_tailored_one.py` |
| Self-scaffold mirror | `.ai-badger/skills/task-decomposition/**` + `.ai-badger/manifest.json` row | `scaffold_freshness_guard.py` (lane `scaffold`); `tests/test_expected_skill_names.py` |
| Index entry | `index.json → stacks.common.skills[]` `{name,path,scope}` | `index_build.py --check` (lane `index`) + `index.schema.json` |
| Docs row + counts | `docs/skills.md` table row and the 5 numerals in its opening paragraph | `tests/test_docs_match_the_catalog.py:123-186` |
| MCP descriptor | `features/common/mcp/task-graph/{meta.json,server.md,tools.json}` (+ `scripts/` if needed) | `validate.py --all` (3 MCP schemas); `tests/test_mcp_catalog_instructions.py` (server.md ≤15 lines, tags closed, intents non-empty); `tests/test_mcp_prerequisites.py` |
| MCP declaration | `features/common/stack-mcp.json` `servers[]` | `stack-mcp.schema.json` via `validate.py --all`; `tests/test_stack_mcp_servers.py`, `tests/test_mcp_declared_servers.py` |
| MCP index entry | `index.json → stacks.common.mcp[]` | `index_build.py --check` |
| New MCP tags (only if needed) | `features/common/mcp-tags.json` | `mcp-tags.schema.json`; `tests/test_mcp_catalog_instructions.py:198` |
| Consumer-project deps | `features/common/dependencies.json` | `dependency_check.py` (run by `scaffold.py:532,720`); `tests/test_dependency_check.py` |
| Framework deps | `engine/requirements.txt` | `gates/deps_guard.py` (lane `deps`) |
| Vendored module/packet | per-skill `scripts/<module>.py` or `<skill>/vendor.json` + `tooling/vendor_archify.py` | `tests/test_badger_store_vendored.py`; `tests/test_archify_vendor.py` (ADR-0024/ADR-0030) |
| New tests | `tests/test_<area>.py` (never beside the skill) | `pyproject.toml:82-85`; `gates/tdd_guard.py` (lane `tdd`) |
| New tooling/gate script | `tooling/*.py` or `gates/*.py` | `docs/scripts.md` row (`tests/test_docs_match_the_catalog.py` `TestScriptsDocCoversTheScripts`); `test_every_check_can_fail.py` (must have a failure provocation and a lane) |
| Docs/claims touch-up | `README.md:392-396`, `docs/getting-started.md:159`, `.ai-badger/config.json:6` then re-scaffold | `gates/docs_guard.py` (links/paths/table); `tests/test_dependency_honesty.py` (summary claims) |
| Release | `VERSION`, `docs/changelog/{v}-{slug}.md`, `docs/changelog/README.md` (generated), `plugin.json`, `marketplace.json`, `index.json`, `model-groups.json`, re-scaffold | `release_guard.py`, `version_sync.py --check`, `changelog_index.py --check`, `scaffold_freshness_guard.py` |
| Dev-only local MCP entry | `.mcp.json.example` (optional) | **no gate** — hand-maintained convenience for this checkout |

**Bottom line:** a new skill needs 5 coordinated surfaces (`features/common/skills/<name>`, `skills/`, `.ai-badger/skills/`, `index.json`, `docs/skills.md`) plus a VERSION+changelog release; a new MCP server needs 4 (`features/common/mcp/<name>`, `stack-mcp.json`, `index.json`, optional `mcp-tags.json`) and, if its code runs in consumers, a dependency declaration that is *not* `engine/requirements.txt` alone.