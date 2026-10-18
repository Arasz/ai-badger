"""mcp_client.py: a stdlib MCP client that asks a server for its own tools (stdio + HTTP).

`--discover` used to depend on `hermes mcp test`; with hermes absent every server the listing
named without tools stayed `tools: {}`. These tests drive the client against a scripted stdio
server (tests/mcp_fake_server.py) and a threaded `http.server`, so each protocol rule the plan
names — initialize handshake, pagination, noise, server-initiated requests, deadlines, session
headers, no redirects — has a test that goes red when the rule is broken.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MODULE = "features/common/skills/mcp-index/scripts/mcp_client.py"
FAKE = str(Path(__file__).resolve().parent / "mcp_fake_server.py")


@pytest.fixture(name="mc")
def _mc(load_script):
    return load_script(MODULE)


def _stdio(mode, **extra):
    return {"command": sys.executable, "args": [FAKE, mode], **extra}


# ── stdio ────────────────────────────────────────────────────────────────────

def test_stdio_follows_pagination_through_noise_and_server_requests(mc):
    tools = mc.list_tools(_stdio("ok"), timeout=10)

    assert tools == [{"name": "alpha", "description": "First tool."},
                     {"name": "beta", "description": ""}]


def test_stdio_passes_config_env_with_expansion(mc, monkeypatch):
    monkeypatch.setenv("FAKE_BASE", "from-env")
    spec = _stdio("solo", env={"FAKE_SOLO_NAME": "${FAKE_BASE}-${FAKE_MISSING:-dflt}"})

    assert [t["name"] for t in mc.list_tools(spec, timeout=10)] == ["from-env-dflt"]


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_stdio_hang_times_out_and_leaves_no_child_or_grandchild(mc, tmp_path):
    """npx/uvx-style launchers fork the real server; killing only the direct child leaks it."""
    pids = tmp_path / "pids"
    started = time.monotonic()
    with pytest.raises(mc.Timeout):
        mc.list_tools(_stdio("hang", env={"FAKE_PID_FILE": str(pids)}), timeout=1)
    assert time.monotonic() - started < 5

    child, grandchild = (int(p) for p in pids.read_text(encoding="utf-8").split())
    give_up = time.monotonic() + 3
    while (_alive(child) or _alive(grandchild)) and time.monotonic() < give_up:
        time.sleep(0.05)
    assert not _alive(child) and not _alive(grandchild)


def test_stdio_exit_wait_never_runs_past_the_deadline(mc, monkeypatch):
    monkeypatch.setattr(mc, "GRACE_SECONDS", 5)
    session = mc._Stdio(_stdio("close-stdout"), time.monotonic() + 0.3, None)  # pylint: disable=protected-access
    try:
        while session.stdout.get(timeout=5) is not None:
            pass
        started = time.monotonic()
        session._exited()  # pylint: disable=protected-access
        assert time.monotonic() - started < 1
    finally:
        monkeypatch.setattr(mc, "GRACE_SECONDS", 0.5)
        session.close()


def test_stdio_an_oversized_line_is_response_too_large(mc, monkeypatch):
    monkeypatch.setattr(mc, "MAX_MESSAGE_BYTES", 1024)
    with pytest.raises(mc.McpClientError, match="response too large"):
        mc.list_tools(_stdio("big"), timeout=10)


def test_stdio_early_exit_reports_the_last_stderr_line(mc):
    with pytest.raises(mc.McpClientError) as caught:
        mc.list_tools(_stdio("exit"), timeout=10)

    assert "exit" in str(caught.value) and "database is locked" in str(caught.value)
    assert "\n" not in str(caught.value)


def test_stdio_a_chatty_stderr_does_not_deadlock(mc):
    started = time.monotonic()
    assert [t["name"] for t in mc.list_tools(_stdio("chatty"), timeout=10)] == ["solo"]
    assert time.monotonic() - started < 8


def test_stdio_an_error_mid_pagination_is_an_error_not_a_partial_list(mc):
    with pytest.raises(mc.McpClientError, match="backend went away"):
        mc.list_tools(_stdio("page-error"), timeout=10)


def test_stdio_a_cursor_loop_stops_at_the_page_cap(mc, monkeypatch):
    monkeypatch.setattr(mc, "PAGE_CAP", 5)
    with pytest.raises(mc.McpClientError, match="5 pages"):
        mc.list_tools(_stdio("loop"), timeout=10)


def test_stdio_a_missing_command_is_a_one_line_failure(mc):
    with pytest.raises(mc.McpClientError, match="not found"):
        mc.list_tools({"command": "/nonexistent/mcp-server-binary"}, timeout=5)


def test_sse_transport_is_named_unsupported(mc):
    with pytest.raises(mc.McpClientError, match="sse"):
        mc.list_tools({"type": "sse", "url": "http://127.0.0.1:1/sse"}, timeout=5)


# ── streamable HTTP ──────────────────────────────────────────────────────────

class _Fake:
    """Behaviour and a request log shared with the handler."""

    def __init__(self, mode):
        self.mode = mode
        self.requests = []


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep pytest output clean
            pass

        def _reply(self, status, body=b"", ctype="application/json", headers=()):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_DELETE(self):  # noqa: N802
            fake.requests.append(("DELETE", dict(self.headers), None))
            self._reply(200)

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.requests.append(("POST", dict(self.headers), body))
            if fake.mode == "401":
                return self._reply(401, b"{}")
            if fake.mode == "redirect":
                return self._reply(307, headers=[("Location", fake.redirect_to)])
            method = body.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {}}
                return self._reply(200, json.dumps(
                    {"jsonrpc": "2.0", "id": body["id"], "result": result}).encode(),
                    headers=[("Mcp-Session-Id", "s-1")])
            if self.headers.get("Mcp-Session-Id") != "s-1":
                return self._reply(400, b'{"error":"no session"}')
            if method is None:  # the client's reply to a server-initiated request
                return self._reply(202)
            if method == "notifications/initialized":
                return self._reply(202)
            result = {"tools": [{"name": "remote", "description": "Remote tool."}]}
            if fake.mode.endswith("big"):
                result["pad"] = "x" * 4096
            reply = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
            if fake.mode == "sse-chatty":
                events = ["data: not json at all",
                          "data: " + json.dumps({"jsonrpc": "2.0", "id": "srv-1",
                                                 "method": "ping"}),
                          "data: " + json.dumps({"jsonrpc": "2.0", "id": "srv-2",
                                                 "method": "sampling/createMessage"})]
                stream = "\n\n".join(events) + "\n\ndata: " + reply  # no trailing blank line
                return self._reply(200, stream.encode(), ctype="text/event-stream")
            if fake.mode in ("sse", "sse-big"):
                note = json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"})
                stream = f"event: message\ndata: {note}\n\nevent: message\ndata: {reply}\n\n"
                return self._reply(200, stream.encode(), ctype="text/event-stream")
            return self._reply(200, reply.encode())

    return Handler


@pytest.fixture(name="serve")
def _serve():
    servers = []

    def start(mode):
        fake = _Fake(mode)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        fake.url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
        return fake

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_http_lists_tools_from_json_or_sse_replies(mc, serve, mode):
    fake = serve(mode)

    tools = mc.list_tools({"type": "http", "url": fake.url}, timeout=10)

    assert tools == [{"name": "remote", "description": "Remote tool."}]


def test_http_echoes_session_and_protocol_headers_and_deletes_the_session(mc, serve):
    fake = serve("json")

    mc.list_tools({"type": "http", "url": fake.url}, timeout=10)

    posts = [r for r in fake.requests if r[0] == "POST"]
    later = [headers for _, headers, _ in posts[1:]]
    assert all(h.get("Mcp-Session-Id") == "s-1" for h in later)
    assert all(h.get("Mcp-Protocol-Version") == "2025-03-26" for h in later)
    assert "text/event-stream" in posts[0][1]["Accept"]
    assert any(r[0] == "DELETE" for r in fake.requests)


def test_http_sends_expanded_config_headers(mc, serve, monkeypatch):
    fake = serve("json")
    monkeypatch.setenv("FAKE_TOKEN", "abc")

    mc.list_tools({"type": "http", "url": fake.url,
                   "headers": {"X-Key": "${FAKE_TOKEN}"}}, timeout=10)

    assert fake.requests[0][1]["X-Key"] == "abc"


def test_http_401_is_needs_authorization(mc, serve):
    fake = serve("401")

    with pytest.raises(mc.Unauthorized, match="needs authorization"):
        mc.list_tools({"type": "http", "url": fake.url}, timeout=10)


def test_http_never_follows_a_redirect_with_config_headers(mc, serve):
    elsewhere = serve("json")
    fake = serve("redirect")
    fake.redirect_to = elsewhere.url

    with pytest.raises(mc.McpClientError, match="redirect"):
        mc.list_tools({"type": "http", "url": fake.url,
                       "headers": {"Authorization": "Bearer secret"}}, timeout=10)

    assert elsewhere.requests == []


def test_http_sse_answers_server_requests_skips_noise_and_flushes_the_last_event(mc, serve):
    fake = serve("sse-chatty")

    tools = mc.list_tools({"type": "http", "url": fake.url}, timeout=10)

    assert [t["name"] for t in tools] == ["remote"]
    replies = {b["id"]: b for _, _, b in fake.requests if b and "method" not in b}
    assert replies["srv-1"]["result"] == {}
    assert replies["srv-2"]["error"]["code"] == -32601


@pytest.mark.parametrize("mode", ["big", "sse-big"])
def test_http_an_oversized_reply_is_response_too_large(mc, serve, monkeypatch, mode):
    monkeypatch.setattr(mc, "MAX_MESSAGE_BYTES", 1024)
    fake = serve(mode)

    with pytest.raises(mc.McpClientError, match="response too large"):
        mc.list_tools({"type": "http", "url": fake.url}, timeout=10)
