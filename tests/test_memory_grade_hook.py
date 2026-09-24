"""Tests for `ai-raccoon-memory/scripts/memory_grade_hook.py`'s `_hook_result` payload parsing.

L9-6's memory-grade counterpart (R7/D#498): once mcp-matchers activates Claude's own MCP
PostToolUse hooks, this hook receives Claude's `tool_response` shape too, whose exact form
hooks.md:2004 leaves unverified. `_hook_result` must accept the two candidate shapes covered by
the gate below without a real capture, and the real Claude shape becomes a third branch and a
fixture when it is captured — never a new caller.
"""
from __future__ import annotations

import json

import pytest

SCRIPT = "features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py"

SEARCH_RESULT = {
    "meta": {"correlationId": "abc-123"},
    "results": [
        {"sourceFile": "/project/docs/adr/0001.md"},
        {"sourceFile": "/project/src/Program.cs"},
    ],
}


@pytest.fixture
def hook(load_script):
    return load_script(SCRIPT)


class _FakeStore:
    """Records every `log_append` call instead of touching real SQLite."""

    def __init__(self):
        self.appended = []

    def log_append(self, table, ts, payload):
        self.appended.append((table, ts, payload))

    def prune_expired(self, table, max_age_days):  # pylint: disable=unused-argument
        pass

    def close(self):
        pass


class TestHookResultShapes:
    """`_hook_result` unwraps `payload["result"]`/`payload["response"]` in each shape a host
    might send it."""

    def test_a_plain_dict_result_passes_through(self, hook):
        assert hook._hook_result({"result": SEARCH_RESULT}) == SEARCH_RESULT

    def test_a_json_string_result_is_decoded(self, hook):
        payload = {"result": json.dumps(SEARCH_RESULT)}
        assert hook._hook_result(payload) == SEARCH_RESULT

    def test_a_call_tool_result_envelope_is_unwrapped(self, hook):
        """L9-6: the standard MCP `CallToolResult` shape,
        `{"content": [{"type": "text", "text": <json>}]}`."""
        payload = {"result": {"content": [
            {"type": "text", "text": json.dumps(SEARCH_RESULT)},
        ]}}
        assert hook._hook_result(payload) == SEARCH_RESULT

    def test_a_json_string_call_tool_result_envelope_is_unwrapped(self, hook):
        payload = {"result": json.dumps({"content": [
            {"type": "text", "text": json.dumps(SEARCH_RESULT)},
        ]})}
        assert hook._hook_result(payload) == SEARCH_RESULT

    def test_a_bare_content_block_list_is_unwrapped(self, hook):
        """No wrapping `{"content": ...}` dict at all — a bare list of blocks."""
        payload = {"result": [{"type": "text", "text": json.dumps(SEARCH_RESULT)}]}
        assert hook._hook_result(payload) == SEARCH_RESULT

    def test_response_key_is_read_when_result_is_absent(self, hook):
        payload = {"response": {"content": [
            {"type": "text", "text": json.dumps(SEARCH_RESULT)},
        ]}}
        assert hook._hook_result(payload) == SEARCH_RESULT

    def test_an_empty_content_list_falls_back_to_the_outer_dict(self, hook):
        """A `content` key present but carrying nothing parseable must not turn a dict result
        into an empty one; the outer dict is still the best available document."""
        payload = {"result": {"content": [], "meta": {"correlationId": "x"}}}
        assert hook._hook_result(payload) == {"content": [], "meta": {"correlationId": "x"}}

    def test_an_unparsable_result_is_empty(self, hook):
        assert hook._hook_result({"result": "not json"}) == {}

    def test_no_result_or_response_is_empty(self, hook):
        assert hook._hook_result({}) == {}


class TestMemorySearchStashAcrossShapes:
    """The gate: the memory-grade hook receives each candidate shape and records the search
    sources exactly the same way regardless of which one arrived."""

    @pytest.mark.parametrize("result", [
        SEARCH_RESULT,
        json.dumps(SEARCH_RESULT),
        {"content": [{"type": "text", "text": json.dumps(SEARCH_RESULT)}]},
        [{"type": "text", "text": json.dumps(SEARCH_RESULT)}],
    ], ids=["plain-dict", "json-string", "call-tool-result-envelope", "bare-block-list"])
    def test_stash_records_the_search_sources(self, hook, monkeypatch, result):
        fake_store = _FakeStore()
        monkeypatch.setattr(hook, "open_store", lambda: fake_store)

        hook._stash_search_sources(hook._hook_result({"result": result}))

        assert len(fake_store.appended) == 1
        table, _ts, entry = fake_store.appended[0]
        assert table == "searches"
        assert entry["correlationId"] == "abc-123"
        assert entry["sourceFiles"] == [
            "/project/docs/adr/0001.md", "/project/src/Program.cs"]
