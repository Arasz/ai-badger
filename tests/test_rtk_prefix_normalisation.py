"""A command behind `rtk` gets the verdict the same command gets without it.

rtk (rtk-ai/rtk) rewrites `git status` into `rtk git status`, and its run-anything
subcommands (`err`, `test`, `summary`, `run`, `bypass`, `proxy`) run any command after them.
A guard that reads `rtk` as the program sees nothing it knows, so the prefix is a bypass.

Designed failure modes, each with the mutation that proves the test real:
  - `rtk` missing from shell_parser.WRAPPERS -> red: `rtk git config --edit` and
    `rtk err pkill node` are allowed;
  - rtk's runner subcommands not unwrapped -> red: the program is `err`, not `pkill`;
  - a runner's shell string not parsed -> red: `rtk run -c 'pkill node'` runs nothing;
  - memory_first_gate / suite_economy reading `rtk` as the first word -> red: `rtk grep`
    is not text search and `rtk pytest -q` is not a test run.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys

import pytest

INTERNALS = "features/common/skills/git-work/scripts/git_internals_guard.py"
BLAST = "features/common/skills/worktree-agent-isolation/scripts/blast_radius_kill_guard.py"
MEMORY_GATE = "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py"
ECONOMY = "features/common/skills/test-economy/scripts/suite_economy.py"
HERMES_HOOKS = "features/common/hooks/ai_badger_hooks.py"
CWD = "/tmp/project"

PREFIXES = [
    "rtk", "rtk err", "rtk test", "rtk summary", "rtk proxy", "rtk run", "rtk bypass",
    "rtk -v", "rtk -vv err", "rtk --ultra-compact", "/opt/homebrew/bin/rtk",
    "RTK_DISABLED=1 rtk", "rtk --skip-env summary --skip-env", "rtk err --",
]
# Each one is refused by git_internals_guard or blast_radius_kill_guard without rtk.
REFUSED = ["git config --edit", "rm .git/config", "pkill node"]
SCRIPTS = [
    "rtk run -c 'pkill node'",
    "rtk run --command 'git config --edit'",
    "rtk run --command='rm .git/config'",
    "rtk run --shell bash -c 'pkill node'",
    "rtk err --shell bash 'pkill node'",
    "rtk summary --shell=zsh 'git config --edit'",
]


@pytest.fixture
def internals(load_script):
    return load_script(INTERNALS)


@pytest.fixture
def blast(load_script):
    return load_script(BLAST)


@pytest.fixture
def verdict(internals, blast):
    def _verdict(command):
        return internals.find_violation(command, CWD), blast.find_hazard(command)
    return _verdict


@pytest.mark.parametrize("command", REFUSED)
def test_the_bare_commands_are_refused(verdict, command):
    assert verdict(command) != (None, None)


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("command", REFUSED + ["git push --force origin main"])
def test_rtk_and_its_runners_get_the_bare_verdict(verdict, prefix, command):
    assert verdict(f"{prefix} {command}") == verdict(command)


@pytest.mark.parametrize("command", REFUSED + ["git push --force origin main"])
def test_rtk_in_a_later_segment_gets_the_bare_verdict(verdict, command):
    assert verdict(f"cd x && rtk {command}") == verdict(f"cd x && {command}")


@pytest.mark.parametrize("command", SCRIPTS)
def test_a_runner_shell_string_is_judged_as_a_script(verdict, command):
    assert verdict(command) != (None, None)


# ------------------------------------------------------------------------- classifiers

@pytest.mark.parametrize("prefix", ["rtk", "/opt/homebrew/bin/rtk -v"])
@pytest.mark.parametrize("command", ["grep -rn pattern src/", "rg pattern", "find . -name x"])
def test_memory_gate_treats_rtk_search_as_search(load_script, prefix, command):
    gate = load_script(MEMORY_GATE)

    assert gate.is_text_search("terminal", {"command": f"{prefix} {command}"}) is True
    assert gate.is_text_search("terminal", {"command": command}) is True


@pytest.mark.parametrize("command", ["rtk git status", "rtk", "rtk gain", "rtk -v"])
def test_memory_gate_leaves_other_rtk_commands_alone(load_script, command):
    gate = load_script(MEMORY_GATE)

    assert gate.is_text_search("Bash", {"command": command}) is False


@pytest.mark.parametrize("command,expected", [
    ("rtk pytest -q", {"runner": "pytest", "kind": "full"}),
    ("rtk test pytest", {"runner": "pytest", "kind": "full"}),
    ("rtk -v test python3 -m pytest tests/test_x.py",
     {"runner": "pytest", "kind": "filtered"}),
    ("rtk cargo test", {"runner": "cargo test", "kind": "full"}),
    ("/opt/homebrew/bin/rtk err --skip-env go test ./...", {"runner": "go test", "kind": "full"}),
])
def test_suite_economy_counts_an_rtk_test_run(load_script, command, expected):
    economy = load_script(ECONOMY)

    assert economy.is_test_run(command) == expected


@pytest.mark.parametrize("command", ["rtk", "rtk gain", "rtk test", "rtk git status"])
def test_suite_economy_ignores_rtk_commands_that_run_no_tests(load_script, command):
    assert load_script(ECONOMY).is_test_run(command) is None


# ------------------------------------------------------------------------- harness payloads

def _pi_payload(command):
    """What features/pi/adjustments/adapter/hook-bridge.ts toClaudePayload sends a gate."""
    return {"hook_event_name": "PreToolUse", "session_id": "pi-session", "cwd": CWD,
            "tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def pi_decisions(internals, blast, monkeypatch, capsys):
    monkeypatch.setattr(blast, "_live_lane_pids", lambda: [101, 102])
    monkeypatch.setattr(blast, "deny_count", lambda *_: 0)
    monkeypatch.setattr(blast, "increment_denials", lambda *_: True)

    def _decisions(command):
        internals.decide(_pi_payload(command))
        printed = capsys.readouterr().out
        internals_decision = json.loads(printed)["hookSpecificOutput"]["permissionDecision"] \
            if printed else None
        blast_decision = blast.decide(_pi_payload(command)).get(
            "hookSpecificOutput", {}).get("permissionDecision")
        return internals_decision, blast_decision
    return _decisions


@pytest.mark.parametrize("command", ["git push --force origin main", "git config --edit",
                                     "pkill node"])
def test_a_pi_bridge_payload_with_rtk_gets_the_bare_verdict(pi_decisions, command):
    bare = pi_decisions(command)

    assert pi_decisions(f"rtk {command}") == bare
    assert pi_decisions(f"rtk err {command}") == bare
    assert command.startswith("git push") or "deny" in bare


def _hermes_call(hooks, command):
    """How hermes_cli.plugins invokes a pre_tool_call callback for the `terminal` tool."""
    return hooks.pre_tool_call_git_internals_guard(
        tool_name="terminal", args={"command": command}, task_id="t1", session_id="s1",
        tool_call_id="call-1", turn_id="turn-1", api_request_id="req-1", middleware_trace=[])


@pytest.mark.parametrize("command", ["git push --force origin main", "git config --edit"])
def test_a_hermes_pre_tool_call_with_rtk_gets_the_bare_verdict(load_script, internals,
                                                               monkeypatch, command):
    hooks = load_script(HERMES_HOOKS)
    monkeypatch.setitem(sys.modules, hooks.GIT_INTERNALS_GUARD_MODULE_NAME, internals)
    bare = _hermes_call(hooks, command)

    assert _hermes_call(hooks, f"rtk {command}") == bare
    assert _hermes_call(hooks, f"rtk err {command}") == bare
    assert command.startswith("git push") or bare["action"] == "block"
