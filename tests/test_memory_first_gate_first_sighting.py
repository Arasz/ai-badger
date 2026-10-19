"""The first sighting of a repo search pattern searches memory and captures raw output."""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import stat
import sys
import time
from types import SimpleNamespace

import badger_store
import pytest

SCRIPTS = "features/common/skills/ai-raccoon-memory/scripts/"
PROJECT = "proj-first-sighting"
HITS = "## Memory context\n- hit: docs/merge.md"
USER_EXAMPLE = ("sed -n 50,95p features/codex/adjustments/adjust_hooks.py; echo '---'; "
                "grep -n \"def merge_hooks\\|def _prune\\|append\\|extend\" "
                "features/common/skills/welcome-ai-badger/scripts/hook_wiring.py | head -20")


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

    def fake_hits(query, project_id, *_rest):
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
def test_user_example_denied_first_then_unmarked_retry_passes(env, monkeypatch, capsys):
    """Mutation: detect only tokens[0] (the command starts with sed, so it slips through)."""
    reason = _bash(env, monkeypatch, capsys, USER_EXAMPLE)

    assert reason is not None
    assert "hit: docs/merge.md" in reason
    assert "memory-checked" not in reason
    assert "def merge_hooks" in env.calls[0][0]
    assert env.calls[0][1] == PROJECT

    assert _bash(env, monkeypatch, capsys, USER_EXAMPLE) is None
    assert len(env.calls) == 1  # the retry ran no second search


def test_first_sighting_launches_async_capture_and_returns_exact_pattern_hash(
        env, monkeypatch, capsys):
    pattern = "def merge_hooks"
    pattern_hash = hashlib.sha256(pattern.encode("utf-8")).hexdigest()
    launched = []

    def fake_popen(args, **kwargs):
        launched.append((args, kwargs))
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(env.gate.subprocess, "Popen", fake_popen)
    reason = _bash(env, monkeypatch, capsys,
                   "grep -n 'def merge_hooks' features/hook_wiring.py")

    assert reason is not None
    assert pattern_hash in reason
    assert len(launched) == 1
    capture_args = launched[0][0]
    assert "--capture" in capture_args
    capture_at = capture_args.index("--capture")
    assert pattern_hash in capture_args[capture_at + 1]
    assert json.loads(capture_args[capture_at + 2]) == [
        "grep", "-n", pattern, "features/hook_wiring.py"]
    assert launched[0][1]["start_new_session"] is True
    assert launched[0][1]["stdin"] is env.gate.subprocess.DEVNULL
    assert launched[0][1]["cwd"] == str(env.tmp)


def test_first_sighting_returns_and_logs_search_result_with_pattern_hash_mapping(
        env, monkeypatch, capsys):
    patterns = ["jsonlNeedle_42", "jsonlNeedle_43", "jsonlNeedle_44"]
    log_path = env.tmp / "memory-first.jsonl"
    monkeypatch.setattr(env.gate, "SEARCH_LOG_PATH", log_path)
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: SimpleNamespace(pid=1236))

    command = "grep -n " + " ".join(f"-e {pattern}" for pattern in patterns) + " source.py"
    reason = _bash(env, monkeypatch, capsys, command)

    expected = {
        "searchResult": {"mem_search_result_output": HITS},
        "rawGrepInput": [
            {"pattern": pattern,
             "hash": hashlib.sha256(pattern.encode("utf-8")).hexdigest()}
            for pattern in patterns
        ],
    }
    assert json.loads(reason) == expected
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == expected
    assert stat.S_IMODE(log_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600


def test_search_jsonl_log_stays_bounded_and_valid(env, monkeypatch):
    log_path = env.tmp / "memory-first" / "searches.jsonl"
    log_path.parent.mkdir(mode=0o755)
    log_path.parent.chmod(0o755)
    log_path.write_text("old record\n", encoding="utf-8")
    log_path.chmod(0o644)
    monkeypatch.setattr(env.gate, "SEARCH_LOG_PATH", log_path)
    monkeypatch.setattr(env.gate, "MAX_SEARCH_LOG_BYTES", 300)
    payload = {
        "searchResult": {"mem_search_result_output": "a" * 30},
        "rawGrepInput": [{"pattern": "needle", "hash": "f" * 64}],
    }

    for _ in range(6):
        env.gate.append_search_result(payload)

    content = log_path.read_bytes()
    assert len(content) <= 300
    assert content.endswith(b"\n")
    assert all(json.loads(line) == payload for line in content.splitlines())
    assert stat.S_IMODE(log_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600


def test_rg_first_sighting_launches_async_capture_with_exact_pattern_hash(
        env, monkeypatch, capsys):
    pattern = "def _prune"
    pattern_hash = hashlib.sha256(pattern.encode("utf-8")).hexdigest()
    launched = []

    def fake_popen(args, **kwargs):
        launched.append((args, kwargs))
        return SimpleNamespace(pid=1235)

    monkeypatch.setattr(env.gate.subprocess, "Popen", fake_popen)
    command = "rg -n 'def _prune' features/hook_wiring.py"
    reason = _bash(env, monkeypatch, capsys, command)

    assert reason is not None
    assert pattern_hash in reason
    assert len(launched) == 1
    capture_args = launched[0][0]
    assert "--capture" in capture_args
    capture_at = capture_args.index("--capture")
    assert pattern_hash in capture_args[capture_at + 1]
    assert json.loads(capture_args[capture_at + 2]) == [
        "rg", "-n", pattern, "features/hook_wiring.py"]


def test_rtk_rg_standalone_capture_uses_an_argv_payload(env, monkeypatch, capsys):
    pattern = "rtkNeedle"
    pattern_hash = hashlib.sha256(pattern.encode("utf-8")).hexdigest()
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs))
                        or SimpleNamespace(pid=1239))

    reason = _bash(env, monkeypatch, capsys, "rtk rg -n rtkNeedle src/file.py")

    assert reason is not None and pattern_hash in reason
    assert len(launched) == 1
    capture_args = launched[0][0][0]
    capture_at = capture_args.index("--capture")
    assert json.loads(capture_args[capture_at + 2]) == [
        "rg", "-n", pattern, "src/file.py"]


def test_hook_launched_capture_can_be_retrieved_from_same_working_directory(
        env, monkeypatch, capsys, load_script):
    pattern = "captureNeedle_73"
    source = env.tmp / "capture-source.txt"
    source.write_text(chr(10).join(("before", pattern + " result", "after")) + chr(10),
                      encoding="utf-8")
    monkeypatch.chdir(env.tmp)
    command = f"grep -n {pattern} {shlex.quote(str(source))}"

    reason = _bash(env, monkeypatch, capsys, command)
    pattern_hash = hashlib.sha256(pattern.encode("utf-8")).hexdigest()
    assert reason is not None and pattern_hash in reason

    retrieval = load_script(
        "features/common/skills/get-raw-grep-result/scripts/get_raw_grep_result.py")
    deadline = time.monotonic() + 3
    result = retrieval.get_result(pattern_hash=pattern_hash)
    while result["status"] == "pending" and time.monotonic() < deadline:
        time.sleep(0.02)
        result = retrieval.get_result(pattern_hash=pattern_hash)

    assert result["status"] == "ready"
    assert "captureNeedle_73 result" in result["stdout"]


def test_identical_retry_without_marker_passes_after_search(env, monkeypatch, capsys):
    """A completed memory search is sufficient; the marker no longer gates retry."""
    _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    reason = _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    assert reason is None
    assert len(env.calls) == 1


def test_already_searched_pattern_does_not_replay_grep(env, monkeypatch, capsys):
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs)))
    _memory_search(env, monkeypatch, "already-searched-pattern")

    assert _bash(env, monkeypatch, capsys,
                 "grep already-searched-pattern src/file.py") is None
    assert launched == []


def test_same_pattern_in_compound_search_launches_capture_once(env, monkeypatch, capsys):
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs))
                        or SimpleNamespace(pid=1236))

    _bash(env, monkeypatch, capsys,
          "grep -n shared src/a.py; rg -n shared src/b.py")

    assert launched == []


def test_piped_rg_capture_does_not_replay_an_arbitrary_upstream(
        env, monkeypatch, capsys):
    """A capture must not repeat a potentially stateful or networked producer."""
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs))
                        or SimpleNamespace(pid=1237))
    command = "curl -X POST https://example.invalid/submit | rg responseNeedle"

    reason = _bash(env, monkeypatch, capsys, command)

    assert reason is not None
    assert launched == []


@pytest.mark.parametrize("operand", ["*.txt", "$SEARCH_ROOT/result.txt"])
def test_dynamic_file_operands_are_not_captured_with_changed_shell_semantics(
        env, monkeypatch, capsys, operand):
    """A reconstructed command must not quote away glob or variable expansion."""
    if "*" in operand:
        (env.tmp / "matched.txt").write_text("dynamicNeedle\n", encoding="utf-8")
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs))
                        or SimpleNamespace(pid=1238))
    command = f"rg dynamicNeedle {operand}"

    reason = _bash(env, monkeypatch, capsys, command)

    assert reason is not None
    assert launched == []


def test_glob_pattern_that_would_expand_is_not_captured(env, monkeypatch, capsys):
    (env.tmp / "matched.txt").write_text("content\n", encoding="utf-8")
    source_dir = env.tmp / "src"
    source_dir.mkdir()
    (source_dir / "file.py").write_text("content\n", encoding="utf-8")
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs))
                        or SimpleNamespace(pid=1240))

    reason = _bash(env, monkeypatch, capsys, "rg *.txt src/file.py")

    assert reason is not None
    assert launched == []


@pytest.mark.parametrize("pattern", ["foo{bar,baz}", "$?"])
def test_shell_expansion_patterns_are_not_captured(env, monkeypatch, capsys, pattern):
    source_dir = env.tmp / "src"
    source_dir.mkdir()
    (source_dir / "file.py").write_text("content\n", encoding="utf-8")
    launched = []
    monkeypatch.setattr(env.gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append((args, kwargs))
                        or SimpleNamespace(pid=1241))

    reason = _bash(env, monkeypatch, capsys, f"rg -e {pattern} src/file.py")

    assert reason is not None
    assert launched == []


def test_capture_worker_executes_argv_without_a_shell(
        env, monkeypatch, load_script):
    retrieval = load_script(
        "features/common/skills/get-raw-grep-result/scripts/get_raw_grep_result.py")
    pattern = "argvWorkerNeedle"
    scope = hashlib.sha256(os.path.realpath(env.tmp).encode("utf-8")).hexdigest()
    capture_key = f"{scope}:{hashlib.sha256(pattern.encode('utf-8')).hexdigest()}"
    argv = ["rg", "-n", pattern, "src/file with spaces.py"]
    launched = []

    def fake_popen(args, **kwargs):
        launched.append((args, kwargs))
        raise OSError("prevent worker process in test")

    monkeypatch.setattr(retrieval.subprocess, "Popen", fake_popen)
    retrieval.main(["--capture", capture_key, json.dumps(argv)])

    assert launched
    args, kwargs = launched[0]
    assert args == argv
    assert kwargs.get("shell", False) is False
    assert "executable" not in kwargs


def test_never_searched_pattern_is_denied(env, monkeypatch, capsys):
    reason = _bash(env, monkeypatch, capsys, "grep -n zebra f.py")

    assert reason is not None
    assert env.calls and "zebra" in env.calls[0][0]


def test_same_pattern_with_other_flags_and_path_passes(env, monkeypatch, capsys):
    """Mutation: key on the command string instead of the pattern."""
    _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    assert _bash(env, monkeypatch, capsys, "grep -rn foo src/ other/") is None


def test_agent_memory_search_containing_the_pattern_counts(env, monkeypatch, capsys):
    """Mutation: the post hook records nothing but telemetry."""
    _memory_search(env, monkeypatch, "Where is merge_hooks defined?")

    assert _bash(env, monkeypatch, capsys, "grep -n merge_hooks f.py") is None
    assert not env.calls


def test_memory_search_on_another_topic_unlocks_nothing(env, monkeypatch, capsys):
    """Mutation: restore the session-wide unlock."""
    _memory_search(env, monkeypatch, "release ritual")

    assert _bash(env, monkeypatch, capsys, "grep -n foo f.py") is not None


def test_grep_tool_seen_pattern_passes_after_memory_search(env, monkeypatch, capsys):
    first = _tool(env, monkeypatch, capsys, "Grep", {"pattern": "fooBar"})
    assert first is not None

    assert _tool(env, monkeypatch, capsys, "Grep", {"pattern": "fooBar", "path": "src"}) is None
    assert _tool(env, monkeypatch, capsys, "Glob", {"pattern": "**/*.md"}) is not None


def test_a_new_pattern_in_the_same_shape_is_denied(env, monkeypatch, capsys):
    """Mutation: treat every pattern as seen once one was."""
    _bash(env, monkeypatch, capsys, "grep -n foo a.py")

    assert _bash(env, monkeypatch, capsys, "grep -n bar a.py") is not None


def test_compound_with_one_seen_and_one_unseen_pattern_is_denied(env, monkeypatch, capsys):
    """Mutation: `any` instead of `all`; the search query must carry only the unseen one."""
    _bash(env, monkeypatch, capsys, "grep foo a.py")

    reason = _bash(env, monkeypatch, capsys, "grep foo a.py; rg quux b")

    assert reason is not None
    assert "quux" in env.calls[-1][0] and "foo" not in env.calls[-1][0]


def test_alternation_is_split_into_patterns(env, monkeypatch, capsys):
    """Mutation: drop the `\\|` / bare `|` split."""
    _bash(env, monkeypatch, capsys, "grep 'alpha1\\|beta2' f")
    assert _bash(env, monkeypatch, capsys, "rg beta2") is None

    _bash(env, monkeypatch, capsys, "rg 'gamma3|delta4' src")
    assert _bash(env, monkeypatch, capsys, "grep -E delta4 f") is None


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
    # alternation: `\|` always, bare `|` only under rg / -E / egrep (BRE `|` is a literal)
    assert gate.search_patterns("Bash", {"command": USER_EXAMPLE}) == [
        "def merge_hooks", "def _prune", "append", "extend"]
    assert gate.search_patterns("Bash", {"command": "rg 'c3|d4' src"}) == ["c3", "d4"]
    assert gate.search_patterns("Bash", {"command": "grep -E 'c3|d4' f"}) == ["c3", "d4"]
    assert gate.search_patterns("Bash", {"command": "grep 'c3|d4' f"}) == ["c3|d4"]


def test_regex_escapes_are_normalized(env, monkeypatch, capsys):
    _memory_search(env, monkeypatch, "foo.bar and def merge")

    assert _bash(env, monkeypatch, capsys, "grep 'foo\\.bar' f") is None
    assert _bash(env, monkeypatch, capsys, "grep '^def merge\\b' f") is None


def test_sed_and_cat_are_never_touched(env, monkeypatch, capsys):
    assert _bash(env, monkeypatch, capsys, "sed -n 1,2p f; cat g | head") is None
    assert not env.calls


# ------------------------------------------------------------------ search unavailable
def test_no_executable_names_memory_search_then_post_hook_then_passes(
        env, monkeypatch, capsys):
    """Owner rule: a search that could not run records nothing; the agent's own does."""
    env.state.reply = None

    reason = _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py")
    payload = json.loads(reason)
    assert payload["searchResult"]["mem_search_result_output"] is None
    assert payload["rawGrepInput"][0]["pattern"] == "widgetFactory"
    assert "memory-checked" not in reason
    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py") is not None

    _memory_search(env, monkeypatch, "widgetFactory")

    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py") is None


def test_search_raising_still_denies_and_exits_zero(env, monkeypatch, capsys):
    env.state.reply = RuntimeError("boom")

    reason = _bash(env, monkeypatch, capsys, "grep -n foo f")

    assert json.loads(reason)["searchResult"]["mem_search_result_output"] is None
    assert env.gate.unsearched(PROJECT, ["foo"]) == ["foo"]


def test_fourth_new_pattern_denial_still_denies(env, monkeypatch, capsys):
    """Mutation: restore the 3-strike pass-through."""
    env.state.reply = None
    for _ in range(4):
        assert _bash(env, monkeypatch, capsys, "grep -n foo f") is not None


# ------------------------------------------------------------------ persistence
def test_searched_patterns_live_in_the_hook_state_row(env, monkeypatch, capsys):
    _bash(env, monkeypatch, capsys, "grep -n foo f")

    store = badger_store.open_audit()
    try:
        row = store.kv_get("hook_state", "memory_first.searched." + PROJECT)
    finally:
        store.close()
    assert "p:foo" in row


def test_store_missing_falls_back_to_the_file(env, monkeypatch, capsys):
    def _broken(*_a, **_k):
        raise OSError("store unavailable")

    monkeypatch.setattr(badger_store, "open_audit", _broken)
    _bash(env, monkeypatch, capsys, "grep -n foo f")

    assert _bash(env, monkeypatch, capsys, "grep -n foo f") is None
    lines = (env.tmp / "memory-first-searched" / PROJECT).read_text().splitlines()
    assert "p:foo" in lines


def test_seen_pattern_survives_a_new_session(env, monkeypatch, capsys):
    _bash(env, monkeypatch, capsys, "grep -n foo f", session="old")

    assert _bash(env, monkeypatch, capsys, "grep -n foo f", session="new") is None


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
                        "toolArgs": json.dumps({"projectId": PROJECT, "query": "gizmo"})})
    assert env.post.main([]) == 0

    _feed(monkeypatch, {"hookEventName": "preToolUse", "sessionId": "c1",
                        "cwd": str(env.tmp), "toolName": "bash",
                        "toolArgs": json.dumps({"command": "grep -n gizmo f"})})
    assert env.pre.main([]) == 0
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ excluded upstream programs
def test_grep_over_git_log_passes_without_search(env, monkeypatch, capsys):
    """Owner rule: memory cannot answer a filter over live command output.
    Mutation: return [] instead of skipping the segment -> memory search is demanded -> red."""
    assert _bash(env, monkeypatch, capsys, "git log | grep fix") is None
    assert not env.calls
    assert env.gate.unsearched(PROJECT, ["fix"]) == ["fix"]


@pytest.mark.parametrize("command", [
    "git log | grep fix",
    "git log |& grep fix",
    "rtk git log | grep fix",
    "sudo docker ps | grep fix",
    "env | grep PATH",
    "printenv | egrep 'A|B'",
    "ps aux | rg python",
    "git log | grep -e fix",
    "git log | grep -i -A 2 fix",
    "kubectl get pods | fgrep Running",
    "/usr/bin/git log | grep fix",
])
def test_piped_grep_over_an_excluded_program_is_not_text_search(env, command):
    """Mutation: drop the wrapper resolution (`rtk`/`sudo` read as the upstream) -> red."""
    assert env.gate.search_patterns("Bash", {"command": command}) is None


@pytest.mark.parametrize("command", [
    "cat f | grep x",                              # cat is not listed
    "git log --oneline | head -50 | grep fix",     # only the immediate upstream counts
    "git log | grep fix file.txt",                 # a file operand of its own
    "git log | grep -e fix file.txt",              # with -e every operand is a file
    "git log | grep fix -",                        # an explicit stdin operand is an operand
    "git log | grep -r fix",                       # recursion searches the tree
    "git log | grep -R fix",
    "git log | grep -rn fix",
    "git log | grep --recursive fix",
    "git log | grep -d recurse fix",
    "git log | grep --directories=recurse fix",
    "ls | rg --files",
    "ls | rg fix src",                             # rg with a path
    "ls | find . -name x",                         # find never reads stdin
    "git ls-files | xargs grep foo",               # xargs turns stdin into file operands
    "ls | xargs rg foo",
    "git log | grep foo < f",                      # stdin redirected away from the pipe
    "git log | grep foo <<< text",
    "git log | bash -c 'grep x'",                  # nested script: its stdin is not proven
    "git log || grep fix",
    "git log; grep fix",
])
def test_piped_grep_that_is_still_repo_search_stays_gated(env, command):
    """Mutations, one per row family: drop the upstream check; read the whole pipeline back;
    ignore operands; ignore -r/-R/--recursive/-d recurse; ignore rg --files; exempt under
    xargs; ignore an input redirect."""
    assert env.gate.search_patterns("Bash", {"command": command})


def test_excluded_segment_does_not_exempt_a_file_grep_beside_it(env, monkeypatch, capsys):
    reason = _bash(env, monkeypatch, capsys, "git log | grep fix && grep -rn fix src/")

    assert reason is not None
    assert env.calls and "fix" in env.calls[0][0]
    assert env.gate.search_patterns(
        "Bash", {"command": "git log | grep alpha && grep -rn beta src/"}) == ["beta"]


def test_excluded_upstream_is_a_module_constant(env):
    assert env.gate.EXCLUDED_UPSTREAM == (
        "git", "gh", "ps", "ls", "env", "printenv", "history", "docker", "kubectl", "pip",
        "npm", "lsof", "brew", "dotnet")


# ------------------------------------------------------------------ what counts as searched
def test_a_query_unlocks_whole_word_runs_not_substrings(env):
    """Mutation: restore `key in entry` -> `def`, `con`, `oade` count as searched -> red."""
    env.gate.record_query(PROJECT, "how does the default config loader handle a missing file")

    assert env.gate.unsearched(PROJECT, ["def", "con", "oade", "config loader", "missing file",
                                         "loader handle a"]) == ["def", "con", "oade"]


def test_a_recorded_pattern_unlocks_only_itself(env):
    """Mutation: let a recorded pattern match by containment like a query -> red."""
    env.gate.remember(PROJECT, ["def merge_hooks"])

    assert env.gate.unsearched(PROJECT, ["merge", "merge_hooks", "def merge_hooks"]) == [
        "merge", "merge_hooks"]


def test_stored_entries_carry_their_kind(env):
    env.gate.remember(PROJECT, ["Foo"])
    env.gate.record_query(PROJECT, "Bar baz")

    assert env.gate.searched(PROJECT) == {"p:foo", "q:bar baz"}


# ------------------------------------------------------------------ fail open
@pytest.mark.parametrize("host", ["claude", "copilot", "hermes"])
def test_an_unknown_project_fails_open_on_every_host(env, monkeypatch, host):
    """Mutation: deny when the project id cannot be persisted -> red."""
    monkeypatch.setattr(env.gate, "project_id", lambda _cwd="": "unknown")

    assert env.gate.decide(host, "Bash", {"command": "grep -n foo f"}, "s1") == {}
    assert not env.calls


def test_a_search_that_cannot_be_recorded_fails_open(env, monkeypatch):
    """Mutation: ignore remember()'s False and deny -> red (the pattern could never pass)."""
    monkeypatch.setattr(env.gate, "remember", lambda *_a, **_k: False)

    assert env.gate.decide("claude", "Bash", {"command": "grep -n foo f"}, "s1") == {}
    assert len(env.calls) == 1


def test_the_searched_store_opens_with_a_short_timeout(env, monkeypatch):
    """Mutation: open the store with its 5 s default -> red; a locked store could eat the
    hook's 10 s budget twice over (read, then write)."""
    seen = []
    real = badger_store.open_audit

    def spy(*args, **kwargs):
        seen.append(kwargs.get("timeout"))
        return real(*args, **kwargs)

    monkeypatch.setattr(badger_store, "open_audit", spy)
    env.gate.remember(PROJECT, ["foo"])
    env.gate.searched(PROJECT)

    assert len(seen) == 2
    assert all(t is not None and 0 < t <= 1.0 for t in seen)
    assert env.gate.STORE_TIMEOUT_SECONDS <= 1.0
    assert "p:foo" in env.gate.searched(PROJECT)


def test_open_audit_honours_the_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv(badger_store.DEBUG_DIR_ENV, str(tmp_path / "debug"))
    store = badger_store.open_audit(timeout=0.5)
    try:
        assert store.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 500
    finally:
        store.close()


# ------------------------------------------------------------------ the capped query
def test_only_patterns_inside_the_capped_query_are_recorded(env):
    """Mutation: remember every unseen pattern -> the ones past the 500-char cap count as
    searched though memory never saw them -> red."""
    patterns = [f"pattern{n:03d}x" for n in range(60)]  # 12 chars + a space each: ~780 chars
    command = "grep " + " ".join(f"-e {p}" for p in patterns) + " f"

    assert env.gate.decide("claude", "Bash", {"command": command}, "s1")

    query = env.calls[0][0]
    assert len(query) <= env.gate.QUERY_MAX_CHARS
    left = env.gate.unsearched(PROJECT, patterns)
    assert left and all(p not in query.split() for p in left)
    assert [p for p in patterns if p not in left] == query.split()


def test_grouping_parens_are_not_part_of_a_key(env):
    """Mutation: keep `(`/`)` in normalize -> keys `(foo` and `bar)baz` -> red."""
    found = env.gate.search_patterns("Bash", {"command": "grep -E '(foo|bar)baz' f"})

    assert [env.gate.normalize(p) for p in found] == ["foo", "barbaz"]


def test_a_single_overlong_pattern_is_recorded_after_its_truncated_search(env):
    """Mutation: return [] when no pattern fits the cap -> a >500-char pattern is never
    recorded and every retry re-searches and denies -> red."""
    long_pattern = "a" * 600
    query, queried = env.gate.search_query([long_pattern])

    assert len(query) == env.gate.QUERY_MAX_CHARS
    assert queried == [long_pattern]


@pytest.mark.parametrize("command", [
    "git ls-files | grep gate",
    "git -C sub ls-files | grep gate",
    "git grep foo | grep bar",
    "git ls-tree -r HEAD | grep gate",
    "ls -R | grep gate",
    "ls -laR src | grep gate",
    "ls --recursive | grep gate",
])
def test_a_file_listing_upstream_is_not_exempt(env, command):
    """Mutation: drop the file-listing check -> any git/ls upstream exempts -> red."""
    assert env.gate.search_patterns("Bash", {"command": command})


@pytest.mark.parametrize("command", ["git log | grep fix", "git -C sub status | grep x",
                                     "ls -la | grep x"])
def test_live_output_upstreams_stay_exempt(env, command):
    """Mutation: treat every git/ls upstream as file listing -> red."""
    assert env.gate.search_patterns("Bash", {"command": command}) is None


# ------------------------------------------------------------------ crediting a memory_search
def _post(env, monkeypatch, payload):
    _feed(monkeypatch, payload)
    assert env.post.main([]) == 0


def test_a_memory_search_for_another_project_credits_nothing(env, monkeypatch, capsys):
    """Mutation: ignore the call's projectId -> project B's search unlocks A's grep -> red."""
    env.state.reply = None
    _post(env, monkeypatch, {"hook_event_name": "PostToolUse", "cwd": str(env.tmp),
                             "tool_name": "mcp__ai-raccoon__memory_search",
                             "tool_input": {"projectId": "other-project", "query": "widgetFactory"}})

    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py") is not None


def test_a_memory_search_without_a_project_id_credits_nothing(env, monkeypatch, capsys):
    """Mutation: treat a missing projectId as a match -> red."""
    env.state.reply = None
    _post(env, monkeypatch, {"hook_event_name": "PostToolUse", "cwd": str(env.tmp),
                             "tool_name": "mcp__ai-raccoon__memory_search",
                             "tool_input": {"query": "widgetFactory"}})

    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py") is not None


@pytest.mark.parametrize("payload", [
    {"hookEventName": "postToolUse", "toolName": "memory_search",
     "toolArgs": json.dumps({"projectId": PROJECT, "query": "widgetFactory"}),
     "toolResult": {"resultType": "failure", "textResultForLlm": "boom"}},
    {"hook_event_name": "PostToolUseFailure", "tool_name": "mcp__ai-raccoon__memory_search",
     "tool_input": {"projectId": PROJECT, "query": "widgetFactory"}, "error": "boom"},
])
def test_a_failed_memory_search_credits_nothing(env, monkeypatch, capsys, payload):
    """Mutation: record the query whatever the result -> a failed search unlocks grep -> red."""
    env.state.reply = None
    _post(env, monkeypatch, dict(payload, cwd=str(env.tmp)))

    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py") is not None


def test_a_successful_copilot_memory_search_credits_its_query(env, monkeypatch, capsys):
    """Guards the failure check against rejecting every Copilot result."""
    env.state.reply = None
    _post(env, monkeypatch, {"hookEventName": "postToolUse", "cwd": str(env.tmp),
                             "toolName": "memory_search",
                             "toolArgs": json.dumps({"projectId": PROJECT, "query": "widgetFactory"}),
                             "toolResult": {"resultType": "success"}})

    assert _bash(env, monkeypatch, capsys, "grep -n widgetFactory f.py") is None


@pytest.mark.parametrize("command", ["grep -f patterns.txt target.py",
                                     "rg -f patterns.txt target.py",
                                     "grep --file=patterns.txt target.py"])
def test_a_pattern_file_search_is_keyed_on_its_words_not_its_target(env, command):
    """Mutation: take the first operand as the pattern under -f -> keyed on target.py -> red."""
    found = env.gate.search_patterns("Bash", {"command": command})

    assert found == [command]
