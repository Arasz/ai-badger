"""Shared hermetic fixtures for the memory-context tests: env scrub, guards, the fake proxy.

Import `memory_context_env` into a test module to make it autouse there. Every guard refusal is
recorded and raised as `GuardRefusal(BaseException)`; the fixture's teardown fails the test on
any record, so production code that catches the refusal cannot hide it.
"""
from __future__ import annotations

import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "features" / "common" / "skills" / "ai-raccoon-memory" / "scripts"
MODULE_PATH = SCRIPTS / "memory_context.py"
FIXTURES = ROOT / "tests" / "fixtures" / "memory_context"
FAKE_SOURCE = FIXTURES / "fake_ai_raccoon.py"

FAKE_CEILING_SECONDS = 20
PROXY_VARIABLES = tuple(name for base in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
                        for name in (base, base.upper()))
NET_MARKER_ENV = "AI_BADGER_TEST_NET_MARKER"
LOOPBACK = "127.0.0.1"


class GuardRefusal(BaseException):
    """A guard refused a spawn or a network call; never an `Exception`, so it is not swallowed."""


def _real_executables() -> frozenset:
    """Realpaths of the real ai-raccoon, captured before any test redirects PATH or HOME."""
    found = set()
    on_path = shutil.which("ai-raccoon")
    if on_path:
        found.add(os.path.realpath(on_path))
    home = pwd.getpwuid(os.getuid()).pw_dir
    found.add(os.path.realpath(os.path.join(home, ".dotnet", "tools", "ai-raccoon")))
    return frozenset(found)


REAL_EXECUTABLES = _real_executables()


class Guards:
    """Per-test record of spawns, network attempts and refusals."""

    def __init__(self, forbidden: frozenset, marker: Path):
        self.forbidden = forbidden
        self.marker = marker
        self.refusals: List[str] = []
        self.spawns: List[dict] = []
        self.net_attempts: List[object] = []

    def refuse(self, what: str) -> None:
        """Record the refusal, then raise it."""
        self.refusals.append(what)
        raise GuardRefusal(what)

    def take_refusals(self) -> List[str]:
        """Return and clear the refusals, and remove the subprocess marker."""
        taken = list(self.refusals)
        self.refusals.clear()
        if self.marker.exists():
            taken.append(f"subprocess marker: {self.marker.read_text(encoding='utf-8')}")
            self.marker.unlink()
        return taken


def assert_no_refusals(guards: Guards) -> None:
    """Fail the test when any guard refused anything, in-process or in a child."""
    problems = list(guards.refusals)
    if guards.marker.exists():
        problems.append(f"subprocess marker: {guards.marker.read_text(encoding='utf-8')}")
    if problems:
        pytest.fail("guard refusals: " + "; ".join(problems))


def _argv0(args) -> str:
    if isinstance(args, (str, bytes, os.PathLike)):
        return os.fsdecode(args)
    return os.fsdecode(list(args)[0])


def install_popen_guard(monkeypatch, guards: Guards) -> None:
    """Wrap `subprocess.Popen`: log every spawn, refuse a real ai-raccoon by realpath."""
    base = subprocess.Popen

    class GuardedPopen(base):  # type: ignore[misc, valid-type]
        """Popen that records argv and refuses the real executable."""

        def __init__(self, args, *rest, **kwargs):
            guards.spawns.append({"argv": [os.fsdecode(a) for a in
                                           ([args] if isinstance(args, (str, bytes)) else args)],
                                  "shell": kwargs.get("shell", False),
                                  "stderr": kwargs.get("stderr")})
            if os.path.realpath(_argv0(args)) in guards.forbidden:
                guards.refuse(f"spawn of real ai-raccoon: {_argv0(args)}")
            super().__init__(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)


def _loopback_address(address) -> bool:
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX: not the network
    return isinstance(address, tuple) and bool(address) and address[0] == LOOPBACK


def install_network_guard(monkeypatch, guards: Guards) -> None:
    """Refuse DNS for any host but 127.0.0.1 and any connect elsewhere, before a packet."""
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def getaddrinfo(host, *args, **kwargs):
        guards.net_attempts.append(("getaddrinfo", host))
        if host != LOOPBACK:
            guards.refuse(f"getaddrinfo {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self, address):
        guards.net_attempts.append(("connect", address))
        if not _loopback_address(address):
            guards.refuse(f"connect {address!r}")
        return real_connect(self, address)

    def connect_ex(self, address):
        guards.net_attempts.append(("connect_ex", address))
        if not _loopback_address(address):
            guards.refuse(f"connect_ex {address!r}")
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        guards.net_attempts.append(("create_connection", address))
        if not _loopback_address(address):
            guards.refuse(f"create_connection {address!r}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)


SITECUSTOMIZE = textwrap.dedent(f'''\
    """Test-only network guard for child interpreters: refuse and mark any non-loopback call."""
    import os
    import socket

    _MARKER = os.environ.get("{NET_MARKER_ENV}", "")


    class GuardRefusal(SystemExit):
        """Raised on a refused network call."""


    def _refuse(what):
        if _MARKER:
            with open(_MARKER, "a", encoding="utf-8") as handle:
                handle.write(what + "\\n")
        raise GuardRefusal(what)


    def _ok(address):
        if isinstance(address, (str, bytes)):
            return True
        return isinstance(address, tuple) and bool(address) and address[0] == "{LOOPBACK}"


    _getaddrinfo = socket.getaddrinfo
    _connect = socket.socket.connect
    _connect_ex = socket.socket.connect_ex
    _create = socket.create_connection


    def _guarded_getaddrinfo(host, *args, **kwargs):
        if host != "{LOOPBACK}":
            _refuse("getaddrinfo %r" % (host,))
        return _getaddrinfo(host, *args, **kwargs)


    def _guarded_connect(self, address):
        if not _ok(address):
            _refuse("connect %r" % (address,))
        return _connect(self, address)


    def _guarded_connect_ex(self, address):
        if not _ok(address):
            _refuse("connect_ex %r" % (address,))
        return _connect_ex(self, address)


    def _guarded_create(address, *args, **kwargs):
        if not _ok(address):
            _refuse("create_connection %r" % (address,))
        return _create(address, *args, **kwargs)


    socket.getaddrinfo = _guarded_getaddrinfo
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.create_connection = _guarded_create
''')


def env_names() -> tuple:
    """`memory_context.ENV_NAMES`, read from the module under test."""
    return load_module().ENV_NAMES


def scrub_env(monkeypatch, home: Path, bin_dir: Path, guard_dir: Path, marker: Path) -> None:
    """Delete every memory-context and proxy variable; point HOME, PATH and the child guard."""
    for name in (*env_names(), *PROXY_VARIABLES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PYTHONPATH", str(guard_dir))
    monkeypatch.setenv(NET_MARKER_ENV, str(marker))


def write_fake(bin_dir: Path) -> Path:
    """Install the fake as `<bin_dir>/ai-raccoon` (0755) plus a `python3` symlink."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "ai-raccoon"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_SOURCE.read_text(encoding="utf-8"),
                    encoding="utf-8")
    fake.chmod(0o755)
    link = bin_dir / "python3"
    if not link.exists():
        link.symlink_to(sys.executable)
    return fake


class Fake:
    """Handle on one test's fake proxy: its path, mode, hits map and event log."""

    def __init__(self, monkeypatch, root: Path):
        self.monkeypatch = monkeypatch
        self.bin_dir = root / "bin"
        self.path = write_fake(self.bin_dir)
        self.log = root / "fake.jsonl"
        self.hits_file = root / "hits.json"
        monkeypatch.setenv("FAKE_RACCOON_LOG", str(self.log))
        monkeypatch.setenv("FAKE_RACCOON_HITS", str(self.hits_file))
        self.mode("hits")

    def mode(self, name: str) -> None:
        """Select the fake's behaviour for later spawns."""
        self.monkeypatch.setenv("FAKE_RACCOON_MODE", name)

    def ceiling(self, seconds: float) -> None:
        """Lower the fake's hard ceiling for later spawns."""
        self.monkeypatch.setenv("FAKE_RACCOON_CEILING", str(seconds))

    def hits(self, table: Dict[str, dict]) -> None:
        """Set the query -> {results, code} map for perquery and latereply modes."""
        self.hits_file.write_text(json.dumps(table), encoding="utf-8")

    def events(self) -> List[dict]:
        """Every logged event, in order."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def runs(self) -> List[dict]:
        """One `{pid, argv, mode, stdin_lines, saw_eof, ...}` record per fake process."""
        runs: Dict[int, dict] = {}
        for event in self.events():
            run = runs.setdefault(event["pid"], {"pid": event["pid"], "argv": None, "mode": None,
                                                 "stdin_lines": [], "saw_eof": False})
            if event["event"] == "start":
                run["argv"], run["mode"] = event["argv"], event["mode"]
            elif event["event"] == "line":
                run["stdin_lines"].append(event["line"])
            elif event["event"] == "eof":
                run["saw_eof"] = True
            else:
                run.update({k: v for k, v in event.items() if k not in ("pid", "event")})
        return list(runs.values())

    def requests(self, run: Optional[dict] = None) -> List[dict]:
        """The JSON messages one fake run read (the last run by default)."""
        run = run if run is not None else self.runs()[-1]
        out = []
        for line in run["stdin_lines"]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def calls(self, run: Optional[dict] = None) -> List[dict]:
        """The tools/call requests one fake run read."""
        return [m for m in self.requests(run) if m.get("method") == "tools/call"]


def pid_gone(pid: int) -> bool:
    """True when *pid* no longer exists (reaped, not a zombie)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def live_openrouter_threads() -> list:
    """Live threads named `ai-badger-openrouter-*`, plus live `threading.Timer`s."""
    return [t for t in threading.enumerate()
            if t.is_alive() and (t.name.startswith("ai-badger-openrouter-")
                                 or isinstance(t, threading.Timer))]


_MODULE_KEY = "ai_badger_test_memory_context"


def load_module():
    """Load `memory_context.py` by path once per test session."""
    import importlib.util  # pylint: disable=import-outside-toplevel
    cached = sys.modules.get(_MODULE_KEY)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MODULE_KEY, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_KEY] = module
    spec.loader.exec_module(module)
    return module


class Env:
    """What the autouse fixture hands a test: guards, fake, dirs."""

    def __init__(self, guards: Guards, fake: Fake, root: Path, home: Path):
        self.guards = guards
        self.fake = fake
        self.root = root
        self.home = home

    def project(self, project_id: Optional[str] = "proj-123", name: str = "proj") -> Path:
        """A project dir with `.ai-badger/project-id` (none when *project_id* is None)."""
        path = self.root / name
        (path / ".ai-badger").mkdir(parents=True, exist_ok=True)
        if project_id is not None:
            (path / ".ai-badger" / "project-id").write_text(project_id, encoding="utf-8")
        return path


@pytest.fixture(autouse=True)
def memory_context_env(monkeypatch, tmp_path):
    """Hermetic env for every memory-context test; fails the test on any guard refusal."""
    root = tmp_path / "mc"
    home = root / "home"
    home.mkdir(parents=True)
    guard_dir = root / "guard"
    guard_dir.mkdir()
    (guard_dir / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    marker = root / "net-marker"
    fake_root = root / "fake"
    fake_root.mkdir()
    scrub_env(monkeypatch, home, fake_root / "bin", guard_dir, marker)
    guards = Guards(REAL_EXECUTABLES, marker)
    fake = Fake(monkeypatch, fake_root)
    install_popen_guard(monkeypatch, guards)
    install_network_guard(monkeypatch, guards)
    yield Env(guards, fake, root, home)
    assert_no_refusals(guards)
