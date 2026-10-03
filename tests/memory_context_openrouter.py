"""Fake OpenRouter servers for the openrouter_client tests: plain HTTP, TLS, a TLS-handshake drip,
and an HTTP CONNECT proxy.

`FakeOpenRouter` scripts replies per route and records every request; a second instance serves as
the capture server that must never be reached. `CaptureProxy` records every CONNECT and relays it
to one fixed loopback port. Every blocking behaviour ends by `FAKE_CEILING_SECONDS` (the proxy by
`PROXY_CEILING_SECONDS`) or when the server stops, so no mutant can hang the suite.
"""
from __future__ import annotations

import json
import select
import shutil
import socket
import ssl
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from memory_context_support import FAKE_CEILING_SECONDS, LOOPBACK

CHAT_PATH = "/api/v1/chat/completions"
DECISIONS_PATH = "/api/alpha/decisions"
DRIP_SECONDS = 0.05
PROXY_CEILING_SECONDS = 3.0
PROXY_THREAD = "fake-capture-proxy"
READ_SIZE = 64 * 1024
DECIDER_HOST = "decider.test"
OPENSSL = shutil.which("openssl")


@dataclass
class Step:
    """One scripted reply: a plain response, or a behaviour (`hang`, `header-drip`,
    `body-drip`, `oversize`, `redirect`, `close`)."""

    behaviour: str = "reply"
    status: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b"{}"
    size: int = 0
    location: str = ""


def reply(status: int = 200, body: bytes = b"{}", headers: Optional[Dict[str, str]] = None) -> Step:
    """A plain response."""
    return Step(status=status, body=body, headers=dict(headers or {}))


def redirect(code: int, location: str) -> Step:
    """A redirect to *location*."""
    return Step("redirect", status=code, location=location)


def oversize(size: int) -> Step:
    """A 200 whose body is *size* bytes."""
    return Step("oversize", size=size)


def behaviour(name: str) -> Step:
    """`hang`, `header-drip`, `body-drip` or `close`."""
    return Step(name)


class _Handler(BaseHTTPRequestHandler):
    # pylint: disable=attribute-defined-outside-init
    server: "_Server"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # pylint: disable=arguments-differ
        return

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw
        self.server.owner.requests.append({
            "method": self.command, "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()}, "body": parsed})

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Record, then answer with the next step."""
        self._record()
        self._answer(self.server.owner.next_step(self.path))

    do_POST = do_GET

    def _answer(self, step: Step) -> None:
        owner = self.server.owner
        if step.behaviour == "hang":
            owner.stopping.wait(owner.ceiling)
            return
        if step.behaviour == "close":
            self.close_connection = True
            return
        if step.behaviour == "redirect":
            self._head(step.status, {"Location": step.location, "Content-Length": "2"})
            self.wfile.write(b"{}")
            return
        if step.behaviour == "oversize":
            self._head(200, {"Content-Type": "application/json", "Content-Length": str(step.size)})
            self._send(b"x" * step.size)
            return
        if step.behaviour == "header-drip":
            head = (b"HTTP/1.1 200 OK\r\n" + b"".join(b"X-Pad-%d: v\r\n" % i for i in range(400))
                    + b"Content-Length: 2\r\n\r\n{}")
            self._drip(head)
            return
        if step.behaviour == "body-drip":
            self._head(200, {"Content-Type": "application/json", "Content-Length": "4000"})
            self._drip(b"x" * 4000)
            return
        self._head(step.status, {"Content-Type": "application/json",
                                 "Content-Length": str(len(step.body)), **step.headers})
        self._send(step.body)

    def _head(self, status: int, headers: Dict[str, str]) -> None:
        self.send_response_only(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()

    def _send(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
        except OSError:
            self.close_connection = True

    def _drip(self, data: bytes) -> None:
        owner = self.server.owner
        self.wfile.flush()
        end = time.monotonic() + owner.ceiling
        for index in range(len(data)):
            if owner.stopping.is_set() or time.monotonic() > end:
                break
            try:
                self.connection.sendall(data[index:index + 1])
            except OSError:
                break
            owner.stopping.wait(DRIP_SECONDS)
        self.close_connection = True


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, owner: "FakeOpenRouter", tls: Optional[ssl.SSLContext]):
        self.owner = owner
        self.tls = tls
        if tls is not None:
            tls.sni_callback = self._record_sni
        super().__init__((LOOPBACK, 0), _Handler)

    def _record_sni(self, _sock, server_name, _context) -> None:
        self.owner.sni.append(server_name)

    def get_request(self):
        sock, address = super().get_request()
        self.owner.connections += 1
        if self.tls is not None:
            sock = self.tls.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, address

    def handle_error(self, request, client_address) -> None:
        return


class FakeOpenRouter:
    """A scripted OpenRouter on 127.0.0.1; `tls` wraps it with a server context and records the
    server name each TLS client sent (`None` when it sent none)."""

    def __init__(self, tls: Optional[ssl.SSLContext] = None, ceiling: float = FAKE_CEILING_SECONDS):
        self.ceiling = ceiling
        self.requests: List[dict] = []
        self.sni: List[Optional[str]] = []
        self.connections = 0
        self.stopping = threading.Event()
        self.scripts: Dict[str, List[Step]] = {}
        self.server = _Server(self, tls)
        self.thread = threading.Thread(target=self.server.serve_forever, name="fake-openrouter",
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        """The bound port."""
        return self.server.server_address[1]

    @property
    def url(self) -> str:
        """`http://127.0.0.1:<port>` (`https` when wrapped)."""
        scheme = "https" if self.server.tls is not None else "http"
        return f"{scheme}://{LOOPBACK}:{self.port}"

    def script(self, path: str, *steps: Step) -> None:
        """Queue *steps* for *path*; an empty queue answers `reply()`."""
        self.scripts.setdefault(path, []).extend(steps)

    def next_step(self, path: str) -> Step:
        """The next scripted step for *path*."""
        queue = self.scripts.get(path)
        return queue.pop(0) if queue else reply()

    def stop(self) -> None:
        """End every blocking behaviour, stop serving and join the handler threads."""
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(self.ceiling)


class DripTcp:
    """A TCP listener that answers every connection by dripping a TLS record header."""

    def __init__(self, ceiling: float = FAKE_CEILING_SECONDS):
        self.ceiling = ceiling
        self.stopping = threading.Event()
        self.connections = 0
        self.listener = socket.socket()
        self.listener.bind((LOOPBACK, 0))
        self.listener.listen(4)
        self.listener.settimeout(0.05)
        self.thread = threading.Thread(target=self._serve, name="fake-drip-tcp", daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        """The bound port."""
        return self.listener.getsockname()[1]

    def _serve(self) -> None:
        end = time.monotonic() + self.ceiling
        while not self.stopping.is_set() and time.monotonic() < end:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                continue
            self.connections += 1
            with conn:
                record = b"\x16\x03\x03\x40\x00" + b"\x02" * 4096
                for index in range(len(record)):
                    if self.stopping.is_set() or time.monotonic() > end:
                        break
                    try:
                        conn.sendall(record[index:index + 1])
                    except OSError:
                        break
                    self.stopping.wait(DRIP_SECONDS)

    def stop(self) -> None:
        """End the drip and close the listener."""
        self.stopping.set()
        self.thread.join(self.ceiling)
        self.listener.close()


class _ProxyHandler(BaseHTTPRequestHandler):
    # pylint: disable=attribute-defined-outside-init
    server: "_ProxyServer"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # pylint: disable=arguments-differ
        return

    def parse_request(self) -> bool:
        parsed = super().parse_request()
        if parsed and self.command != "CONNECT":
            self.server.owner.violations.append(f"non-CONNECT request: {self.requestline}")
            self.close_connection = True
            return False
        return parsed

    def do_CONNECT(self) -> None:  # pylint: disable=invalid-name
        """Record the CONNECT, then relay, refuse or hang as the owner's mode says."""
        owner = self.server.owner
        owner.connects.append({"line": self.requestline,
                               "headers": {k.lower(): v for k, v in self.headers.items()}})
        self.close_connection = True
        if owner.mode == "refuse":
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        if owner.mode == "hang":
            owner.stopping.wait(owner.ceiling)
            return
        upstream = None
        try:
            upstream = socket.create_connection((LOOPBACK, owner.upstream_port),
                                                timeout=owner.ceiling)
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self._relay(upstream)
        except BaseException as err:  # pylint: disable=broad-except
            owner.violations.append(f"relay: {type(err).__name__}")
        finally:
            if upstream is not None:
                upstream.close()
            _close_quietly(self.connection)

    def _relay(self, upstream: socket.socket) -> None:
        owner = self.server.owner
        pair = {self.connection: upstream, upstream: self.connection}
        end = time.monotonic() + owner.ceiling
        while not owner.stopping.is_set() and time.monotonic() < end:
            ready, _, _ = select.select(list(pair), [], [], DRIP_SECONDS)
            for sock in ready:
                try:
                    data = sock.recv(READ_SIZE)
                    if data:
                        pair[sock].sendall(data)
                except OSError:
                    data = b""
                if not data:
                    return


def _close_quietly(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, owner: "CaptureProxy"):
        self.owner = owner
        self.handlers: List[threading.Thread] = []
        super().__init__((LOOPBACK, 0), _ProxyHandler)

    def process_request(self, request, client_address) -> None:
        thread = threading.Thread(target=self.process_request_thread,
                                  args=(request, client_address),
                                  name=f"{PROXY_THREAD}-handler", daemon=True)
        self.handlers.append(thread)
        thread.start()

    def handle_error(self, request, client_address) -> None:
        self.owner.violations.append("handler error")


class CaptureProxy:
    """An HTTP CONNECT proxy on 127.0.0.1 that records each CONNECT's request line and headers.

    `relay` answers 200 and relays raw bytes to `127.0.0.1:<upstream_port>`, dialled at call time
    (never the CONNECT target); `refuse` answers 403; `hang` holds the connection until it stops
    or `ceiling` passes. Anything that is not a CONNECT, and any failed dial, is a violation.
    """

    def __init__(self, upstream_port: int = 0, mode: str = "relay",
                 ceiling: float = PROXY_CEILING_SECONDS):
        self.upstream_port = upstream_port
        self.mode = mode
        self.ceiling = ceiling
        self.connects: List[dict] = []
        self.violations: List[str] = []
        self.stopping = threading.Event()
        self.server = _ProxyServer(self)
        self.thread = threading.Thread(target=self.server.serve_forever, name=PROXY_THREAD,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        """`http://127.0.0.1:<port>`."""
        return f"http://{LOOPBACK}:{self.server.server_address[1]}"

    def stop(self) -> None:
        """End every blocking behaviour, stop serving and join the handler threads."""
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(self.ceiling)
        for thread in self.server.handlers:
            thread.join(self.ceiling)


def make_certificate(directory: Path) -> Optional[Tuple[Path, Path]]:
    """A throwaway self-signed EC certificate for IP 127.0.0.1 and `decider.test`; `None`
    without `openssl`."""
    if OPENSSL is None:
        return None
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [OPENSSL, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=127.0.0.1",
         "-addext", f"subjectAltName=IP:127.0.0.1,DNS:{DECIDER_HOST}",
         "-addext", "keyUsage=critical,digitalSignature,keyCertSign",
         "-addext", "extendedKeyUsage=serverAuth"],
        check=True, capture_output=True, timeout=FAKE_CEILING_SECONDS)
    return cert, key


def server_context(cert: Path, key: Path) -> ssl.SSLContext:
    """A server-side TLS context for the throwaway certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    return context
