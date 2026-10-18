"""Memory-first gate: the first sighting of each search pattern runs a memory search.

A repo text-search call passes only when (a) every pattern it searches for was already
memory-searched for this project and (b) a call carrying a `command` string ends with the
`# memory-checked` marker. The first sighting is denied; the hook searches memory itself
and records the pattern when the search answered. Searched patterns persist per project
and are never reset.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

import badger_store
import pytest

SCRIPTS = "features/common/skills/ai-raccoon-memory/scripts/"
PROJECT = "proj-first-sighting"
HITS = "## Memory context\n- hit: docs/merge.md"
USER_EXAMPLE = ("sed -n 50,95p features/codex/adjustments/adjust_hooks.py; echo '---'; "
                "grep -n \"def merge_hooks\\|def _prune\\|append\\|extend\" "
                "features/common/skills/welcome-ai-badger/scripts/hook_wiring.py | head -20")
MARK = "  # memory-checked"


@pytest.fixture
def env(load_script, monkeypatch, tmp_path):
    """Gate + both hooks; every store and fallback path redirected; the search faked."""
    monkeypatch.setenv(badger_store.DEBUG_DIR_ENV, str(tmp_path / "debug"))
    monkeypatch.setenv(badger_store.USER_ROOT_ENV, str(tmp_path / "user-root"))
    monkeypatch.setenv("AI_BADGER_PROJECT_ID", PROJECT)
    gate = load_script(SCRIPTS + "memory_first_gate.py")
    monkeypatch.setattr(gate, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setattr(gate, "SEARCHED_DIR", tmp_path / "memory-first-searched", raising=False)
    calls = []
    state = SimpleNamespace(reply=HITS)

    def fake_hits(query, project_id, session_id, cwd):
        calls.append((query, project_id))
        if isinstance(state.reply, Exception):
            raise state.reply
        return state.reply

    monkeypatch.setattr(gate, "memory_hits", fake_hits, raising=False)
    monkeypatch.setitem(sys.modules, "memory_first_gate", gate)
    return SimpleNamespace(
        gate=gate, calls=calls, state=state, tmp=tmp_path,
        pre=load_script(SCRIPTS + "memory_first_gate_hook.py"),
        post=load_script(SCRIPTS + "memory_first_gate_post_hook.py"))


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(
        payload if isinstance(payload, str) else json.dumps(payload)))


def _bash(env, monkeypatch, capsys, command, session="s1"):
    """Run the Claude PreToolUse hook on a Bash call; the deny reason, or None on pass."""
    _feed(monkeypatch, {"hook_event_name": "PreToolUse", "session_id": session,
                        "cwd": str(env.tmp), "tool_name": "Bash",
                        "tool_input": {"command": command}})
    assert env.pre.main([]) == 0
    out = capsys.readouterr().out
    if not out:
        return None
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def _tool(env, monkeypatch, capsys, name, tool_input):
    _feed(monkeypatch, {"hook_event_name": "PreToolUse", "session_id": "s1",
                        "cwd": str(env.tmp), "tool_name": name, "tool_input": tool_input})
    assert env.pre.main([]) == 0
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else None


def _memory_search(env, monkeypatch, query):
    _feed(monkeypatch, {"hook_event_name": "PostToolUse", "session_id": "s1",
                        "cwd": str(env.tmp), "tool_name": "mcp__ai-raccoon__memory_search",
                        "tool_input": {"projectId": PROJECT, "query": query}})
    assert env.post.main([]) == 0


# ------------------------------------------------------------------ the owner's example
def test_user_example_denied_first_with_hits_then_marker_retry_passes(env, monkeypatch, capsys):
    """Mutation: detect only tokens[0] (the command starts with sed, so it slips through)."""
    reason = _bash(env, monkeypatch, capsys, USER_EXAMPLE)

    assert reason is not None
    assert "hit: docs/merge.md" in reason
    assert "# memory-checked" in reason
    assert "def merge_hooks" in env.calls[0][0]
    assert env.calls[0][1] == PROJECT

    assert _bash(env, monkeypatch, capsys, USER_EXAMPLE + MARK) is None
    assert len(env.calls) == 1  # the retry ran no second search


def test_identical_retry_without_marker_is_still_denied(env, monkeypatch, capsys):
    """Mutation: drop the marker check (a searched pattern alone unlocks)."""
    _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    reason = _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    assert reason is not None and "# memory-checked" in reason
    assert len(env.calls) == 1


def test_marker_on_a_never_searched_pattern_is_denied(env, monkeypatch, capsys):
    """Mutation: let the marker alone unlock."""
    reason = _bash(env, monkeypatch, capsys, "grep -n zebra f.py" + MARK)

    assert reason is not None
    assert env.calls and "zebra" in env.calls[0][0]


def test_spoofed_marker_inside_a_quoted_word_is_denied(env, monkeypatch, capsys):
    env.gate.remember(PROJECT, ["# memory-checked", "foo"])

    assert _bash(env, monkeypatch, capsys, "grep '# memory-checked' f") is not None
    # the raw line ends in the marker, but the lexer reads it as an argument, not a comment
    assert _bash(env, monkeypatch, capsys, "grep foo f \\ # memory-checked") is not None


def test_same_pattern_other_flags_and_path_with_marker_passes(env, monkeypatch, capsys):
    """Mutation: key on the command string instead of the pattern."""
    _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    assert _bash(env, monkeypatch, capsys, "grep -rn foo src/ other/" + MARK) is None


def test_agent_memory_search_containing_the_pattern_counts(env, monkeypatch, capsys):
    """Mutation: the post hook records nothing but telemetry."""
    _memory_search(env, monkeypatch, "Where is merge_hooks defined?")

    assert _bash(env, monkeypatch, capsys, "grep -n merge_hooks f.py" + MARK) is None
    assert not env.calls


def test_memory_search_on_another_topic_unlocks_nothing(env, monkeypatch, capsys):
    """Mutation: restore the session-wide unlock."""
    _memory_search(env, monkeypatch, "release ritual")

    assert _bash(env, monkeypatch, capsys, "grep -n foo f.py" + MARK) is not None


def test_grep_tool_seen_pattern_passes_without_marker(env, monkeypatch, capsys):
    """Mutation: demand the marker from a tool that has no command string."""
    first = _tool(env, monkeypatch, capsys, "Grep", {"pattern": "fooBar"})
    assert first is not None and "# memory-checked" in first

    assert _tool(env, monkeypatch, capsys, "Grep", {"pattern": "fooBar", "path": "src"}) is None
    assert _tool(env, monkeypatch, capsys, "Glob", {"pattern": "**/*.md"}) is not None


def test_a_new_pattern_in_the_same_shape_is_denied(env, monkeypatch, capsys):
    """Mutation: treat every pattern as seen once one was."""
    _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    assert _bash(env, monkeypatch, capsys, "grep -n bar a.py" + MARK) is not None


def test_compound_with_one_seen_and_one_unseen_pattern_is_denied(env, monkeypatch, capsys):
    """Mutation: `any` instead of `all`; the search query must carry only the unseen one."""
    _bash(env, monkeypatch, capsys, "grep foo a.py")

    reason = _bash(env, monkeypatch, capsys, "grep foo a.py; rg quux b" + MARK)

    assert reason is not None
    assert "quux" in env.calls[-1][0] and "foo" not in env.calls[-1][0]


def test_alternation_is_split_into_patterns(env, monkeypatch, capsys):
    """Mutation: drop the `\\|` / bare `|` split."""
    _bash(env, monkeypatch, capsys, "grep 'alpha1\\|beta2' f")
    assert _bash(env, monkeypatch, capsys, "rg beta2" + MARK) is None

    _bash(env, monkeypatch, capsys, "rg 'gamma3|delta4' src")
    assert _bash(env, monkeypatch, capsys, "grep -E delta4 f" + MARK) is None


def test_pattern_extraction(env):
    gate = env.gate
    assert gate.search_patterns("Bash", {"command": "grep -A 3 -e foo f"}) == ["foo"]
    assert gate.search_patterns("Bash", {"command": "grep -A3 foo f"}) == ["foo"]
    assert gate.search_patterns("Bash", {"command": "grep --regexp=foo -e bar f"}) == ["foo", "bar"]
    assert gate.search_patterns("Bash", {"command": "rg -g '*.py' -t py bar src"}) == ["bar"]
    assert gate.search_patterns("Bash", {"command": "find . -name '*.py' -type f"}) == ["*.py"]
    words = gate.search_patterns("Bash", {"command": "find . -type f"})
    assert words and "find" in words[0]
    assert gate.search_patterns("Bash", {"command": "sed -n 1,2p f; cat g"}) is None
    assert gate.search_patterns("Grep", {"pattern": "x\\.y"}) == ["x\\.y"]
    assert gate.search_patterns("search_files", {"query": "q1"}) == ["q1"]


def test_regex_escapes_are_normalized(env, monkeypatch, capsys):
    _memory_search(env, monkeypatch, "foo.bar and def merge")

    assert _bash(env, monkeypatch, capsys, "grep 'foo\\.bar' f" + MARK) is None
    assert _bash(env, monkeypatch, capsys, "grep '^def merge\\b' f" + MARK) is None


def test_sed_and_cat_are_never_touched(env, monkeypatch, capsys):
    assert _bash(env, monkeypatch, capsys, "sed -n 1,2p f; cat g | head") is None
    assert not env.calls


# ------------------------------------------------------------------ search unavailable
def test_no_executable_names_memory_search_then_post_hook_then_marker_passes(
        env, monkeypatch, capsys):
    """Owner rule: a search that could not run records nothing; the agent's own does."""
    env.state.reply = None

    reason = _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py")
    assert "memory_search" in reason and "widgetfactory" in reason.lower()
    assert "# memory-checked" in reason
    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py" + MARK) is not None

    _memory_search(env, monkeypatch, "widgetFactory")

    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py" + MARK) is None


def test_search_raising_still_denies_and_exits_zero(env, monkeypatch, capsys):
    env.state.reply = RuntimeError("boom")

    reason = _bash(env, monkeypatch, capsys, "grep -n foo f")

    assert reason is not None and "memory_search" in reason
    assert env.gate.unsearched(PROJECT, ["foo"]) == ["foo"]


def test_fourth_new_pattern_denial_still_denies(env, monkeypatch, capsys):
    """Mutation: restore the 3-strike pass-through."""
    env.state.reply = None
    for _ in range(4):
        assert _bash(env, monkeypatch, capsys, "grep -n foo f" + MARK) is not None


# ------------------------------------------------------------------ persistence
def test_searched_patterns_live_in_the_hook_state_row(env, monkeypatch, capsys):
    _bash(env, monkeypatch, capsys, "grep -n foo f")

    store = badger_store.open_audit()
    try:
        row = store.kv_get("hook_state", "memory_first.searched." + PROJECT)
    finally:
        store.close()
    assert "foo" in row


def test_store_missing_falls_back_to_the_file(env, monkeypatch, capsys):
    def _broken(*_a, **_k):
        raise OSError("store unavailable")

    monkeypatch.setattr(badger_store, "open_audit", _broken)
    _bash(env, monkeypatch, capsys, "grep -n foo f")

    assert _bash(env, monkeypatch, capsys, "grep -n foo f" + MARK) is None
    lines = (env.tmp / "memory-first-searched" / PROJECT).read_text().splitlines()
    assert "foo" in lines


def test_seen_pattern_survives_a_new_session(env, monkeypatch, capsys):
    _bash(env, monkeypatch, capsys, "grep -n foo f", session="old")

    assert _bash(env, monkeypatch, capsys, "grep -n foo f" + MARK, session="new") is None


def test_unknown_project_never_persists(env):
    assert env.gate.remember("unknown", ["foo"]) is False
    assert env.gate.unsearched("unknown", ["foo"]) == ["foo"]


# ------------------------------------------------------------------ Copilot transport
def test_copilot_string_tool_args_on_both_hooks(env, monkeypatch, capsys):
    env.state.reply = None
    _feed(monkeypatch, {"hookEventName": "preToolUse", "sessionId": "c1",
                        "cwd": str(env.tmp), "toolName": "bash",
                        "toolArgs": json.dumps({"command": "grep -n gizmo f"})})
    assert env.pre.main([]) == 0
    assert json.loads(capsys.readouterr().out)["permissionDecision"] == "deny"

    _feed(monkeypatch, {"hookEventName": "postToolUse", "sessionId": "c1",
                        "cwd": str(env.tmp), "toolName": "memory_search",
                        "toolArgs": json.dumps({"query": "gizmo"})})
    assert env.post.main([]) == 0

    _feed(monkeypatch, {"hookEventName": "preToolUse", "sessionId": "c1",
                        "cwd": str(env.tmp), "toolName": "bash",
                        "toolArgs": json.dumps({"command": "grep -n gizmo f" + MARK})})
    assert env.pre.main([]) == 0
    assert capsys.readouterr().out == ""
