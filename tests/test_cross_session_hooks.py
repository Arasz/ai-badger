"""The two cross-session PreToolUse hooks and the probe gate that proves them.

`verify_hooks.py` holds the 80-odd probes; this module is what makes them run in CI and what
keeps the gate honest. A gate that has only ever passed is indistinguishable from one whose
comparison can produce a single answer, so the second test reintroduces the defect the gate
exists to catch — the `sh -c` recursion narrowed back to an exact `"-c"` match, which is how
`-lc`/`-ec`/`-cx` used to slip past — and asserts it goes red.

The remaining tests derive their cases from `STACK_HAZARDS` itself: a row nobody probes is
decoration, and a hand-written mirror of the table drifts the moment someone adds to one side.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _test_write

SCRIPTS = "features/common/skills/worktree-agent-isolation/scripts"
GUARD = f"{SCRIPTS}/blast_radius_kill_guard.py"
GATE = f"{SCRIPTS}/verify_hooks.py"

# The exact-match spelling the combined shell flags escape through.
NARROWED = '    return args.index("-c") if "-c" in args else None'
LEXER = ('    for index, token in enumerate(args):\n'
         '        if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:\n'
         '            return index\n'
         '    return None')


def _run_gate(scripts_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(scripts_dir / "verify_hooks.py")],
                          capture_output=True, text=True, timeout=300, check=False)


@pytest.fixture
def scripts_copy(root, tmp_path) -> Path:
    """The three scripts on their own, so a mutation never touches the checkout."""
    out = tmp_path / "scripts"
    out.mkdir()
    for name in ("badger_store.py", "blast_radius_kill_guard.py",
                 "cross_worktree_dirty_warning.py", "verify_hooks.py"):
        shutil.copy(root / SCRIPTS / name, out / name)
    return out


def test_the_probe_gate_passes_on_the_shipped_hooks(root):
    result = _run_gate(root / SCRIPTS)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "all probes passed" in result.stdout


def test_the_gate_goes_red_when_the_shell_recursion_is_narrowed(scripts_copy):
    """The defect the gate exists to catch: `bash -lc '<hazard>'` reads as an ordinary bash."""
    guard = scripts_copy / "blast_radius_kill_guard.py"
    text = guard.read_text(encoding="utf-8")
    assert LEXER in text, "the lexer this mutation removes is no longer spelled that way"
    _test_write(guard, text.replace(LEXER, NARROWED), encoding="utf-8")

    result = _run_gate(scripts_copy)

    assert result.returncode == 1, result.stdout
    assert "-lc" in result.stdout and "-ec" in result.stdout and "-cx" in result.stdout


def test_every_stack_hazard_row_is_denied(load_script):
    """Derived from the table: adding a row without its hazard being caught fails here."""
    guard = load_script(GUARD)
    assert guard.STACK_HAZARDS, "an empty table would make this test vacuous"

    for stack, hazards in guard.STACK_HAZARDS.items():
        for program, words in hazards.commands:
            command = " ".join((program, *words))
            assert guard.find_hazard(command), f"{stack}: {command!r} allowed through"
        for fragment in hazards.caches:
            command = "rm -rf ~/" + fragment.replace(r"\.", ".")
            assert guard.find_hazard(command), f"{stack}: {command!r} allowed through"


def test_an_ordinary_command_of_a_listed_program_is_allowed(load_script):
    """The table names shared-resource *commands*, never programs: `dotnet build` is not a reap."""
    guard = load_script(GUARD)

    for command in ("dotnet build", "npm cache verify", "pip install -r requirements.txt",
                    "cargo build --release", "rm -rf ./node_modules"):
        assert guard.find_hazard(command) is None, f"{command!r} denied"


def test_an_unscoped_kill_is_denied_and_a_pid_kill_is_not(load_script):
    """The incident in one line: a pattern match kills another lane's process, a PID does not."""
    guard = load_script(GUARD)

    assert guard.find_hazard("pkill -f build")
    assert guard.find_hazard("bash -lc 'killall java'")
    assert guard.find_hazard("kill $(pgrep -f build)")
    assert guard.find_hazard("kill 12345") is None
    assert guard.find_hazard("kill -9 12345") is None
