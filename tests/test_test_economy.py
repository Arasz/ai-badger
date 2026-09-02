"""TDD gates for test_economy.py — the pure logic of the test-run economy hook.

Covers test-runner detection and full-vs-filtered classification from a shell command,
the per-session counting rule (nudge on the run after the allowed budget, escalate past
the escalation bar, silence in between), the message text (imperative, names the local
gate wiring, carries the diagnosis carve-out), and local-gate detection.
"""
from __future__ import annotations

import pytest


def _logic(load_script):
    return load_script("features/common/skills/test-economy/scripts/suite_economy.py")


# --- runner detection ---------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "pytest",
    "pytest -q",
    "python -m pytest",
    "python3 -m pytest -x -q",
    "dotnet test",
    "npm test",
    "npm run test",
    "yarn test",
    "pnpm test",
    "bun test",
    "go test ./...",
    "cargo test",
    "mvn test",
    "./gradlew test",
    "mix test",
    "rake test",
    "swift test",
    "npx jest",
    "npx vitest run",
])
def test_bare_runner_commands_are_full_suite_runs(load_script, command):
    logic = _logic(load_script)
    run = logic.is_test_run(command)
    assert run is not None, command
    assert run["kind"] == "full", command


@pytest.mark.parametrize("command", [
    "pytest tests/test_hook.py",
    "pytest -k economy",
    "pytest -m 'not slow' tests/",
    "python -m pytest tests/test_economy_hook.py -q",
    "dotnet test --filter Category=Unit",
    "npm test -- tests/economy.test.ts",
    "npx jest economy",
    "npx vitest run src/economy",
    "go test ./features/economy/...",
    "go test -run TestEconomy ./...",
    "cargo test economy::",
    "cargo test --test economy_integration",
    "mvn test -Dtest=EconomyTest",
    "./gradlew test --tests '*Economy*'",
    "mix test test/economy_test.exs",
])
def test_selector_commands_are_filtered_runs(load_script, command):
    logic = _logic(load_script)
    run = logic.is_test_run(command)
    assert run is not None, command
    assert run["kind"] == "filtered", command


@pytest.mark.parametrize("command", [
    "git status --porcelain",
    "ls -la",
    "git commit -m 'test: something'",
    "python tooling/validate.py --all",
    "grep -rn pytest tests/",
    "echo pytest",
    "",
])
def test_non_test_commands_are_not_runs(load_script, command):
    logic = _logic(load_script)
    assert logic.is_test_run(command) is None, command


def test_detected_run_names_the_runner(load_script):
    logic = _logic(load_script)
    assert logic.is_test_run("pytest -q")["runner"] == "pytest"
    assert logic.is_test_run("dotnet test")["runner"] == "dotnet test"
    assert logic.is_test_run("npm test")["runner"] == "npm test"


# --- the counting rule --------------------------------------------------------------


def test_full_runs_below_the_budget_stay_silent(load_script):
    logic = _logic(load_script)
    entry = logic.new_session_entry()
    fires1, escalated, entry = logic.advance(entry, True, now="t1")
    assert not fires1 and not escalated
    fires2, escalated, entry = logic.advance(entry, True, now="t2")
    assert not fires2 and not escalated
    assert entry["full"] == 2


def test_the_run_after_the_budget_fires_the_nudge(load_script):
    logic = _logic(load_script)
    entry = logic.new_session_entry()
    _, _, entry = logic.advance(entry, True, now="t1")
    _, _, entry = logic.advance(entry, True, now="t2")
    fires3, escalated, entry = logic.advance(entry, True, now="t3")
    assert fires3
    assert not escalated
    assert entry["full"] == 3
    assert entry["fired"] == 1
    assert entry["since"] == "t3"


def test_the_escalation_bar_fires_the_stop_message(load_script):
    logic = _logic(load_script)
    entry = logic.new_session_entry()
    for i in range(5):
        fires, escalated, entry = logic.advance(entry, True, now=f"t{i}")
    assert fires and escalated

def test_filtered_runs_never_count_against_the_budget(load_script):
    logic = _logic(load_script)
    entry = logic.new_session_entry()
    for i in range(10):
        fires, escalated, entry = logic.advance(entry, False, now=f"t{i}")
    assert not fires and not escalated
    assert entry["filtered"] == 10
    assert entry["full"] == 0


def test_thresholds_are_env_overridable(load_script, monkeypatch):
    logic = _logic(load_script)
    monkeypatch.setenv("AI_BADGER_TEST_ECONOMY_MAX_FULL", "1")
    monkeypatch.setenv("AI_BADGER_TEST_ECONOMY_ESCALATE_AT", "3")
    entry = logic.new_session_entry()
    _, _, entry = logic.advance(entry, True, now="t1")
    fires2, _, _ = logic.advance(entry, True, now="t2")
    assert fires2


def test_bad_env_values_fall_back_to_defaults(load_script, monkeypatch):
    logic = _logic(load_script)
    monkeypatch.setenv("AI_BADGER_TEST_ECONOMY_MAX_FULL", "many")
    monkeypatch.setenv("AI_BADGER_TEST_ECONOMY_ESCALATE_AT", "")
    entry = logic.new_session_entry()
    _, _, entry = logic.advance(entry, True, now="t1")
    _, _, entry = logic.advance(entry, True, now="t2")
    fires3, _, _ = logic.advance(entry, True, now="t3")
    assert fires3


# --- the message --------------------------------------------------------------------


def test_message_is_a_command_not_a_suggestion(load_script):
    logic = _logic(load_script)
    message = logic.build_message(3, "pytest", ["lefthook"], escalated=False)
    assert message.startswith("[ai-badger]")
    assert "3" in message and "pytest" in message
    assert "CI" in message
    assert "diagnos" in message, "the flake-diagnosis carve-out must be in the message"
    assert "lefthook" in message


def test_message_without_local_gates_names_the_manual_fallback(load_script):
    logic = _logic(load_script)
    message = logic.build_message(3, "npm test", [], escalated=False)
    assert "manual" in message or "No local gate" in message


def test_escalated_message_tells_the_agent_to_stop(load_script):
    logic = _logic(load_script)
    plain = logic.build_message(3, "pytest", [], escalated=False)
    escalated = logic.build_message(6, "pytest", [], escalated=True)
    assert escalated != plain
    assert "STOP" in escalated


# --- local gate wiring --------------------------------------------------------------


def test_detects_lefthook_and_pre_commit(tmp_path, load_script):
    logic = _logic(load_script)
    (tmp_path / "lefthook.yml").write_text("pre-push:\n")
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
    assert set(logic.detect_local_gates(str(tmp_path))) >= {"lefthook", "pre-commit"}


def test_detects_husky_and_git_pre_push_hook(tmp_path, load_script):
    logic = _logic(load_script)
    (tmp_path / ".husky").mkdir()
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    pre_push = hooks / "pre-push"
    pre_push.write_text("#!/bin/sh\n")
    pre_push.chmod(0o755)
    found = set(logic.detect_local_gates(str(tmp_path)))
    assert "husky" in found
    assert any("pre-push" in gate for gate in found)


def test_sample_git_hooks_are_not_gate_wiring(tmp_path, load_script):
    logic = _logic(load_script)
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    sample = hooks / "pre-push.sample"
    sample.write_text("#!/bin/sh\n")
    sample.chmod(0o755)
    assert logic.detect_local_gates(str(tmp_path)) == []


def test_no_gate_wiring_in_an_empty_project(tmp_path, load_script):
    logic = _logic(load_script)
    assert logic.detect_local_gates(str(tmp_path)) == []


def test_gate_detection_never_raises_on_a_missing_root(load_script):
    logic = _logic(load_script)
    assert logic.detect_local_gates("/definitely/not/a/repo") == []
