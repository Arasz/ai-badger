"""`--discover` honours `headersHelper` and reports 401/403 with what the challenge said.

Claude Code's contract (code.claude.com/docs/en/mcp, "headersHelper", read 2026-10-18): a shell
command whose stdout is a JSON object of string headers, merged over static `headers`; 10s
timeout; cwd by where the server is declared (user scope: ~/.claude; project: the project dir;
plugin: its root); CLAUDE_CODE_MCP_SERVER_NAME/_URL set; project and plugin helpers run without
credential-looking env vars; a project or local helper runs only once that directory is trusted.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"
CLIENT = "features/common/skills/mcp-index/scripts/mcp_client.py"
CHALLENGE = ('Bearer error="invalid_token", '
             'resource_metadata="https://mcp.example.test/.well-known/oauth-protected-resource",'
             ' scope="mcp:connect files:read"')


class _Fake:
    def __init__(self, mode):
        self.mode = mode
        self.headers = []


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, status, body=b"", headers=()):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_DELETE(self):  # noqa: N802
            self._reply(200)

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.headers.append(dict(self.headers))
            if fake.mode == "401":
                return self._reply(401, b"{}", [("WWW-Authenticate", CHALLENGE)])
            if fake.mode == "403":
                return self._reply(403, b"{}", [("WWW-Authenticate",
                                                 'Bearer error="insufficient_scope", '
                                                 'scope="admin"')])
            if fake.mode == "401-bare":
                return self._reply(401, b"{}")
            method = body.get("method")
            if method is None or method.startswith("notifications/"):
                return self._reply(202)
            result = ({"protocolVersion": "2025-06-18", "capabilities": {}}
                      if method == "initialize"
                      else {"tools": [{"name": "remote", "description": "Remote tool."}]})
            return self._reply(200, json.dumps(
                {"jsonrpc": "2.0", "id": body["id"], "result": result}).encode())

    return Handler


@pytest.fixture(name="serve")
def _serve():
    servers = []

    def start(mode="json"):
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


def _names_only(*names):
    return json.dumps({"servers": [
        {"name": n, "enabled": True, "tools": [], "tools_known": False} for n in names]})


def _source(target: Path, name: str):
    index = json.loads((target / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))
    return next(s for s in index["sources"] if s["name"] == name)


def _discover(mod, target, *names):
    return mod.main(["init", "--target", str(target), "--discover", "--no-host-tools",
                     "--from-json", _names_only(*names)])


@pytest.fixture(name="claude_json")
def _claude_json(monkeypatch):
    """Write ~/.claude.json (HOME is a scratch dir for the suite) and remove it afterwards."""
    path = Path.home() / ".claude.json"
    (Path.home() / ".claude").mkdir(exist_ok=True)
    yield lambda data: path.write_text(json.dumps(data), encoding="utf-8")
    path.unlink(missing_ok=True)


@pytest.fixture(name="mod")
def _mod(load_script, monkeypatch):
    mod = load_script(SCRIPT)
    monkeypatch.setattr(mod.hl, "enrich_with_hermes_test", lambda servers, run=None: [])
    return mod


# ── headersHelper ────────────────────────────────────────────────────────────

def test_a_user_helper_runs_in_the_config_dir_and_overrides_static_headers(
        mod, serve, claude_json, tmp_path):
    fake = serve()
    seen = tmp_path / "helper.seen"
    helper = (f'echo "$PWD|$CLAUDE_CODE_MCP_SERVER_NAME|$CLAUDE_CODE_MCP_SERVER_URL" > {seen}; '
              "printf '%s' '{\"Authorization\": \"Bearer dynamic\", \"X-Extra\": \"1\"}'")
    claude_json({"mcpServers": {"remote": {
        "type": "http", "url": fake.url, "headersHelper": helper,
        "headers": {"Authorization": "Bearer static", "X-Static": "kept"}}}})

    assert _discover(mod, tmp_path, "remote") == 0

    assert list(_source(tmp_path, "remote")["tools"]) == ["remote"]
    first = fake.headers[0]
    assert first["Authorization"] == "Bearer dynamic"
    assert first["X-Static"] == "kept" and first["X-Extra"] == "1"
    cwd, name, url = seen.read_text().strip().split("|")
    assert Path(cwd).resolve() == (Path.home() / ".claude").resolve()
    assert (name, url) == ("remote", fake.url)


@pytest.mark.parametrize("helper, reason", [
    ("echo nope >&2; exit 7", "exited 7: nope"),
    ("echo 'not json'", "output is not a JSON object of string headers"),
    ("echo '{\"X-N\": 5}'", "output is not a JSON object of string headers"),
    ("printf '%s' '{\"X-A\": \"a\\r\\nX-B: b\"}'", "output is not a JSON object of string headers"),
])
def test_a_failing_helper_fails_only_its_server(mod, serve, claude_json, tmp_path, capsys,
                                                helper, reason):
    bad, good = serve(), serve()
    claude_json({"mcpServers": {
        "bad": {"type": "http", "url": bad.url, "headersHelper": helper},
        "good": {"type": "http", "url": good.url}}})

    assert _discover(mod, tmp_path, "bad", "good") == 0

    err = capsys.readouterr().err
    assert f"bad: failed: headersHelper {reason}" in err
    assert bad.headers == []  # never connected without the headers it was configured with
    assert list(_source(tmp_path, "good")["tools"]) == ["remote"]


def test_a_hung_helper_times_out(mod, serve, claude_json, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(mod.tdisc.hh, "TIMEOUT", 0.5)
    fake = serve()
    claude_json({"mcpServers": {"slow": {"type": "http", "url": fake.url,
                                         "headersHelper": "sleep 30"}}})

    assert _discover(mod, tmp_path, "slow") == 0

    assert "slow: failed: headersHelper timed out after 0.5s" in capsys.readouterr().err


def test_helper_headers_go_only_to_their_own_server(mod, serve, claude_json, tmp_path):
    a, b = serve(), serve()
    claude_json({"mcpServers": {
        "a": {"type": "http", "url": a.url,
              "headersHelper": "printf '%s' '{\"X-Secret\": \"for-a\"}'"},
        "b": {"type": "http", "url": b.url}}})

    assert _discover(mod, tmp_path, "a", "b") == 0

    assert a.headers[0]["X-Secret"] == "for-a"
    assert all("X-Secret" not in h for h in b.headers)


def _project_helper(target: Path, url: str, marker: Path, approved: bool):
    helper = (f'echo "$PWD|${{FAKE_SECRET_TOKEN:-unset}}" > {marker}; '
              "printf '%s' '{\"Authorization\": \"Bearer project\"}'")
    (target / ".mcp.json").write_text(json.dumps({"mcpServers": {"proj": {
        "type": "http", "url": url, "headersHelper": helper,
        "headers": {"X-Static": "s"}}}}), encoding="utf-8")
    (target / ".claude").mkdir(exist_ok=True)
    (target / ".claude" / "settings.local.json").write_text(
        json.dumps({"enableAllProjectMcpServers": approved}), encoding="utf-8")


def test_an_unapproved_project_helper_never_runs(mod, serve, claude_json, tmp_path, capsys):
    fake, marker = serve(), tmp_path / "ran"
    _project_helper(tmp_path, fake.url, marker, approved=False)
    claude_json({"projects": {str(tmp_path): {"hasTrustDialogAccepted": True}}})

    assert _discover(mod, tmp_path, "proj") == 0

    assert not marker.exists() and fake.headers == []
    assert "proj: not run: project server not approved" in capsys.readouterr().err


def test_an_untrusted_project_helper_is_skipped_and_static_headers_are_used(
        mod, serve, claude_json, tmp_path, capsys):
    fake, marker = serve(), tmp_path / "ran"
    _project_helper(tmp_path, fake.url, marker, approved=True)
    claude_json({"projects": {str(tmp_path.parent): {"hasTrustDialogAccepted": True}}})

    assert _discover(mod, tmp_path, "proj") == 0

    assert not marker.exists()  # a parent folder's trust does not count
    assert fake.headers[0]["X-Static"] == "s" and "Authorization" not in fake.headers[0]
    assert "headersHelper not run: project not trusted" in capsys.readouterr().err


def test_a_trusted_project_helper_runs_in_the_project_without_credentials(
        mod, serve, claude_json, tmp_path, monkeypatch):
    fake, marker = serve(), tmp_path / "ran"
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "do-not-leak")
    _project_helper(tmp_path, fake.url, marker, approved=True)
    claude_json({"projects": {str(tmp_path): {"hasTrustDialogAccepted": True}}})

    assert _discover(mod, tmp_path, "proj") == 0

    cwd, secret = marker.read_text().strip().split("|")
    assert Path(cwd).resolve() == tmp_path.resolve()
    assert secret == "unset"
    assert fake.headers[0]["Authorization"] == "Bearer project"


# ── 401 vs 403 ───────────────────────────────────────────────────────────────

def test_a_401_carries_its_challenge(load_script, serve):
    mc = load_script(CLIENT)
    fake = serve("401")

    with pytest.raises(mc.Unauthorized) as caught:
        mc.list_tools({"type": "http", "url": fake.url}, timeout=10)

    assert caught.value.status == 401
    assert caught.value.resource_metadata == (
        "https://mcp.example.test/.well-known/oauth-protected-resource")
    assert caught.value.scope == "mcp:connect files:read"
    assert "needs authorization (HTTP 401)" in str(caught.value)


def test_a_403_is_told_apart_from_a_401(load_script, serve):
    mc = load_script(CLIENT)
    fake = serve("403")

    with pytest.raises(mc.Unauthorized) as caught:
        mc.list_tools({"type": "http", "url": fake.url}, timeout=10)

    assert caught.value.status == 403
    assert "forbidden (HTTP 403" in str(caught.value)
    assert caught.value.scope == "admin"


def test_the_skip_report_names_the_challenge_and_the_fix(mod, serve, claude_json, tmp_path,
                                                        capsys):
    a, b, c = serve("401"), serve("403"), serve("401-bare")
    claude_json({"mcpServers": {"a": {"type": "http", "url": a.url},
                                "b": {"type": "http", "url": b.url},
                                "c": {"type": "http", "url": c.url}}})

    assert _discover(mod, tmp_path, "a", "b", "c") == 0

    err = capsys.readouterr().err
    line_a = next(line for line in err.splitlines() if line.strip().startswith("a:"))
    assert "needs authorization (HTTP 401)" in line_a
    assert "resource_metadata=https://mcp.example.test/.well-known/oauth-protected-resource" \
        in line_a
    assert "scope=mcp:connect files:read" in line_a
    assert "/mcp" in line_a
    line_b = next(line for line in err.splitlines() if line.strip().startswith("b:"))
    assert "forbidden (HTTP 403)" in line_b and "scope=admin" in line_b
    line_c = next(line for line in err.splitlines() if line.strip().startswith("c:"))
    assert "needs authorization (HTTP 401)" in line_c and "resource_metadata" not in line_c
