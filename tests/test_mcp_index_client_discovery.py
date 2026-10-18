"""`init|update --discover` asks each unenumerated server directly, through mcp_client.

The configs come from the target's `.mcp.json` (HOME is a scratch dir for the whole suite), the
servers are tests/mcp_fake_server.py, and each test pins one rule of the plan: the enumerated
list is the truth (R1), a partial answer changes nothing (R2), a real answer outranks a failing
health phrase (R3), the deadline holds, and what cannot be run is named.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"
FAKE = str(Path(__file__).resolve().parent / "mcp_fake_server.py")


def _mcp_json(target: Path, env=None, **modes):
    servers = {name: {"command": sys.executable, "args": [FAKE, mode], "env": env or {}}
               for name, mode in modes.items()}
    (target / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    (target / ".claude").mkdir(exist_ok=True)
    (target / ".claude" / "settings.local.json").write_text(
        json.dumps({"enableAllProjectMcpServers": True}), encoding="utf-8")


def _names_only(*names):
    return json.dumps({"servers": [
        {"name": n, "enabled": True, "tools": [], "tools_known": False} for n in names]})


def _index(target: Path):
    return json.loads((target / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))


def _source(target: Path, name: str):
    return next(s for s in _index(target)["sources"] if s["name"] == name)


def _no_hermes(mod, monkeypatch):
    asked = []
    monkeypatch.setattr(mod.hl, "enrich_with_hermes_test",
                        lambda servers, run=None: asked.extend(s["name"] for s in servers) or [])
    return asked


def test_init_discover_fills_tools_from_the_project_mcp_json(tmp_path, load_script, monkeypatch,
                                                             capsys):
    mod = load_script(SCRIPT)
    asked = _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, fake="ok")

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("fake")]) == 0

    source = _source(tmp_path, "fake")
    assert sorted(source["tools"]) == ["alpha", "beta"]
    assert source["status"] == "ok"
    assert asked == []
    assert "fake: enumerated 2 tool(s)" in capsys.readouterr().err


def test_update_discover_keeps_manual_curation_and_removes_unlisted_seeds(tmp_path, load_script,
                                                                          monkeypatch):
    """R1: once the server answers, a catalog-seeded tool it did not list goes `removed`."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, fake="solo")
    assert mod.main(["init", "--target", str(tmp_path),
                     "--from-json", _names_only("fake")]) == 0
    index = _index(tmp_path)
    index["sources"][0]["tools"] = {
        "solo": {"tags": ["search"], "intent": "Hand-curated intent text.", "origin": "manual"},
        "ghost": {"tags": ["read"], "intent": "Seeded from the catalog.", "origin": "catalog"},
    }
    (tmp_path / ".ai-badger" / "mcp-tools.json").write_text(json.dumps(index), encoding="utf-8")

    assert mod.main(["update", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("fake")]) == 0

    tools = _source(tmp_path, "fake")["tools"]
    assert tools["solo"]["origin"] == "manual" and tools["solo"]["tags"] == ["search"]
    assert tools["solo"].get("status") != "removed"
    assert tools["ghost"]["status"] == "removed"


def test_an_error_mid_pagination_leaves_the_server_unenumerated(tmp_path, load_script,
                                                                monkeypatch, capsys):
    """R2: `tools_known` flips only after the last page."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, flaky="page-error")

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("flaky")]) == 0

    source = _source(tmp_path, "flaky")
    assert source["tools"] == {} and source["status"] == "unknown"
    assert "flaky: failed: tools/list failed: backend went away" in capsys.readouterr().err


def test_a_successful_enumeration_clears_a_failing_health_phrase(tmp_path, load_script,
                                                                 monkeypatch):
    """R3: `claude mcp list` said failed to connect, but the server answered — status is ok."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, fake="solo")
    servers = [{"name": "fake", "tools": [], "tools_known": False,
                "host_status": "Failed to connect"}]

    mod._discover_tools(servers, str(tmp_path))  # pylint: disable=protected-access

    assert mod.td.server_status(servers[0]) == "ok"
    assert servers[0]["discovered_via"] == "mcp-client"


def test_hung_servers_time_out_in_parallel_within_the_deadline(tmp_path, load_script,
                                                               monkeypatch, capsys):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, a="hang", b="hang", c="hang")

    started = time.monotonic()
    assert mod.main(["init", "--target", str(tmp_path), "--discover", "--discover-timeout", "1",
                     "--from-json", _names_only("a", "b", "c")]) == 0

    assert time.monotonic() - started < 6
    err = capsys.readouterr().err
    assert all(f"{n}: timed out" in err for n in "abc")


def test_unresolved_servers_are_named_and_only_they_reach_hermes(tmp_path, load_script,
                                                                 monkeypatch, capsys):
    mod = load_script(SCRIPT)
    asked = _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, fake="solo")
    listing = json.dumps({"servers": [
        {"name": n, "tools": [], "tools_known": False}
        for n in ("fake", "missing", "claude.ai Gmail")]})

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", listing]) == 0

    err = capsys.readouterr().err
    assert "missing: no config" in err
    assert "claude.ai Gmail: not enumerated: host-managed connector (OAuth)" in err
    assert asked == ["missing"]


def test_a_server_pending_approval_is_not_run(tmp_path, load_script, monkeypatch):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, fake="solo")
    servers = [{"name": "fake", "tools": [], "tools_known": False,
                "host_status": "Pending approval"}]

    mod._discover_tools(servers, str(tmp_path))  # pylint: disable=protected-access

    assert servers[0]["tools_known"] is False


def test_a_bad_discover_timeout_is_a_usage_error(tmp_path, load_script):
    mod = load_script(SCRIPT)

    assert mod.main(["init", "--target", str(tmp_path), "--discover", "--discover-timeout",
                     "soon", "--from-json", _names_only("x")]) == 2


def test_a_server_description_outside_the_intent_bounds_still_indexes(tmp_path, load_script,
                                                                     monkeypatch):
    """Live smoke 2026-10-18: real servers describe tools in 300-700 chars, and the schema caps
    `intent` at 200 — the whole write was refused. A too-short one (<10) fails the same way."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    for description in ("word " * 120, "Ping."):
        _mcp_json(tmp_path, env={"FAKE_SOLO_DESC": description}, fake="solo")

        assert mod.main(["init", "--target", str(tmp_path), "--discover",
                         "--from-json", _names_only("fake")]) == 0

        intent = _source(tmp_path, "fake")["tools"]["solo"]["intent"]
        assert 10 <= len(intent) <= 200


def test_update_discover_from_another_cwd_lists_the_targets_servers(tmp_path, load_script,
                                                                    monkeypatch):
    """Host CLIs run in --target, not the caller's cwd. From elsewhere `claude mcp list` named a
    different, enumerable server, the listing then carried tool detail, and every one of the
    target's real servers went `absent` (PR #602 live smoke)."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    target, elsewhere, bindir = tmp_path / "repo", tmp_path / "elsewhere", tmp_path / "bin"
    for path in (target, elsewhere, bindir):
        path.mkdir()
    _mcp_json(target, fake="solo")
    home = Path.home()
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {
        "other": {"command": sys.executable, "args": [FAKE, "solo"]}}}), encoding="utf-8")
    seen = tmp_path / "cwd-seen"
    claude = bindir / "claude"
    claude.write_text(
        f"#!{sys.executable}\nimport os, pathlib\n"
        f"pathlib.Path({str(seen)!r}).write_text(os.getcwd())\n"
        f"name = 'fake' if pathlib.Path(os.getcwd(), '.mcp.json').exists() else 'other'\n"
        "print(f'{name}: python fake.py - \\u2714 Connected')\n", encoding="utf-8")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{__import__('os').environ['PATH']}")
    try:
        assert mod.main(["init", "--target", str(target), "--host", "claude"]) == 0
        monkeypatch.chdir(elsewhere)

        assert mod.main(["update", "--target", str(target), "--host", "claude",
                         "--discover"]) == 0
    finally:
        (home / ".claude.json").unlink()

    assert Path(seen.read_text()).resolve() == target.resolve()
    names = [s["name"] for s in _index(target)["sources"]]
    assert names == ["fake"]
    assert _source(target, "fake")["status"] == "ok"
    assert "solo" in _source(target, "fake")["tools"]


def test_enumeration_does_not_make_unnamed_sources_absent(tmp_path, load_script, monkeypatch):
    """Enumerating Y proves Y's tools, not that the listing names every server: a source the
    listing does not name (here a hermes-sourced X) stays untouched."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, y="solo")
    native = json.dumps({"servers": [
        {"name": "x", "tools": [{"name": "xt", "description": "Hermes-listed tool."}]},
        {"name": "y", "tools": [], "tools_known": False}]})
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", native]) == 0
    before = _source(tmp_path, "x")

    assert mod.main(["update", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("y")]) == 0

    assert _source(tmp_path, "x") == before
    assert "solo" in _source(tmp_path, "y")["tools"]


def test_an_unexpected_client_error_fails_one_server_not_the_run(tmp_path, load_script,
                                                                 monkeypatch, capsys):
    """`${MCP_URL}` unset gives urllib an empty URL and a ValueError, not an McpClientError."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    monkeypatch.delenv("FAKE_UNSET_MCP_URL", raising=False)
    _mcp_json(tmp_path, fake="solo")
    config = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    config["mcpServers"]["broken"] = {"type": "http", "url": "${FAKE_UNSET_MCP_URL}"}
    (tmp_path / ".mcp.json").write_text(json.dumps(config), encoding="utf-8")

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("broken", "fake")]) == 0

    assert "broken: failed: " in capsys.readouterr().err
    assert "solo" in _source(tmp_path, "fake")["tools"]


def test_an_unapproved_repo_server_is_not_run_whatever_the_host(tmp_path, load_script,
                                                                 monkeypatch, capsys):
    """The hermes host prints no `Pending approval` phrase, so approval comes from config."""
    mod = load_script(SCRIPT)
    asked = _no_hermes(mod, monkeypatch)
    _mcp_json(tmp_path, repo="solo")
    (tmp_path / ".claude" / "settings.local.json").unlink()

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("repo")]) == 0

    assert "repo: not run: project server not approved in Claude Code" in capsys.readouterr().err
    assert _source(tmp_path, "repo")["tools"] == {}
    assert asked == []
