"""A server with no visible tools is recorded, not dropped (ADR-0014 decision 7).

`enabled: false` and enabled-but-exposing-nothing have opposite remedies. #145 dropped both at
write time, so both looked identical — absent. Each source now carries the status the host's
listing actually supports.
"""

from __future__ import annotations

import json
from pathlib import Path

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"

TEXT_LISTING = """\
  MCP Servers:

  Name             Transport                      Tools        Status
  ──────────────── ────────────────────────────── ──────────── ──────────
  rider            http://127.0.0.1:64342/st...   all          ✓ enabled
  llmstudio        http://127.0.0.1:1235          all          ✗ disabled
"""


def _read_index(project: Path) -> dict:
    return json.loads((project / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))


def _write_index(project: Path, data: dict) -> None:
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "mcp-tools.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


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

def test_text_listing_carries_the_enabled_flag_and_admits_tools_are_unknown(load_script):
    """`hermes mcp list` (no --json) prints a Tools column of 'all' — no tool detail at all."""
    mod = load_script(SCRIPT)
    servers = mod._parse_mcp_list_text(TEXT_LISTING)

    assert [s["name"] for s in servers] == ["rider", "llmstudio"]
    assert [s["enabled"] for s in servers] == [True, False]
    assert all(s["tools_known"] is False for s in servers)


def test_init_over_a_text_listing_records_unknown_not_empty(tmp_path, load_script, monkeypatch):
    """Never asked is not the same as asked and got nothing."""
    mod = load_script(SCRIPT)
    monkeypatch.setattr(mod, "_fetch_mcp_tools",
                        lambda from_json=None: mod._parse_mcp_list_text(TEXT_LISTING))

    assert mod.main(["init", "--target", str(tmp_path)]) == 0

    index = _read_index(tmp_path)
    assert _source(index, "rider")["status"] == "unknown"
    assert _source(index, "llmstudio")["status"] == "disabled"


def test_update_over_a_text_listing_does_not_mark_every_tool_removed(
        tmp_path, load_script, monkeypatch):
    """A listing with no tool detail must not wipe the curation of a whole index."""
    _write_index(tmp_path, _existing_index())
    mod = load_script(SCRIPT)
    monkeypatch.setattr(mod, "_fetch_mcp_tools",
                        lambda from_json=None: mod._parse_mcp_list_text(TEXT_LISTING))

    assert mod.main(["update", "--target", str(tmp_path)]) == 0

    rider = _source(_read_index(tmp_path), "rider")
    assert rider["status"] == "unknown"
    assert "status" not in rider["tools"]["build_solution"]


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
