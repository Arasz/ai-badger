"""memory_context's use of the session broker: broker first, per-call spawn as the fallback."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from memory_context_support import load_module, memory_context_env  # noqa: F401  # fixture

mc = load_module()
SESSION = "sess-client-1"
PROJECT = "proj-123"


@pytest.fixture
def short_home(monkeypatch):
    """A short HOME so the broker socket path fits the unix-socket limit."""
    root = Path(tempfile.mkdtemp(prefix="bc", dir="/tmp" if os.path.isdir("/tmp") else None))
    monkeypatch.setenv("HOME", str(root))
    yield root
    shutil.rmtree(root, ignore_errors=True)


class StubBroker:
    """A minimal broker: answers every call line with one canned MCP reply."""

    def __init__(self, home: Path, session: str, text: str):
        directory = home / ".ai-badger" / "memory-broker"
        directory.mkdir(parents=True, mode=0o700)
        self.path = directory / f"{session}.sock"
        self.requests = []
        self.text = text
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.path))
        self.server.listen(8)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                if data:
                    self.requests.append(json.loads(data.split(b"\n")[0]))
                reply = {"jsonrpc": "2.0", "id": 1, "result": {"content": [
                    {"type": "text", "text": self.text}]}}
                conn.sendall(json.dumps({"ok": True, "reply": reply}).encode() + b"\n")

    def close(self):
        """Stop listening."""
        self.server.close()


def broker_hits(snippet):
    return json.dumps({"data": {"results": [{"hash": "b", "path": "/broker.md",
                                             "snippet": snippet}], "code": []}})


def search(env, session=SESSION, budget=5.0):
    return mc.search_block("alpha beta", PROJECT, session, mc.Budget(budget),
                           env=dict(os.environ), home=str(env.home))


def test_no_socket_falls_back_to_the_per_call_spawn(memory_context_env, short_home):
    block = search(memory_context_env)
    assert block and "Memory context" in block
    assert len(memory_context_env.fake.runs()) == 1


def test_stale_socket_falls_back_and_is_removed(memory_context_env, short_home):
    directory = short_home / ".ai-badger" / "memory-broker"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / f"{SESSION}.sock"
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(str(path))
    dead.close()
    block = search(memory_context_env)
    assert block and "Memory context" in block
    assert len(memory_context_env.fake.runs()) == 1
    assert not path.exists()


def test_live_broker_answers_without_spawning_a_proxy(memory_context_env, short_home):
    stub = StubBroker(short_home, SESSION, broker_hits("from the broker"))
    try:
        block = search(memory_context_env)
    finally:
        stub.close()
    assert block and "from the broker" in block
    assert memory_context_env.fake.runs() == []
    sent = stub.requests[0]
    assert sent["op"] == "call" and sent["method"] == "tools/call"
    assert sent["params"]["name"] == "query"
    assert sent["params"]["arguments"]["projectId"] == PROJECT


def test_broker_that_answers_garbage_falls_back(memory_context_env, short_home):
    stub = StubBroker(short_home, SESSION, "not json")
    try:
        block = search(memory_context_env)
    finally:
        stub.close()
    assert block and "Memory context" in block
    assert len(memory_context_env.fake.runs()) == 1


def test_the_broker_is_keyed_by_session(memory_context_env, short_home):
    stub = StubBroker(short_home, "other-session", broker_hits("other"))
    try:
        block = search(memory_context_env)
    finally:
        stub.close()
    assert block and "other" not in block
    assert len(memory_context_env.fake.runs()) == 1


def test_build_uses_the_broker_for_the_single_search(memory_context_env, short_home):
    stub = StubBroker(short_home, SESSION, broker_hits("built via broker"))
    env = memory_context_env
    try:
        block = mc.build("why does the memory context hook stay silent on every prompt",
                         str(env.project()), SESSION, env=dict(os.environ), home=str(env.home))
    finally:
        stub.close()
    assert block and "built via broker" in block
    assert env.fake.runs() == []


def test_a_refused_connect_falls_back_instead_of_raising(memory_context_env, short_home,
                                                         monkeypatch):
    directory = short_home / ".ai-badger" / "memory-broker"
    directory.mkdir(parents=True, mode=0o700)
    (directory / f"{SESSION}.sock").write_text("", encoding="utf-8")

    def refuse(self, address):
        raise PermissionError("denied")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    block = search(memory_context_env)
    assert block and "Memory context" in block
    assert len(memory_context_env.fake.runs()) == 1
