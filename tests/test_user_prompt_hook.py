# pylint: disable=redefined-outer-name  # module-local fixture reuse
"""Tests for skills/prompt-markers/scripts/user_prompt_hook.py.

Covers marker detection (prefix at the very start of the prompt, case-insensitive),
additionalContext injection via main()'s stdin/stdout hook contract, silent behavior on
no-match / missing-or-invalid markers-context.json, and best-effort marker-usage
recording that is gated on an already-existing ".ai-badger" tracking directory.
"""
from __future__ import annotations

import io
import json
import os

import pytest

from conftest import _test_write

TEST_MARKERS_CONTEXT = {
    "markers": [
        {
            "id": "hint",
            "prefixes": ["h:", "hint:"],
            "inject": "TEST INJECTED HINT CONTEXT",
        },
    ]
}


def _write_markers_context(path, data=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, json.dumps(data if data is not None else TEST_MARKERS_CONTEXT), encoding="utf-8")


def _marker_rows(project, hook, monkeypatch):
    """Read the marker_state rows the hook wrote, through the module the hook used."""
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT",
                       str(project / ".ai-badger" / "task-tracking"))
    store = hook.badger_store.open_tracking()
    try:
        return store.kv_all("marker_state")
    finally:
        store.close()


def _call_main(module, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def _run_main_never_raises(module, monkeypatch, payload):
    """Mirror the script's own top-level guard (the `if __name__ == "__main__":` block):
    a broken hook must never crash or block the prompt, so main()'s exceptions are
    swallowed and treated as exit 0. main() itself has no internal try/except, so this
    helper reproduces the guard that actually ships around it.
    """
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    try:
        return module.main()
    except Exception:  # pylint: disable=broad-exception-caught
        return 0


def test_recognized_marker_prefix_injects_expected_context(tmp_path, load_script, monkeypatch,
                                                             capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    rc = _call_main(hook, monkeypatch, {"prompt": "h: check this idea", "cwd": str(tmp_path)})

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "TEST INJECTED HINT CONTEXT",
        }
    }


def test_marker_match_is_case_insensitive(tmp_path, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    rc = _call_main(hook, monkeypatch, {"prompt": "HINT: Some Suggestion", "cwd": str(tmp_path)})

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "TEST INJECTED HINT CONTEXT"


def test_no_marker_present_is_silent(tmp_path, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    rc = _call_main(hook, monkeypatch, {"prompt": "just a normal prompt", "cwd": str(tmp_path)})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_marker_text_not_at_start_is_not_treated_as_marker(tmp_path, load_script, monkeypatch,
                                                             capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    rc = _call_main(hook, monkeypatch,
                     {"prompt": "well h: this is mid-sentence", "cwd": str(tmp_path)})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_missing_markers_context_file_is_silent_failure(tmp_path, load_script, monkeypatch,
                                                          capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", tmp_path / "does-not-exist.json")

    rc = _run_main_never_raises(hook, monkeypatch, {"prompt": "h: test", "cwd": str(tmp_path)})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_invalid_markers_context_json_is_silent_failure(tmp_path, load_script, monkeypatch,
                                                          capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _test_write(config_path, "{not valid json", encoding="utf-8")
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    rc = _run_main_never_raises(hook, monkeypatch, {"prompt": "h: test", "cwd": str(tmp_path)})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_marker_usage_recorded_when_tracking_dir_exists(tmp_path, load_script, monkeypatch,
                                                          capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)
    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)

    rc = _call_main(hook, monkeypatch, {"prompt": "h: check this", "cwd": str(project)})

    assert rc == 0
    rows = _marker_rows(project, hook, monkeypatch)
    history = rows["history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["markerId"] == "hint"
    assert entry["matchedPrefix"] == "h:"
    assert entry["originalPrompt"] == "h: check this"
    assert entry["injectedContext"] == "TEST INJECTED HINT CONTEXT"


def test_marker_usage_not_recorded_when_tracking_dir_absent(tmp_path, load_script, monkeypatch,
                                                              capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)
    project = tmp_path / "no-tracking-project"
    project.mkdir(parents=True)

    rc = _call_main(hook, monkeypatch, {"prompt": "h: check this", "cwd": str(project)})

    assert rc == 0
    assert not (project / ".ai-badger").exists()
    assert not list(tmp_path.rglob("marker-state.json"))
    assert not list(tmp_path.rglob("tracking.db"))


def test_internal_error_is_recorded_somewhere(tmp_path, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    errors = tmp_path / "hook-errors.log"
    monkeypatch.setattr(hook, "HOOK_ERRORS_FILE", errors)

    def explode():
        raise RuntimeError("broken marker table")

    monkeypatch.setattr(hook, "main", explode)

    rc = hook.guarded_main()

    assert rc == 0
    assert "user_prompt_hook" in errors.read_text(encoding="utf-8")
    assert "user_prompt_hook" in capsys.readouterr().err


def _markers():
    return [{"id": "hint", "prefixes": ["h:", "hint:"]},
            {"id": "feedback", "prefixes": ["f:", "feedback:"]}]


def test_windows_drive_letter_path_is_not_a_marker(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")

    match = hook.match_marker(r"H:\Projects\foo.py, can you check this?", _markers())

    assert match is None


def test_bare_prefix_needs_whitespace_after_it(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")

    assert hook.match_marker("h: check the cache layer", _markers())[0]["id"] == "hint"
    assert hook.match_marker("h:", _markers())[0]["id"] == "hint"
    assert hook.match_marker("h:no-space-here", _markers()) is None


def test_spelled_out_prefix_still_matches_without_whitespace(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")

    assert hook.match_marker("hint:check the cache", _markers())[0]["id"] == "hint"


def test_the_marker_state_store_is_owner_readable_only(tmp_path, load_script, monkeypatch):
    """The store carries whole prompts verbatim — the tracking DB is not world-readable
    (security I5; the legacy marker-state.json 0600 contract, byte → row)."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    tracking = tmp_path / ".ai-badger"
    tracking.mkdir()

    hook.record_transformation(str(tmp_path), "h: check the cache", "h:", "hint", "HINT: ...")

    db = tracking / "task-tracking" / "tracking.db"
    assert db.exists()
    assert db.stat().st_mode & 0o777 == 0o600


def test_debug_logging_records_fire_event(tmp_path, load_script, monkeypatch):
    """Debug log fires a fire event when a marker matches."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    calls = []

    class FakeDebugLog:
        def log_event(self, component, event, **fields):
            calls.append((component, event, fields))

        def resolve_project_root(self, payload=None):
            return (payload or {}).get("cwd")

    monkeypatch.setattr(hook, "debug_log", FakeDebugLog())
    _call_main(hook, monkeypatch, {"prompt": "h: check the cache", "cwd": str(tmp_path)})

    events = {e: (c, f) for c, e, f in calls}
    assert "fire" in events
    assert events["fire"][0] == "prompt_markers_hook"


def test_debug_logging_is_noop_when_unavailable(tmp_path, load_script, monkeypatch):
    """Hook runs normally when debug_log is None."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)
    monkeypatch.setattr(hook, "debug_log", None)

    rc = _call_main(hook, monkeypatch, {"prompt": "h: check the cache", "cwd": str(tmp_path)})
    assert rc == 0


def test_queue_and_important_markers_are_detected(load_script):
    """Canonical markers-context.json defines q:/queue: and i!:/important!: markers."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    markers = hook.load_markers_context().get("markers", [])

    q_match = hook.match_marker("q: run this after current work", markers)
    assert q_match is not None and q_match[0]["id"] == "queue"

    imp_match = hook.match_marker("i!: stop everything now", markers)
    assert imp_match is not None and imp_match[0]["id"] == "important"


def test_feedback_marker_inject_requires_evidence(load_script):
    """Rule 3 (grounded feedback): the feedback marker's injected text must require the agent
    to cite failing output, validator results, or source evidence — not just address the feedback
    vaguely.  The prompt-rules-ranking-framework-plan mandates this for every f: turn."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    markers = hook.load_markers_context().get("markers", [])
    feedback = next(m for m in markers if m["id"] == "feedback")
    inject = feedback["inject"].lower()
    assert any(word in inject for word in ("evidence", "failing", "validator", "error", "source")), (
        "feedback marker inject must require evidence-backed correction; "
        f"got: {feedback['inject']!r}"
    )


def test_feedback_marker_inject_requires_referencing_prior_work(load_script):
    """The feedback marker must instruct the agent to refer back to the specific prior output."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    markers = hook.load_markers_context().get("markers", [])
    feedback = next(m for m in markers if m["id"] == "feedback")
    inject = feedback["inject"].lower()
    assert any(word in inject for word in ("refer", "prior", "previous", "history", "session")), (
        "feedback marker inject must require referencing prior work; "
        f"got: {feedback['inject']!r}"
    )


# --- Consolidated restart detection (Rule 2B/2C) ---

def test_count_trailing_feedback_returns_zero_for_empty_state(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    assert hook.count_trailing_feedback({}) == 0
    assert hook.count_trailing_feedback({"history": []}) == 0


def test_count_trailing_feedback_reads_the_streak(load_script):
    """The restart counter is the persisted feedbackStreak, not history length."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    assert hook.count_trailing_feedback({"feedbackStreak": 3}) == 3


def test_advance_feedback_streak_increments_and_resets(tmp_path, load_script, monkeypatch):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)
    cwd = str(project)

    assert hook.advance_feedback_streak(cwd, is_feedback=True) == 1
    assert hook.advance_feedback_streak(cwd, is_feedback=True) == 2
    assert hook.advance_feedback_streak(cwd, is_feedback=True) == 3
    assert hook.advance_feedback_streak(cwd, is_feedback=False) == 0
    assert hook.advance_feedback_streak(cwd, is_feedback=True) == 1
    assert _marker_rows(project, hook, monkeypatch)["feedbackStreak"] == 1


def test_interleaved_normal_prompt_resets_the_streak(tmp_path, load_script,
                                                     monkeypatch, capsys):
    """f: → normal prompt → f: must NOT fire the restart advisory (Copilot review)."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, {"markers": [
        {"id": "hint", "prefixes": ["h:", "hint:"], "inject": "HINT"},
        {"id": "feedback", "prefixes": ["f:", "feedback:"], "inject": "FEEDBACK"},
    ]})
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)

    rc = _call_main(hook, monkeypatch, {"prompt": "f: first correction", "cwd": str(project)})
    assert rc == 0
    capsys.readouterr()  # discard the first turn's output

    rc = _call_main(hook, monkeypatch, {"prompt": "a normal prompt in between", "cwd": str(project)})
    assert rc == 0
    assert capsys.readouterr().out == ""  # silent — no marker

    rc = _call_main(hook, monkeypatch, {"prompt": "f: second correction", "cwd": str(project)})
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "CONSOLIDATED RESTART ADVISORY" not in ctx


def test_consolidated_restart_advisory_injected_after_two_feedback(tmp_path, load_script,
                                                                    monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, {"markers": [
        {"id": "hint", "prefixes": ["h:", "hint:"], "inject": "HINT"},
        {"id": "feedback", "prefixes": ["f:", "feedback:"], "inject": "FEEDBACK"},
    ]})
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)

    # Pre-populate marker-state.json with a prior feedback turn's streak
    state_dir = project / ".ai-badger" / "prompt-markers"
    state_dir.mkdir(parents=True)
    _test_write(state_dir / "marker-state.json", json.dumps({
        "history": [{"markerId": "feedback", "timestamp": "2026-01-01T00:00:00Z"}],
        "feedbackStreak": 1,
    }), encoding="utf-8")

    rc = _call_main(hook, monkeypatch, {"prompt": "f: this is still wrong", "cwd": str(project)})
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "CONSOLIDATED RESTART ADVISORY" in ctx
    assert "2 consecutive" in ctx

    # Lazy migration (D6): the seeded legacy document became rows + *.migrated.json on
    # the hook's first store write.
    state_dir = project / ".ai-badger" / "prompt-markers"
    assert not (state_dir / "marker-state.json").exists()
    assert (state_dir / "marker-state.migrated.json").exists()
    rows = _marker_rows(project, hook, monkeypatch)
    assert rows["feedbackStreak"] == 2
    assert len(rows["history"]) == 2


def test_no_restart_advisory_after_single_feedback(tmp_path, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, {"markers": [
        {"id": "hint", "prefixes": ["h:", "hint:"], "inject": "HINT"},
        {"id": "feedback", "prefixes": ["f:", "feedback:"], "inject": "FEEDBACK"},
    ]})
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)

    rc = _call_main(hook, monkeypatch, {"prompt": "f: first correction", "cwd": str(project)})
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "CONSOLIDATED RESTART ADVISORY" not in ctx


# ------------------------------------------------------------------ importance token (!)

def _bang_context():
    """A catalog shaped like the shipped one post-split: base prefixes, the important
    marker carrying both a base and an interrupt inject text."""
    return {
        "markers": [
            {"id": "hint", "prefixes": ["h:", "hint:"], "inject": "TEST HINT"},
            {"id": "feedback", "prefixes": ["f:", "feedback:"], "inject": "TEST FEEDBACK"},
            {"id": "extension", "prefixes": ["e:", "extension:"], "inject": "TEST EXTENSION"},
            {"id": "queue", "prefixes": ["q:", "queue:"], "inject": "TEST QUEUE"},
            {
                "id": "important",
                "prefixes": ["i:", "important:"],
                "inject": "TEST IMPORTANT BASE",
                "injectInterrupt": "TEST IMPORTANT EMERGENCY",
            },
        ]
    }


@pytest.mark.parametrize("prompt,marker_id", [
    ("f!: fix it now", "feedback"),
    ("feedback!: fix it now", "feedback"),
    ("hint!: validate first", "hint"),
    ("q!: do this immediately", "queue"),
])
def test_interrupt_variant_of_every_marker_fires(tmp_path, load_script, monkeypatch, capsys,
                                                 prompt, marker_id):
    """The importance token works on EVERY marker, spelled short or long."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, _bang_context())
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    rc = _call_main(hook, monkeypatch, {"prompt": prompt, "cwd": str(tmp_path)})

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    injected = out["hookSpecificOutput"]["additionalContext"]
    assert marker_id in injected.lower() or f"TEST {marker_id.upper()}" in injected
    assert hook.IMPORTANCE_SUFFIX in injected


def test_important_bang_forms_keep_the_emergency_text_exactly(tmp_path, load_script,
                                                               monkeypatch, capsys):
    """Legacy behavior: i!: / important!: inject the interrupt text, un-suffixed."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, _bang_context())
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    for prompt in ("i!: stop", "important!: stop"):
        _call_main(hook, monkeypatch, {"prompt": prompt, "cwd": str(tmp_path)})
        out = json.loads(capsys.readouterr().out)
        injected = out["hookSpecificOutput"]["additionalContext"]
        assert injected == "TEST IMPORTANT EMERGENCY"


def test_important_base_form_is_high_priority_without_preemption(tmp_path, load_script,
                                                                  monkeypatch, capsys):
    """The split: i: / important: carry the meaning without the interrupt demand."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, _bang_context())
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)

    for prompt in ("i: remember this", "important: remember this"):
        _call_main(hook, monkeypatch, {"prompt": prompt, "cwd": str(tmp_path)})
        out = json.loads(capsys.readouterr().out)
        injected = out["hookSpecificOutput"]["additionalContext"]
        assert injected == "TEST IMPORTANT BASE"


def test_bang_match_reports_itself_to_the_caller(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    markers = _bang_context()["markers"]

    marker, prefix, bang = hook.match_marker("f!: fix it now", markers)
    assert marker["id"] == "feedback"
    assert prefix == "f!:"
    assert bang is True

    marker, prefix, bang = hook.match_marker("f: fix it later", markers)
    assert prefix == "f:"
    assert bang is False


def test_bang_marker_mid_line_is_not_a_marker(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    assert hook.match_marker("please f!: look at this", _bang_context()["markers"]) is None


def test_bang_single_letter_alias_needs_whitespace_after_it(load_script):
    """F-21 extended to the !-variant: h!:x is not a marker; h!: x is."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    markers = _bang_context()["markers"]

    assert hook.match_marker("h!:x", markers) is None
    assert hook.match_marker("h!: check", markers) is not None


def test_bang_match_is_case_insensitive(load_script):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    marker, prefix, bang = hook.match_marker("F!: fix it now", _bang_context()["markers"])
    assert marker["id"] == "feedback"
    assert bang is True


def test_bang_recorded_in_audit(tmp_path, load_script, monkeypatch):
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path, _bang_context())
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)
    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)

    _call_main(hook, monkeypatch, {"prompt": "f!: fix it now", "cwd": str(project)})

    entry = _marker_rows(project, hook, monkeypatch)["history"][0]
    assert entry["matchedPrefix"] == "f!:"
    assert entry["bang"] is True


def test_audit_history_row_is_capped_at_max_history(tmp_path, load_script, monkeypatch, capsys):
    """The audit cap survives the store: the history row is the legacy document's capped
    "history" list — MAX_HISTORY entries, oldest dropped, newest kept (byte → row)."""
    hook = load_script("features/common/skills/prompt-markers/scripts/user_prompt_hook.py")
    config_path = tmp_path / "markers-context.json"
    _write_markers_context(config_path)
    monkeypatch.setattr(hook, "MARKERS_CONTEXT_FILE", config_path)
    project = tmp_path / "project"
    (project / ".ai-badger").mkdir(parents=True)

    total = hook.MAX_HISTORY + 5
    for i in range(total):
        rc = _call_main(hook, monkeypatch, {"prompt": f"h: prompt {i}", "cwd": str(project)})
        assert rc == 0
        capsys.readouterr()

    history = _marker_rows(project, hook, monkeypatch)["history"]
    assert len(history) == hook.MAX_HISTORY
    assert history[-1]["originalPrompt"] == f"h: prompt {total - 1}"
    assert history[0]["originalPrompt"] == f"h: prompt {total - hook.MAX_HISTORY}"
