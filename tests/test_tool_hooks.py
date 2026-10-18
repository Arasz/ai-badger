"""tool_hooks: the guarded, marked hook command for opt-in CLI tools, and its recogniser.

The command is run the way a harness runs a hook: through a shell, with the hook JSON on
stdin. A stub `rtk` on PATH stands in for the real binary.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from conftest import _test_write

SCRIPT = "features/common/skills/welcome-ai-badger/scripts/tool_hooks.py"
HOOK_JSON = '{"tool_name":"Bash","tool_input":{"command":"git status"}}'
REWRITE = '{"hookSpecificOutput":{"updatedInput":{"command":"rtk git status"}}}'
EXPECTED = (
    "env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c '"
    "command -v rtk >/dev/null 2>&1 || exit 0; "
    "out=$(rtk hook claude) || exit 0; "
    "case \"$out\" in \"{\"*) printf \"%s\" \"$out\";; esac'"
)


@pytest.fixture(name="tool_hooks")
def tool_hooks_module(load_script):
    return load_script(SCRIPT)


def _stub(tmp_path, body):
    """A bin dir holding an `rtk` that records its stdin and env, then runs `body`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    rtk = bin_dir / "rtk"
    _test_write(rtk, "#!/bin/sh\n"
                     f"cat > '{tmp_path}/stdin'\n"
                     f"echo \"$*|$AI_BADGER_TOOL|$RTK_TELEMETRY_DISABLED\" > '{tmp_path}/args'\n"
                     f"{body}\n")
    rtk.chmod(0o755)
    return bin_dir


def _run(cmd, bin_dir=None):
    path = "/usr/bin:/bin" if bin_dir is None else f"{bin_dir}:/usr/bin:/bin"
    return subprocess.run(["/bin/sh", "-c", cmd], input=HOOK_JSON, capture_output=True,
                          text=True, env={"PATH": path}, timeout=10, check=False)


def test_guarded_command_has_the_exact_guarded_shape(tool_hooks):
    assert tool_hooks.guarded_command("rtk", "claude") == EXPECTED


def test_guarded_command_carries_marker_and_telemetry_off(tool_hooks):
    cmd = tool_hooks.guarded_command("rtk", "codex")
    assert cmd.startswith("env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 ")
    assert "rtk hook codex" in cmd


@pytest.mark.parametrize("tool, hook_arg", [
    ("rtk", "claude; rm -rf ~"), ("rtk", "a'b"), ("rtk", ""), ("r tk", "claude"),
    ("rtk$(id)", "claude"), ("", "claude"),
])
def test_guarded_command_refuses_shell_unsafe_names(tool_hooks, tool, hook_arg):
    with pytest.raises(ValueError):
        tool_hooks.guarded_command(tool, hook_arg)


@pytest.mark.parametrize("cmd, ours", [
    (EXPECTED, True),
    ("env AI_BADGER_TOOL=rtk sh -c 'anything else'", True),
    ("rtk hook claude", False),
    ("sh -c 'command -v rtk || exit 0; out=$(rtk hook claude)'", False),
    ("env AI_BADGER_CODEX_HOOK=1 python3 hook.py", False),
    ("env NOT_AI_BADGER_TOOL=rtk rtk hook claude", False),
    ("", False),
    (None, False),
])
def test_is_ours_matches_by_marker_only(tool_hooks, cmd, ours):
    assert tool_hooks.is_ours(cmd) is ours


def test_without_rtk_on_path_exits_zero_silently(tool_hooks):
    result = _run(tool_hooks.guarded_command("rtk", "claude"))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_json_output_passes_through_verbatim_and_stub_gets_stdin(tool_hooks, tmp_path):
    bin_dir = _stub(tmp_path, f"printf '%s' '{REWRITE}'")
    result = _run(tool_hooks.guarded_command("rtk", "claude"), bin_dir)
    assert (result.returncode, result.stdout) == (0, REWRITE)
    assert (tmp_path / "stdin").read_text(encoding="utf-8") == HOOK_JSON
    assert (tmp_path / "args").read_text(encoding="utf-8") == "hook claude|rtk|1\n"


def test_nonzero_exit_with_json_is_swallowed(tool_hooks, tmp_path):
    bin_dir = _stub(tmp_path, f"printf '%s' '{REWRITE}'; exit 2")
    result = _run(tool_hooks.guarded_command("rtk", "claude"), bin_dir)
    assert (result.returncode, result.stdout) == (0, "")


def test_non_json_output_is_dropped(tool_hooks, tmp_path):
    bin_dir = _stub(tmp_path, "echo garbage")
    result = _run(tool_hooks.guarded_command("rtk", "claude"), bin_dir)
    assert (result.returncode, result.stdout) == (0, "")


def test_stderr_is_preserved_on_failure(tool_hooks, tmp_path):
    bin_dir = _stub(tmp_path, "echo 'rtk: hook integrity check FAILED' >&2; exit 1")
    result = _run(tool_hooks.guarded_command("rtk", "claude"), bin_dir)
    assert (result.returncode, result.stdout) == (0, "")
    assert "hook integrity check FAILED" in result.stderr


@pytest.mark.parametrize("mutate, body, use_stub", [
    (lambda c: c.replace(" >/dev/null 2>&1 || exit 0;", " >/dev/null 2>&1;"), None, False),
    (lambda c: c.replace(") || exit 0;", ");"), f"printf '%s' '{REWRITE}'; exit 2", True),
    (lambda c: c.replace("case \"$out\" in \"{\"*) printf \"%s\" \"$out\";; esac",
                         "printf \"%s\" \"$out\""), "echo garbage", True),
], ids=["no-command-v-guard", "no-exit-guard", "no-case-filter"])
def test_each_guard_is_load_bearing(tool_hooks, tmp_path, mutate, body, use_stub):
    cmd = tool_hooks.guarded_command("rtk", "claude")
    mutated = mutate(cmd)
    assert mutated != cmd
    bin_dir = _stub(tmp_path, body) if use_stub else None
    good, bad = _run(cmd, bin_dir), _run(mutated, bin_dir)
    assert (good.returncode, good.stdout, good.stderr) == (0, "", "")
    assert (bad.returncode, bad.stdout, bad.stderr) != (0, "", "")


PROGRAM = 'import sys; print(sys.stdin.read().replace("git", "rtk git") + "|" + sys.argv[1])'


def test_a_program_form_runs_the_inlined_source_with_the_arg_and_stdin(tool_hooks, tmp_path):
    bin_dir = _stub(tmp_path, "exit 1")
    cmd = tool_hooks.guarded_command("rtk", "codex", PROGRAM)
    result = _run(cmd, bin_dir)
    assert (result.returncode, result.stdout) == (0, HOOK_JSON.replace("git", "rtk git") + "|codex")
    assert "rtk hook" not in cmd
    assert not (tmp_path / "args").exists(), "the program form must not call rtk hook"


def test_a_program_form_keeps_the_marker_and_the_rtk_guard(tool_hooks):
    cmd = tool_hooks.guarded_command("rtk", "claude", PROGRAM)
    assert tool_hooks.is_ours(cmd)
    assert cmd.startswith("env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c "
                          "'command -v rtk >/dev/null 2>&1 || exit 0; ")
    assert _run(cmd).stdout == ""


def test_a_program_with_single_quotes_survives_the_shell(tool_hooks, tmp_path):
    program = """print('{"q": "it' + "'" + 's"}')"""
    result = _run(tool_hooks.guarded_command("rtk", "claude", program), _stub(tmp_path, "exit 1"))
    assert result.stdout == '{"q": "it\'s"}', result.stderr


def test_rtk_is_not_found_on_the_bare_test_path():
    assert not any(os.path.exists(f"{d}/rtk") for d in ("/usr/bin", "/bin"))
