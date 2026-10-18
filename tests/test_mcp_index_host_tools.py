"""`--discover` reads tool names from Claude Code's own headless init event (host_tools.py).

`claude` is always a fake here: a script that prints a few lines that are not the init event,
then a recorded init event, then sleeps. Each test pins one rule: the name mapping and its
refusals, the deadline and the process-group kill, connected-only authority, direct-beats-host,
and the `--host-tools` / `--no-host-tools` switches.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"
HOST = "features/common/skills/mcp-index/scripts/host_tools.py"
FAKE_SERVER = str(Path(__file__).resolve().parent / "mcp_fake_server.py")

FAKE_CLAUDE = """#!{python}
import json, os, subprocess, sys, time
mode = os.environ.get("FAKE_CLAUDE_MODE", "init")
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(os.environ["FAKE_CLAUDE_PIDS"], "w") as fh:
    fh.write(f"{{os.getpid()}} {{child.pid}}")
if mode == "hang":
    time.sleep(120)
if mode == "exit":
    print("not json")
    sys.stderr.write("boom: not logged in\\n")
    sys.exit(3)
print("garbage that is not json")
print(json.dumps(["a list, not an event"]))
print(json.dumps({{"type": "system", "subtype": "hook_started"}}))
sys.stdout.write(open(os.environ["FAKE_CLAUDE_INIT"]).read().strip() + "\\n")
sys.stdout.flush()
time.sleep(120)
"""


def init_event(servers, extra_tools=()):
    """A system/init event: `servers` maps listing name -> (status, [full mcp__ tool names])."""
    tools = ["Bash", "Read", *extra_tools]
    for _, names in servers.values():
        tools.extend(names)
    return {"type": "system", "subtype": "init", "tools": tools,
            "mcp_servers": [{"name": n, "status": s} for n, (s, _) in servers.items()]}


@pytest.fixture(name="fake_claude")
def _fake_claude(tmp_path, monkeypatch):
    """Install a fake `claude`; returns a setter taking the init event and an optional mode."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    exe.chmod(0o755)
    state = {"log": tmp_path / "claude.log", "pids": tmp_path / "claude.pids", "exe": exe,
             "bindir": bindir}
    monkeypatch.setenv("MCP_INDEX_CLAUDE", str(exe))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(state["log"]))
    monkeypatch.setenv("FAKE_CLAUDE_PIDS", str(state["pids"]))

    def install(event=None, mode="init"):
        init = tmp_path / "init.json"
        init.write_text(json.dumps(event or init_event({})), encoding="utf-8")
        monkeypatch.setenv("FAKE_CLAUDE_INIT", str(init))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        return state

    return install


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _all_dead(pids_file: Path, within: float = 3.0) -> bool:
    pids = [int(p) for p in pids_file.read_text().split()]
    end = time.monotonic() + within
    while time.monotonic() < end:
        if not any(_alive(p) for p in pids):
            return True
        time.sleep(0.05)
    return False


def _calls(state):
    log = state["log"]
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


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


# ── the name mapping ─────────────────────────────────────────────────────────

def test_listing_names_map_to_init_prefixes_by_claude_codes_rule(load_script):
    """Every character outside [A-Za-z0-9_-] becomes `_` (measured on 2.1.302: `claude.ai Exa`
    -> `claude_ai_Exa`, `plugin:context7:context7` -> `plugin_context7_context7`)."""
    host = load_script(HOST)
    event = init_event({
        "plugin:context7:context7": ("connected", ["mcp__plugin_context7_context7__query-docs"]),
        "claude.ai Exa": ("connected", ["mcp__claude_ai_Exa__web_search_exa"]),
        "ai-raccoon": ("connected", ["mcp__ai-raccoon__memory_get",
                                     "mcp__ai-raccoon__memory_write"]),
        "plugin:canva:canva": ("needs-auth", []),
    })

    found = host.map_tools(event)

    assert found.tools == {
        "plugin:context7:context7": ["query-docs"],
        "claude.ai Exa": ["web_search_exa"],
        "ai-raccoon": ["memory_get", "memory_write"],
        "plugin:canva:canva": [],
    }
    assert found.statuses["plugin:canva:canva"] == "needs-auth"
    assert found.ambiguous == set()


def test_two_names_that_normalize_alike_are_both_refused(load_script):
    host = load_script(HOST)
    event = init_event({"a.b": ("connected", ["mcp__a_b__t"]), "a:b": ("connected", []),
                        # no tool to collide on: an empty list would still be read as the truth
                        "c.d": ("connected", []), "c:d": ("connected", [])})

    found = host.map_tools(event)

    assert found.ambiguous == {"a.b", "a:b", "c.d", "c:d"}
    assert not set(found.tools) & found.ambiguous


def test_a_tool_two_prefixes_could_own_refuses_both_servers(load_script):
    """`mcp__x__y__t` is tool `y__t` of `x` or tool `t` of `x__y`; guessing would misfile it."""
    host = load_script(HOST)
    event = init_event({"x": ("connected", ["mcp__x__ok"]),
                        "x__y": ("connected", ["mcp__x__y__t"])})

    found = host.map_tools(event)

    assert found.ambiguous == {"x", "x__y"}


def test_malformed_init_entries_are_ignored_not_fatal(load_script):
    host = load_script(HOST)
    event = {"type": "system", "subtype": "init",
             "tools": ["mcp__s__t", 7, None, "mcp__", "mcp__s__"],
             "mcp_servers": [{"name": "s", "status": "connected"}, "junk", {"status": "x"}]}

    found = host.map_tools(event)

    assert found.tools == {"s": ["t"]}


# ── reading the init event ───────────────────────────────────────────────────

def test_the_init_event_is_read_past_garbage_and_the_process_group_is_killed(load_script,
                                                                              fake_claude,
                                                                              tmp_path):
    host = load_script(HOST)
    event = init_event({"s": ("connected", ["mcp__s__t"])})
    state = fake_claude(event)

    started = time.monotonic()
    got = host.read_init(str(state["exe"]), str(tmp_path), timeout=20)

    assert time.monotonic() - started < 10  # the fake sleeps 120s after printing it
    assert got["mcp_servers"] == event["mcp_servers"]
    assert _all_dead(state["pids"])


def test_the_argv_asks_for_no_model_turn_no_hooks_and_no_transcript(load_script, fake_claude,
                                                                    tmp_path):
    """Step 0 (2026-10-18, 2.1.302): `/cost` gives init with 0 API requests and cost 0;
    `disableAllHooks` ran 0 settings hooks (43 without); no transcript is written."""
    host = load_script(HOST)
    state = fake_claude()

    host.read_init(str(state["exe"]), str(tmp_path), timeout=20)

    argv = _calls(state)[0]["argv"]
    assert argv[-1] == "/cost"
    assert {"-p", "--verbose", "--no-session-persistence"} <= set(argv)
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}
    assert Path(_calls(state)[0]["cwd"]).resolve() == tmp_path.resolve()


def test_a_hang_hits_the_deadline_and_the_whole_group_dies(load_script, fake_claude, tmp_path):
    host = load_script(HOST)
    state = fake_claude(mode="hang")

    started = time.monotonic()
    with pytest.raises(host.HostToolsError, match="timed out"):
        host.read_init(str(state["exe"]), str(tmp_path), timeout=1)

    assert time.monotonic() - started < 6
    assert _all_dead(state["pids"])


def test_an_exit_before_init_names_the_last_stderr_line(load_script, fake_claude, tmp_path):
    host = load_script(HOST)
    state = fake_claude(mode="exit")

    with pytest.raises(host.HostToolsError, match="boom: not logged in"):
        host.read_init(str(state["exe"]), str(tmp_path), timeout=20)


def test_an_oversized_line_is_refused(load_script, fake_claude, tmp_path, monkeypatch):
    host = load_script(HOST)
    monkeypatch.setattr(host.mc, "MAX_MESSAGE_BYTES", 1024)
    state = fake_claude(init_event({}, extra_tools=["x" * 4096]))

    with pytest.raises(host.HostToolsError, match="too large"):
        host.read_init(str(state["exe"]), str(tmp_path), timeout=20)


# ── --discover with the host source ──────────────────────────────────────────

def test_discover_fills_connectors_and_unauthorized_servers_from_claude_init(
        tmp_path, load_script, monkeypatch, fake_claude, capsys):
    mod = load_script(SCRIPT)
    asked = _no_hermes(mod, monkeypatch)
    fake_claude(init_event({
        "claude.ai Exa": ("connected", ["mcp__claude_ai_Exa__web_search_exa"]),
        "plugin:p:s": ("connected", ["mcp__plugin_p_s__alpha", "mcp__plugin_p_s__beta"]),
    }))

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("claude.ai Exa", "plugin:p:s")]) == 0

    assert sorted(_source(tmp_path, "plugin:p:s")["tools"]) == ["alpha", "beta"]
    exa = _source(tmp_path, "claude.ai Exa")
    assert list(exa["tools"]) == ["web_search_exa"] and exa["status"] == "ok"
    err = capsys.readouterr().err
    assert "claude.ai Exa: enumerated 1 tool(s) via claude init" in err
    assert asked == []  # filled by the host, so hermes is never asked


def test_a_server_the_host_reports_unauthenticated_is_left_as_listed(tmp_path, load_script,
                                                                     monkeypatch, fake_claude,
                                                                     capsys):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    fake_claude(init_event({"plugin:canva:canva": ("needs-auth", []),
                            "broken": ("failed", [])}))

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("plugin:canva:canva", "broken")]) == 0

    canva = _source(tmp_path, "plugin:canva:canva")
    assert canva["tools"] == {} and canva["status"] == "unauthenticated"
    assert _source(tmp_path, "broken")["status"] == "unreachable"
    err = capsys.readouterr().err
    assert "plugin:canva:canva: no config; claude init reports needs-auth" in err
    assert "broken: no config; claude init reports failed" in err


def test_a_direct_answer_beats_the_host_for_the_same_server(tmp_path, load_script, monkeypatch,
                                                           fake_claude):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "fake": {"command": sys.executable, "args": [FAKE_SERVER, "solo"]}}}), encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text(
        json.dumps({"enableAllProjectMcpServers": True}), encoding="utf-8")
    fake_claude(init_event({"fake": ("connected", ["mcp__fake__from_host"]),
                            "claude.ai Exa": ("connected", ["mcp__claude_ai_Exa__x"])}))

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("fake", "claude.ai Exa")]) == 0

    assert list(_source(tmp_path, "fake")["tools"]) == ["solo"]
    assert list(_source(tmp_path, "claude.ai Exa")["tools"]) == ["x"]


def test_the_host_is_not_spawned_when_direct_answers_cover_everything(tmp_path, load_script,
                                                                      monkeypatch, fake_claude):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "fake": {"command": sys.executable, "args": [FAKE_SERVER, "solo"]}}}), encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text(
        json.dumps({"enableAllProjectMcpServers": True}), encoding="utf-8")
    state = fake_claude()

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("fake")]) == 0

    assert _calls(state) == []


def test_host_tools_make_removal_apply_but_never_make_unnamed_sources_absent(
        tmp_path, load_script, monkeypatch, fake_claude):
    """Connected in init is authoritative for that server (a seeded tool it lacks goes removed);
    a source the listing does not name (hermes-sourced `x`) stays untouched."""
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    native = json.dumps({"servers": [
        {"name": "x", "tools": [{"name": "xt", "description": "Hermes-listed tool."}]},
        {"name": "y", "tools": [], "tools_known": False}]})
    assert mod.main(["init", "--target", str(tmp_path), "--from-json", native]) == 0
    index = _index(tmp_path)
    y = next(s for s in index["sources"] if s["name"] == "y")
    y["tools"] = {"ghost": {"tags": ["read"], "intent": "Seeded from the catalog.",
                            "origin": "catalog"}}
    (tmp_path / ".ai-badger" / "mcp-tools.json").write_text(json.dumps(index), encoding="utf-8")
    before = _source(tmp_path, "x")
    fake_claude(init_event({"y": ("connected", ["mcp__y__real"])}))

    assert mod.main(["update", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("y")]) == 0

    assert _source(tmp_path, "x") == before
    tools = _source(tmp_path, "y")["tools"]
    assert tools["ghost"]["status"] == "removed"
    assert tools["real"]["intent"] == "TODO: describe what real does"  # no invented description


def test_an_unapproved_project_server_is_never_filled_by_the_host(tmp_path, load_script,
                                                                  monkeypatch, fake_claude):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "repo": {"command": sys.executable, "args": [FAKE_SERVER, "solo"]}}}), encoding="utf-8")
    fake_claude(init_event({"repo": ("connected", ["mcp__repo__solo"])}))

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("repo")]) == 0

    assert _source(tmp_path, "repo")["tools"] == {}


def test_a_failing_host_run_fails_only_the_host_source(tmp_path, load_script, monkeypatch,
                                                       fake_claude, capsys):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    fake_claude(mode="exit")

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("claude.ai Exa")]) == 0

    assert _source(tmp_path, "claude.ai Exa")["tools"] == {}
    assert "claude init failed" in capsys.readouterr().err


def test_no_host_tools_never_spawns_claude(tmp_path, load_script, monkeypatch, fake_claude):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    state = fake_claude(init_event({"claude.ai Exa": ("connected", ["mcp__claude_ai_Exa__x"])}))

    assert mod.main(["init", "--target", str(tmp_path), "--discover", "--no-host-tools",
                     "--from-json", _names_only("claude.ai Exa")]) == 0

    assert _calls(state) == []
    assert _source(tmp_path, "claude.ai Exa")["tools"] == {}


def test_by_default_the_claude_on_path_is_used(tmp_path, load_script, monkeypatch, fake_claude):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    state = fake_claude(init_event({"claude.ai Exa": ("connected", ["mcp__claude_ai_Exa__x"])}))
    monkeypatch.delenv("MCP_INDEX_CLAUDE")
    monkeypatch.setenv("PATH", str(state["bindir"]))

    assert mod.main(["init", "--target", str(tmp_path), "--discover",
                     "--from-json", _names_only("claude.ai Exa")]) == 0

    assert list(_source(tmp_path, "claude.ai Exa")["tools"]) == ["x"]


def test_host_tools_without_a_claude_says_so(tmp_path, load_script, monkeypatch, capsys):
    mod = load_script(SCRIPT)
    _no_hermes(mod, monkeypatch)
    monkeypatch.delenv("MCP_INDEX_CLAUDE")
    monkeypatch.setenv("PATH", str(tmp_path))

    assert mod.main(["init", "--target", str(tmp_path), "--discover", "--host-tools",
                     "--from-json", _names_only("claude.ai Exa")]) == 0

    assert "claude not found on PATH" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["soon", "0", "-3"])
def test_a_bad_host_tools_timeout_is_a_usage_error(tmp_path, load_script, value):
    mod = load_script(SCRIPT)

    assert mod.main(["init", "--target", str(tmp_path), "--discover", "--host-tools-timeout",
                     value, "--from-json", _names_only("x")]) == 2
