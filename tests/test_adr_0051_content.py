"""ADR-0051 must record the owner decisions the review-flow implementation is built against.

The owner settled storage, rule activation, publishing and the v1 interface before the ADR was
written. These tests fail when the record drops one of those decisions, and when the GitHub API
surface names an endpoint without a docs.github.com source or an explicit UNVERIFIED mark.
"""
from __future__ import annotations

import re
from pathlib import Path

ADR = Path(__file__).resolve().parents[1] / "docs" / "adr" / "0051-review-flow-coordinator.md"
ENDPOINT = re.compile(r"\b(?:GET|POST|PATCH|PUT|DELETE)\b|/repos/|GraphQL|\bmutation\b|\bgh api\b")


def _text() -> str:
    assert ADR.exists(), f"{ADR.name} is missing"
    return ADR.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ") and heading in line), None)
    assert start is not None, f"the ADR has no '## {heading}' section"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1:end]


def test_storage_adds_a_table_without_a_schema_version_bump():
    text = _text()
    assert "review_flows" in text
    assert "CREATE TABLE IF NOT EXISTS" in text
    assert re.search(r"no `?SCHEMA_VERSION`? bump", text, re.IGNORECASE), "the ADR must say there is no SCHEMA_VERSION bump"
    assert "engine/badger_store.py:331-334" in text and "engine/badger_store.py:496-504" in text


def test_rules_file_is_loaded_from_the_base_ref_never_the_head():
    text = _text()
    assert ".ai-badger/review/rules.json" in text
    assert re.search(r"base ref", text, re.IGNORECASE)
    assert re.search(r"never (?:from )?the (?:PR )?head", text, re.IGNORECASE)


def test_publish_posts_comment_events_only():
    text = _text()
    assert re.search(r"`?event`?\s*(?:is always|=|always)\s*`?COMMENT`?", text), "publish must be COMMENT-only"


def test_the_three_activation_paths_are_recorded():
    text = _text().lower()
    assert "maintainer" in text and "confirm" in text
    assert "citation" in text and "script-verified" in text
    assert re.search(r"(?:two|2) or more independent threads|>= ?2 independent threads|≥ ?2 independent threads", text)
    assert "distinct thread ids" in text and "distinct authors" in text


def test_only_trusted_associations_teach():
    text = _text()
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert association in text, f"{association} is not named as a teaching association"


def test_v1_is_cli_only_with_no_mcp_server():
    text = _text()
    assert re.search(r"CLI only|CLI-only", text)
    assert re.search(r"no MCP server in v1", text, re.IGNORECASE)


def test_every_api_surface_endpoint_line_cites_docs_or_says_unverified():
    lines = [line for line in _section(_text(), "GitHub API surface") if line.strip().startswith(("-", "|"))]
    endpoint_lines = [line for line in lines if ENDPOINT.search(line)]
    assert len(endpoint_lines) >= 8, f"the API surface lists only {len(endpoint_lines)} endpoint lines"
    bare = [line for line in endpoint_lines if "docs.github.com" not in line and "UNVERIFIED" not in line]
    assert not bare, "endpoint lines without a docs.github.com URL or UNVERIFIED:\n" + "\n".join(bare)
