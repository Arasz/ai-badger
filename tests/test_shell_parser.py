"""The one shell lexer every PreToolUse guard reads a Bash command through.

Designed failure modes, each with the mutation that proves the test real:
  - per-line lexing (split the text on newlines first -> red): a quote spanning a newline
    drops the line holding the command;
  - a heredoc body read as commands (stop skipping it -> red): a commit message line that
    starts with `rm` becomes a command;
  - wrapper flags without their values (stop consuming the value -> red): `sudo -u root rm`
    runs `root`;
  - a copy drifting from the others (edit one copy -> red): one guard lexes differently.
"""
from __future__ import annotations

import re
import subprocess

import pytest
from conftest import ROOT

PARSER = "features/common/skills/git-work/scripts/shell_parser.py"


@pytest.fixture(name="sp")
def _sp(load_script):
    return load_script(PARSER)


def _programs(sp, command, **kwargs):
    return [c.program for c in sp.parse(command, **kwargs) if c.program]


# ------------------------------------------------------------------------------ splitting

def test_a_quote_spanning_a_newline_stays_one_word(sp):
    commands = sp.parse('rm x; echo "a\nb"')

    assert [c.argv for c in commands] == [("rm", "x"), ("echo", "a\nb")]


@pytest.mark.parametrize("command", [
    "a; b", "a && b", "a || b", "a | b", "a & b", "a\nb", "a |& b", "(a) ; b",
])
def test_every_list_operator_and_a_newline_split_commands(sp, command):
    assert _programs(sp, command) == ["a", "b"]


def test_a_quoted_operator_is_a_word_not_a_split(sp):
    (command,) = sp.parse('rm ";" -rf x')

    assert command.argv == ("rm", ";", "-rf", "x")


def test_a_comment_runs_nothing(sp):
    assert _programs(sp, "# pkill -f build\nls") == ["ls"]


# ------------------------------------------------------------------------------ recursion

@pytest.mark.parametrize("command", [
    "echo $(pkill node)",
    "echo \"$(pkill node)\"",
    "echo `pkill node`",
    "diff <(pkill node) x",
    "bash -c 'pkill node'",
    "sh -lc \"echo ok; pkill node\"",
    "eval 'pkill node'",
    "echo $(echo $(pkill node))",
])
def test_nested_commands_are_found(sp, command):
    assert "pkill" in _programs(sp, command)


def test_single_quotes_run_nothing(sp):
    assert _programs(sp, "echo '$(pkill node)' '`pkill node`'") == ["echo"]


def test_a_substitution_runs_in_its_own_scope(sp):
    outer, inner = sp.parse("echo $(cd /tmp)")[::-1]

    assert outer.program == "echo" and inner.program == "cd"
    assert inner.scope[:-1] == outer.scope and inner.scope != outer.scope


# ------------------------------------------------------------------------------ heredocs

def test_a_heredoc_body_is_data(sp):
    command = "git commit -F - <<'EOF'\nfix\nrm .git/config is what broke it\nEOF\nls"

    assert _programs(sp, command) == ["git", "ls"]


def test_a_heredoc_inside_a_substitution_is_data(sp):
    command = "git commit -m \"$(cat <<'EOF'\nfix\n\nrm x is why\nEOF\n)\""

    assert _programs(sp, command) == ["cat", "git"]


def test_an_unquoted_heredoc_expands_its_substitutions(sp):
    assert "rm" in _programs(sp, "cat <<EOF\n$(rm x)\nEOF")
    assert "rm" not in _programs(sp, "cat <<'EOF'\n$(rm x)\nEOF")


def test_a_tab_stripping_heredoc_ends_at_an_indented_delimiter(sp):
    assert _programs(sp, "cat <<-EOF\n\trm x\n\tEOF\nls") == ["cat", "ls"]


# ------------------------------------------------------------------------------ wrappers

@pytest.mark.parametrize("command", [
    "sudo -u root rm x",
    "sudo -nu root rm x",
    "sudo -uroot rm x",
    "sudo --user root rm x",
    "sudo --user=root rm x",
    "env -u X rm x",
    "env -i A=1 B=2 rm x",
    "nice -n 5 rm x",
    "nice -10 rm x",
    "timeout 5 rm x",
    "timeout -s KILL 5s rm x",
    "command rm x",
    "exec -a name rm x",
    "nohup rm x",
    "time -p rm x",
    "FOO=1 sudo -E env BAR=2 nice rm x",
    "/usr/bin/sudo -- /bin/rm x",
    "xargs -I {} rm x",
    "if true; then rm x; fi",
    "{ rm x; }",
])
def test_wrappers_and_their_option_values_are_stripped(sp, command):
    last = [c for c in sp.parse(command) if c.program not in ("true", "")][-1]

    assert (last.program, last.args) == ("rm", ("x",))


def test_command_v_only_looks_a_program_up(sp):
    (command,) = sp.parse("command -v pkill")

    assert command.program == ""


def test_short_flags_combine_clusters_and_stop_where_a_value_starts(sp):
    (command,) = sp.parse("sed -Ei -n s/a/b/ -- -z x")

    assert command.short_flags == "Ein"
    assert sp.short_flags(["-Mstrict", "-pi"], stop="M") == "Mpi"


# ------------------------------------------------------------------------------ redirects

def test_redirects_leave_the_words_and_name_their_targets(sp):
    (command,) = sp.parse("echo x >out 2>>log &>both >| clobber < in 2>&1 >&-")

    assert command.argv == ("echo", "x")
    assert command.redirects == ((">", "out"), (">>", "log"), ("&>", "both"),
                                 (">|", "clobber"), ("<", "in"))


def test_a_subshell_carries_its_own_redirect(sp):
    commands = sp.parse("(echo x) > out")

    assert commands[-1].words == () and commands[-1].redirects == ((">", "out"),)


# ------------------------------------------------------------------------------ bad input

def test_an_unterminated_quote_drops_only_the_command_it_opens(sp):
    assert _programs(sp, "rm x\necho 'unbalanced > y") == ["rm"]


def test_blind_mode_splits_an_unterminated_command_quote_blind(sp):
    commands = sp.parse('rm -rf "/tmp/x', blind=True)

    assert [c.argv for c in commands] == [("rm", "-rf", '"/tmp/x')]


@pytest.mark.parametrize("command", [
    "kill $(", "pkill \x00 x", "kill \\", "echo ${", "echo $((1", "a <", "`",
    "bash -c '" * 10 + "pkill x" + "'" * 10, "$(" * 200 + ")" * 200,
])
def test_hostile_input_never_raises(sp, command):
    sp.parse(command)
    sp.parse(command, blind=True)


# ------------------------------------------------------------------------------ the copies

def _copies():
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--",
         "*shell_parser.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted(set(listed.split()))


def test_every_copy_is_byte_identical():
    """Each guard loads the copy beside itself, so a drifted copy is a guard that lexes
    differently from the others."""
    copies = _copies()
    assert len(copies) >= 3, copies
    canonical = (ROOT / PARSER).read_bytes()

    drifted = [path for path in copies if (ROOT / path).read_bytes() != canonical]

    assert not drifted, f"differs from {PARSER}: {drifted}"


def test_every_module_that_loads_the_parser_has_a_copy_beside_it():
    """Derived from the sources: a guard that loads `shell_parser.py` with no copy beside it
    has no lexer in the shape it ships in."""
    loaders = [path for path in ROOT.glob("features/**/*.py")
               if path.name != "shell_parser.py"
               and re.search(r"[\"']shell_parser\.py[\"']", path.read_text(encoding="utf-8"))]
    assert len(loaders) >= 3, loaders

    missing = [str(p.relative_to(ROOT)) for p in loaders
               if not (p.parent / "shell_parser.py").is_file()]

    assert not missing, missing


def test_the_hermes_arm_ships_the_parser_beside_the_git_guard(load_script):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")

    assert ("git-work", "shell_parser.py") in adjust_hooks.SHARED_SKILL_MODULES
