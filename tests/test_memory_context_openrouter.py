"""openrouter_client.py against fake OpenRouter servers: proxy, redirect, TLS, deadlines, key hygiene.

Every test runs under `memory_context_env` (scrubbed env, temp HOME, spawn and network guards).
Timing rows bound at most 1.5 s against fakes whose blocking behaviour ends by a 20 s ceiling.
"""
from __future__ import annotations

import importlib.util
import socket
import ssl
import sys
import threading
import time
import urllib.request

import pytest

import memory_context_openrouter as fakes
from memory_context_openrouter import CHAT_PATH
from memory_context_support import (SCRIPTS, GuardRefusal, live_openrouter_threads, load_module,
                                    memory_context_env)  # noqa: F401

mc = load_module()

KEY = "sk-test-q1-secret-key"
PRODUCTION_LOOKING_KEY = "sk-or-v1-x"
LEAK_MARKERS = (KEY, PRODUCTION_LOOKING_KEY, "q1-secret")


def load_client():
    """Load `openrouter_client.py` by path once per test session."""
    name = "ai_badger_test_openrouter_client"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "openrouter_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


oc = load_client()


@pytest.fixture(autouse=True)
def no_leak_no_threads(capsys, caplog):
    """After every row: no key text in stdout, stderr or logs; no live client thread."""
    yield
    out, err = capsys.readouterr()
    for text in (out, err, caplog.text):
        for marker in LEAK_MARKERS:
            assert marker not in text
    assert live_openrouter_threads() == []


@pytest.fixture(autouse=True)
def no_stale_proxy_faults():
    """Every row starts with the client's proxy-fault record empty."""
    oc.take_proxy_faults()


@pytest.fixture(name="fake")
def fake_server():
    server = fakes.FakeOpenRouter()
    yield server
    server.stop()


@pytest.fixture(name="capture")
def capture_server():
    server = fakes.FakeOpenRouter()
    yield server
    server.stop()


def post(url, share=2.0, key=KEY, body=None, **route):
    """`post_json` that must return a `Reply` carrying no key text, never raise; *route* is the
    egress `env`/`cwd` pair."""
    budget = share if isinstance(share, mc.Budget) else mc.Budget(share)
    try:
        reply = oc.post_json(url, body if body is not None else {"model": "m"}, key, budget,
                             **route)
    except Exception as err:  # pylint: disable=broad-except
        for marker in LEAK_MARKERS:
            assert marker not in str(err)
        raise
    assert isinstance(reply, oc.Reply)
    for marker in LEAK_MARKERS:
        assert marker not in repr(reply)
    return reply


def timed_post(url, share, key=KEY, **route):
    start = time.monotonic()
    reply = post(url, share, key, **route)
    return reply, time.monotonic() - start


# ------------------------------------------------------------------- O1 proxy

TARGET = f"https://{fakes.DECIDER_HOST}/x"
CONNECT_PREFIX = f"CONNECT {fakes.DECIDER_HOST}:443 "


def opted_in(cwd, **variables):
    """The egress route for an opted-in POST from an unlocked *cwd*, plus *variables* in env."""
    return {"env": {oc.ALLOW_ENV: "1", **variables}, "cwd": str(cwd)}


def named(guards, host):
    """Every guarded network attempt that names *host*."""
    return [attempt for attempt in guards.net_attempts if host in repr(attempt)]


@pytest.fixture(name="thread_errors")
def thread_exceptions(monkeypatch):
    """Exceptions that escaped a thread during the row, instead of pytest's warning."""
    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    return errors


def assert_dialled_direct(guards, host, thread_errors):
    """The only refusals were the guard stopping one direct lookup of *host*, raised on the
    resolver thread."""
    refusals = guards.take_refusals()
    assert refusals and all(host in refusal for refusal in refusals)
    assert [type(error) for error in thread_errors] == [GuardRefusal]
    assert host in str(thread_errors[0])


@pytest.fixture(name="proxy")
def capture_proxy(tls_fake):
    """A relaying CaptureProxy whose only upstream is the TLS fake."""
    server = fakes.CaptureProxy(tls_fake.port)
    yield server
    server.stop()


@pytest.fixture(name="bare_proxy")
def bare_capture_proxy():
    """A CaptureProxy with no upstream: any CONNECT it records is a dial that should not be."""
    server = fakes.CaptureProxy()
    yield server
    server.stop()


@pytest.fixture(name="second_proxy")
def second_capture_proxy(tls_fake):
    """Another relaying CaptureProxy, for the variable-precedence rows."""
    server = fakes.CaptureProxy(tls_fake.port)
    yield server
    server.stop()


def test_o1_an_env_proxy_tunnels_an_https_post(memory_context_env, proxy, tls_fake, tmp_path):
    reply = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=proxy.url))
    assert (reply.status, reply.error) == (200, None)
    assert [c["line"][:len(CONNECT_PREFIX)] for c in proxy.connects] == [CONNECT_PREFIX]
    assert "authorization" not in proxy.connects[0]["headers"]
    assert "proxy-authorization" not in proxy.connects[0]["headers"]
    assert proxy.violations == []
    assert len(tls_fake.requests) == 1
    assert tls_fake.requests[0]["headers"]["authorization"] == f"Bearer {KEY}"
    assert tls_fake.requests[0]["headers"]["host"] == fakes.DECIDER_HOST
    assert tls_fake.sni == [fakes.DECIDER_HOST]
    assert named(memory_context_env.guards, fakes.DECIDER_HOST) == []


def test_o1_loopback_is_never_proxied(fake, proxy, tls_fake, tmp_path):
    for url in (fake.url + CHAT_PATH, tls_fake.url + CHAT_PATH):
        reply = post(url, **opted_in(tmp_path, HTTPS_PROXY=proxy.url, https_proxy=proxy.url))
        assert (reply.status, reply.error) == (200, None)
    assert (len(fake.requests), len(tls_fake.requests)) == (1, 1)
    assert proxy.connects == []


def test_o1_an_os_environ_proxy_is_ignored(memory_context_env, proxy, tmp_path, monkeypatch,
                                          thread_errors):
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                 "ALL_PROXY"):
        monkeypatch.setenv(name, proxy.url)
    reply = post(TARGET, **opted_in(tmp_path))
    assert reply.error == oc.TRANSPORT
    assert proxy.connects == []
    assert_dialled_direct(memory_context_env.guards, fakes.DECIDER_HOST, thread_errors)


def test_o1_an_os_environ_no_proxy_is_ignored(proxy, tmp_path, monkeypatch):
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(name, fakes.DECIDER_HOST)
    reply = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=proxy.url))
    assert (reply.status, reply.error) == (200, None)
    assert len(proxy.connects) == 1


P = "http://127.0.0.1:1"
Q = "http://127.0.0.1:2"


@pytest.mark.parametrize("variables,expected", [
    ({}, None),
    ({"HTTPS_PROXY": ""}, None),
    ({"HTTPS_PROXY": " \t"}, None),
    ({"https_proxy": ""}, None),
    ({"https_proxy": "", "HTTPS_PROXY": Q}, None),
    ({"https_proxy": "  ", "HTTPS_PROXY": Q}, None),
    ({"HTTPS_PROXY": Q}, "127.0.0.1:2"),
    ({"https_proxy": P}, "127.0.0.1:1"),
    ({"https_proxy": P, "HTTPS_PROXY": Q}, "127.0.0.1:1"),
    ({"https_proxy": P + "/"}, "127.0.0.1:1"),
    ({"https_proxy": P, "no_proxy": fakes.DECIDER_HOST}, None),
    ({"https_proxy": P, "NO_PROXY": fakes.DECIDER_HOST}, None),
    ({"https_proxy": P, "NO_PROXY": "*"}, None),
    ({"https_proxy": P, "NO_PROXY": ""}, "127.0.0.1:1"),
    ({"https_proxy": P, "NO_PROXY": " "}, "127.0.0.1:1"),
    ({"https_proxy": P, "no_proxy": "", "NO_PROXY": fakes.DECIDER_HOST}, "127.0.0.1:1"),
    ({"https_proxy": P, "no_proxy": "other.test", "NO_PROXY": fakes.DECIDER_HOST}, "127.0.0.1:1"),
    ({"https_proxy": P, "no_proxy": "other.test, .decider.test"}, None),
])
def test_o1_proxy_variable_precedence(variables, expected):
    assert oc.proxy_for(TARGET, variables) == expected


def test_o1_no_proxy_matches_a_domain_suffix_not_a_lookalike():
    variables = {"HTTPS_PROXY": P, "NO_PROXY": "corp.example"}
    assert oc.proxy_for("https://a.corp.example/x", variables) is None
    assert oc.proxy_for("https://corp.example/x", variables) is None
    assert oc.proxy_for("https://evil-corp.example/x", variables) == "127.0.0.1:1"


def test_o1_only_https_off_loopback_is_proxied():
    variables = {"https_proxy": P}
    assert oc.proxy_for("https://127.0.0.1:9/x", variables) is None
    assert oc.proxy_for("https://localhost/x", variables) is None
    assert oc.proxy_for("http://127.0.0.1:9/x", variables) is None
    assert oc.proxy_for(TARGET, variables) == "127.0.0.1:1"


def test_o1_the_lowercase_proxy_wins_end_to_end(proxy, second_proxy, tmp_path):
    reply = post(TARGET, **opted_in(tmp_path, https_proxy=proxy.url,
                                    HTTPS_PROXY=second_proxy.url))
    assert (reply.status, reply.error) == (200, None)
    assert (len(proxy.connects), len(second_proxy.connects)) == (1, 0)


def test_o1_a_blank_lowercase_proxy_masks_the_uppercase_one(memory_context_env, proxy, tmp_path,
                                                            thread_errors):
    reply = post(TARGET, **opted_in(tmp_path, https_proxy="", HTTPS_PROXY=proxy.url))
    assert reply.error == oc.TRANSPORT
    assert proxy.connects == []
    assert_dialled_direct(memory_context_env.guards, fakes.DECIDER_HOST, thread_errors)


def test_o1_a_target_in_no_proxy_dials_direct(memory_context_env, proxy, tmp_path, thread_errors):
    reply = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=proxy.url,
                                    NO_PROXY=fakes.DECIDER_HOST))
    assert reply.error == oc.TRANSPORT
    assert proxy.connects == []
    assert_dialled_direct(memory_context_env.guards, fakes.DECIDER_HOST, thread_errors)


def test_o1_a_host_port_no_proxy_entry_never_matches():
    variables = {"HTTPS_PROXY": P, "NO_PROXY": f"{fakes.DECIDER_HOST}:8443"}
    assert oc.proxy_for(f"https://{fakes.DECIDER_HOST}:8443/x", variables) == "127.0.0.1:1"


def test_o1_a_non_default_port_rides_the_connect_line_and_host(proxy, tls_fake, tmp_path):
    reply = post(f"https://{fakes.DECIDER_HOST}:8443/x",
                 **opted_in(tmp_path, HTTPS_PROXY=proxy.url,
                            NO_PROXY=f"{fakes.DECIDER_HOST}:8443"))
    assert (reply.status, reply.error) == (200, None)
    connect = f"CONNECT {fakes.DECIDER_HOST}:8443 "
    assert [c["line"][:len(connect)] for c in proxy.connects] == [connect]
    assert tls_fake.requests[0]["headers"]["host"] == f"{fakes.DECIDER_HOST}:8443"
    assert tls_fake.sni == [fakes.DECIDER_HOST]


@pytest.mark.parametrize("value,expected", [
    ("127.0.0.1:8080", "127.0.0.1:8080"),
    ("h:1", "h:1"),
    ("proxy.corp.example:3128", "proxy.corp.example:3128"),
    ("HTTP://Proxy.Corp.Example:3128/", "proxy.corp.example:3128"),
    ("[::1]:3128", "[::1]:3128"),
    ("http://[::1]:3128", "[::1]:3128"),
])
def test_o1_a_scheme_less_or_http_proxy_is_a_normalised_address(value, expected):
    assert oc.proxy_for(TARGET, {"HTTPS_PROXY": value}) == expected


def test_o1_a_scheme_less_proxy_tunnels_like_curl(proxy, tls_fake, tmp_path):
    reply = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=proxy.url.removeprefix("http://")))
    assert (reply.status, reply.error) == (200, None)
    assert [c["line"][:len(CONNECT_PREFIX)] for c in proxy.connects] == [CONNECT_PREFIX]
    assert len(tls_fake.requests) == 1


def _refused(port):
    """`(value, cause)` for every proxy value refused before any dial."""
    unsupported = [f"https://127.0.0.1:{port}", f"socks5://127.0.0.1:{port}",
                   f"http://u:p@127.0.0.1:{port}", f"http://@127.0.0.1:{port}",
                   f"u:p@127.0.0.1:{port}"]
    malformed = ["http://127.0.0.1", "http://127.0.0.1:", f"http://127.0.0.1:{port}/x",
                 f"http://127.0.0.1:{port}?q=1", f"http://127.0.0.1:{port}#f",
                 "http://127.0.0.1:0", "http://127.0.0.1:99999", f"http://127.0.0.1:{port}\n",
                 "http://:1", "127.0.0.1", "h;x:1", "http://h;x:1", "pr%6Fxy:1",
                 "http://pr%6Fxy:1"]
    return ([(value, "unsupported") for value in unsupported]
            + [(value, "malformed") for value in malformed])


@pytest.mark.parametrize("index", range(len(_refused(1))))
def test_o1_a_refused_proxy_is_transport_before_any_dial(memory_context_env, bare_proxy, tmp_path,
                                                         request, index):
    port = str(bare_proxy.port)
    value, cause = _refused(port)[index]
    for variables in ({"HTTPS_PROXY": value},
                      {"HTTPS_PROXY": value, "NO_PROXY": fakes.DECIDER_HOST}):
        with pytest.raises(ValueError) as raised:
            oc.proxy_for(TARGET, variables)
        assert raised.value.cause == cause
        assert value.strip() not in str(raised.value) and port not in str(raised.value)
        reply = post(TARGET, **opted_in(tmp_path, **variables))
        assert reply.error == oc.TRANSPORT
        assert oc.take_proxy_faults() == {cause}
    assert memory_context_env.guards.net_attempts == []
    assert bare_proxy.connects == []
    proxy = request.getfixturevalue("proxy")
    control = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=proxy.url))
    assert (control.status, control.error) == (200, None)
    assert oc.take_proxy_faults() == set()


def test_o1_a_hanging_proxy_is_bounded_by_the_share(tmp_path):
    hang = fakes.CaptureProxy(mode="hang")
    try:
        reply, elapsed = timed_post(TARGET, 0.3, **opted_in(tmp_path, HTTPS_PROXY=hang.url))
    finally:
        hang.stop()
    assert reply.error == oc.TIMEOUT
    assert elapsed < 1.5
    assert len(hang.connects) == 1
    assert live_openrouter_threads() == []


@pytest.mark.parametrize("status", [403, 407])
def test_o1_a_refusing_proxy_is_transport_with_its_status_token(tmp_path, status):
    refuse = fakes.CaptureProxy(mode="refuse", refuse_status=status)
    try:
        reply = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=refuse.url))
    finally:
        refuse.stop()
    assert reply.error == oc.TRANSPORT
    assert len(refuse.connects) == 1 and refuse.violations == []
    assert oc.take_proxy_faults() == {f"connect-{status}"}
    assert oc.take_proxy_faults() == set()


@pytest.fixture(name="ip_only_certificate", scope="session")
def ip_only_certificate_files(tmp_path_factory):
    made = fakes.make_certificate(tmp_path_factory.mktemp("tls-ip"), names="IP:127.0.0.1")
    if made is None:
        pytest.skip("openssl is not installed; the throwaway certificate cannot be made")
    return made


def test_o1_the_target_name_is_verified_inside_the_tunnel(ip_only_certificate, tmp_path,
                                                          monkeypatch):
    cert, key = ip_only_certificate
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    ip_only = fakes.FakeOpenRouter(tls=fakes.server_context(cert, key))
    relay = fakes.CaptureProxy(ip_only.port)
    try:
        trusted = post(ip_only.url + CHAT_PATH)
        reply = post(TARGET, **opted_in(tmp_path, HTTPS_PROXY=relay.url))
    finally:
        relay.stop()
        ip_only.stop()
    assert (trusted.status, trusted.error) == (200, None)
    assert reply.error == oc.TRANSPORT
    assert [c["line"][:len(CONNECT_PREFIX)] for c in relay.connects] == [CONNECT_PREFIX]
    assert [r["path"] for r in ip_only.requests] == [CHAT_PATH]
    assert oc.take_proxy_faults() == {"tls-verify"}


def test_o1_an_allowlisted_host_in_a_locked_project_goes_through_the_proxy(proxy, tls_fake,
                                                                          tmp_path):
    project = tmp_path / "proj"
    (project / ".ai-badger").mkdir(parents=True)
    config = project / ".ai-badger" / "config.json"
    config.write_text('{"dataPolicy": {"mode": "local-only", "allowHosts": ["decider.test"]}}',
                      encoding="utf-8")
    reply = post(TARGET, **opted_in(project, HTTPS_PROXY=proxy.url))
    assert (reply.status, reply.error) == (200, None)
    assert len(proxy.connects) == 1 and len(tls_fake.requests) == 1
    config.write_text('{"dataPolicy": "local-only"}', encoding="utf-8")
    refused = post(TARGET, **opted_in(project, HTTPS_PROXY=proxy.url))
    assert refused.error == oc.EGRESS_REFUSED
    assert len(proxy.connects) == 1


# ---------------------------------------------------------------- O2 redirect


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_o2_redirect_is_refused_and_never_followed(fake, capture, code):
    fake.script(CHAT_PATH, fakes.redirect(code, capture.url + "/x"))
    reply = post(fake.url + CHAT_PATH)
    assert reply.status == code
    assert len(fake.requests) == 1
    assert capture.requests == []


# --------------------------------------------------------------------- O3 TLS


def test_o3_opener_is_verified_tls_with_deadline_handlers_only(monkeypatch):
    built = []
    real = ssl.create_default_context

    def spy(*args, **kwargs):
        context = real(*args, **kwargs)
        built.append(context)
        return context

    monkeypatch.setattr(ssl, "create_default_context", spy)
    call = oc.Call(mc.Budget(1.0))
    opener = oc.make_opener(call)
    https = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
    plain = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPHandler)]
    redirects = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    proxies = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert [type(h) for h in https] == [oc.DeadlineHTTPSHandler]
    assert [type(h) for h in plain] == [oc.DeadlineHTTPHandler]
    assert [type(h) for h in redirects] == [oc.NoRedirect]
    assert proxies == []
    context = https[0].tls
    assert built and context is built[-1]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_o3_authorization_is_an_unredirected_header(fake, monkeypatch):
    seen = []
    real_open = urllib.request.OpenerDirector.open

    def spy(self, request, *args, **kwargs):
        seen.append(request)
        return real_open(self, request, *args, **kwargs)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", spy)
    post(fake.url + CHAT_PATH)
    assert len(seen) == 1
    assert seen[0].unredirected_hdrs.get("Authorization") == f"Bearer {KEY}"
    assert "Authorization" not in seen[0].headers


# ------------------------------------------------------------ O4 plain bounds


@pytest.mark.parametrize("mode", ["header-drip", "body-drip", "hang"])
def test_o4_plain_http_share_bounds_drip_and_hang(fake, mode):
    fake.script(CHAT_PATH, fakes.behaviour(mode))
    reply, elapsed = timed_post(fake.url + CHAT_PATH, 0.3)
    assert reply.error == oc.TIMEOUT
    assert elapsed < 1.5
    assert live_openrouter_threads() == []


def test_o4_quick_reply_releases_the_watchdog_at_once(fake):
    for _ in range(20):
        reply, elapsed = timed_post(fake.url + CHAT_PATH, 10.0)
        assert (reply.status, reply.error) == (200, None)
        assert elapsed < 1.5
        assert live_openrouter_threads() == []


# -------------------------------------------------------------- O4b TLS bounds


@pytest.fixture(name="certificate", scope="session")
def certificate_files(tmp_path_factory):
    made = fakes.make_certificate(tmp_path_factory.mktemp("tls"))
    if made is None:
        pytest.skip("openssl is not installed; the throwaway certificate cannot be made")
    return made


@pytest.fixture(name="tls_fake")
def tls_server(certificate, monkeypatch):
    cert, key = certificate
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    server = fakes.FakeOpenRouter(tls=fakes.server_context(cert, key))
    yield server
    server.stop()


def test_o4b_tls_trust_control(tls_fake):
    reply = post(tls_fake.url + CHAT_PATH)
    assert (reply.status, reply.error) == (200, None)
    assert tls_fake.requests[0]["headers"]["authorization"] == f"Bearer {KEY}"


def test_o4b_tls_body_drip_is_bounded(tls_fake):
    tls_fake.script(CHAT_PATH, fakes.behaviour("body-drip"))
    reply, elapsed = timed_post(tls_fake.url + CHAT_PATH, 0.3)
    assert reply.error == oc.TIMEOUT
    assert elapsed < 1.5
    assert len(tls_fake.requests) == 1


def test_o4b_tls_handshake_drip_is_bounded(certificate, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate[0]))
    drip = fakes.DripTcp()
    try:
        reply, elapsed = timed_post(f"https://127.0.0.1:{drip.port}{CHAT_PATH}", 0.3)
    finally:
        drip.stop()
    assert reply.error == oc.TIMEOUT
    assert elapsed < 1.5
    assert drip.connections == 1


# ---------------------------------------------------------- O6 expired budget


def test_o6_expired_budget_makes_no_connection(fake):
    reply = post(fake.url + CHAT_PATH, mc.Budget(0))
    assert reply.error == oc.TIMEOUT
    assert fake.connections == 0 and fake.requests == []
    control = post(fake.url + CHAT_PATH)
    assert (control.status, control.error) == (200, None)


# ------------------------------------------------------------------ O7 oversize


def test_o7_oversize_body_is_transport(fake):
    fake.script(CHAT_PATH, fakes.oversize(2 * 1024 * 1024))
    reply = post(fake.url + CHAT_PATH, 5.0)
    assert reply.error == oc.TRANSPORT
    fake.script(CHAT_PATH, fakes.oversize(1024 * 1024))
    control = post(fake.url + CHAT_PATH, 5.0)
    assert (control.status, control.error, len(control.body)) == (200, None, 1024 * 1024)


# ------------------------------------------------------------------ O8 base URL


def _refused_bases(port):
    return [
        f"http://localhost:{port}", f"http://127.0.0.2:{port}", f"http://[::1]:{port}",
        f"https://127.0.0.1:{port}", f"http://user@127.0.0.1:{port}",
        "http://127.0.0.1.example.com:80", "http://127.0.0.1", f"http://127.0.0.1:{port}/api",
        f"http://127.0.0.1:{port}/", f"http://127.0.0.1:{port}?q=1", "", "not a url",
    ]


def test_o8_base_url_seam_accepts_only_loopback_with_test_key(fake, capture):
    name = "AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE"
    assert oc.api_base({}, KEY) == "https://openrouter.ai"
    assert oc.api_base({}, PRODUCTION_LOOKING_KEY) == "https://openrouter.ai"
    accepted = oc.api_base({name: fake.url}, KEY)
    assert accepted == fake.url
    assert post(accepted + CHAT_PATH).status == 200
    assert len(fake.requests) == 1
    cases = [(fake.url, PRODUCTION_LOOKING_KEY)] + [(base, KEY) for base in
                                                   _refused_bases(fake.port)]
    for base, key in cases:
        found = oc.api_base({name: base}, key)
        if found is not None:
            post(found + CHAT_PATH, key=key)
        assert found is None, base
    assert len(fake.requests) == 1
    assert capture.requests == []


# ----------------------------------------------------------------------- O9 key


@pytest.mark.parametrize("raw,expected", [
    ("sk-test-abc", "sk-test-abc"),
    ("  sk-test-abc\n", "sk-test-abc"),
    ("", None), ("   ", None), ("sk test", None), ("sk-a\nb", None), ("sk-\tx", None),
    ("sk-café", None), ("sk-\x7f", None), ("sk-\x00", None),
])
def test_o9_key_comes_from_env_only_and_must_be_clean(raw, expected):
    assert oc.api_key({"OPENROUTER_API_KEY": raw}) == expected


def test_o9_key_files_are_ignored(memory_context_env, monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text(f"OPENROUTER_API_KEY={KEY}\n", encoding="utf-8")
    (memory_context_env.home / ".openrouter").write_text(KEY, encoding="utf-8")
    monkeypatch.chdir(work)
    assert oc.api_key({}) is None
    assert oc.api_key({"HOME": str(memory_context_env.home)}) is None


def test_o9_request_headers_and_bad_key_never_sent(fake):
    reply = post(fake.url + CHAT_PATH, body={"model": "m", "messages": []})
    assert reply.status == 200
    seen = fake.requests[0]
    assert seen["headers"]["authorization"] == f"Bearer {KEY}"
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["body"] == {"model": "m", "messages": []}
    for bad in (KEY + "\nX-Injected: 1", "q1-secret key", ""):
        assert post(fake.url + CHAT_PATH, key=bad).error == oc.TRANSPORT
    assert len(fake.requests) == 1


# -------------------------------------------------------- O10 multi-address


def test_o10_every_connect_attempt_shares_one_deadline(fake, monkeypatch):
    attempts = []

    def getaddrinfo(host, port, *args, **kwargs):
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))] * 4

    def connect(self, address):
        attempts.append(address)
        time.sleep(min(self.gettimeout() or fakes.FAKE_CEILING_SECONDS,
                       fakes.FAKE_CEILING_SECONDS))
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    reply, elapsed = timed_post(fake.url + CHAT_PATH, 0.4)
    assert reply.error == oc.TIMEOUT
    assert elapsed < 0.9
    assert attempts


# ---------------------------------------------------------------- O11 DNS


def test_o11_dns_is_under_the_deadline_with_one_resolver_per_host(fake, monkeypatch, tmp_path):
    release = threading.Event()
    resolved_on = []
    guarded = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        resolved_on.append((host, threading.current_thread().name))
        if host == "openrouter.test":
            release.wait(fakes.FAKE_CEILING_SECONDS)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        return guarded(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    url = f"https://openrouter.test:{fake.port}{CHAT_PATH}"
    # A named host is third-party: only https with the opt-in from an unlocked cwd lets it be
    # resolved. The resolve hangs past the share, so no TLS handshake is ever attempted.
    opted_in = {"env": {oc.ALLOW_ENV: "1"}, "cwd": str(tmp_path)}
    assert post(url, 0.3).error == oc.EGRESS_REFUSED
    assert resolved_on == []

    def dns_threads():
        return [t for t in threading.enumerate()
                if t.is_alive() and t.name == "ai-badger-openrouter-dns"]

    try:
        reply, elapsed = timed_post(url, 0.3, **opted_in)
        assert reply.error == oc.TIMEOUT
        assert elapsed < 0.8
        again, again_elapsed = timed_post(url, 0.3, **opted_in)
        assert again.error == oc.TIMEOUT
        assert again_elapsed < 0.1
        assert len(dns_threads()) == 1
    finally:
        release.set()
    end = time.monotonic() + 1.0
    while dns_threads() and time.monotonic() < end:
        time.sleep(0.01)
    assert dns_threads() == []
    assert fake.requests == []
    assert [host for host, _ in resolved_on] == ["openrouter.test"]
    literal = post(fake.url + CHAT_PATH)
    assert literal.status == 200
    assert resolved_on[-1] == ("127.0.0.1", threading.current_thread().name)
