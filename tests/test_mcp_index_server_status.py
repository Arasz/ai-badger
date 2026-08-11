"""A server with no visible tools is recorded, not dropped (ADR-0014 decision 7).

`enabled: false` and enabled-but-exposing-nothing have opposite remedies. #145 dropped both at
write time, so both looked identical — absent. Each source now carries the status the host's
listing actually supports.
"""

from __future__ import annotations

import json
from pathlib import Path
from conftest import _test_write

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"
LISTINGS = "features/common/skills/mcp-index/scripts/host_listings.py"

TEXT_LISTING = """\
  MCP Servers:

  Name             Transport                      Tools        Status
  ──────────────── ────────────────────────────── ──────────── ──────────
  rider            http://127.0.0.1:64342/st...   all          ✓ enabled
  llmstudio        http://127.0.0.1:1235          all          ✗ disabled
"""

# Captured verbatim from `claude mcp list` (see tests/test_mcp_index_host_listings.py).
CLAUDE_LISTING = """\
Checking MCP server health…

rider: http://127.0.0.1:64482/stream (HTTP) - ✔ Connected
claude.ai Microsoft 365: https://microsoft365.mcp.claude.com/mcp - ! Needs authentication
plugin:github:github: https://api.githubcopilot.com/mcp/ (HTTP) - ✘ Failed to connect — HTTP 400
"""


def _read_index(project: Path) -> dict:
    return json.loads((project / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))


def _write_index(project: Path, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    _test_write(aib / "mcp-tools.json", json.dumps(data, indent=2), encoding="utf-8")


def _source(index: dict, name: str) -> dict:
    return next(s for s in index["sources"] if s["name"] == name)


def _existing_index() -> dict:
    return {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{
            "name": "rider",
            "tools": {"build_solution": {"tags": ["build"], "intent": "Compile the solution"}},
        }],
    }


# ── init ─────────────────────────────────────────────────────────────────────

def test_init_records_ok_for_a_server_that_reports_tools(tmp_path, load_script):
    """The unremarkable case still gets a status, so absence of one is never the signal."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", json.dumps({"servers": [
        {"name": "rider", "enabled": True,
         "tools": [{"name": "build_solution", "description": "Compile the solution"}]},
    ]})]) == 0

    assert _source(_read_index(tmp_path), "rider")["status"] == "ok"


def test_init_keeps_a_zero_tool_server_and_calls_it_empty(tmp_path, load_script):
    """The server is enabled and was asked; it answered with nothing. That is not 'gone'."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", json.dumps({"servers": [
        {"name": "rider", "enabled": True,
         "tools": [{"name": "build_solution", "description": "Compile the solution"}]},
        {"name": "dotnet-sdk", "enabled": True, "tools": []},
    ]})]) == 0

    empty = _source(_read_index(tmp_path), "dotnet-sdk")
    assert empty["status"] == "empty"
    assert empty["tools"] == {}


def test_init_records_disabled_when_the_host_says_the_server_is_off(tmp_path, load_script):
    """`enabled: false` has its own remedy — switch it on — and must not read as 'empty'."""
    mod = load_script(SCRIPT)
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", json.dumps({"servers": [
        {"name": "rider", "enabled": True,
         "tools": [{"name": "build_solution", "description": "Compile the solution"}]},
        {"name": "llmstudio", "enabled": False, "tools": []},
    ]})]) == 0

    assert _source(_read_index(tmp_path), "llmstudio")["status"] == "disabled"


# ── the text-table fallback knows the servers but not their tools ────────────

def test_init_over_a_text_listing_records_unknown_not_empty(tmp_path, load_script, monkeypatch):
    """Never asked is not the same as asked and got nothing."""
    mod = load_script(SCRIPT)
    listings = load_script(LISTINGS)
    monkeypatch.setattr(mod, "_fetch_mcp_tools",
                        lambda from_json=None, host=None:
                        listings.parse_hermes_text_listing(TEXT_LISTING))

    assert mod.main(["init", "--target", str(tmp_path)]) == 0

    index = _read_index(tmp_path)
    assert _source(index, "rider")["status"] == "unknown"
    assert _source(index, "llmstudio")["status"] == "disabled"


def test_update_over_a_text_listing_does_not_mark_every_tool_removed(
        tmp_path, load_script, monkeypatch):
    """A listing with no tool detail must not wipe the curation of a whole index."""
    _write_index(tmp_path, _existing_index())
    mod = load_script(SCRIPT)
    listings = load_script(LISTINGS)
    monkeypatch.setattr(mod, "_fetch_mcp_tools",
                        lambda from_json=None, host=None:
                        listings.parse_hermes_text_listing(TEXT_LISTING))

    assert mod.main(["update", "--target", str(tmp_path)]) == 0

    rider = _source(_read_index(tmp_path), "rider")
    assert rider["status"] == "unknown"
    assert "status" not in rider["tools"]["build_solution"]


# ── `claude mcp list` says more than "no tools": it says why ─────────────────

def test_a_server_needing_authentication_is_not_merely_unknown(tmp_path, load_script, monkeypatch):
    """Log in is a different remedy from "the listing carried no tool detail" (issue #188)."""
    mod = load_script(SCRIPT)
    listings = load_script(LISTINGS)
    monkeypatch.setattr(mod, "_fetch_mcp_tools",
                        lambda from_json=None, host=None:
                        listings.parse_claude_listing(CLAUDE_LISTING))

    assert mod.main(["init", "--target", str(tmp_path)]) == 0

    index = _read_index(tmp_path)
    assert _source(index, "claude.ai Microsoft 365")["status"] == "unauthenticated"
    assert _source(index, "plugin:github:github")["status"] == "unreachable"
    assert _source(index, "rider")["status"] == "unknown"


def test_the_status_vocabulary_maps_only_phrases_this_release_has_seen(load_script):
    """An unrecognised phrase degrades to `unknown` rather than inventing a distinction."""
    mod = load_script("features/common/skills/mcp-index/scripts/tool_descriptions.py")

    def listed(phrase):
        # The shape parse_claude_listing produces: a phrase, and never any tool detail.
        return {"name": "x", "tools": [], "tools_known": False, "host_status": phrase}

    assert mod.server_status(listed("Connected")) == "unknown"
    assert mod.server_status(listed("Needs authentication")) == "unauthenticated"
    assert mod.server_status(listed("Failed to connect")) == "unreachable"
    assert mod.server_status(listed("Pending approval")) == "pending_approval"
    assert mod.server_status(listed("Reticulating splines")) == "unknown"


def test_a_tool_less_listing_leaves_a_server_it_never_names_alone(
        tmp_path, load_script, monkeypatch, capsys):
    """Switching host CLI must not read as "every hermes server was removed" (issue #188)."""
    data = _existing_index()
    data["sources"][0]["status"] = "ok"
    _write_index(tmp_path, data)
    mod = load_script(SCRIPT)
    listings = load_script(LISTINGS)
    monkeypatch.setattr(mod, "_fetch_mcp_tools",
                        lambda from_json=None, host=None:
                        listings.parse_claude_listing(
                            "plugin:github:github: https://x/mcp (HTTP) - ✔ Connected\n"))

    assert mod.main(["update", "--target", str(tmp_path)]) == 0

    rider = _source(_read_index(tmp_path), "rider")
    assert rider["status"] == "ok"
    assert "status" not in rider["tools"]["build_solution"]
    assert "left untouched" in capsys.readouterr().out


# ── update ───────────────────────────────────────────────────────────────────

def test_update_calls_a_server_the_host_no_longer_lists_absent(tmp_path, load_script):
    """Its tools are marked removed; a stale `ok` beside them would contradict that."""
    _write_index(tmp_path, _existing_index())
    mod = load_script(SCRIPT)

    assert mod.main(["update", "--target", str(tmp_path), "--from-json", json.dumps({"servers": [
        {"name": "playwright", "enabled": True,
         "tools": [{"name": "browser_navigate", "description": "Navigate to a URL"}]},
    ]})]) == 0

    index = _read_index(tmp_path)
    assert _source(index, "rider")["status"] == "absent"
    assert _source(index, "rider")["tools"]["build_solution"]["status"] == "removed"
    assert _source(index, "playwright")["status"] == "ok"


def test_update_refreshes_the_status_of_a_server_that_went_quiet(tmp_path, load_script):
    """The status is a fact about the last listing, so every update restates it."""
    data = _existing_index()
    data["sources"][0]["status"] = "ok"
    _write_index(tmp_path, data)
    mod = load_script(SCRIPT)

    assert mod.main(["update", "--target", str(tmp_path), "--from-json", json.dumps({"servers": [
        {"name": "rider", "enabled": False, "tools": []},
    ]})]) == 0

    assert _source(_read_index(tmp_path), "rider")["status"] == "disabled"


# ── the schema and the reporting ─────────────────────────────────────────────

def test_schema_accepts_a_source_with_no_tools(root):
    """schemas/mcp-tools.schema.json is what made dropping them look mandatory."""
    import badger_lib as bl  # pylint: disable=import-outside-toplevel

    schema = json.loads((root / "schemas" / "mcp-tools.schema.json").read_text(encoding="utf-8"))
    doc = {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [{"name": "llmstudio", "status": "disabled", "tools": {}}],
    }
    assert bl.validate(doc, schema) == []


def test_schema_accepts_every_status_the_script_can_produce(root, load_script):
    """The enum and the vocabulary are two writers of one decision; drift is silent."""
    import badger_lib as bl  # pylint: disable=import-outside-toplevel

    schema = json.loads((root / "schemas" / "mcp-tools.schema.json").read_text(encoding="utf-8"))
    td = load_script("features/common/skills/mcp-index/scripts/tool_descriptions.py")
    allowed = set(schema["$defs"]["mcpSource"]["properties"]["status"]["enum"])

    assert td.ALL_STATUSES <= allowed
    assert {"unreachable", "unauthenticated", "pending_approval"} <= td.ALL_STATUSES


def test_validate_names_every_server_that_reported_no_tools(tmp_path, load_script, capsys):
    """The remedy differs per status, so the status is what gets printed."""
    _write_index(tmp_path, {
        "version": "0.1.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sources": [
            {"name": "rider", "status": "ok",
             "tools": {"build_solution": {"tags": ["build"], "intent": "Compile the solution"}}},
            {"name": "llmstudio", "status": "disabled", "tools": {}},
            {"name": "dotnet-sdk", "status": "empty", "tools": {}},
        ],
    })
    mod = load_script(SCRIPT)

    assert mod.main(["validate", "--target", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "llmstudio (disabled)" in out
    assert "dotnet-sdk (empty)" in out
