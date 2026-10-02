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
import threading
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


def _dangling_symlink(project):
    (project / ".ai-badger").mkdir(parents=True)
    (project / ".ai-badger" / "config.json").symlink_to(project / "missing.json")


def _over_one_mib(project):
    write_config(project, {"project": {}, "pad": "x" * (1 << 20)})


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
    ("dangling-symlink", _dangling_symlink, True),
    ("over-1-mib", _over_one_mib, True),
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


def not_root():
    return not (hasattr(os, "geteuid") and os.geteuid() == 0)


@pytest.mark.skipif(not not_root(), reason="root searches a mode-000 folder")
def test_an_unsearchable_dot_dir_holding_a_lock_still_locks(tmp_path):
    project = write_config(tmp_path / "proj", {"dataPolicy": "local-only"})
    dot = project / ".ai-badger"
    dot.chmod(0)
    try:
        assert oc.project_locked(str(project)) is True
    finally:
        dot.chmod(0o700)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_a_fifo_config_locks_without_blocking(tmp_path):
    project = tmp_path / "proj"
    (project / ".ai-badger").mkdir(parents=True)
    fifo = project / ".ai-badger" / "config.json"
    os.mkfifo(fifo)
    result = []
    worker = threading.Thread(target=lambda: result.append(oc.project_locked(str(project))),
                              daemon=True)
    worker.start()
    worker.join(timeout=3)
    hung = worker.is_alive()
    if hung:  # release a reader stuck in open() so the thread can finish
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        worker.join(timeout=3)
    assert not hung
    assert result == [True]


def test_an_in_tree_worktree_is_locked_by_the_checkout_above_it(tmp_path):
    checkout = write_config(tmp_path / "checkout", {"dataPolicy": "local-only"})
    (checkout / ".git").mkdir()
    tree = write_config(checkout / ".ai-badger" / "worktrees" / "x", {"project": {}})
    (tree / ".git").write_text("gitdir: ../../../.git/worktrees/x\n", encoding="utf-8")
    assert oc.project_locked(str(tree)) is True


def test_an_unresolvable_cwd_is_locked():
    assert oc.project_locked("/tmp/bad\0cwd") is True


def test_a_physical_cwd_is_locked_through_a_logical_pwd_naming_it(tmp_path, monkeypatch):
    corp = write_config(tmp_path / "corp", {"dataPolicy": "local-only"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = corp / "proj"
    link.symlink_to(elsewhere, target_is_directory=True)
    physical = str(elsewhere.resolve())
    monkeypatch.setenv("PWD", str(link))
    assert oc.project_locked(physical) is True


def test_a_pwd_naming_another_folder_adds_no_lock(tmp_path, monkeypatch):
    corp = write_config(tmp_path / "corp", {"dataPolicy": "local-only"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("PWD", str(corp))
    assert oc.project_locked(str(elsewhere)) is False


def config_path(project):
    return os.path.join(os.path.abspath(project), ".ai-badger", "config.json")


@pytest.mark.parametrize("raw,cause", [({"dataPolicy": "local-only"}, "dataPolicy"),
                                       (b"{not json", "unreadable"), ([], "not-object")])
def test_lock_reason_names_the_config_and_its_cause(tmp_path, raw, cause):
    project = write_config(tmp_path / "proj", raw)
    assert oc.lock_reason(str(project)) == f"{config_path(project)}: {cause}"


def test_lock_reason_is_none_for_an_open_project_and_names_an_unresolvable_cwd(tmp_path):
    assert oc.lock_reason(str(write_config(tmp_path / "proj", {"project": {}}))) is None
    assert oc.lock_reason("/tmp/bad\0cwd") == "unresolvable cwd"


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


def test_post_json_ignores_an_ambient_opt_in_when_no_env_is_passed(memory_context_env,
                                                                  monkeypatch, tmp_path):
    seen = recording_opener(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ALLOW, "1")
    reply = oc.post_json(REMOTE, {"model": "m"}, KEY, mc.Budget(2.0))
    assert reply.error == oc.EGRESS_REFUSED
    assert seen == []
    assert memory_context_env.guards.net_attempts == []


def test_post_json_without_a_cwd_checks_the_process_cwd(memory_context_env, monkeypatch,
                                                         tmp_path):
    seen = recording_opener(monkeypatch)
    monkeypatch.chdir(write_config(tmp_path / "proj", {"dataPolicy": "local-only"}))
    reply = oc.post_json(REMOTE, {"model": "m"}, KEY, mc.Budget(2.0), env={ALLOW: "1"})
    assert reply.error == oc.EGRESS_REFUSED
    assert seen == []
    assert memory_context_env.guards.net_attempts == []


def test_a_keyless_post_sends_no_authorization_header():
    server = fakes.FakeOpenRouter()
    try:
        reply = oc.post_json(server.url + CHAT_PATH, {"model": "m"}, None, mc.Budget(2.0))
        assert (reply.status, reply.error) == (200, None)
        assert len(server.requests) == 1
        assert "authorization" not in server.requests[0]["headers"]
    finally:
        server.stop()


def test_a_keyed_post_sends_the_bearer_header():
    server = fakes.FakeOpenRouter()
    try:
        reply = oc.post_json(server.url + CHAT_PATH, {"model": "m"}, KEY, mc.Budget(2.0))
        assert reply.status == 200
        assert server.requests[0]["headers"]["authorization"] == f"Bearer {KEY}"
    finally:
        server.stop()


@pytest.mark.parametrize("dirty", ["", " " + KEY, KEY + "\nX: 1"])
def test_a_dirty_key_fails_before_any_request(dirty):
    server = fakes.FakeOpenRouter()
    try:
        assert oc.post_json(server.url + CHAT_PATH, {}, dirty, mc.Budget(2.0)).error == oc.TRANSPORT
        assert server.requests == []
    finally:
        server.stop()


# ------------------------------------------------------------------ allowHosts (object form)

DECIDER = "decider.corp.example"
DECIDER_URL = "https://decider.corp.example/v1"


def allow_lock(directory, hosts=(DECIDER,), **policy):
    """A lock in *directory* whose object form allowlists *hosts*; extra *policy* keys merge in."""
    return write_config(directory, {"dataPolicy": {"mode": "local-only", "allowHosts": list(hosts),
                                                   **policy}})


def sent(monkeypatch, url, env, cwd):
    """`post_json` to *url* through the recording opener: the reply error and the URLs dialled."""
    seen = recording_opener(monkeypatch)
    reply = oc.post_json(url, {"model": "m"}, KEY, mc.Budget(2.0), env=env, cwd=str(cwd))
    return reply.error, [request.full_url for request in seen]


def test_a1_an_allowlisted_host_in_a_locked_project_is_sent_with_the_opt_in(monkeypatch,
                                                                           tmp_path):
    project = allow_lock(tmp_path / "proj")
    assert sent(monkeypatch, DECIDER_URL, {ALLOW: "1"}, project) == (oc.TRANSPORT, [DECIDER_URL])


def test_a2_an_allowlisted_host_still_needs_the_opt_in(memory_context_env, monkeypatch, tmp_path):
    project = allow_lock(tmp_path / "proj")
    assert sent(monkeypatch, DECIDER_URL, {}, project) == (oc.EGRESS_REFUSED, [])
    assert memory_context_env.guards.net_attempts == []


def test_a3_a_host_outside_the_allowlist_is_refused_with_the_opt_in(monkeypatch, tmp_path):
    project = allow_lock(tmp_path / "proj")
    assert sent(monkeypatch, REMOTE, {ALLOW: "1"}, project) == (oc.EGRESS_REFUSED, [])


@pytest.mark.parametrize("url", ["https://evil-decider.corp.example/v1",
                                 "https://decider.corp.example.evil.example/v1",
                                 "https://corp.example/v1"])
def test_a4_a_lookalike_host_is_refused(monkeypatch, tmp_path, url):
    project = allow_lock(tmp_path / "proj")
    assert sent(monkeypatch, url, {ALLOW: "1"}, project) == (oc.EGRESS_REFUSED, [])


@pytest.mark.parametrize("url", ["https://decider.corp.example:/x",
                                 "https://evil.com\t.decider.corp.example/",
                                 "https://decider.corp.example\\@evil.com",
                                 "https://user@decider.corp.example/x",
                                 " https://decider.corp.example/x",
                                 "https://decider.corp.example\x7f/x"],
                         ids=["empty-port", "tab", "backslash", "userinfo", "leading-space",
                              "control"])
def test_a5_a_url_whose_dialled_host_is_ambiguous_is_refused(monkeypatch, tmp_path, url):
    project = allow_lock(tmp_path / "proj")
    assert sent(monkeypatch, url, {ALLOW: "1"}, project) == (oc.EGRESS_REFUSED, [])
    assert oc.dialled_host(url) is None


def test_a5_the_dialled_host_is_the_request_host_normalised():
    assert oc.dialled_host("https://DECIDER.corp.example.:8443/x") == DECIDER
    assert oc.dialled_host(DECIDER_URL) == DECIDER


def test_a6_plain_http_off_loopback_is_refused_even_opted_in_and_unlocked(monkeypatch,
                                                                         tmp_path):
    plain = "http://decider.corp.example/v1"
    assert sent(monkeypatch, plain, {ALLOW: "1"}, tmp_path) == (oc.EGRESS_REFUSED, [])
    loop = "http://127.0.0.1:9/v1"
    assert sent(monkeypatch, loop, {}, tmp_path) == (oc.TRANSPORT, [loop])


def test_a7_matching_ignores_case_a_trailing_dot_and_the_port(monkeypatch, tmp_path):
    project = allow_lock(tmp_path / "proj", hosts=["Decider.Corp.Example."])
    url = "https://DECIDER.corp.example.:8443/x"
    assert sent(monkeypatch, url, {ALLOW: "1"}, project) == (oc.TRANSPORT, [url])
    assert oc.allowed_hosts(str(project)) == frozenset({DECIDER})


VOIDING = [
    ("wildcard", {"allowHosts": ["*.corp.example", DECIDER]}),
    ("port", {"allowHosts": ["other.corp.example:443", DECIDER]}),
    ("url", {"allowHosts": ["https://other.corp.example", DECIDER]}),
    ("ipv4", {"allowHosts": ["203.0.113.7", DECIDER]}),
    ("single-label", {"allowHosts": ["decider", DECIDER]}),
    ("non-string", {"allowHosts": [7, DECIDER]}),
    ("newline", {"allowHosts": ["other.corp.example\n", DECIDER]}),
    ("duplicate", {"allowHosts": [DECIDER, DECIDER]}),
    ("other-mode", {"mode": "open"}),
    ("unknown-key", {"extra": True}),
    ("not-a-list", {"allowHosts": DECIDER}),
]


@pytest.mark.parametrize("name,policy", VOIDING, ids=[v[0] for v in VOIDING])
def test_a8_one_bad_part_voids_the_whole_list_and_still_locks(monkeypatch, tmp_path, name,
                                                             policy):
    del name
    project = write_config(tmp_path / "proj", {"dataPolicy": {"mode": "local-only",
                                                              "allowHosts": [DECIDER], **policy}})
    assert oc.project_locked(str(project)) is True
    assert oc.allowed_hosts(str(project)) == frozenset()
    assert sent(monkeypatch, DECIDER_URL, {ALLOW: "1"}, project) == (oc.EGRESS_REFUSED, [])


def test_a8_a_policy_without_allow_hosts_voids_the_list(tmp_path):
    project = write_config(tmp_path / "proj", {"dataPolicy": {"mode": "local-only"}})
    assert oc.project_locked(str(project)) is True
    assert oc.allowed_hosts(str(project)) == frozenset()


def test_a9_nested_allowlists_intersect(monkeypatch, tmp_path):
    parent = allow_lock(tmp_path / "parent", hosts=["a.corp.example", "b.corp.example"])
    child = allow_lock(parent / "child", hosts=["b.corp.example", "c.corp.example"])
    assert oc.allowed_hosts(str(child)) == frozenset({"b.corp.example"})
    for host, expected in (("a", oc.EGRESS_REFUSED), ("b", oc.TRANSPORT),
                           ("c", oc.EGRESS_REFUSED)):
        url = f"https://{host}.corp.example/v1"
        assert sent(monkeypatch, url, {ALLOW: "1"}, child)[0] == expected, host


def test_a9_a_string_form_parent_over_an_object_child_allows_nothing(monkeypatch, tmp_path):
    parent = write_config(tmp_path / "parent", {"dataPolicy": "local-only"})
    child = allow_lock(parent / "child")
    assert oc.allowed_hosts(str(child)) == frozenset()
    assert sent(monkeypatch, DECIDER_URL, {ALLOW: "1"}, child) == (oc.EGRESS_REFUSED, [])


def test_a9_an_unlocked_project_does_not_consult_any_allowlist(monkeypatch, tmp_path):
    assert sent(monkeypatch, REMOTE, {ALLOW: "1"}, tmp_path) == (oc.TRANSPORT, [REMOTE])
