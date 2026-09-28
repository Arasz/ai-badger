## S8 complete — commit `f6eb991e`, branch `lane/S8-catalog`, not pushed

### AC-by-AC evidence

**AC1 — both prerequisite fixtures green with exact expected strings + RED witnesses.**

Two PATH-controlled fixtures in `tests/test_task_graph_mcp_catalog.py` (patch only `mcp_tools.shutil.which` via a proxy + empty `USER_TOOL_DIRS` + delete `AI_BADGER_MCP_AVAILABILITY`, so `~/.local/bin/uv` on the host cannot leak in):

- `uv_on_path` → `test_with_uv_the_claude_declaration_is_written`: `.mcp.json` entry `== {"command": "uv", "args": ["run","--script","${CLAUDE_PROJECT_DIR}/.ai-badger/skills/task-decomposition/scripts/task_graph_server.py"], "tools": ["*"]}`.
- `uv_on_path` → `test_with_uv_the_copilot_declaration_is_written`: same entry in **both** `.mcp.json` and `.github/mcp.json` with the plain relative script path.
- `uv_missing` → `test_without_uv_the_declaration_is_still_written_and_the_note_is_exact`: entry still written **and** the probe is proven in play (`"'uv' was not found"` present), **and** the prerequisite note list is exactly:
  `prerequisite — task-graph needs uv on PATH; the server and its pydantic env are fetched on first launch (PEP 723); check: uv --version; install: curl -LsSf https://astral.sh/uv/install.sh | sh; local: curl -LsSf https://astral.sh/uv/install.sh | sh; global: curl -LsSf https://astral.sh/uv/install.sh | sh. ai-badger declares the server, it does not install it.`

RED witnesses (verbatim, `/tmp/s8-red.txt` — initial run before any deliverable existed, all 10 failed):

```
E       KeyError: 'task-graph'        # test_with_uv_the_claude_declaration_is_written
E       KeyError: 'task-graph'        # test_with_uv_the_copilot_declaration_is_written
E       KeyError: 'task-graph'        # test_without_uv_..._note_is_exact
E       AssertionError: assert False = is_file()   # test_the_catalog_directory_carries_the_packet_files
E       AssertionError: assert {'name': 'task-graph', ...} in [...5 entries...]  # index
```

One test (`the_curated_tools...`) failed RED with a missing-fixture `NameError`, so I added mutation witnesses for every check that only ever passed — each mutated, seen red, restored, then re-run green:

```
A availability gate added      -> test_without_uv... FAILED
B prerequisite summary mutated -> assert prerequisite_notes == [EXPECTED_NOTE] FAILED
C tag "banana" added           -> test_the_curated_tools... FAILED (plan_get)
D server.md over 15 lines      -> test_server_md_stays_within_the_line_budget FAILED
restored                       -> 10 passed
```

**AC2 — `validate.py --all` + `index_build.py --check` green:** chained gate `chain_exit=0`; `ok features/common/mcp/task-graph/{meta,tools}.json`, `ok features/common/stack-mcp.json`, `ok index.json`, `index.json up to date`.

**AC3 — catalog rules green:** packet tests + repo-wide catalog test, `server.md` = **14 lines** (≤15), 12 tools, longest intent **145** chars, tags == frozen mapping and ⊆ closed vocabulary, `meta.prerequisite` exact (summary/check/install/local/global), `name` == dir == `tools.server` == declaration name. Extra guard run: `tests/test_agent_doc_budget.py` **4 passed** (new prose fits the shipped default).

Exact chained gate: **`103 passed`** (my file + catalog instructions + prerequisites + stack servers + declared servers) `&& validate --all && index_build --check` → exit 0.

### Rejected alternatives

- **`availability: {command: "uv"}`** — DR3 forbids it; witness A proves it silently drops the entry (fixture b red), which is the failure being designed against.
- **One scaffold with `agents: ["claude","copilot"]` asserting both files** — #193 dedup sees the Claude override as a different rendering and deliberately declares task-graph only in `.mcp.json`, noting it; the AC's two exact strings therefore need one single-reader scaffold per destination.
- **`package` in meta.json** — not a distribution; test pins it absent.
- **Deriving `EXPECTED_NOTE` from meta.json** — a meta mutation would move both sides and the check could never fail; the note is hard-coded and pinned byte-exact instead.
- **New tags** — every proposed tag resolves in `features/common/mcp-tags.json`; it is untouched.

### Files changed (6; 309 insertions)

`features/common/mcp/task-graph/{meta.json,server.md,tools.json}` (new), `features/common/stack-mcp.json` (+15), `index.json` (regenerated, +4), `tests/test_task_graph_mcp_catalog.py` (new). Nothing else touched.

### Deviations / notes for the orchestrator

1. **Test filename**: used `tests/test_task_graph_mcp_catalog.py` per the operator brief; plan §S8 says `tests/test_mcp_task_graph_catalog.py`.
2. **Commit ran with `SKIP=scaffold-freshness-guard`**: the guard fails on exactly the 10 orchestrator-owned surfaces (`.ai-badger/**` + agent discovery files) my catalog change stales; verified by running the guard at base `5537dbae` in a scratch worktree → **PASS**, so the findings are mine-by-design and belong to the wave-join re-scaffold (plan §4). All other pre-commit hooks passed: version-sync, index-build, changelog-index, plugin-skills-sync, docs-guard, deps-guard, shipped-paths-guard, rules-index-regen, pylint.
3. Conservative reading used where brief and P2 draft differed: `local`/`global` carry `uv --version` checks plus the install one-liner (so the note surfaces them), and `server.md` states the CLI twin path exactly as drafted. Sub-agents: 0.