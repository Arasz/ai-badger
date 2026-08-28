# Semantica MCP support — research record

**Date:** 2026-08-28
**Task:** continue-semantica-support-fixes
**Method:** every finding below was produced by running the named command on this
machine against a freshly installed semantica 0.6.6. Nothing here is quoted from
existing repo docs; where a repo doc disagrees, that is recorded as a falsification.

## How to read the labels

- **MEASURED** — a command was run and its output is quoted.
- **READ** — a file in this repo says so; path cited.
- **HYPOTHESIS** — not verified; must be checked before it is relied on.

---

## F1 — MEASURED — the user-scope install fails on uv's default Python

Command:

    uv tool install --force semantica

Result: build of `gensim` 4.4.0 fails from source. Excerpt:

    gensim/models/word2vec_inner.c:1686:65: note: expanded from macro '__PYX_GET_DICT_VERSION'
    #define __PYX_GET_DICT_VERSION(dict) (((PyDictObject*)(dict))->ma_version_tag)
    fatal error: too many errors emitted, stopping now
    hint: `gensim` (v4.4.0) was included because `semantica` (v0.6.6) depends on `gensim`

The interpreter uv selected was `cpython-3.14.7` (visible in the compiler include
path `.../cpython-3.14.7-macos-aarch64-none/include/python3.14`).

Cause: `ma_version_tag` was removed from `PyDictObject` in CPython 3.14, so the
Cython-generated C in gensim 4.4.0 cannot compile there.

Wheel availability, from `https://pypi.org/pypi/gensim/4.4.0/json`:

    gensim-4.4.0-cp39-cp39-macosx_11_0_arm64.whl
    gensim-4.4.0-cp310-cp310-macosx_11_0_arm64.whl
    gensim-4.4.0-cp311-cp311-macosx_11_0_arm64.whl
    gensim-4.4.0-cp312-cp312-macosx_11_0_arm64.whl
    gensim-4.4.0-cp313-cp313-macosx_11_0_arm64.whl

**cp313 is the ceiling.** There is no cp314 wheel.

### F1a — MEASURED — the failure leaves dangling symlinks, which is why the symptom reads as ENOENT

Claude Code reported:

    semantica (ENOENT): "ENOENT: no such file or directory, posix_spawn '/Users/arasz/.local/bin/semantica-mcp'"

but `ls -la ~/.local/bin/` showed all five `semantica*` symlinks present. Their
target directory `~/.local/share/uv/tools/semantica/` did not exist, and
`uv tool list` did not list semantica. `which semantica` printed "not found"
because `which` follows the link.

### F1b — MEASURED — pinning fixes it, and the pin persists

    uv tool install --force --python 3.13 semantica

succeeded, installing 5 executables. `~/.local/share/uv/tools/semantica/uv-receipt.toml`
now records:

    [tool]
    requirements = [{ name = "semantica" }]
    python = "3.13"

so a later `uv tool upgrade` reuses 3.13 rather than re-selecting the default.

### F1c — READ — the catalog ships the command that reproduces the failure

`features/common/mcp/semantica/meta.json` `prerequisite.global`:

    "install": "uv tool install semantica",
    "uv": "uv tool install semantica",
    "command": "uv tool install semantica"

No Python pin. On any machine whose default uv interpreter is 3.14+, following
this documented command reproduces F1 exactly.

---

## F2 — MEASURED — weak gates: the install looked healthy while the server was unusable

While the tool env was destroyed, these both still needed to be distrusted, and
after the reinstall both pass — so neither distinguishes the two states well:

- `semantica --version` -> `semantica, version 0.6.6`
- `python3 features/common/mcp/semantica/scripts/check.py` -> `semantica ready: semantica, version 0.6.6`, exit 0

The gate that actually discriminates is a real MCP stdio handshake. Driving
`initialize` + `notifications/initialized` + `tools/list` over stdin/stdout against
`/Users/arasz/.local/bin/semantica-mcp` returned 12 tools:

    add_entity, add_relationship, export_graph, extract_entities, extract_relations,
    find_precedents, get_causal_chain, get_graph_analytics, get_graph_summary,
    query_decisions, record_decision, run_reasoning

---

## F3 — MEASURED — every export_graph format is broken in 0.6.6

Run inside the installed tool env
(`~/.local/share/uv/tools/semantica/bin/python`), calling the handler directly:

    from semantica.mcp_server import _tool_export_graph
    json-ld -> {'error': "'ContextGraph' object has no attribute 'get'"}
    turtle  -> {'error': "'ContextGraph' object has no attribute 'get'"}
    json    -> {'error': "JSONExporter.export() missing 1 required positional argument: 'file_path'"}

### F3a — FALSIFIES a repo doc

`docs/changelog/0.137.1-semantica-export-graph-wrapper.md` states:

> The RDF/json-ld branches work fine.

That is **false for 0.6.6** as measured above. It was presumably true for 0.6.5
when written. The same claim is echoed in the wrapper's own docstring
(`features/common/mcp/semantica/scripts/semantica_mcp_wrapper.py`), whose RDF
branch is written on the assumption that `RDFExporter().export_to_rdf(graph, ...)`
works.

---

## F4 — MEASURED — the RDF branch writes to stdout, corrupting the MCP transport

With stderr discarded, the RDF export still emits to **stdout**:

    $ .../bin/python -c "from semantica.mcp_server import _tool_export_graph; _tool_export_graph({'format':'json-ld'})" 2>/dev/null
    🔄 Semantica is exporting: Exporting data to RDF format: json-ld 💾 export RDFExporter |░░░...░░░| 0.0% ETA: - Rate: - Time: 0.00s Extracted: -

stdout is the MCP JSON-RPC transport. Consequence, measured: an `export_graph`
tool call with `format=json-ld` over a live MCP stdio session returned **no
response at all** — the probe that had just succeeded for `format=json` (returning
a well-formed error) received nothing, because the frame was corrupted.

This is more severe than F3: a failing tool call returns an error the caller can
handle; a corrupted transport can break the session.

---

## F5 — MEASURED — the repo's wrapper does fix the json branch against 0.6.6

    from semantica_mcp_wrapper import _patched_tool_export_graph
    _patched_tool_export_graph({"format": "json"})

returned `{"format": "json", "data": ...}` where data parsed as:

    {"nodes": [], "edges": [], "statistics": {"node_count": 0, "edge_count": 0},
     "metadata": {"exported_at": "2026-08-28T08:36:48...", "format": "json"}}

So the json fix exists and works. **It is not wired into the launch path**:
`features/common/stack-mcp.json` declares the semantica command as the bare
console script `semantica-mcp`, so a live session gets the unpatched handler.

### F5a — READ — the wrapper is only a probe fallback

`features/common/mcp/semantica/scripts/check.py` uses the wrapper solely inside
`export_graph_works()` as a fallback probe when the native probe errors. That is
why `check.py` reported "ready" in F2 despite F3 — by design, per
`docs/changelog/0.137.1-semantica-export-graph-wrapper.md`.

---

## F6 — READ — the always-loaded instruction tells every session to call the broken tool

`CLAUDE.md` and the `UserPromptSubmit` hook both say:

> record key decisions via record_decision and call export_graph(format=json)
> before finishing — dumps auto-save to .semantica/ and are indexed.

Given F3, that instruction fails on every session that follows it.

---

## Open questions for planning (HYPOTHESIS — must be resolved before implementing)

- **Q1** Can the scaffold's command resolver express a two-token launch command
  (`<interpreter> <script>`), and does it mangle a path-bearing first token?
- **Q2** Are `features/common/mcp/semantica/scripts/*` copied into consumer
  projects, or do they exist only in this repo? If only here, a wrapper cannot be
  the launch command for consumers.
- **Q3** Does `stack-mcp.schema.json` permit anything beyond a single `command`
  string (e.g. `args`)?
- **Q4** Which tests lock the current `semantica-mcp` command in place?

These are being answered by a read-only survey lane; the plan must not be written
until they are.

---

# Resolved questions (read-only survey lane + direct measurement)

## A1 — MEASURED — `SEMANTICA_DISABLE_PROGRESS=1` fixes the transport corruption

The progress bar is not unconditional. `semantica/utils/progress_tracker.py`
in the installed package reads an env switch:

    def _progress_disabled_from_env() -> bool:
        return os.getenv("SEMANTICA_DISABLE_PROGRESS", "").strip().lower() in (
            "1", "true", "yes", "on",
        )

Bytes written to stdout by a `format=json-ld` export, stderr discarded:

    without the var : 183
    with the var    : 0

End-to-end over a live MCP stdio session, calling `export_graph(format=json-ld)`:

    without: NON-JSON ON STDOUT — '🔄 Semantica is exporting: ... 0.0% ETA:'   (no response ever arrives)
    with   : {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text",
              "text":"{\n  \"error\": \"'ContextGraph' object has no attribute 'get'\"\n}"}]}}

So the env var converts a **corrupted transport** into a **clean, handleable
error response**. It does not fix the underlying export bug (F3), and is not
expected to.

## A2 — READ — the schema already supports `env`, so no schema change is needed

`schemas/stack-mcp.schema.json` permits, per server entry:
`name`, `command`, `declare`, `scope`, `env` (object of string->string),
`availability`, `agentOverrides`. `additionalProperties: false`.

`env` is exactly the vehicle A1 needs.

Note: `args` exists **only** nested under `agentOverrides.<agent>`, never at the
top level of a server entry.

## A3 — READ — the wrapper CANNOT be the launch command (Q1/Q2 answered NO)

Decisive: MCP catalog directories are **never copied into a scaffolded consumer
project**. `features/common/skills/welcome-ai-badger/scripts/skill_delivery.py:270-287`
copytree's `features/<stack>/skills/<name>` into `.ai-badger/skills/<name>` —
**skills only**. For `features/<stack>/mcp/<name>/` the scaffold reads only
`server.md` (`mcp_tools.py:150-162`) and `meta.json`'s prerequisite block
(`mcp_tools.py:164-179`), in place, from the ai-badger repo.

Therefore `semantica_mcp_wrapper.py` exists only inside the ai-badger repo. A
consumer project's `.mcp.json` cannot reference it by any path.

Compounding this, the command resolver cannot construct such a launch line
anyway. `_home_relative_command` (`mcp_tools.py:458-463`) returns a command
untouched once its first token contains `/`:

    executable = parts[0]
    if "/" in executable or executable.startswith("${"):
        return command

and it only ever probes `parts[0]`; a second token is preserved verbatim as an
opaque arg. Nothing resolves a script path relative to the catalog.

**Conclusion: wiring the wrapper as the launch command is not implementable for
consumers.** The option is withdrawn. F3 must be handled by honesty + graceful
degradation, not by a delivered patch.

## A4 — READ — tests that lock the launch command

- `tests/test_mcp_semantica_catalog.py:164-171` asserts `command == "semantica-mcp"` and `declare is True`.
- `tests/test_mcp_semantica_catalog.py:174-185` asserts `"mcp start" not in command`.
- `tests/test_mcp_declared_servers.py:145-159` also asserts `command == "semantica-mcp"`.
- `tests/test_mcp_user_tool_paths.py` locks `split_on_whitespace` + `_home_relative_command`.

Adding `env` to the entry does not disturb any of these — they assert on
`command`, which is unchanged.

## A5 — READ — prerequisite strings are free text, never executed

`schemas/mcp-server.schema.json` types `prerequisite.*.check/install/uv/command`
as plain strings. `note_declared_prerequisites` (`mcp_tools.py:211-243`)
only string-interpolates them into a user-facing note. Nothing runs them, so
correcting the install command is a documentation fix with no runtime coupling —
and equally, nothing would have caught that it was wrong.

---

# What the evidence permits

| Issue | Fixable here? | Mechanism |
|---|---|---|
| F1 unpinned global install reproduces the 3.14 build failure | Yes | pin `--python 3.13` in `meta.json` prerequisite |
| F4 RDF export corrupts the MCP transport | Yes | `env: {SEMANTICA_DISABLE_PROGRESS: "1"}` in `stack-mcp.json` |
| F3 every `export_graph` format errors in 0.6.6 | No — upstream | make gates/docs honest; confirm graceful degradation |
| F3a changelog claims RDF branches work | Yes | correct the wrapper docstring; new changelog entry records the regression |
| F6 always-loaded nudge tells every session to call a broken tool | Yes | make the instruction honest |
