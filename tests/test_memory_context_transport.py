"""memory_context.py transport and single-search build, against the fake ai-raccoon proxy.

Every test runs under `memory_context_env` (tests/memory_context_support.py): scrubbed env, temp
HOME, PATH holding only the fake, the spawn and network guards. Timing rows bound at most 3 s
against fakes whose blocking behaviour ends by a 20 s ceiling.
"""
# pylint: disable=redefined-outer-name  # the shared autouse fixture is requested by name
from __future__ import annotations

import ast
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import memory_context_support as support
from memory_context_support import SCRIPTS, load_module, memory_context_env  # noqa: F401

mc = load_module()

PROMPT = "why does the memory context hook stay silent on every prompt"
FAILURE_MODES = ["iserror", "rpcerror", "hang", "drip", "nostdin", "oversize", "crash"]


def open_session(env, budget=5.0):
    return mc.RaccoonSession.open(str(env.fake.path), "proj-123", "sess-1", mc.Budget(budget))


def run_search(env, query="alpha", budget=5.0):
    session = open_session(env, budget)
    assert session is not None
    try:
        return session, session.search(query, mc.Budget(budget))
    finally:
        session.close(mc.Budget(budget))


def build(env, prompt=PROMPT, cwd=None, session_id="sess-1", budget=None):
    cwd = cwd if cwd is not None else env.project()
    return mc.build(prompt, str(cwd), session_id, env=dict(os.environ), home=str(env.home),
                    budget=mc.Budget(budget) if budget is not None else None)


# -------------------------------------------------------------------- G rows


def test_g1_real_executable_guard_refuses_by_realpath(memory_context_env, tmp_path):
    env = memory_context_env
    stand_in = tmp_path / "real" / "ai-raccoon"
    stand_in.parent.mkdir()
    stand_in.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stand_in.chmod(0o755)
    alias = tmp_path / "alias-ai-raccoon"
    alias.symlink_to(stand_in)
    env.guards.forbidden = frozenset({os.path.realpath(stand_in)})

    with pytest.raises(support.GuardRefusal):
        subprocess.Popen([str(alias)])
    assert len(env.guards.refusals) == 1

    def production_catch_all():
        try:
            subprocess.Popen([str(stand_in)])
        except Exception:  # pylint: disable=broad-exception-caught
            return "swallowed"
        return "spawned"

    with pytest.raises(support.GuardRefusal):
        production_catch_all()
    assert len(env.guards.refusals) == 2
    with pytest.raises(pytest.fail.Exception):
        support.assert_no_refusals(env.guards)
    env.guards.take_refusals()

    session, found = run_search(env)
    assert found is not None and session is not None


def test_g2_scrub_holds_against_outer_env(memory_context_env, monkeypatch):
    env = memory_context_env
    for name, value in (("AI_BADGER_MEMORY_CONTEXT", "0"), ("AI_BADGER_PROJECT_ID", "x"),
                        ("OPENROUTER_API_KEY", "k"), ("https_proxy", "http://203.0.113.9:1")):
        monkeypatch.setenv(name, value)
    support.scrub_env(monkeypatch, env.home, env.fake.bin_dir, env.root / "guard",
                      env.guards.marker)
    block = build(env, cwd=env.project("file-id"))
    assert block is not None
    runs = env.fake.runs()
    assert len(runs) == 1
    assert env.fake.calls()[0]["params"]["arguments"]["projectId"] == "file-id"
    assert env.guards.net_attempts == []
    assert env.guards.refusals == []


@pytest.mark.parametrize("mode", ["hits", "empty", "iserror", "rpcerror", "malformed", "perquery",
                                  "slowinit", "crash"])
def test_g3_fake_modes_that_answer(memory_context_env, mode):
    env = memory_context_env
    env.fake.mode(mode)
    env.fake.hits({"alpha": {"results": [{"hash": "p", "path": "/p.md", "snippet": "p"}],
                             "code": []}})
    proc = subprocess.Popen([str(env.fake.path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "alpha"}}}
    out, _ = proc.communicate((json.dumps(init) + "\n" + json.dumps(call) + "\n").encode(),
                              timeout=5)
    replies = [json.loads(line) for line in out.decode().splitlines() if line.startswith("{")]
    assert replies[0]["id"] == 1
    if mode == "crash":
        assert proc.returncode == 3 and len(replies) == 1
        return
    last = replies[-1]
    assert last["id"] == 2
    text = last.get("result", {}).get("content", [{}])[0].get("text")
    expected = {"iserror": lambda: last["result"]["isError"] is True,
                "rpcerror": lambda: "error" in last,
                "empty": lambda: json.loads(text)["data"] == {"results": [], "code": []},
                "perquery": lambda: json.loads(text)["data"]["results"][0]["hash"] == "p"}
    assert expected.get(mode, lambda: json.loads(text)["data"]["results"])()
    if mode == "malformed":
        assert b"not json at all" in out
    if mode == "slowinit":
        assert env.fake.runs()[-1]["early_write"] is True


@pytest.mark.parametrize("mode", ["hang", "drip", "nostdin"])
def test_g3_blocking_modes_end_by_the_ceiling(memory_context_env, mode):
    env = memory_context_env
    env.fake.mode(mode)
    env.fake.ceiling(1)
    proc = subprocess.Popen([str(env.fake.path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    started = time.monotonic()
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "alpha"}}}
    try:
        out, _ = proc.communicate((json.dumps(init) + "\n" + json.dumps(call) + "\n").encode(),
                                  timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(f"fake mode {mode} outlived its 1 s ceiling")
    assert time.monotonic() - started < 3
    replies = [line for line in out.decode(errors="replace").splitlines() if line.strip()]
    assert json.loads(replies[0])["id"] == 1
    assert not any('"id": 2' in line and line.endswith("}") for line in replies[1:])


def test_g3_latereply_holds_reply_until_second_request_is_read(memory_context_env):
    env = memory_context_env
    env.fake.mode("latereply")
    env.fake.hits({"a": {"results": [{"hash": "A", "path": "/a", "snippet": "a"}], "code": []},
                   "b": {"results": [{"hash": "B", "path": "/b", "snippet": "b"}], "code": []}})
    proc = subprocess.Popen([str(env.fake.path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    try:
        def line(obj):
            proc.stdin.write((json.dumps(obj) + "\n").encode())
            proc.stdin.flush()

        line({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert json.loads(proc.stdout.readline())["id"] == 1
        line({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "memory_search", "arguments": {"query": "a"}}})
        time.sleep(0.3)
        assert not any(r["event"] == "line" and '"id": 3' in r["line"]
                       for r in env.fake.events())
        line({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "memory_search", "arguments": {"query": "b"}}})
        first = json.loads(proc.stdout.readline())
        second = json.loads(proc.stdout.readline())
        assert (first["id"], second["id"]) == (2, 3)
        lines = [r["line"] for r in env.fake.events() if r["event"] == "line"]
        assert any('"id": 3' in text for text in lines)
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
        proc.stdout.close()


def test_g4_network_guard(memory_context_env, tmp_path):
    env = memory_context_env
    with pytest.raises(support.GuardRefusal):
        socket.getaddrinfo("openrouter.ai", 443)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(support.GuardRefusal):
            sock.connect(("203.0.113.1", 443))
    finally:
        sock.close()
    assert len(env.guards.refusals) == 2

    def production_catch_all():
        try:
            socket.create_connection(("203.0.113.1", 443), timeout=1)
        except Exception:  # pylint: disable=broad-exception-caught
            return "swallowed"
        return "connected"

    with pytest.raises(support.GuardRefusal):
        production_catch_all()
    with pytest.raises(pytest.fail.Exception):
        support.assert_no_refusals(env.guards)
    env.guards.take_refusals()

    child = subprocess.run(
        [sys.executable, "-c",
         "import socket; socket.create_connection(('203.0.113.1', 443), timeout=1)"],
        env=dict(os.environ), capture_output=True, timeout=10, check=False)
    assert child.returncode != 0
    assert "203.0.113.1" in env.guards.marker.read_text(encoding="utf-8")
    with pytest.raises(pytest.fail.Exception):
        support.assert_no_refusals(env.guards)
    env.guards.take_refusals()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    try:
        client = socket.create_connection(server.getsockname(), timeout=2)
        client.close()
        socket.getaddrinfo("127.0.0.1", 80)
        ok = subprocess.run(
            [sys.executable, "-c",
             f"import socket; socket.create_connection({server.getsockname()!r}, timeout=2)"],
            env=dict(os.environ), capture_output=True, timeout=10, check=False)
        assert ok.returncode == 0, ok.stderr
    finally:
        server.close()
    assert env.guards.refusals == [] and not env.guards.marker.exists()


# ------------------------------------------------------------------- T rows


def test_t1_find_executable(memory_context_env, tmp_path):
    env = memory_context_env
    home = tmp_path / "h"
    tools = home / ".dotnet" / "tools"
    tools.mkdir(parents=True)
    fallback = tools / "ai-raccoon"
    fallback.write_text("#!/bin/sh\n", encoding="utf-8")

    on_path = mc.find_executable({"PATH": str(env.fake.bin_dir)}, str(home))
    assert on_path == str(env.fake.path) and os.path.isabs(on_path)
    empty_bin = tmp_path / "empty"
    empty_bin.mkdir()
    assert mc.find_executable({"PATH": str(empty_bin)}, str(home)) is None
    fallback.chmod(0o755)
    assert mc.find_executable({"PATH": str(empty_bin)}, str(home)) == str(fallback)
    assert mc.find_executable({}, str(home)) == str(fallback)
    assert mc.find_executable({"PATH": str(empty_bin)}, str(tmp_path / "nohome")) is None


def test_t2_spawn_shape_across_modes(memory_context_env):
    env = memory_context_env
    for mode in ["hits", "empty", "iserror", "rpcerror", "malformed", "crash", "hang"]:
        env.fake.mode(mode)
        env.guards.spawns.clear()
        build(env, budget=0.5)
        assert [s["argv"] for s in env.guards.spawns] == [[str(env.fake.path)]], mode
        assert env.guards.spawns[0]["shell"] is False
        assert env.guards.spawns[0]["stderr"] == subprocess.DEVNULL


def test_t3_wire(memory_context_env):
    env = memory_context_env
    run_search(env, query="alpha query")
    requests = env.fake.requests()
    assert requests[0]["method"] == "initialize" and requests[0]["id"] == 1
    assert requests[0]["params"]["protocolVersion"] == "2024-11-05"
    assert requests[1] == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    call = requests[2]
    assert call["method"] == "tools/call" and call["params"]["name"] == "memory_search"
    assert call["params"]["arguments"] == {"projectId": "proj-123", "sessionId": "sess-1",
                                           "query": "alpha query", "limit": 5,
                                           "scope": "project"}


def test_t4_nothing_written_before_initialize_reply(memory_context_env):
    env = memory_context_env
    env.fake.mode("slowinit")
    _, found = run_search(env)
    assert found is not None
    assert env.fake.runs()[-1]["early_write"] is False


def test_t5_hits_parsed_from_text_part(memory_context_env):
    _, found = run_search(memory_context_env)
    assert [h["hash"] for h in found.mem] == ["m-one", "m-two"]
    assert [h["hash"] for h in found.code] == ["c-one"]


@pytest.mark.parametrize("mode", ["iserror", "rpcerror"])
def test_t7_t8_error_replies_are_none(memory_context_env, mode):
    memory_context_env.fake.mode(mode)
    assert run_search(memory_context_env)[1] is None


def test_t9_malformed_framing_still_parses(memory_context_env):
    memory_context_env.fake.mode("malformed")
    _, found = run_search(memory_context_env)
    assert [h["hash"] for h in found.mem] == ["m-one", "m-two"]


def _reply(result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": 2}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


@pytest.mark.parametrize("msg,expected", [
    (_reply({"content": []}), None),
    (_reply({"content": [{"type": "image", "data": "x"}]}), None),
    (_reply({"content": [{"type": "text", "text": "not json"}]}), None),
    (_reply({"content": [{"type": "text", "text": "{}"}]}), ([], [])),
    (_reply({"content": [{"type": "text", "text": '{"data": {"code": []}}'}]}), ([], [])),
    (_reply({"content": [{"type": "text", "text": '{"data": {"results": [], "code": []}}'}]}),
     ([], [])),
    (_reply({"content": [{"type": "text", "text": '{"data": {"results": "x", "code": [1]}}'}]}),
     ([], [])),
    (_reply(None), None),
    (_reply(error={"code": 1}), None),
])
def test_t10_payload_table(msg, expected):
    found = mc.parse_search_reply(msg)
    if expected is None:
        assert found is None
    else:
        assert (found.mem, found.code) == expected


def test_t12_hang_returns_within_bound_and_reaps(memory_context_env):
    env = memory_context_env
    env.fake.mode("hang")
    started = time.monotonic()
    session = open_session(env, 0.3)
    budget = mc.Budget(0.3)
    assert session.search("alpha", budget) is None
    session.close(budget)
    assert time.monotonic() - started < 2
    assert support.pid_gone(env.fake.runs()[-1]["pid"])


def test_t13_drip_returns_within_bound(memory_context_env):
    env = memory_context_env
    env.fake.mode("drip")
    started = time.monotonic()
    assert build(env, budget=0.3) is None
    assert time.monotonic() - started < 2
    assert support.pid_gone(env.fake.runs()[-1]["pid"])


def test_t14_blocked_stdin_returns_within_bound(memory_context_env):
    env = memory_context_env
    env.fake.mode("nostdin")
    started = time.monotonic()
    session = open_session(env, 0.3)
    assert session is not None
    budget = mc.Budget(0.3)
    assert session.search("x" * (1024 * 1024), budget) is None
    session.close(budget)
    assert time.monotonic() - started < 2


def test_t15_oversize_is_none_and_killed(memory_context_env):
    env = memory_context_env
    env.fake.mode("oversize")
    started = time.monotonic()
    session, found = run_search(env, budget=3.0)
    assert found is None
    assert session.process.returncode == -signal.SIGKILL
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("mode", FAILURE_MODES)
def test_t16_never_raises(memory_context_env, mode):
    env = memory_context_env
    env.fake.mode(mode)
    session = open_session(env, 0.5)
    budget = mc.Budget(0.5)
    assert session.search("alpha", budget) is None
    session.close(budget)
    assert build(env, budget=0.5) is None


def test_t17_sequential_runs_leave_no_process_or_thread(memory_context_env):
    env = memory_context_env
    before = {t.name for t in threading.enumerate()}
    for index in range(20):
        env.fake.mode(["hits", "hang", "crash"][index % 3])
        build(env, budget=0.3)
    pids = [run["pid"] for run in env.fake.runs()]
    assert len(pids) == 20
    assert all(support.pid_gone(pid) for pid in pids)
    assert {t.name for t in threading.enumerate()} == before


def test_t18_graceful_close(memory_context_env):
    env = memory_context_env
    session, found = run_search(env)
    assert found is not None
    assert session.process.returncode == 0
    assert env.fake.runs()[-1]["saw_eof"] is True


def test_t19_kill_scope_is_the_pid_not_the_group(memory_context_env):
    env = memory_context_env
    env.fake.mode("grandchild")
    session = open_session(env, 0.3)
    budget = mc.Budget(0.3)
    session.search("alpha", budget)
    session.close(budget)
    run = env.fake.runs()[-1]
    grandchild = run["grandchild"]
    try:
        assert support.pid_gone(run["pid"])
        assert not support.pid_gone(grandchild)
    finally:
        os.kill(grandchild, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while not support.pid_gone(grandchild) and time.monotonic() < deadline:
            time.sleep(0.02)
    assert support.pid_gone(grandchild)


def test_t20_spawn_failure_is_none(memory_context_env, tmp_path):
    missing = tmp_path / "gone" / "ai-raccoon"
    assert mc.RaccoonSession.open(str(missing), "p", "s", mc.Budget(1)) is None
    not_exec = tmp_path / "ai-raccoon"
    not_exec.write_text("#!/bin/sh\n", encoding="utf-8")
    not_exec.chmod(0o644)
    assert mc.RaccoonSession.open(str(not_exec), "p", "s", mc.Budget(1)) is None


def test_t21_one_session_two_searches(memory_context_env):
    env = memory_context_env
    session = open_session(env)
    try:
        assert session.search("one", mc.Budget(5)) is not None
        assert session.search("two", mc.Budget(5)) is not None
    finally:
        session.close(mc.Budget(5))
    assert len(env.fake.runs()) == 1
    requests = env.fake.requests()
    assert [r["method"] for r in requests].count("initialize") == 1
    assert [c["id"] for c in env.fake.calls()] == [2, 3]


def test_t22_budget_child_and_expired_budget(memory_context_env):
    now = [100.0]
    parent = mc.Budget(2.0, clock=lambda: now[0])
    child = parent.child(10.0)
    assert child.remaining() == pytest.approx(2.0)
    assert parent.child(1.0).remaining() == pytest.approx(1.0)
    now[0] = 101.5
    assert child.remaining() == pytest.approx(0.5)
    assert child.child(5).remaining() == pytest.approx(0.5)
    now[0] = 103.0
    assert parent.expired() and child.expired() and child.remaining() == 0

    env = memory_context_env
    session = open_session(env)
    writes = []
    real_write = session._write  # pylint: disable=protected-access
    session._write = lambda data, budget: writes.append(data) or real_write(data, budget)
    try:
        assert session.search("alpha", mc.Budget(0.0)) is None
    finally:
        session.close(mc.Budget(1))
    assert writes == []


def test_t23_windows_is_inert(memory_context_env, monkeypatch):
    env = memory_context_env
    monkeypatch.setattr(mc.sys, "platform", "win32")
    assert open_session(env) is None
    assert build(env) is None
    assert env.guards.spawns == []


def test_t24_late_reply_is_skipped_by_id(memory_context_env):
    env = memory_context_env
    env.fake.mode("latereply")
    env.fake.hits({"a": {"results": [{"hash": "A", "path": "/a", "snippet": "a"}], "code": []},
                   "b": {"results": [{"hash": "B", "path": "/b", "snippet": "b"}], "code": []},
                   "c": {"results": [{"hash": "C", "path": "/c", "snippet": "c"}], "code": []}})
    session = open_session(env)
    try:
        assert session.search("a", mc.Budget(0.2)) is None
        found_b = session.search("b", mc.Budget(2))
        found_c = session.search("c", mc.Budget(2))
    finally:
        session.close(mc.Budget(1))
    assert [h["hash"] for h in found_b.mem] == ["B"]
    assert [h["hash"] for h in found_c.mem] == ["C"]
    assert len(env.fake.calls()) == 3


@pytest.mark.parametrize("mode,query", [("nostdin", "x" * (1024 * 1024)),
                                        ("oversize", "alpha"), ("crash", "alpha")],
                         ids=["nostdin", "oversize", "crash"])
def test_t25_poisoned_session_stops_at_once(memory_context_env, mode, query):
    env = memory_context_env
    env.fake.mode(mode)
    session = open_session(env)
    try:
        assert session.search(query, mc.Budget(0.5)) is None
        writes, waits = [], []
        session._write = lambda *a: writes.append(a)  # pylint: disable=protected-access
        session._wait = lambda *a: waits.append(a)  # pylint: disable=protected-access
        started = time.monotonic()
        assert session.search("again", mc.Budget(5)) is None
        assert session.search("third", mc.Budget(5)) is None
        assert time.monotonic() - started < 1
        assert writes == [] and waits == []
    finally:
        session.close(mc.Budget(0.1))


# ---------------------------------------------------------------- S1 static

NEW_FILES = ["memory_context.py", "openrouter_client.py", "query_pipeline.py",
             "memory_context_hook.py"]
NETWORK_MODULES = {"urllib", "http", "ssl", "socket", "threading"}
FORBIDDEN_OS = {"system", "popen", "fork", "forkpty"}
FORBIDDEN_OS_PREFIXES = ("exec", "spawn", "posix_spawn")


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def static_findings(sources):
    """Every S1 violation across {file name: source}."""
    findings, popen_sites = [], []
    for name, source in sources.items():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                caught = (node.type.elts if isinstance(node.type, ast.Tuple) else [node.type])
                if node.type is None or "BaseException" in {_dotted(t) for t in caught}:
                    findings.append(f"{name}: except BaseException or bare except")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module or ""])
                for module in modules:
                    top = module.split(".")[0]
                    if top == "multiprocessing":
                        findings.append(f"{name}: multiprocessing")
                    if top in NETWORK_MODULES and name != "openrouter_client.py":
                        findings.append(f"{name}: imports {module}")
            if not isinstance(node, ast.Call):
                continue
            func = _dotted(node.func)
            leaf = func.rsplit(".", 1)[-1]
            if leaf == "Popen":
                popen_sites.append(name)
            if func.startswith("subprocess.") and leaf != "Popen":
                findings.append(f"{name}: {func}")
            if func.startswith("os.") and (leaf in FORBIDDEN_OS
                                          or leaf.startswith(FORBIDDEN_OS_PREFIXES)):
                findings.append(f"{name}: {func}")
            if any(k.arg == "shell" and not (isinstance(k.value, ast.Constant)
                                             and k.value.value is False) for k in node.keywords):
                findings.append(f"{name}: shell= not literal False")
            if leaf in ("urlopen", "install_opener"):
                findings.append(f"{name}: {leaf}")
            if leaf == "build_opener" and name != "openrouter_client.py":
                findings.append(f"{name}: build_opener")
            if leaf == "ProxyHandler" and not (
                    len(node.args) == 1 and isinstance(node.args[0], ast.Dict)
                    and not node.args[0].keys):
                findings.append(f"{name}: ProxyHandler without literal {{}}")
            if func == "time.sleep" and name == "query_pipeline.py":
                findings.append(f"{name}: time.sleep")
            for arg in node.args:
                if (isinstance(arg, (ast.List, ast.Tuple)) and arg.elts
                        and isinstance(arg.elts[0], ast.Constant) and arg.elts[0].value == "pi"):
                    findings.append(f"{name}: pi in argv position")
    if popen_sites != ["memory_context.py"]:
        findings.append(f"Popen call sites: {popen_sites}")
    return findings


def _sources():
    return {name: (SCRIPTS / name).read_text(encoding="utf-8")
            for name in NEW_FILES if (SCRIPTS / name).is_file()}


def test_s1_static_shape():
    sources = _sources()
    assert "memory_context.py" in sources
    assert static_findings(sources) == []


@pytest.mark.parametrize("extra", [
    'import subprocess\nsubprocess.run(["pi", "x"])\n',
    'from urllib.request import urlopen\nurlopen("http://x")\n',
    'try:\n    pass\nexcept BaseException:\n    pass\n',
    'import os\nos.execv("/bin/sh", [])\n',
    'import threading\n',
])
def test_s1_catches_each_violation(extra):
    sources = _sources()
    sources["memory_context.py"] += "\n" + extra
    assert static_findings(sources) != []


# ------------------------------------------------------------------- B rows


def test_b1_kill_switch_does_no_work(memory_context_env, monkeypatch):
    env = memory_context_env
    store = mc.load_badger_store()
    calls = []
    monkeypatch.setattr(store, "resolve_project_id", lambda cwd: calls.append(cwd) or "p")
    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT", "0")
    assert build(env) is None
    assert env.guards.spawns == [] and env.guards.net_attempts == [] and calls == []
    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT", "1")
    assert build(env) is not None


@pytest.mark.parametrize("value", ["", "false", "off", "no", "00", " 0"])
def test_b2_only_literal_zero_disables(memory_context_env, monkeypatch, value):
    env = memory_context_env
    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT", value)
    assert build(env) is not None
    assert len(env.guards.spawns) == 1


def test_b3_default_on_needs_id_and_executable(memory_context_env, monkeypatch, tmp_path):
    env = memory_context_env
    assert build(env) is not None
    assert len(env.guards.spawns) == 1
    assert build(env, cwd=env.project(None, name="no-id")) is None
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    assert build(env) is None
    assert len(env.guards.spawns) == 1


def test_b4_project_id_resolution(memory_context_env, monkeypatch):
    env = memory_context_env
    proj = env.project("file-id")
    deep = proj / "a" / "b"
    deep.mkdir(parents=True)

    def sent_project_id():
        return env.fake.calls()[0]["params"]["arguments"]["projectId"]

    assert build(env, cwd=deep) is not None
    assert sent_project_id() == "file-id"
    monkeypatch.setenv("AI_BADGER_PROJECT_ID", " X ")
    assert build(env, cwd=deep) is not None
    assert env.fake.calls(env.fake.runs()[-1])[0]["params"]["arguments"]["projectId"] == "X"
    monkeypatch.setenv("AI_BADGER_PROJECT_ID", "   ")
    assert build(env, cwd=deep) is not None
    assert env.fake.calls(env.fake.runs()[-1])[0]["params"]["arguments"]["projectId"] == "file-id"
    monkeypatch.delenv("AI_BADGER_PROJECT_ID")
    spawns = len(env.guards.spawns)
    nested = deep / "inner"
    (nested / ".ai-badger").mkdir(parents=True)
    assert build(env, cwd=nested) is None
    blank = env.project("  \n", name="blank")
    assert build(env, cwd=blank) is None
    assert len(env.guards.spawns) == spawns


@pytest.mark.parametrize("prompt", ["", "stop", "/delegations", "short prompt",
                                    "alpha bravo charlie delta echo"])
def test_b5_gate_skip_spawns_nothing(memory_context_env, prompt):
    env = memory_context_env
    assert build(env, prompt=prompt) is None
    assert env.guards.spawns == [] and env.guards.net_attempts == []


@pytest.mark.parametrize("session_id", ["", "   ", None])
def test_b6_blank_session_spawns_nothing(memory_context_env, session_id):
    env = memory_context_env
    assert build(env, session_id=session_id) is None
    assert env.guards.spawns == []
    assert build(env, session_id="s") is not None
    assert len(env.guards.spawns) == 1


def test_b7_only_droppable_hits_is_none(memory_context_env):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits({PROMPT: {"results": [{"hash": "d", "snippet": "  "}],
                            "code": [{"hash": "e", "path": "?", "snippet": ""}]}})
    assert build(env) is None
    assert len(env.guards.spawns) == 1


def test_b8_long_prompt_is_sent_whole(memory_context_env):
    env = memory_context_env
    words = " ".join(f"word{i}" for i in range(2000))
    prompt = "  " + words[:10000] + "  "
    assert build(env, prompt=prompt, budget=5) is not None
    assert env.fake.calls()[0]["params"]["arguments"]["query"] == prompt.strip()
    assert len(prompt.strip()) == 10000


def test_build_happy_block(memory_context_env):
    block = build(memory_context_env)
    assert block.startswith("Memory context (ai-raccoon memory_search, snippets")
    assert "[m1] /repo/docs/one.md (rank 1) :: first memory" in block
    assert "[c1] /repo/src/one.py:1-2 (rank 0.75) :: def one(): pass" in block


def test_env_names_and_sibling_constants():
    assert set(mc.ENV_NAMES) == {
        "AI_BADGER_PROJECT_ID", "AI_BADGER_MEMORY_CONTEXT", "AI_BADGER_MEMORY_CONTEXT_PIPELINE",
        "AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL", "AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE",
        "OPENROUTER_API_KEY"}
    assert mc.SIBLINGS == ("openrouter_client.py", "query_pipeline.py")
    assert mc.RESOLVER == "model_groups.py"
    assert Path(mc.__file__).name == "memory_context.py"


# ------------------------------------------------------------------- env names against real use

ENV_OWNED_BY_THE_FIXTURE = {"PATH", "HOME"}


def _env_reads(path, module):
    """Every variable name *path* reads from an `env` mapping or `os.environ`, resolved
    through *module*'s globals when passed by constant name."""
    def is_env(node):
        return (isinstance(node, ast.Name) and node.id == "env") or _dotted(node) == "os.environ"

    def name_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and isinstance(getattr(module, node.id, None), str):
            return getattr(module, node.id)
        return None

    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and is_env(node.func.value) and node.args):
            found.add(name_of(node.args[0]))
        elif isinstance(node, ast.Subscript) and is_env(node.value):
            found.add(name_of(node.slice))
        elif (isinstance(node, ast.Compare) and len(node.ops) == 1
              and isinstance(node.ops[0], (ast.In, ast.NotIn)) and is_env(node.comparators[0])):
            found.add(name_of(node.left))
    return found


def test_env_names_are_every_variable_the_modules_read():
    """ENV_NAMES is what the fixture scrubs: a read it does not list escapes the scrub."""
    load = mc._load_sibling  # pylint: disable=protected-access
    modules = {"memory_context.py": mc, "openrouter_client.py": load("openrouter_client"),
               "query_pipeline.py": load("query_pipeline")}
    read = set()
    for name, module in modules.items():
        read |= _env_reads(SCRIPTS / name, module)
    assert None not in read, "an env read the scan cannot name"
    assert read - ENV_OWNED_BY_THE_FIXTURE == set(mc.ENV_NAMES)


# ------------------------------------------------------------------- failure recording


def _build_with(env, on_error, **kwargs):
    return mc.build(PROMPT, str(env.project()), "sess-x", env=dict(os.environ),
                    home=str(env.home), on_error=on_error, **kwargs)


def test_x1_a_programming_error_in_build_is_reported_once_and_returns_none(memory_context_env,
                                                                           monkeypatch):
    env = memory_context_env
    monkeypatch.setattr(mc, "_REPORTED", set())

    def broken(_prompt):
        raise NameError("x1-never-logged")
    monkeypatch.setattr(mc, "should_enrich", broken)
    seen = []

    def record(where):
        seen.append((where, sys.exc_info()[0]))

    assert _build_with(env, record) is None
    assert _build_with(env, record) is None

    assert seen == [("memory_context.build", NameError)]
    assert env.guards.spawns == []


@pytest.mark.parametrize("mode", FAILURE_MODES)
def test_x1_expected_runtime_failures_stay_unreported(memory_context_env, monkeypatch, mode):
    env = memory_context_env
    monkeypatch.setattr(mc, "_REPORTED", set())
    env.fake.mode(mode)
    seen = []

    assert _build_with(env, seen.append, budget=mc.Budget(0.5)) is None

    assert seen == []


def test_x1_an_os_error_is_an_expected_failure(memory_context_env, monkeypatch):
    env = memory_context_env
    monkeypatch.setattr(mc, "_REPORTED", set())

    def unreadable(*_args, **_kwargs):
        raise PermissionError("x1")
    monkeypatch.setattr(mc, "find_executable", unreadable)
    seen = []

    assert _build_with(env, seen.append) is None

    assert seen == []


# ------------------------------------------------------------------- interrupted open


def test_x3_an_interrupt_during_the_handshake_still_reaps_the_child(memory_context_env,
                                                                    monkeypatch):
    env = memory_context_env
    children = []

    def interrupted(self, _budget):
        children.append(self.process)
        raise KeyboardInterrupt
    monkeypatch.setattr(mc.RaccoonSession, "handshake", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            open_session(env)
        assert len(children) == 1
        assert children[0].poll() is not None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


# ------------------------------------------------------------------- child environment


def test_x7_the_proxy_child_gets_no_openrouter_key_or_memory_context_variables(
        memory_context_env, monkeypatch):
    env = memory_context_env
    seen = []
    spawn = subprocess.Popen

    class Capture(spawn):  # type: ignore[misc, valid-type]
        """Record the env each spawn is given."""

        def __init__(self, args, *rest, **kwargs):
            seen.append(kwargs.get("env"))
            super().__init__(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Capture)
    outer = dict(os.environ, OPENROUTER_API_KEY="sk-test-x7",
                 AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE="http://127.0.0.1:1",
                 AI_BADGER_MEMORY_CONTEXT_PIPELINE="0",
                 AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL="vendor/model")

    block = mc.build(PROMPT, str(env.project()), "sess-x7", env=outer, home=str(env.home))

    assert block is not None
    assert len(seen) == 1 and seen[0] is not None
    assert "OPENROUTER_API_KEY" not in seen[0]
    assert [k for k in seen[0] if k.startswith("AI_BADGER_MEMORY_CONTEXT_")] == []
    assert seen[0]["PATH"] == outer["PATH"]
    assert seen[0]["FAKE_RACCOON_MODE"] == outer["FAKE_RACCOON_MODE"]


# ------------------------------------------------------------------- relative PATH entries


def test_x9_a_relative_path_entry_is_never_searched(memory_context_env, tmp_path, monkeypatch):
    env = memory_context_env
    work = tmp_path / "work"
    relbin = work / "relbin"
    relbin.mkdir(parents=True)
    planted = relbin / "ai-raccoon"
    planted.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    planted.chmod(0o755)
    monkeypatch.chdir(work)
    nohome = str(tmp_path / "nohome")

    assert mc.find_executable({"PATH": "relbin"}, nohome) is None
    assert mc.find_executable({"PATH": os.pathsep.join([".", "relbin"])}, nohome) is None
    assert mc.find_executable({"PATH": os.pathsep.join(["relbin", str(env.fake.bin_dir)])},
                              nohome) == str(env.fake.path)
