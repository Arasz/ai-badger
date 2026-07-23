"""Tests for skills/task/scripts/tracker_lib.py.

tracker_lib.py resolves its data-directory constants (DATA_DIR, EXECUTED_TASKS, TOKEN_USAGE,
CURRENT_SESSION, LOCK_FILE, STATE_JSON, CONFIG_JSON, CLAUDE_MD, PROJECT_ROOT) relative to its own
file location at import time. Every test here loads a *fresh* module instance via `load_script`
and immediately overwrites those constants to point into `tmp_path`, so nothing ever touches the
real ai-badger repo checkout.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import timedelta


def _redirect(tl, tmp_path):
    """Point every tracker_lib path constant at a fake project root under tmp_path."""
    data_dir = tmp_path / ".ai-badger" / "task-tracking"
    tl.PROJECT_ROOT = tmp_path
    tl.DATA_DIR = data_dir
    tl.EXECUTED_TASKS = data_dir / "executed-tasks.json"
    tl.TOKEN_USAGE = data_dir / "token-usage.json"
    tl.CURRENT_SESSION = data_dir / "current-session.json"
    tl.LOCK_FILE = data_dir / ".write.lock"
    tl.STATE_JSON = tmp_path / ".ai-badger" / "state.json"
    tl.CONFIG_JSON = tmp_path / ".ai-badger" / "config.json"
    tl.CLAUDE_MD = tmp_path / "CLAUDE.md"
    return data_dir


def _load(load_script, tmp_path):
    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")
    _redirect(tl, tmp_path)
    return tl


def _write_transcript(path, records):
    """records: list of (is_sidechain, input, output, cache_read, cache_creation) tuples."""
    lines = []
    for is_side, inp, out, cr, cc in records:
        lines.append(json.dumps({
            "type": "assistant",
            "isSidechain": is_side,
            "message": {
                "usage": {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": cr,
                    "cache_creation_input_tokens": cc,
                }
            },
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# resolve_project_root / compute_paths
# ---------------------------------------------------------------------------

def test_resolve_project_root_uses_claude_project_dir_env_when_set_and_valid(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    env_project = tmp_path / "env-project"
    env_project.mkdir()

    resolved = tl.resolve_project_root(env={"CLAUDE_PROJECT_DIR": str(env_project)})

    assert resolved == env_project


def test_resolve_project_root_env_wins_over_cwd_walk(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    env_project = tmp_path / "env-project"
    env_project.mkdir()
    cwd_project = tmp_path / "cwd-project"
    (cwd_project / ".ai-badger").mkdir(parents=True)
    (cwd_project / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")

    resolved = tl.resolve_project_root(
        env={"CLAUDE_PROJECT_DIR": str(env_project)}, cwd=cwd_project,
    )

    assert resolved == env_project


def test_resolve_project_root_ignores_claude_project_dir_pointing_nowhere(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    cwd_project = tmp_path / "cwd-project"
    (cwd_project / ".ai-badger").mkdir(parents=True)
    (cwd_project / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")

    resolved = tl.resolve_project_root(
        env={"CLAUDE_PROJECT_DIR": str(tmp_path / "does-not-exist")}, cwd=cwd_project,
    )

    assert resolved == cwd_project


def test_resolve_project_root_walks_cwd_up_to_ai_badger_config_marker(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    project_root = tmp_path / "project"
    (project_root / ".ai-badger").mkdir(parents=True)
    (project_root / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    nested_cwd = project_root / "src" / "deep" / "nested"
    nested_cwd.mkdir(parents=True)

    resolved = tl.resolve_project_root(env={}, cwd=nested_cwd)

    assert resolved == project_root


def test_resolve_project_root_nearest_ancestor_wins_when_nested(load_script, tmp_path):
    """A nested project (e.g. a vendored copy) closer to cwd must win over an outer one."""
    tl = _load(load_script, tmp_path)
    outer_root = tmp_path / "outer"
    (outer_root / ".ai-badger").mkdir(parents=True)
    (outer_root / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    inner_root = outer_root / "vendor" / "nested-project"
    (inner_root / ".ai-badger").mkdir(parents=True)
    (inner_root / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    cwd = inner_root / "src"
    cwd.mkdir(parents=True)

    resolved = tl.resolve_project_root(env={}, cwd=cwd)

    assert resolved == inner_root


def test_resolve_project_root_falls_back_to_parents_index_when_no_marker_found(load_script, tmp_path):
    """Today's behavior, unchanged: no env var, no `.ai-badger/config.json` anywhere above cwd."""
    tl = _load(load_script, tmp_path)
    fake_repo_root = tmp_path / "fake-repo"
    script_dir = fake_repo_root / ".claude" / "skills" / "task" / "scripts"
    script_dir.mkdir(parents=True)
    isolated_cwd = tmp_path / "isolated-cwd"
    isolated_cwd.mkdir()

    resolved = tl.resolve_project_root(env={}, cwd=isolated_cwd, script_dir=script_dir)

    assert resolved == fake_repo_root


def test_resolve_project_root_regression_plugin_cache_does_not_misroot(load_script, tmp_path):
    """The actual bug: a script running from a plugin-cache-shaped depth, with no
    CLAUDE_PROJECT_DIR and a cwd inside a real project tree, must resolve to the project --
    never into the cache tree via the naive parents[3] fallback."""
    tl = _load(load_script, tmp_path)
    home = tmp_path / "home"
    cache_script_dir = (
        home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger"
        / "skills" / "task" / "scripts"
    )
    cache_script_dir.mkdir(parents=True)
    wrong_root = home / ".claude" / "plugins" / "cache" / "ai-badger"
    assert cache_script_dir.parents[3] == wrong_root  # sanity: this is the bug's mis-root

    real_project = tmp_path / "real-project"
    (real_project / ".ai-badger").mkdir(parents=True)
    (real_project / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    cwd = real_project / "src"
    cwd.mkdir()

    resolved = tl.resolve_project_root(env={}, cwd=cwd, script_dir=cache_script_dir)

    assert resolved == real_project
    assert resolved != wrong_root


def test_module_level_constants_fall_back_to_parents_index_by_default(load_script, tmp_path, monkeypatch):
    """A real (non-redirected) import with no CLAUDE_PROJECT_DIR and a cwd outside any
    `.ai-badger` project must match today's SCRIPT_DIR.parents[3] behavior exactly."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    isolated_cwd = tmp_path / "isolated"
    isolated_cwd.mkdir()
    monkeypatch.chdir(isolated_cwd)

    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    assert tl.PROJECT_ROOT == tl.SCRIPT_DIR.parents[3]
    assert tl.DATA_DIR == tl.PROJECT_ROOT / ".ai-badger" / "task-tracking"


def test_module_level_constants_pick_up_claude_project_dir_env_at_import(
    load_script, tmp_path, monkeypatch
):
    env_project = tmp_path / "env-project"
    env_project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(env_project))

    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    assert tl.PROJECT_ROOT == env_project
    assert tl.DATA_DIR == env_project / ".ai-badger" / "task-tracking"
    assert tl.CLAUDE_MD == env_project / "CLAUDE.md"


def test_compute_paths_derives_every_path_from_project_root(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    project_root = tmp_path / "some-project"

    paths = tl.compute_paths(project_root)

    data_dir = project_root / ".ai-badger" / "task-tracking"
    assert paths["project_root"] == project_root
    assert paths["data_dir"] == data_dir
    assert paths["executed_tasks"] == data_dir / "executed-tasks.json"
    assert paths["token_usage"] == data_dir / "token-usage.json"
    assert paths["current_session"] == data_dir / "current-session.json"
    assert paths["lock_file"] == data_dir / ".write.lock"
    assert paths["claude_md"] == project_root / "CLAUDE.md"
    assert paths["state_json"] == project_root / ".ai-badger" / "state.json"
    assert paths["config_json"] == project_root / ".ai-badger" / "config.json"


# ---------------------------------------------------------------------------
# now_iso / parse_iso
# ---------------------------------------------------------------------------

def test_now_iso_is_timezone_aware_utc_and_round_trips_through_parse_iso(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    stamp = tl.now_iso()
    parsed = tl.parse_iso(stamp)

    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_parse_iso_raises_on_garbage_input(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    try:
        tl.parse_iso("not-a-timestamp")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for malformed ISO timestamp")


# ---------------------------------------------------------------------------
# load_json / save_json
# ---------------------------------------------------------------------------

def test_save_json_then_load_json_round_trips(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    path = tl.DATA_DIR / "sample.json"

    tl.save_json(path, {"a": 1, "b": [1, 2, 3]})

    assert tl.load_json(path, "default") == {"a": 1, "b": [1, 2, 3]}


def test_load_json_returns_default_when_file_missing(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert tl.load_json(tl.DATA_DIR / "nope.json", {"x": 1}) == {"x": 1}


def test_load_json_returns_default_when_file_is_malformed(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.ensure_data_dir()
    bad = tl.DATA_DIR / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")

    assert tl.load_json(bad, {"fallback": True}) == {"fallback": True}


# ---------------------------------------------------------------------------
# ensure_data_dir
# ---------------------------------------------------------------------------

def test_ensure_data_dir_creates_missing_directory(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert not tl.DATA_DIR.exists()
    tl.ensure_data_dir()
    assert tl.DATA_DIR.is_dir()


# ---------------------------------------------------------------------------
# locked_store
# ---------------------------------------------------------------------------

def test_locked_store_round_trips_and_creates_lock_file(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    path = tl.DATA_DIR / "state.json"

    with tl.locked_store():
        doc = tl.load_json(path, {"n": 0})
        doc["n"] += 1
        tl.save_json(path, doc)

    assert tl.load_json(path, {"n": 0}) == {"n": 1}
    assert tl.LOCK_FILE.exists()


def test_locked_store_serializes_concurrent_read_modify_write(load_script, tmp_path):
    """Many threads racing a read-increment-write must not lose updates under the lock."""
    tl = _load(load_script, tmp_path)
    path = tl.DATA_DIR / "counter.json"
    tl.save_json(path, {"n": 0})

    def increment():
        with tl.locked_store():
            doc = tl.load_json(path, {"n": 0})
            current = doc["n"]
            doc["n"] = current + 1
            tl.save_json(path, doc)

    threads = [threading.Thread(target=increment) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tl.load_json(path, {"n": 0}) == {"n": 20}


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

def test_load_config_returns_empty_dict_when_missing(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert tl.load_config() == {}


def test_load_config_returns_empty_dict_when_unreadable(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    tl.CONFIG_JSON.write_text("{ this is not json", encoding="utf-8")

    assert tl.load_config() == {}


def test_load_config_returns_saved_profile(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    tl.CONFIG_JSON.write_text(json.dumps({"stacks": ["dotnet"]}), encoding="utf-8")

    assert tl.load_config() == {"stacks": ["dotnet"]}


# ---------------------------------------------------------------------------
# load_tasks / load_usage
# ---------------------------------------------------------------------------

def test_load_tasks_defaults_to_empty_task_list(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert tl.load_tasks() == {"tasks": []}


def test_load_usage_defaults_to_empty_task_list(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert tl.load_usage() == {"tasks": []}


# ---------------------------------------------------------------------------
# find_entry / find_other_entry_with_session
# ---------------------------------------------------------------------------

def test_find_entry_returns_matching_task(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    doc = {"tasks": [{"taskId": "T01"}, {"taskId": "T02"}]}

    assert tl.find_entry(doc, "T02") == {"taskId": "T02"}


def test_find_entry_returns_none_when_absent(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    doc = {"tasks": [{"taskId": "T01"}]}

    assert tl.find_entry(doc, "T99") is None


def test_find_other_entry_with_session_finds_cross_task_collision(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    doc = {"tasks": [
        {"taskId": "T01", "sessionId": "sid-1", "state": "STARTED"},
        {"taskId": "T02", "sessionId": "sid-2", "state": "STARTED"},
    ]}

    conflict = tl.find_other_entry_with_session(doc, "sid-1", "T02")

    assert conflict == {"taskId": "T01", "sessionId": "sid-1", "state": "STARTED"}


def test_find_other_entry_with_session_ignores_the_task_itself(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    doc = {"tasks": [{"taskId": "T01", "sessionId": "sid-1", "state": "STARTED"}]}

    assert tl.find_other_entry_with_session(doc, "sid-1", "T01") is None


def test_find_other_entry_with_session_returns_none_when_no_session_match(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    doc = {"tasks": [{"taskId": "T01", "sessionId": "sid-1", "state": "STARTED"}]}

    assert tl.find_other_entry_with_session(doc, "sid-does-not-exist", "T02") is None


# ---------------------------------------------------------------------------
# parse_transcript_usage / make_checkpoint
# ---------------------------------------------------------------------------

def test_parse_transcript_usage_missing_file_returns_zeroed_result(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    result = tl.parse_transcript_usage(str(tmp_path / "does-not-exist.jsonl"))

    assert result == {
        "contextTokens": 0,
        "assistantMessages": 0,
        "cumulative": {
            "inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheCreationTokens": 0,
        },
        "transcriptFound": False,
    }


def test_parse_transcript_usage_empty_path_returns_zeroed_result(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    result = tl.parse_transcript_usage("")

    assert result["transcriptFound"] is False
    assert result["contextTokens"] == 0


def test_parse_transcript_usage_empty_existing_file_is_found_but_zeroed(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text("", encoding="utf-8")

    result = tl.parse_transcript_usage(str(transcript))

    assert result["transcriptFound"] is True
    assert result["assistantMessages"] == 0
    assert result["contextTokens"] == 0


def test_parse_transcript_usage_aggregates_main_chain_and_sidechain_messages(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({
            "type": "assistant", "isSidechain": False,
            "message": {"usage": {
                "input_tokens": 100, "output_tokens": 20,
                "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5,
            }},
        }),
        json.dumps({
            "type": "assistant", "isSidechain": True,
            "message": {"usage": {
                "input_tokens": 50, "output_tokens": 5,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            }},
        }),
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        "not-json-at-all",
        "",
        json.dumps({"type": "assistant", "isSidechain": False, "message": {}}),
        json.dumps({
            "type": "assistant", "isSidechain": False,
            "message": {"usage": {
                "input_tokens": 200, "output_tokens": 40,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            }},
        }),
    ]
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = tl.parse_transcript_usage(str(transcript))

    assert result["transcriptFound"] is True
    assert result["assistantMessages"] == 3
    assert result["cumulative"] == {
        "inputTokens": 350, "outputTokens": 65, "cacheReadTokens": 10, "cacheCreationTokens": 5,
    }
    # Last non-sidechain assistant message wins for context occupancy: 200 + 0 + 0.
    assert result["contextTokens"] == 200


def test_make_checkpoint_wraps_parsed_usage_with_a_timestamp(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, [(False, 10, 2, 0, 0)])

    checkpoint = tl.make_checkpoint(str(transcript))

    assert checkpoint["contextTokens"] == 10
    assert checkpoint["assistantMessages"] == 1
    assert checkpoint["cumulative"]["inputTokens"] == 10
    tl.parse_iso(checkpoint["timestamp"])  # must not raise


# ---------------------------------------------------------------------------
# compute_usage
# ---------------------------------------------------------------------------

def test_compute_usage_computes_deltas_cache_efficiency_and_totals(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    start_cp = {
        "contextTokens": 100,
        "cumulative": {
            "inputTokens": 1000, "outputTokens": 200, "cacheReadTokens": 50, "cacheCreationTokens": 10,
        },
    }
    finish_cp = {
        "contextTokens": 150,
        "cumulative": {
            "inputTokens": 1500, "outputTokens": 300, "cacheReadTokens": 80, "cacheCreationTokens": 20,
        },
    }
    subagents = [{"totalTokens": 500}, {"totalTokens": 250}]

    usage = tl.compute_usage(start_cp, finish_cp, subagents)

    assert usage["inputTokens"] == 500
    assert usage["outputTokens"] == 100
    assert usage["cacheReadTokens"] == 30
    assert usage["cacheCreationTokens"] == 10
    assert usage["cacheEfficiency"] == 0.75
    assert usage["subagentTokens"] == 750
    assert usage["contextTokensAtStart"] == 100
    assert usage["contextTokensAtFinish"] == 150
    assert usage["contextGrowth"] == 50
    assert usage["mainSessionTotal"] == 640
    assert usage["grandTotal"] == 1390


def test_compute_usage_cache_efficiency_is_none_when_nothing_cacheable(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    start_cp = {"contextTokens": 0, "cumulative": {
        "inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheCreationTokens": 0,
    }}
    finish_cp = {"contextTokens": 0, "cumulative": {
        "inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 0, "cacheCreationTokens": 0,
    }}

    usage = tl.compute_usage(start_cp, finish_cp, [])

    assert usage["cacheEfficiency"] is None
    assert usage["subagentTokens"] == 0


def test_compute_usage_clamps_negative_deltas_to_zero(load_script, tmp_path):
    """A transcript that looks smaller at 'finish' than 'start' (e.g. compaction) must not
    produce a negative token count."""
    tl = _load(load_script, tmp_path)
    start_cp = {"contextTokens": 500, "cumulative": {
        "inputTokens": 1000, "outputTokens": 200, "cacheReadTokens": 50, "cacheCreationTokens": 10,
    }}
    finish_cp = {"contextTokens": 10, "cumulative": {
        "inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 0, "cacheCreationTokens": 0,
    }}

    usage = tl.compute_usage(start_cp, finish_cp, [])

    assert usage["inputTokens"] == 0
    assert usage["outputTokens"] == 0
    assert usage["cacheReadTokens"] == 0
    assert usage["cacheCreationTokens"] == 0
    assert usage["contextGrowth"] == -490


# ---------------------------------------------------------------------------
# claude_md_stats
# ---------------------------------------------------------------------------

def test_claude_md_stats_when_file_missing(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    stats = tl.claude_md_stats()

    assert stats["chars"] == 0
    assert stats["lines"] == 0
    assert stats["overBudget"] is False


def test_claude_md_stats_within_budget(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.CLAUDE_MD.write_text("line one\nline two\n", encoding="utf-8")

    stats = tl.claude_md_stats()

    assert stats["lines"] == 2
    assert stats["overBudget"] is False


def test_claude_md_stats_over_line_budget(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.CLAUDE_MD.write_text("x\n" * (tl.CLAUDE_MD_MAX_LINES + 5), encoding="utf-8")

    stats = tl.claude_md_stats()

    assert stats["overBudget"] is True


# ---------------------------------------------------------------------------
# state_json_updated_since
# ---------------------------------------------------------------------------

def test_state_json_updated_since_false_when_file_missing(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert tl.state_json_updated_since(tl.now_iso()) is False


def test_state_json_updated_since_true_when_mtime_after_started_at(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    tl.STATE_JSON.write_text("{}", encoding="utf-8")

    started_at = "2000-01-01T00:00:00+00:00"

    assert tl.state_json_updated_since(started_at) is True


def test_state_json_updated_since_false_when_mtime_before_started_at(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    tl.STATE_JSON.write_text("{}", encoding="utf-8")

    started_at = "2999-01-01T00:00:00+00:00"

    assert tl.state_json_updated_since(started_at) is False


# ---------------------------------------------------------------------------
# save_current_session / load_current_sessions
# ---------------------------------------------------------------------------

def test_save_current_session_records_transcript_cwd_and_pid(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    tl.save_current_session("sid-new", "/tmp/t.jsonl", cwd="/work/dir")

    sessions = tl.load_current_sessions()
    assert sessions["sid-new"]["transcriptPath"] == "/tmp/t.jsonl"
    assert sessions["sid-new"]["cwd"] == "/work/dir"
    assert sessions["sid-new"]["pid"] == os.getppid()


def test_save_current_session_prunes_entries_with_dead_pids(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.ensure_data_dir()
    tl.CURRENT_SESSION.write_text(json.dumps({
        "sessions": {
            "old-dead": {
                "transcriptPath": "/tmp/old.jsonl", "cwd": "/old", "pid": 999999999,
                "recordedAt": tl.now_iso(),
            }
        }
    }), encoding="utf-8")

    tl.save_current_session("sid-new", "/tmp/new.jsonl", cwd="/new")

    sessions = tl.load_current_sessions()
    assert "old-dead" not in sessions
    assert "sid-new" in sessions


def test_save_current_session_keeps_entries_with_alive_pids(load_script, tmp_path):
    tl = _load(load_script, tmp_path)
    tl.ensure_data_dir()
    tl.CURRENT_SESSION.write_text(json.dumps({
        "sessions": {
            "alive-sid": {
                "transcriptPath": "/tmp/alive.jsonl", "cwd": "/alive", "pid": os.getpid(),
                "recordedAt": tl.now_iso(),
            }
        }
    }), encoding="utf-8")

    tl.save_current_session("sid-new", "/tmp/new.jsonl", cwd="/new")

    sessions = tl.load_current_sessions()
    assert "alive-sid" in sessions
    assert "sid-new" in sessions


def test_load_current_sessions_defaults_to_empty_dict(load_script, tmp_path):
    tl = _load(load_script, tmp_path)

    assert tl.load_current_sessions() == {}


# ---------------------------------------------------------------------------
# resolve_own_session
# ---------------------------------------------------------------------------

def test_resolve_own_session_uses_env_var_when_session_is_known(load_script, tmp_path, monkeypatch):
    tl = _load(load_script, tmp_path)
    tl.save_current_session("sid-env", "/tmp/env.jsonl", cwd="/env")
    monkeypatch.setenv(tl.CLAUDE_SESSION_ENV, "sid-env")

    resolved = tl.resolve_own_session()

    assert resolved["sessionId"] == "sid-env"
    assert resolved["transcriptPath"] == "/tmp/env.jsonl"


def test_resolve_own_session_env_var_set_but_not_yet_recorded(load_script, tmp_path, monkeypatch):
    tl = _load(load_script, tmp_path)
    monkeypatch.setenv(tl.CLAUDE_SESSION_ENV, "sid-unrecorded")

    resolved = tl.resolve_own_session()

    assert resolved == {"sessionId": "sid-unrecorded", "transcriptPath": None}


def test_resolve_own_session_matches_via_pid_ancestry(load_script, tmp_path, monkeypatch):
    tl = _load(load_script, tmp_path)
    monkeypatch.delenv(tl.CLAUDE_SESSION_ENV, raising=False)
    tl.ensure_data_dir()
    tl.CURRENT_SESSION.write_text(json.dumps({
        "sessions": {"anc-sid": {"transcriptPath": "/tmp/a.jsonl", "cwd": "/a", "pid": 424242}}
    }), encoding="utf-8")
    tl._own_pid_ancestry = lambda max_depth=12: [1, 424242]

    resolved = tl.resolve_own_session()

    assert resolved["sessionId"] == "anc-sid"


def test_resolve_own_session_matches_via_unique_cwd(load_script, tmp_path, monkeypatch):
    tl = _load(load_script, tmp_path)
    monkeypatch.delenv(tl.CLAUDE_SESSION_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    tl._own_pid_ancestry = lambda max_depth=12: []
    tl.ensure_data_dir()
    tl.CURRENT_SESSION.write_text(json.dumps({
        "sessions": {"cwd-sid": {"transcriptPath": "/tmp/c.jsonl", "cwd": str(tmp_path)}}
    }), encoding="utf-8")

    resolved = tl.resolve_own_session()

    assert resolved["sessionId"] == "cwd-sid"


def test_resolve_own_session_ambiguous_cwd_returns_empty(load_script, tmp_path, monkeypatch):
    tl = _load(load_script, tmp_path)
    monkeypatch.delenv(tl.CLAUDE_SESSION_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    tl._own_pid_ancestry = lambda max_depth=12: []
    tl.ensure_data_dir()
    tl.CURRENT_SESSION.write_text(json.dumps({
        "sessions": {
            "sid-a": {"transcriptPath": "/tmp/a.jsonl", "cwd": str(tmp_path)},
            "sid-b": {"transcriptPath": "/tmp/b.jsonl", "cwd": str(tmp_path)},
        }
    }), encoding="utf-8")

    resolved = tl.resolve_own_session()

    assert resolved == {}


def test_resolve_own_session_returns_empty_when_nothing_matches(load_script, tmp_path, monkeypatch):
    tl = _load(load_script, tmp_path)
    monkeypatch.delenv(tl.CLAUDE_SESSION_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    tl._own_pid_ancestry = lambda max_depth=12: []

    resolved = tl.resolve_own_session()

    assert resolved == {}
