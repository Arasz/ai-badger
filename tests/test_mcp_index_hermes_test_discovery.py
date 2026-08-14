"""`hermes mcp test <server>` restores the tool discovery `hermes mcp list --json` took away.

Issue #188 removed the only listing that carried tool names, and #384's candidate list named
`hermes mcp test` as a possible replacement. Measured 2026-08: it does enumerate tools, one
server per invocation, and it **exits 0 whether it succeeded or not** — so the output is the only
signal, and a parser that trusts the exit code would read "server not found" as "server has no
tools" and mark a whole source empty.

Discovery is per-server and costs a subprocess each, so it is opt-in (`--discover`).
"""

from __future__ import annotations

import json

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"
MODULE = "features/common/skills/mcp-index/scripts/host_listings.py"

# Verbatim shapes, measured from the installed hermes.
CONNECTED = """  Testing 'semantica'...
  Transport: stdio → /Users/x/.local/share/uv/tools/semantica/bin/python
  Auth: none
  ✓ Connected (626ms)
  ✓ Tools discovered: 2

    extract_entities                     Extract named entities (people, places, organisation...
    record_decision                      Record a decision into the knowledge graph with prove...
"""

NOT_FOUND = """  ✗ Server 'plugin:github:github' not found in config.
  Available: dotnet-sdk, glider, code-review-graph, ai-raccoon, rider, semantica
"""


def _load(load_script, path):
    return load_script(path)


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parses_the_tool_names_and_descriptions(load_script):
    hl = _load(load_script, MODULE)
    tools = hl.parse_hermes_test_tools(CONNECTED)

    assert [t["name"] for t in tools] == ["extract_entities", "record_decision"]
    assert tools[0]["description"].startswith("Extract named entities")


def test_a_server_it_could_not_test_yields_no_answer_not_an_empty_list(load_script):
    """The bug this guards: exit 0 + no tool block must not read as "exposes nothing"."""
    hl = _load(load_script, MODULE)

    assert hl.parse_hermes_test_tools(NOT_FOUND) is None


def test_a_run_that_printed_nothing_yields_no_answer(load_script):
    hl = _load(load_script, MODULE)

    assert hl.parse_hermes_test_tools("") is None


# ── enrichment ───────────────────────────────────────────────────────────────

def _runner(answers):
    """A fake `run_cli` keyed by the server name in argv, recording what was asked."""
    asked = []

    def run(argv):
        asked.append(tuple(argv))
        return 0, answers.get(argv[-1], NOT_FOUND), ""

    run.asked = asked
    return run


def test_enrichment_fills_a_toolless_server_and_marks_it_known(load_script):
    hl = _load(load_script, MODULE)
    servers = [{"name": "semantica", "tools": [], "tools_known": False}]

    hl.enrich_with_hermes_test(servers, run=_runner({"semantica": CONNECTED}))

    assert servers[0]["tools_known"] is True
    assert [t["name"] for t in servers[0]["tools"]] == ["extract_entities", "record_decision"]


def test_enrichment_leaves_a_server_it_could_not_test_untouched(load_script):
    """Still `tools_known` False, so update keeps treating absence as no evidence."""
    hl = _load(load_script, MODULE)
    servers = [{"name": "plugin:github:github", "tools": [], "tools_known": False}]

    hl.enrich_with_hermes_test(servers, run=_runner({}))

    assert servers[0]["tools_known"] is False
    assert servers[0]["tools"] == []


def test_enrichment_does_not_re_test_a_server_that_already_carries_tools(load_script):
    """A listing that already enumerated tools is authoritative — and a subprocess is not free."""
    hl = _load(load_script, MODULE)
    servers = [{"name": "semantica", "tools": [{"name": "a", "description": ""}]}]
    run = _runner({"semantica": CONNECTED})

    hl.enrich_with_hermes_test(servers, run=run)

    assert run.asked == []
    assert [t["name"] for t in servers[0]["tools"]] == ["a"]


def test_enrichment_reports_which_servers_it_could_not_test(load_script):
    hl = _load(load_script, MODULE)
    servers = [{"name": "semantica", "tools": [], "tools_known": False},
               {"name": "rider", "tools": [], "tools_known": False}]

    notes = hl.enrich_with_hermes_test(servers, run=_runner({"semantica": CONNECTED}))

    assert any("rider" in note for note in notes)
    assert not any("semantica" in note for note in notes)


# ── wiring ───────────────────────────────────────────────────────────────────

def _names_only(*names):
    return json.dumps({"servers": [
        {"name": n, "enabled": True, "tools": [], "tools_known": False} for n in names
    ]})


def test_discover_is_off_by_default(tmp_path, load_script, monkeypatch):
    """A plain init must not fire one subprocess per server."""
    mod = load_script(SCRIPT)
    called = []
    monkeypatch.setattr(mod.hl, "enrich_with_hermes_test",
                        lambda servers, run=None: called.append(servers) or [])

    assert mod.main(["init", "--target", str(tmp_path),
                     "--from-json", _names_only("semantica")]) == 0
    assert called == []


def test_discover_flag_enriches_before_indexing(tmp_path, load_script, monkeypatch):
    mod = load_script(SCRIPT)

    def fake(servers, run=None):
        for server in servers:
            server["tools"] = [{"name": "record_decision", "description": "Record it."}]
            server["tools_known"] = True
        return []

    monkeypatch.setattr(mod.hl, "enrich_with_hermes_test", fake)
    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("semantica")]) == 0

    index = json.loads((tmp_path / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))
    tools = next(s for s in index["sources"] if s["name"] == "semantica")["tools"]
    assert "record_decision" in tools
