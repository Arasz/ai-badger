"""Where the server list comes from once `hermes mcp list --json` is gone (issue #188).

Every sample below is a verbatim capture from the CLI named above it, taken on a 2026-07
install, with the maintainer's home directory replaced by `/opt/`. Parsing a shape nobody
has seen is how #188 happened in the first place.
"""

from __future__ import annotations

import json

import pytest

SCRIPT ="features/common/skills/mcp-index/scripts/host_listings.py"
INDEX_SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"

# Captured: `claude mcp list` (Claude Code 2.x, 17 servers, 13.6s).
CLAUDE_LISTING = """\
Checking MCP server health…

claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected
claude.ai Microsoft 365: https://microsoft365.mcp.claude.com/mcp - ! Needs authentication
plugin:github:github: https://api.githubcopilot.com/mcp/ (HTTP) - ✘ Failed to connect — HTTP 400: \
Streamable HTTP error: Error POSTing to endpoint: bad request: Authorization header is badly formatted
plugin:playwright:playwright: npx @playwright/mcp@latest - ✔ Connected
plugin:terraform:terraform: docker run -i --rm -e TFE_TOKEN=[REDACTED] \
hashicorp/terraform-mcp-server:0.4.0 - ✔ Connected
plugin:dotnet-claude-kit:cwm-roslyn-navigator: cwm-roslyn-navigator  - ✔ Connected
plugin:ai-badger:hermes: /opt/hermes/bin/hermes mcp serve - ✔ Connected
rider: http://127.0.0.1:64482/stream (HTTP) - ✔ Connected
"""

# Captured: `hermes mcp list` (no --json on this hermes — `error: unrecognized arguments: --json`).
HERMES_TEXT_LISTING = """\

  MCP Servers:

  Name             Transport                      Tools        Status
  ──────────────── ────────────────────────────── ──────────── ──────────
  dotnet-sdk       dotnet-mcp                     all          ✓ enabled
  llmstudio        http://127.0.0.1:1235          all          ✗ disabled
  code-review-graph /opt/badger/venv/bin/python    all          ✓ enabled
"""

HERMES_NO_JSON_FLAG = (
    "usage: hermes mcp list [-h]\nhermes mcp list: error: unrecognized arguments: --json\n"
)


def _fake_runner(answers):
    """A `run_cli` stand-in: argv tuple -> (exit code or None, stdout, note)."""
    def _run(argv):
        return answers.get(tuple(argv), (None, "", "not installed"))
    return _run


def _named(servers, name):
    return next(s for s in servers if s["name"] == name)


# ── `claude mcp list`: the second verified surface ───────────────────────────

def test_claude_listing_names_every_server_it_health_checked(load_script):
    mod = load_script(SCRIPT)

    names = [s["name"] for s in mod.parse_claude_listing(CLAUDE_LISTING)]

    assert names == [
        "claude.ai Google Drive", "claude.ai Microsoft 365", "plugin:github:github",
        "plugin:playwright:playwright", "plugin:terraform:terraform",
        "plugin:dotnet-claude-kit:cwm-roslyn-navigator", "plugin:ai-badger:hermes", "rider",
    ]


def test_claude_listing_ignores_the_health_check_banner(load_script):
    """`Checking MCP server health…` is the first line of stdout, and is not a server."""
    mod = load_script(SCRIPT)

    assert all("Checking" not in s["name"] for s in mod.parse_claude_listing(CLAUDE_LISTING))


def test_claude_listing_keeps_the_reachability_phrase_verbatim(load_script):
    """The phrase is the host's word; mapping it to a status is tool_descriptions' job."""
    mod = load_script(SCRIPT)
    servers = mod.parse_claude_listing(CLAUDE_LISTING)

    assert _named(servers, "rider")["host_status"] == "Connected"
    assert _named(servers, "claude.ai Microsoft 365")["host_status"] == "Needs authentication"
    assert _named(servers, "plugin:github:github")["host_status"] == "Failed to connect"


def test_claude_listing_admits_it_never_lists_tools(load_script):
    """No `claude mcp list` mode prints tool names — reading [] as "exposes nothing" wipes an index."""
    mod = load_script(SCRIPT)
    servers = mod.parse_claude_listing(CLAUDE_LISTING)

    assert all(s["tools"] == [] for s in servers)
    assert all(s["tools_known"] is False for s in servers)


def test_claude_listing_records_the_url_of_an_http_server_only(load_script):
    mod = load_script(SCRIPT)
    servers = mod.parse_claude_listing(CLAUDE_LISTING)

    assert _named(servers, "rider")["url"] == "http://127.0.0.1:64482/stream"
    assert "url" not in _named(servers, "plugin:playwright:playwright")


def test_claude_listing_survives_a_command_carrying_flags_and_a_redacted_env_var(load_script):
    """`docker run -i --rm -e TFE_TOKEN=[REDACTED] …` must not be mistaken for the status field."""
    mod = load_script(SCRIPT)
    servers = mod.parse_claude_listing(CLAUDE_LISTING)

    assert _named(servers, "plugin:terraform:terraform")["host_status"] == "Connected"
    assert _named(servers, "plugin:dotnet-claude-kit:cwm-roslyn-navigator")["host_status"] == \
        "Connected"


def test_claude_listing_of_nothing_is_empty_not_a_crash(load_script):
    mod = load_script(SCRIPT)

    assert mod.parse_claude_listing("Checking MCP server health…\n\n") == []


# ── the two hermes surfaces ─────────────────────────────────────────────────

def test_hermes_text_listing_carries_the_enabled_flag_and_no_tool_detail(load_script):
    mod = load_script(SCRIPT)
    servers = mod.parse_hermes_text_listing(HERMES_TEXT_LISTING)

    assert [s["name"] for s in servers] == ["dotnet-sdk", "llmstudio", "code-review-graph"]
    assert [s["enabled"] for s in servers] == [True, False, True]
    assert all(s["tools_known"] is False for s in servers)


def test_hermes_json_listing_is_the_only_source_that_carries_tools(load_script):
    mod = load_script(SCRIPT)
    servers = mod.parse_hermes_json_listing(json.dumps({"servers": [
        {"name": "rider", "enabled": True, "tools": [{"name": "build_solution"}]},
    ]}))

    assert servers[0]["tools"] == [{"name": "build_solution"}]
    assert mod.carries_tool_detail(servers) is True


def test_a_listing_with_no_tool_detail_says_so(load_script):
    """The predicate that stops `update` from calling an unlisted server gone."""
    mod = load_script(SCRIPT)

    assert mod.carries_tool_detail(mod.parse_claude_listing(CLAUDE_LISTING)) is False
    assert mod.carries_tool_detail(mod.parse_hermes_text_listing(HERMES_TEXT_LISTING)) is False
    assert mod.carries_tool_detail([]) is False


# ── the source chain ────────────────────────────────────────────────────────

def test_discover_prefers_the_json_listing_when_a_host_still_has_one(load_script):
    mod = load_script(SCRIPT)
    listing = mod.discover(run=_fake_runner({
        ("hermes", "mcp", "list", "--json"): (0, json.dumps({"servers": [
            {"name": "rider", "enabled": True, "tools": [{"name": "build_solution"}]}]}), ""),
        ("claude", "mcp", "list"): (0, CLAUDE_LISTING, ""),
    }))

    assert listing.label == "hermes mcp list --json"
    assert [s["name"] for s in listing.servers] == ["rider"]


def test_discover_falls_back_to_claude_when_hermes_has_no_json_flag(load_script):
    """Issue #188: this is the measured state of a current install."""
    mod = load_script(SCRIPT)
    listing = mod.discover(run=_fake_runner({
        ("hermes", "mcp", "list", "--json"): (2, "", HERMES_NO_JSON_FLAG.splitlines()[-1]),
        ("claude", "mcp", "list"): (0, CLAUDE_LISTING, ""),
        ("hermes", "mcp", "list"): (0, HERMES_TEXT_LISTING, ""),
    }))

    assert listing.label == "claude mcp list"
    assert "rider" in [s["name"] for s in listing.servers]
    assert any("unrecognized arguments: --json" in note for note in listing.notes)


def test_discover_falls_back_to_the_hermes_text_table_when_claude_is_absent(load_script):
    mod = load_script(SCRIPT)
    listing = mod.discover(run=_fake_runner({
        ("hermes", "mcp", "list", "--json"): (2, "", "unrecognized arguments: --json"),
        ("hermes", "mcp", "list"): (0, HERMES_TEXT_LISTING, ""),
    }))

    assert listing.label == "hermes mcp list"
    assert [s["name"] for s in listing.servers] == \
        ["dotnet-sdk", "llmstudio", "code-review-graph"]
    assert any("claude mcp list: not installed" == note for note in listing.notes)


def test_discover_returns_nothing_and_names_every_source_it_tried(load_script):
    """No host CLI at all: the caller must be able to print why, not guess."""
    mod = load_script(SCRIPT)
    listing = mod.discover(run=_fake_runner({}))

    assert listing.servers == [] and listing.label == ""
    assert [note.split(":")[0] for note in listing.notes] == ["hermes mcp list --json",
                                                              "claude mcp list",
                                                              "hermes mcp list"]


def test_discover_honours_an_explicit_host(load_script):
    """`--host hermes` must not health-check every claude server for 14 seconds."""
    mod = load_script(SCRIPT)
    asked = []

    def _run(argv):
        asked.append(argv[0])
        return _fake_runner({("hermes", "mcp", "list"): (0, HERMES_TEXT_LISTING, ""),
                             ("hermes", "mcp", "list", "--json"): (2, "", "no --json")})(argv)

    listing = mod.discover(host="hermes", run=_run)

    assert listing.label == "hermes mcp list"
    assert set(asked) == {"hermes"}


def test_discover_treats_unreadable_json_as_a_source_that_did_not_answer(load_script):
    mod = load_script(SCRIPT)
    listing = mod.discover(run=_fake_runner({
        ("hermes", "mcp", "list", "--json"): (0, "not json at all", ""),
        ("hermes", "mcp", "list"): (0, HERMES_TEXT_LISTING, ""),
    }))

    assert listing.label == "hermes mcp list"
    assert any("unreadable" in note for note in listing.notes)


def test_run_cli_reports_a_missing_binary_instead_of_raising(load_script):
    """A skill script degrades with a note when the host CLI is not installed."""
    mod = load_script(SCRIPT)

    code, stdout, note = mod.run_cli(["ai-badger-no-such-host-cli", "mcp", "list"])

    assert code is None and stdout == ""
    assert "not installed" in note


# ── what mcp-index does with all of it ──────────────────────────────────────

def test_init_indexes_the_servers_a_claude_listing_reports(tmp_path, load_script, monkeypatch):
    """Discovery is restored: `init` produces sources on a host with no `--json` at all."""
    mod = load_script(INDEX_SCRIPT)
    monkeypatch.setattr(mod.hl, "run_cli", _fake_runner({
        ("hermes", "mcp", "list", "--json"): (2, "", "unrecognized arguments: --json"),
        ("claude", "mcp", "list"): (0, CLAUDE_LISTING, ""),
    }))

    assert mod.main(["init", "--target", str(tmp_path)]) == 0

    index = json.loads((tmp_path / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))
    assert "rider" in [s["name"] for s in index["sources"]]


def test_init_refuses_loudly_when_no_host_cli_answers(tmp_path, load_script, monkeypatch, capsys):
    """The old code raised FileNotFoundError; a skill script must name the remedy instead."""
    mod = load_script(INDEX_SCRIPT)
    monkeypatch.setattr(mod.hl, "run_cli", _fake_runner({}))

    with pytest.raises(SystemExit) as exit_info:
        mod.main(["init", "--target", str(tmp_path)])

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "claude mcp list" in err and "hermes mcp list" in err
    assert not (tmp_path / ".ai-badger" / "mcp-tools.json").exists()


def test_init_reports_which_host_listing_it_used(tmp_path, load_script, monkeypatch, capsys):
    mod = load_script(INDEX_SCRIPT)
    monkeypatch.setattr(mod.hl, "run_cli", _fake_runner({
        ("claude", "mcp", "list"): (0, CLAUDE_LISTING, ""),
    }))

    assert mod.main(["init", "--target", str(tmp_path)]) == 0

    assert "claude mcp list" in capsys.readouterr().err


def test_host_flag_picks_the_listing_to_read(tmp_path, load_script, monkeypatch):
    mod = load_script(INDEX_SCRIPT)
    monkeypatch.setattr(mod.hl, "run_cli", _fake_runner({
        ("claude", "mcp", "list"): (0, CLAUDE_LISTING, ""),
        ("hermes", "mcp", "list"): (0, HERMES_TEXT_LISTING, ""),
    }))

    assert mod.main(["init", "--target", str(tmp_path), "--host", "hermes"]) == 0

    index = json.loads((tmp_path / ".ai-badger" / "mcp-tools.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in index["sources"]] == \
        ["dotnet-sdk", "llmstudio", "code-review-graph"]


def test_an_unknown_host_is_rejected_with_the_choices(load_script, tmp_path, capsys):
    mod = load_script(INDEX_SCRIPT)

    assert mod.main(["init", "--target", str(tmp_path), "--host", "vscode"]) == 2
    assert "hermes" in capsys.readouterr().err
