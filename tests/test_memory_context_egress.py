"""The OpenRouter client's egress rule: loopback always, a third-party host only on opt-in.

`AI_BADGER_ALLOW_THIRD_PARTY=1` opts a session in; a `dataPolicy` key in any
`.ai-badger/config.json` above the cwd (or one that cannot be read as a JSON object) locks the
project local-only whatever the env says. Every lock config is written under `tmp_path`; no row
reaches a non-loopback host (the network guard from `memory_context_support` refuses one).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error

import pytest

import memory_context_openrouter as fakes
from memory_context_openrouter import CHAT_PATH
from memory_context_support import SCRIPTS, load_module, memory_context_env  # noqa: F401

ALLOW = "AI_BADGER_ALLOW_THIRD_PARTY"
REMOTE = "https://openrouter.ai" + CHAT_PATH
KEY = "sk-test-egress"


def load_client():
    """Load `openrouter_client.py` by path under its own module key."""
    name = "ai_badger_test_egress_openrouter_client"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "openrouter_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


oc = load_client()
mc = load_module()


def write_config(directory, raw):
    """`<directory>/.ai-badger/config.json` holding *raw* (bytes, or JSON-encoded otherwise)."""
    target = directory / ".ai-badger"
    target.mkdir(parents=True, exist_ok=True)
    data = raw if isinstance(raw, bytes) else json.dumps(raw).encode("utf-8")
    (target / "config.json").write_bytes(data)
    return directory


def _absent(project):
    project.mkdir(parents=True, exist_ok=True)


def _json(value):
    def make(project):
        write_config(project, value)
    return make


def _raw(data):
    def make(project):
        write_config(project, data)
    return make


def _config_is_a_directory(project):
    (project / ".ai-badger" / "config.json").mkdir(parents=True)


def _dot_dir_is_a_file(project):
    project.mkdir(parents=True, exist_ok=True)
    (project / ".ai-badger").write_text("{}", encoding="utf-8")


def _unreadable(project):
    write_config(project, {})
    (project / ".ai-badger" / "config.json").chmod(0)


# (id, builder, locks): only a config that is a JSON object without `dataPolicy` leaves the env
# in charge; `.ai-badger` as a plain file holds no config at all, so it locks nothing.
CONFIGS = [
    ("absent", _absent, False),
    ("empty-object", _json({}), False),
    ("no-data-policy", _json({"project": {}}), False),
    ("dot-dir-is-a-file", _dot_dir_is_a_file, False),
    ("local-only", _json({"dataPolicy": "local-only"}), True),
    ("wrong-case", _json({"dataPolicy": "Local-Only"}), True),
    ("null-policy", _json({"dataPolicy": None}), True),
    ("number-policy", _json({"dataPolicy": 1}), True),
    ("malformed-json", _raw(b"{not json"), True),
    ("empty-file", _raw(b""), True),
    ("invalid-utf8", _raw(b'{"project": "\xff\xfe"}'), True),
    ("non-object", _json([]), True),
    ("config-is-a-directory", _config_is_a_directory, True),
    ("unreadable", _unreadable, True),
]
ALLOW_VALUES = [(None, False), ("0", False), ("true", False), (" 1", False), ("1\n", False),
                ("1", True)]


def allow_env(value):
    return {} if value is None else {ALLOW: value}


@pytest.mark.parametrize("name,build,locks", CONFIGS, ids=[c[0] for c in CONFIGS])
@pytest.mark.parametrize("allow,opted_in", ALLOW_VALUES, ids=[repr(a[0]) for a in ALLOW_VALUES])
def test_third_party_needs_literal_one_and_no_lock(tmp_path, name, build, locks, allow,
                                                   opted_in):
    if name == "unreadable" and hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    project = tmp_path / "proj"
    build(project)
    try:
        assert oc.project_locked(str(project)) is locks
        assert oc.third_party_allowed(allow_env(allow), str(project)) is (opted_in and not locks)
    finally:
        if name == "unreadable":
            (project / ".ai-badger" / "config.json").chmod(0o600)


def test_a_lock_in_any_ancestor_locks_a_nested_project(tmp_path):
    parent = write_config(tmp_path / "parent", {"dataPolicy": "local-only"})
    child = write_config(parent / "work" / "child", {"project": {}})
    deep = child / "src" / "pkg"
    deep.mkdir(parents=True)
    assert oc.project_locked(str(deep)) is True
    assert oc.project_locked(str(child)) is True
    assert oc.third_party_allowed({ALLOW: "1"}, str(deep)) is False


def test_a_lock_below_the_cwd_does_not_reach_up(tmp_path):
    parent = write_config(tmp_path / "parent", {"project": {}})
    write_config(parent / "child", {"dataPolicy": "local-only"})
    assert oc.project_locked(str(parent)) is False
    assert oc.third_party_allowed({ALLOW: "1"}, str(parent)) is True


def test_a_symlinked_cwd_is_locked_by_the_path_as_given(tmp_path):
    locked = write_config(tmp_path / "locked", {"dataPolicy": "local-only"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (locked / "link").symlink_to(outside, target_is_directory=True)
    assert oc.project_locked(str(outside)) is False
    assert oc.project_locked(str(locked / "link")) is True


def test_a_symlinked_cwd_is_locked_by_its_resolved_path(tmp_path):
    locked = write_config(tmp_path / "locked", {"dataPolicy": "local-only"})
    (locked / "inner").mkdir()
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    (open_dir / "link").symlink_to(locked / "inner", target_is_directory=True)
    assert oc.project_locked(str(open_dir)) is False
    assert oc.project_locked(str(open_dir / "link")) is True


def test_egress_allowed_is_loopback_or_the_opt_in(tmp_path):
    project = write_config(tmp_path / "proj", {"dataPolicy": "local-only"})
    loop = "http://127.0.0.1:9" + CHAT_PATH
    assert oc.egress_allowed(loop, {}, str(project)) is True
    assert oc.egress_allowed(REMOTE, {ALLOW: "1"}, str(project)) is False
    assert oc.egress_allowed(REMOTE, {ALLOW: "1"}, str(tmp_path)) is True
    assert oc.egress_allowed(REMOTE, {}, str(tmp_path)) is False


# ------------------------------------------------------------------ is_loopback


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/x", "http://localhost/x",
                                 "http://[::1]:9/x", "https://127.0.0.1:443/x"])
def test_loopback_hosts_are_loopback(url):
    assert oc.is_loopback(url) is True


@pytest.mark.parametrize("url", ["http://127.0.0.1.evil.example/", "http://localhost@evil.example/",
                                 "http://user@127.0.0.1/", "https://openrouter.ai",
                                 "ftp://127.0.0.1/x", "http://127.0.0.2/", "http://[::1/x",
                                 "http://127.0.0.1:99999/x", "garbage", ""])
def test_everything_else_is_not_loopback(url):
    assert oc.is_loopback(url) is False


# ------------------------------------------------------------------ post_json refusal


class Dialled(Exception):
    """Raised by the recording opener instead of touching the network."""


def recording_opener(monkeypatch):
    """Replace `make_opener` with one that records each request and dials nothing."""
    seen = []

    class Opener:  # pylint: disable=too-few-public-methods
        def open(self, request, timeout=None):
            del timeout
            seen.append(request)
            raise urllib.error.URLError(Dialled("recorded, not sent"))

    monkeypatch.setattr(oc, "make_opener", lambda call: Opener())
    return seen


def test_a_remote_post_without_the_opt_in_is_refused_before_any_dial(memory_context_env,
                                                                     monkeypatch, tmp_path):
    seen = recording_opener(monkeypatch)
    reply = oc.post_json(REMOTE, {"model": "m"}, KEY, mc.Budget(2.0), env={}, cwd=str(tmp_path))
    assert reply.error == oc.EGRESS_REFUSED
    assert reply.status == 0
    assert seen == []
    assert memory_context_env.guards.net_attempts == []
    defaulted = oc.post_json(REMOTE, {"model": "m"}, KEY, mc.Budget(2.0))
    assert defaulted.error == oc.EGRESS_REFUSED
    assert seen == []


def test_a_locked_project_refuses_even_with_the_opt_in(memory_context_env, monkeypatch, tmp_path):
    seen = recording_opener(monkeypatch)
    project = write_config(tmp_path / "proj", {"dataPolicy": "local-only"})
    reply = oc.post_json(REMOTE, {"model": "m"}, KEY, mc.Budget(2.0), env={ALLOW: "1"},
                         cwd=str(project))
    assert reply.error == oc.EGRESS_REFUSED
    assert seen == []
    assert memory_context_env.guards.net_attempts == []


def test_the_opt_in_in_an_unlocked_cwd_reaches_the_opener(monkeypatch, tmp_path):
    seen = recording_opener(monkeypatch)
    reply = oc.post_json(REMOTE, {"model": "m"}, KEY, mc.Budget(2.0), env={ALLOW: "1"},
                         cwd=str(tmp_path))
    assert reply.error == oc.TRANSPORT
    assert [request.full_url for request in seen] == [REMOTE]


def test_a_keyless_post_sends_no_authorization_header():
    server = fakes.FakeOpenRouter()
    try:
        reply = oc.post_json(server.url + CHAT_PATH, {"model": "m"}, None, mc.Budget(2.0))
        assert (reply.status, reply.error) == (200, None)
        assert len(server.requests) == 1
        assert "authorization" not in server.requests[0]["headers"]
        keyed = oc.post_json(server.url + CHAT_PATH, {"model": "m"}, KEY, mc.Budget(2.0))
        assert keyed.status == 200
        assert server.requests[1]["headers"]["authorization"] == f"Bearer {KEY}"
        for dirty in ("", " " + KEY, KEY + "\nX: 1"):
            assert oc.post_json(server.url + CHAT_PATH, {}, dirty,
                                mc.Budget(2.0)).error == oc.TRANSPORT
        assert len(server.requests) == 2
    finally:
        server.stop()
