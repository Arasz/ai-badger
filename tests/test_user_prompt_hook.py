"""Tests for skills/prompt-markers/scripts/user_prompt_hook.py.

Covers marker detection (prefix at the very start of the prompt, case-insensitive),
additionalContext injection via main()'s stdin/stdout hook contract, silent behavior on
no-match / missing-or-invalid markers-context.json, and best-effort marker-usage
recording that is gated on an already-existing ".ai-badger" tracking directory.
"""
from __future__ import annotations

import io
import json

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
    path.write_text(json.dumps(data if data is not None else TEST_MARKERS_CONTEXT),
                     encoding="utf-8")


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
    config_path.write_text("{not valid json", encoding="utf-8")
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
    state_file = project / ".ai-badger" / "prompt-markers" / "marker-state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(state["history"]) == 1
    entry = state["history"][0]
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
