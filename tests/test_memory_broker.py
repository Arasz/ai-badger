"""The per-session memory broker: one proxy per session, many concurrent searches over it.

Every test runs the broker against tests/fixtures/memory_broker/fake_proxy.py, which answers
tools/call requests concurrently and out of order, under a short temp HOME (a unix socket path
is capped near 104 bytes).
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "features" / "common" / "skills" / "ai-raccoon-memory" / "scripts"
FAKE = ROOT / "tests" / "fixtures" / "memory_broker" / "fake_proxy.py"
# A unix socket path is capped near 104 bytes; macOS tempdirs alone nearly fill that.
_SHORT_TMP = "/tmp" if os.path.isdir("/tmp") else None
SESSION = "sess-broker-1"
PROJECT = "proj-1"


def _load(stem: str):
    key = "ai_badger_test_" + stem
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{stem}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


mc = _load("memory_context")
broker = _load("memory_broker")


class Rig:
    """A temp HOME, an executable fake proxy, and helpers to run a broker thread over it."""

    def __init__(self, root: Path):
        self.home = root / "h"
        self.home.mkdir()
        self.exe = root / "ai-raccoon"
        self.exe.write_text(f"#!{sys.executable}\n" + FAKE.read_text(encoding="utf-8"),
                            encoding="utf-8")
        self.exe.chmod(0o755)
        self.log = root / "fake.log"
        self.threads = []
        self.brokers = []

    def starts(self) -> int:
        """How many fake proxy processes were spawned."""
        if not self.log.exists():
            return 0
        return len(self.log.read_text(encoding="utf-8").splitlines())

    def open_session(self, budget):
        """What the broker calls to (re)open its proxy."""
        return mc.RaccoonSession.open(str(self.exe), PROJECT, SESSION, budget, dict(os.environ))

    def start(self, session=SESSION, idle=1800.0) -> "broker.Broker":
        """Run a broker in a thread and wait until its socket answers."""
        instance = broker.Broker(session, str(self.home), self.open_session, idle_seconds=idle)
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        self.threads.append(thread)
        self.brokers.append(instance)
        deadline = time.monotonic() + 15
        while not broker.is_live(session, str(self.home)):
            assert time.monotonic() < deadline, "broker never came up"
            time.sleep(0.01)
        return instance

    def search(self, query: str, seconds: float = 5.0, session=SESSION):
        """One query through the broker; the raw reply, or None."""
        params = {"name": "query", "arguments": {
            "projectId": PROJECT, "sessionId": session, "query": query, "limit": 5,
            "scope": "project"}}
        return broker.call(session, "tools/call", params, seconds, str(self.home))

    def stop(self):
        """Stop every broker and join its thread."""
        for instance in self.brokers:
            instance.stop()
        for thread in self.threads:
            thread.join(5)


@pytest.fixture
def rig(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="bk", dir=_SHORT_TMP))
    monkeypatch.setenv("FAKE_PROXY_LOG", str(root / "fake.log"))
    monkeypatch.setenv("FAKE_PROXY_DELAY", "0.4")
    monkeypatch.setenv("HOME", str(root / "h"))
    made = Rig(root)
    yield made
    made.stop()
    shutil.rmtree(root, ignore_errors=True)


def echoed(reply) -> str:
    """The query a fake reply echoes back, '' when the reply carries none."""
    hits = mc.parse_search_reply(reply)
    return hits.mem[0]["snippet"][len("echo "):] if hits and hits.mem else ""


# ------------------------------------------------------------------ parallel searches


def test_concurrent_requests_share_one_proxy_and_overlap(rig):
    rig.start()
    count = 8
    started = time.monotonic()
    with ThreadPoolExecutor(count) as pool:
        replies = list(pool.map(lambda i: rig.search(f"q{i}"), range(count)))
    elapsed = time.monotonic() - started
    assert [echoed(r) for r in replies] == [f"q{i}" for i in range(count)]
    assert elapsed < count * 0.4 * 0.5, f"{count} requests took {elapsed:.2f}s: serialized"
    assert rig.starts() == 1


def test_replies_route_by_id_when_the_proxy_answers_out_of_order(rig):
    rig.start()
    queries = ["slow:1.0:first", "slow:0.1:second", "slow:0.5:third"]
    with ThreadPoolExecutor(3) as pool:
        replies = list(pool.map(rig.search, queries))
    assert [echoed(r) for r in replies] == ["first", "second", "third"]


def test_a_client_that_times_out_does_not_break_the_next_request(rig):
    rig.start()
    assert rig.search("slow:2.0:late", seconds=0.3) is None
    assert echoed(rig.search("after")) == "after"
    time.sleep(2.0)  # the late reply lands on a removed waiter and is dropped
    assert echoed(rig.search("still-fine")) == "still-fine"
    assert rig.starts() == 1


def test_a_client_that_hangs_up_does_not_break_the_next_request(rig):
    rig.start()
    sock = broker.open_socket(SESSION, str(rig.home))
    sock.sendall(json.dumps({"op": "call", "method": "tools/call", "seconds": 5, "params": {
        "name": "query", "arguments": {"query": "slow:1.0:gone"}}}).encode() + b"\n")
    sock.close()
    assert echoed(rig.search("next")) == "next"


# ------------------------------------------------------------------ proxy lifecycle


def test_a_dead_proxy_is_reopened_lazily_on_the_next_request(rig):
    rig.start()
    assert echoed(rig.search("one")) == "one"
    assert rig.search("die", seconds=3.0) is None
    assert echoed(rig.search("two")) == "two"
    assert rig.starts() == 2


def test_the_proxy_is_warmed_at_start_and_not_reopened_per_request(rig):
    rig.start()
    deadline = time.monotonic() + 15
    while rig.starts() == 0:
        assert time.monotonic() < deadline, "the broker never opened its proxy"
        time.sleep(0.02)
    assert echoed(rig.search("first")) == "first"
    assert echoed(rig.search("second")) == "second"
    assert rig.starts() == 1


# ------------------------------------------------------------------ socket hygiene


def test_directory_is_owner_only_and_socket_is_0600(rig):
    rig.start()
    path = broker.socket_path(SESSION, str(rig.home))
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_session_ids_are_sanitised_and_long_ids_still_fit_a_socket(rig):
    nasty = broker.socket_path("../../etc/passwd", str(rig.home))
    assert nasty.parent == broker.socket_path("x", str(rig.home)).parent
    assert "/" not in nasty.name
    long = broker.socket_path("s" * 300, str(rig.home))
    assert len(os.fsencode(str(long))) < 104


def test_safe_session_matches_the_gate_copy():
    gate = _load("memory_first_gate")
    for raw in ("abc-123", "a/b", "..", ".", "é", "x" * 20, None, ""):
        assert broker.safe_session(raw) == gate._safe_session(raw)  # pylint: disable=protected-access


def test_no_socket_is_unavailable(rig):
    with pytest.raises(broker.Unavailable):
        rig.search("x")


def test_a_stale_socket_file_is_unavailable_and_removed(rig):
    import socket as sk  # pylint: disable=import-outside-toplevel
    path = broker.socket_path(SESSION, str(rig.home))
    path.parent.mkdir(parents=True, mode=0o700)
    dead = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
    dead.bind(str(path))
    dead.close()  # the file stays, nothing listens
    assert path.exists()
    with pytest.raises(broker.Unavailable):
        rig.search("x")
    assert not path.exists()


def test_a_second_broker_for_the_same_session_yields_to_the_first(rig):
    rig.start()
    second = broker.Broker(SESSION, str(rig.home), rig.open_session)
    started = time.monotonic()
    second.serve_forever()  # returns at once: the first holds the lock
    assert time.monotonic() - started < 2
    assert echoed(rig.search("still-first")) == "still-first"


def test_a_stale_socket_does_not_block_a_new_broker(rig):
    import socket as sk  # pylint: disable=import-outside-toplevel
    path = broker.socket_path(SESSION, str(rig.home))
    path.parent.mkdir(parents=True, mode=0o700)
    dead = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
    dead.bind(str(path))
    dead.close()
    rig.start()
    assert echoed(rig.search("fresh")) == "fresh"


# ------------------------------------------------------------------ exit paths


def test_idle_timeout_ends_the_broker_and_removes_the_socket(rig):
    rig.start(idle=0.5)
    path = broker.socket_path(SESSION, str(rig.home))
    rig.threads[0].join(5)
    assert not rig.threads[0].is_alive()
    assert not path.exists()


def test_activity_defers_the_idle_exit(rig):
    rig.start(idle=1.2)
    for _ in range(4):
        time.sleep(0.5)
        assert echoed(rig.search("tick", seconds=3)) == "tick"
    assert rig.threads[0].is_alive()


def test_shutdown_request_ends_the_broker_and_removes_the_socket(rig):
    rig.start()
    rig.search("warm")
    assert broker.shutdown(SESSION, str(rig.home)) is True
    rig.threads[0].join(5)
    assert not rig.threads[0].is_alive()
    assert not broker.socket_path(SESSION, str(rig.home)).exists()
    assert broker.shutdown(SESSION, str(rig.home)) is False


# ------------------------------------------------------------------ hooks, end to end


def run_hook(rig, event, session=SESSION):
    """Run memory_broker_hook.py with a Claude-shaped payload under the rig's env."""
    env = dict(os.environ, HOME=str(rig.home), PATH=str(rig.exe.parent) + os.pathsep
               + os.environ.get("PATH", ""))
    payload = {"hook_event_name": event, "session_id": session, "cwd": str(rig.home)}
    return subprocess.run([sys.executable, str(SCRIPTS / "memory_broker_hook.py")],
                          input=json.dumps(payload), text=True, capture_output=True,
                          env=env, timeout=20, check=False)


def test_session_start_hook_spawns_a_detached_broker_and_session_end_stops_it(rig):
    started = time.monotonic()
    result = run_hook(rig, "SessionStart")
    assert result.returncode == 0 and result.stdout == ""
    assert time.monotonic() - started < 5, "the hook must not wait for the broker"
    deadline = time.monotonic() + 10
    while not broker.is_live(SESSION, str(rig.home)):
        assert time.monotonic() < deadline, "detached broker never came up"
        time.sleep(0.05)
    assert echoed(rig.search("via-hook")) == "via-hook"
    assert run_hook(rig, "SessionStart").returncode == 0  # idempotent: one broker
    assert run_hook(rig, "SessionEnd").returncode == 0
    deadline = time.monotonic() + 10
    while broker.socket_path(SESSION, str(rig.home)).exists():
        assert time.monotonic() < deadline, "SessionEnd did not stop the broker"
        time.sleep(0.05)
    assert rig.starts() == 1


def test_hook_ignores_unknown_events_and_missing_session(rig):
    assert run_hook(rig, "PreToolUse").returncode == 0
    assert run_hook(rig, "SessionStart", session="").returncode == 0
    assert not broker.socket_path(SESSION, str(rig.home)).exists()


def test_hook_accepts_copilot_spellings(rig):
    assert run_hook(rig, "sessionStart").returncode == 0
    deadline = time.monotonic() + 10
    while not broker.is_live(SESSION, str(rig.home)):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert run_hook(rig, "sessionEnd").returncode == 0
