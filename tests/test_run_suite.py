"""TDD gates for `run_suite.py` — the layer 1 (QoS) + layer 2 (worker budget) wrapper.

See `docs/adr/0020-background-qos-and-worker-budget.md` for why these two layers ship and a
queue/daemon/hook/flock/nice do not, and
`features/common/skills/worktree-agent-isolation/references/machine-load.md` for the measured
tables. This suite pins the seven gates from that ADR's blueprint one test class per gate, plus a
couple of composition checks the blueprint implies but does not table explicitly.
"""
# pylint: disable=redefined-outer-name
# The `run_suite` fixture below is used as a same-named parameter by nearly every test in this
# file — the standard pytest injection pattern this repo already uses for a local, file-scoped
# fixture (see tests/test_changelog_index.py's `changelog_index` fixture for the same shape).
from __future__ import annotations

import builtins
import importlib
import subprocess
import sys

import pytest

from conftest import ROOT

SCRIPT = "features/common/skills/worktree-agent-isolation/scripts/run_suite.py"
SCRIPT_ABS = str(ROOT / SCRIPT)


@pytest.fixture
def run_suite(load_script):
    """The module under test, loaded fresh so module-level state never leaks between tests."""
    return load_script(SCRIPT)


# ---------------------------------------------------------------------------
# Gate 1 — budget() never returns 0.
# ---------------------------------------------------------------------------

class TestBudgetNeverZero:
    @pytest.mark.parametrize("cores, agents, reserve, slots", [
        (10, 20, 2, None),   # the briefed pathological case: more agents than cores
        (1, 1, 2, None),     # reserve exceeds cores entirely
        (2, 50, 2, None),    # wildly oversubscribed
        (4, 4, 0, None),
        (8, 3, 2, 1),
    ])
    def test_budget_is_never_zero(self, run_suite, cores, agents, reserve, slots):
        assert run_suite.budget(cores, agents, reserve, slots) >= 1

    def test_the_briefed_case_agents_20_cores_10(self, run_suite):
        # Without max(1, ...) this divides down to 0: (10-2)//20 == 0.
        assert run_suite.budget(10, 20, 2, None) == 1


# ---------------------------------------------------------------------------
# Gate 2 — budget is derived, not hardcoded.
# ---------------------------------------------------------------------------

class TestBudgetIsDerived:
    def test_budget_differs_across_machine_sizes(self, run_suite):
        # A hardcoded `return 2` (or any other constant) passes gate 1's happy path but is
        # blind to the machine it is running on — this is the test that catches it.
        assert run_suite.budget(10, 5) != run_suite.budget(64, 5)

    def test_budget_scales_with_available_cores(self, run_suite):
        small = run_suite.budget(8, 2, reserve=2)
        large = run_suite.budget(32, 2, reserve=2)
        assert large > small

    def test_budget_matches_the_documented_formula(self, run_suite):
        cores, agents, reserve, slots = 12, 4, 2, None
        divisor = min(agents, slots or agents)
        expected = max(1, (cores - reserve) // divisor)
        assert run_suite.budget(cores, agents, reserve, slots) == expected

    def test_slots_caps_the_divisor_below_agents(self, run_suite):
        # slots=1 means "only 1 of the N agents holds a slot right now" -> the divisor is 1,
        # not `agents`, so the full budget goes to the agent(s) actually running.
        assert run_suite.budget(16, 8, reserve=2, slots=1) == run_suite.budget(16, 1, reserve=2)


# ---------------------------------------------------------------------------
# Gate 3 — QoS prefix absent off-macOS and when disabled.
# ---------------------------------------------------------------------------

class TestQosGating:
    def test_prefix_present_on_macos_by_default(self, run_suite, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("AI_BADGER_QOS", raising=False)
        monkeypatch.setattr(run_suite.shutil, "which", lambda name: "/usr/bin/taskpolicy")
        assert run_suite.qos_prefix(no_qos=False) == ["/usr/bin/taskpolicy", "-b"]

    def test_prefix_absent_off_macos(self, run_suite, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("AI_BADGER_QOS", raising=False)
        assert run_suite.qos_prefix(no_qos=False) == []

    def test_prefix_absent_on_windows(self, run_suite, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("AI_BADGER_QOS", raising=False)
        assert run_suite.qos_prefix(no_qos=False) == []

    def test_prefix_absent_when_env_says_off(self, run_suite, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("AI_BADGER_QOS", "off")
        assert run_suite.qos_prefix(no_qos=False) == []

    def test_env_off_is_case_insensitive_and_trims_space(self, run_suite, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("AI_BADGER_QOS", " Off ")
        assert run_suite.qos_prefix(no_qos=False) == []

    def test_prefix_absent_when_no_qos_flag_set(self, run_suite, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("AI_BADGER_QOS", raising=False)
        assert run_suite.qos_prefix(no_qos=True) == []

    def test_hardcoding_the_prefix_would_fail_both(self, run_suite, monkeypatch):
        # Documents the gate's own "watch it fail" trick: a hardcoded ["taskpolicy", "-b"]
        # return would pass the macOS-default test but fail both of these.
        monkeypatch.setattr(sys, "platform", "linux")
        off_macos = run_suite.qos_prefix(no_qos=False)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("AI_BADGER_QOS", "off")
        disabled = run_suite.qos_prefix(no_qos=False)
        assert off_macos == [] and disabled == []


# ---------------------------------------------------------------------------
# Gate 4 — the command runs even when the machinery fails.
# ---------------------------------------------------------------------------

class TestMachineryFailureDoesNotBlockTheCommand:
    def test_unwritable_state_dir_still_runs_the_command_and_warns(self, run_suite, tmp_path,
                                                                     monkeypatch):
        # A plain FILE where the state dir would be: mkdir(parents=True) on it raises
        # NotADirectoryError regardless of who owns the process (chmod bits are meaningless
        # to a root-run CI container, so this simulates "unwritable" portably).
        blocked = tmp_path / "blocked-state-dir"
        blocked.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv("AI_BADGER_RUN_SUITE_STATE_DIR", str(blocked / "run-suite"))

        result = subprocess.run(
            [sys.executable, run_suite.__file__, "--agents", "1", "--no-qos", "--",
             sys.executable, "-c", "print('ran')"],
            capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "AI_BADGER_RUN_SUITE_STATE_DIR":
                 str(blocked / "run-suite")})

        assert result.returncode == 0
        assert "ran" in result.stdout
        assert result.stderr.strip() != ""

    def test_unresolvable_qos_falls_back_to_running_without_it(self, run_suite, monkeypatch):
        # qos_enabled must never raise even if something upstream is broken; a bad env value
        # is still resolved to a boolean, not an exception that stops the run.
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("AI_BADGER_QOS", "OFF")
        assert run_suite.qos_enabled(no_qos=False) is False


# ---------------------------------------------------------------------------
# Gate 5 — imports with no fcntl (platforms: [linux, macos, windows]).
# ---------------------------------------------------------------------------

class TestNoFcntl:
    def test_module_imports_with_fcntl_blocked(self, monkeypatch):
        real_import = builtins.__import__

        def _guarded_import(name, *args, **kwargs):
            if name == "fcntl" or name.startswith("fcntl."):
                raise ImportError("fcntl is Linux/macOS-only; run_suite.py must not import it "
                                   "(platforms: [linux, macos, windows])")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _guarded_import)
        sys.modules.pop("run_suite_under_fcntl_guard", None)
        spec = importlib.util.spec_from_file_location("run_suite_under_fcntl_guard", SCRIPT_ABS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # raises ImportError if the module ever imports fcntl

    def test_module_does_not_call_sched_getaffinity_unguarded(self, run_suite):
        # os.sched_getaffinity is Linux-only and raises AttributeError on macOS/Windows;
        # cpu_count() must not depend on it existing. A prose mention (docstring/comment) is
        # fine; only an actual unguarded call site is the defect.
        import os as os_module
        source = run_suite.__file__
        with open(source, encoding="utf-8") as fh:
            lines = fh.readlines()
        for i, line in enumerate(lines):
            if "os.sched_getaffinity(" in line or "os_module.sched_getaffinity(" in line:
                window = "".join(lines[max(0, i - 2):i + 1])
                assert "hasattr(os" in window, (
                    f"line {i + 1} calls sched_getaffinity without a hasattr guard nearby")
        # And, functionally: cpu_count() must work even if the attribute is absent.
        had = hasattr(os_module, "sched_getaffinity")
        real = getattr(os_module, "sched_getaffinity", None)
        if had:
            delattr(os_module, "sched_getaffinity")
        try:
            assert run_suite.cpu_count() >= 1
        finally:
            if had:
                os_module.sched_getaffinity = real


# ---------------------------------------------------------------------------
# Additional behavioural coverage the blueprint implies (not separately gated above, but load
# bearing for "layered and independently disableable").
# ---------------------------------------------------------------------------

class TestWorkersEnvExport:
    def test_exports_workers_when_unset(self, run_suite, monkeypatch, tmp_path):
        monkeypatch.delenv("AI_BADGER_TEST_WORKERS", raising=False)
        monkeypatch.setenv("AI_BADGER_RUN_SUITE_STATE_DIR", str(tmp_path / "state"))
        result = subprocess.run(
            [sys.executable, run_suite.__file__, "--agents", "2", "--reserve", "1", "--no-qos",
             "--", sys.executable, "-c",
             "import os; print(os.environ.get('AI_BADGER_TEST_WORKERS'))"],
            capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "AI_BADGER_RUN_SUITE_STATE_DIR":
                 str(tmp_path / "state")})
        monkeypatch.delenv("AI_BADGER_TEST_WORKERS", raising=False)
        assert result.returncode == 0
        assert result.stdout.strip() != "None"
        assert int(result.stdout.strip()) >= 1

    def test_does_not_override_a_caller_supplied_value(self, run_suite, tmp_path):
        import os as os_module
        env = {**os_module.environ, "AI_BADGER_TEST_WORKERS": "7",
               "AI_BADGER_RUN_SUITE_STATE_DIR": str(tmp_path / "state")}
        result = subprocess.run(
            [sys.executable, run_suite.__file__, "--agents", "2", "--no-qos",
             "--", sys.executable, "-c",
             "import os; print(os.environ['AI_BADGER_TEST_WORKERS'])"],
            capture_output=True, text=True, check=False, env=env)
        assert result.returncode == 0
        assert result.stdout.strip() == "7"


class TestExitCodePropagation:
    def test_the_wrapped_commands_exit_code_is_preserved(self, run_suite, tmp_path):
        import os as os_module
        env = {**os_module.environ,
               "AI_BADGER_RUN_SUITE_STATE_DIR": str(tmp_path / "state")}
        result = subprocess.run(
            [sys.executable, run_suite.__file__, "--no-qos", "--",
             sys.executable, "-c", "import sys; sys.exit(17)"],
            capture_output=True, text=True, check=False, env=env)
        assert result.returncode == 17

    def test_missing_command_is_a_usage_error_not_a_crash(self, run_suite, tmp_path):
        import os as os_module
        env = {**os_module.environ,
               "AI_BADGER_RUN_SUITE_STATE_DIR": str(tmp_path / "state")}
        result = subprocess.run([sys.executable, run_suite.__file__, "--no-qos"],
                                 capture_output=True, text=True, check=False, env=env)
        assert result.returncode != 0
        assert result.stderr.strip() != ""
