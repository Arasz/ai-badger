"""Git's own storage is written by git, never by hand — refused at edit time.

The incident: a `.git/config` was truncated to 296 bytes by an agent editing it by hand, losing
`remote.origin.fetch` and the `[branch]` tracking sections. Measured in a throwaway repo: with no
fetch refspec, `git fetch origin` prints `* branch HEAD -> FETCH_HEAD` and `refs/remotes/origin/*`
silently stops moving, while fetch keeps reporting success. Nothing downstream notices, which is
why this has to be prevented at edit time rather than detected later.

Every fixture here is a real git dir on disk (`git init`, `git worktree add`, `git init --bare`)
so the structural rule is exercised against what git actually writes, not against path strings.
Row ids (E1-E17, B1-B21) are the pre-written test list the guard was built from.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _test_write

ROOT = Path(__file__).resolve().parents[1]
GUARD = "features/common/skills/git-work/scripts/git_internals_guard.py"
GUARD_PATH = ROOT / GUARD
OVERRIDE_ENV = "AI_BADGER_ALLOW_GIT_DIR_EDITS"

GIT_IDENTITY = ("-c", "user.email=guard@test", "-c", "user.name=Guard Test")


def _git(*args, cwd):
    subprocess.run(("git", *GIT_IDENTITY, *args), cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture(name="guard")
def _guard(load_script, monkeypatch):
    """The guard, loaded with the override cleared — an exported override would hide every deny."""
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    return load_script(GUARD)


@pytest.fixture(name="repo")
def _repo(tmp_path):
    """A real repo with a real linked worktree, plus near-miss files that must stay editable."""
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "-q", cwd=root)
    _git("commit", "-q", "--allow-empty", "-m", "root", cwd=root)
    _git("worktree", "add", "-q", "-b", "lane", str(tmp_path / "wt"), cwd=root)
    _test_write(root / ".gitignore", "*.pyc\n")
    _test_write(root / ".gitattributes", "* text=auto\n")
    (root / ".github" / "workflows").mkdir(parents=True)
    _test_write(root / ".github" / "workflows" / "ci.yml", "on: push\n")
    (root / "docs").mkdir()
    _test_write(root / "docs" / "git-config.md", "# how we configure git\n")
    return root


@pytest.fixture(name="worktree")
def _worktree(repo, tmp_path):  # pylint: disable=unused-argument
    """The linked worktree the `repo` fixture created; its `.git` is a pointer FILE."""
    return tmp_path / "wt"


@pytest.fixture(name="bare")
def _bare(tmp_path):
    """A real bare repo: HEAD/objects/refs with no `.git` component anywhere in the path."""
    path = tmp_path / "bare.git"
    path.mkdir()
    _git("init", "-q", "--bare", cwd=path)
    return path


def _edit(path, tool="Edit", cwd=None):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": {key: str(path)}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def _bash(command, cwd=None, tool="Bash"):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def _decision(guard, payload, capsys):
    """The guard's printed hook output as a dict, or None when it said nothing."""
    assert guard.decide(payload) == 0, "a PreToolUse gate must always exit 0"
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def _deny_reason(guard, payload, capsys) -> str:
    decision = _decision(guard, payload, capsys)
    assert decision is not None, "the guard allowed a hand write into a git dir"
    hook_output = decision["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert hook_output["permissionDecision"] == "deny"
    return hook_output["permissionDecisionReason"]


def _allowed(guard, payload, capsys, why):
    assert _decision(guard, payload, capsys) is None, why


# --------------------------------------------------------------------------------------------
# Edit-tool side (E1-E17)
# --------------------------------------------------------------------------------------------

def test_e1_editing_the_repo_git_config_is_refused_and_names_the_repair(guard, repo, capsys):
    """E1 — the incident itself, and A7: the refusal must name git's own writers."""
    reason = _deny_reason(guard, _edit(repo / ".git" / "config"), capsys)

    assert "git config" in reason
    assert "git remote" in reason
    assert "git config --unset" in reason
    assert OVERRIDE_ENV in reason


def test_e2_writing_git_head_is_refused(guard, repo, capsys):
    """E2 — the rule is the git dir, not the file called `config`."""
    _deny_reason(guard, _edit(repo / ".git" / "HEAD", tool="Write"), capsys)


def test_e3_writing_a_linked_worktrees_git_pointer_file_is_refused(guard, worktree, capsys):
    """E3 — `<wt>/.git` is a FILE holding `gitdir: ...`; truncating it detaches the worktree."""
    pointer = worktree / ".git"
    assert pointer.is_file(), "fixture no longer produces a pointer file — the row is moot"
    assert pointer.read_text(encoding="utf-8").startswith("gitdir:")

    _deny_reason(guard, _edit(pointer, tool="Write"), capsys)


def test_e4_editing_a_per_worktree_config_is_refused(guard, repo, capsys):
    """E4 — `.git/worktrees/<name>/` holds the linked worktree's HEAD and gitdir pointer."""
    _deny_reason(guard, _edit(repo / ".git" / "worktrees" / "lane" / "config"), capsys)


def test_e5_editing_a_submodule_config_is_refused(guard, repo, capsys):
    """E5 — `.git/modules/<sub>/config` is the submodule's real git dir."""
    _deny_reason(guard, _edit(repo / ".git" / "modules" / "sub" / "config"), capsys)


def test_e6_editing_the_global_gitconfig_is_refused(guard, tmp_path, monkeypatch, capsys):
    """E6 — `~/.gitconfig` carries the identity and every url rewrite rule."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    _deny_reason(guard, _edit(home / ".gitconfig"), capsys)


def test_e7_editing_the_xdg_git_config_is_refused(guard, tmp_path, monkeypatch, capsys):
    """E7 — git reads `$XDG_CONFIG_HOME/git/config` when it is set."""
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    _deny_reason(guard, _edit(xdg / "git" / "config"), capsys)


def test_e8_editing_a_bare_repos_config_is_refused(guard, bare, capsys):
    """E8 — no path component is `.git`; only the structural probe (HEAD+objects+refs) sees it."""
    assert not any(part == ".git" for part in bare.parts), "fixture leaks a literal .git component"
    for marker in ("HEAD", "objects", "refs"):
        assert (bare / marker).exists(), f"fixture is not a git dir: no {marker}"

    _deny_reason(guard, _edit(bare / "config"), capsys)


def test_e9_a_relative_path_is_resolved_against_the_calls_cwd(guard, repo, bare, monkeypatch,
                                                              capsys):
    """E9 — the harness sends the tool call's cwd; a relative edit is not a different file.

    The row's own command cannot fail without cwd resolution: `.git/config` still carries a
    literal `.git` component when left relative. The discriminating case is a bare repo, where
    `config` is protected only once it is joined to the cwd — and the same case run through the
    process cwd covers the fallback the payload does not always carry.
    """
    _deny_reason(guard, _edit(".git/config", cwd=repo), capsys)

    _deny_reason(guard, _edit("config", cwd=bare), capsys)

    monkeypatch.chdir(bare)
    _deny_reason(guard, _edit("config"), capsys)


def test_e10_traversal_does_not_defeat_the_match(guard, repo, capsys):
    """E10 — `a/../.git/config` is `.git/config`.

    The row's own mutation (remove `normpath`) cannot make the DENY half fail: `..` only ever
    removes components, so a literal `.git` survives without normalising. The discriminating
    half is the companion ALLOW below — `.git/../notes.md` really is `<repo>/notes.md`, and
    without `normpath` the guard refuses an ordinary working-tree file.
    """
    _deny_reason(guard, _edit(repo / "a" / ".." / ".git" / "config"), capsys)

    _allowed(guard, _edit(repo / ".git" / ".." / "notes.md"), capsys,
             "a path that traverses back out of the git dir is an ordinary working-tree file")


@pytest.mark.parametrize("relative", [".gitignore", ".gitattributes",
                                      ".github/workflows/ci.yml", "docs/git-config.md"])
def test_e11_to_e13_near_miss_names_stay_editable(guard, repo, relative, capsys):
    """E11-E13 — every one of these contains the letters `git`; none is inside a git dir."""
    _allowed(guard, _edit(repo / relative), capsys,
             f"{relative} is a project file, not git's storage")


def test_e14_a_plain_file_named_config_stays_editable(guard, tmp_path, capsys):
    """E14 — with no git dir above it, `src/config` is just a file."""
    plain = tmp_path / "plain" / "src"
    plain.mkdir(parents=True)
    _test_write(plain / "config", "key = value\n")

    _allowed(guard, _edit(plain / "config"), capsys,
             "a file named `config` outside any git dir is not git's storage")


def test_e15_a_read_of_git_config_is_not_a_decision(guard, repo, capsys):
    """E15 — the gate is about writes; reading `.git/config` is how you diagnose the incident."""
    _allowed(guard, _edit(repo / ".git" / "config", tool="Read"), capsys,
             "Read is not an edit tool")


def test_e16_the_override_lets_a_human_through(guard, repo, monkeypatch, capsys):
    """E16 — set in the hook process's own environment, which an agent cannot reach."""
    monkeypatch.setenv(OVERRIDE_ENV, "1")

    _allowed(guard, _edit(repo / ".git" / "config"), capsys,
             "the human-only override did not disarm the gate")


def test_e17_a_payload_without_tool_input_makes_no_decision(guard, capsys):
    """E17 — A5: a PreToolUse hook that dies blocks the tool it gates."""
    _allowed(guard, {"hook_event_name": "PreToolUse", "tool_name": "Edit"}, capsys,
             "a malformed payload must fail open, not deny")


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_every_edit_shaped_tool_is_gated(guard, repo, tool, capsys):
    """A1 — MultiEdit and NotebookEdit write files exactly like Edit does."""
    _deny_reason(guard, _edit(repo / ".git" / "config", tool=tool), capsys)


# --------------------------------------------------------------------------------------------
# Bash side (B1-B21)
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "echo x > .git/config",             # B1 — the likeliest incident vector
    "echo x >> .git/config",
    "echo x >| .git/config",
    "printf x &> .git/config",
])
def test_b1_a_redirect_onto_a_git_dir_path_is_refused(guard, repo, command, capsys):
    """B1 — the shell does the write, whatever program sits in front of it."""
    _deny_reason(guard, _bash(command, cwd=repo), capsys)


def test_b2_a_heredoc_rewrite_is_refused(guard, repo, capsys):
    """B2 — the 296-byte truncation's actual shape: rewrite the whole file from a heredoc."""
    command = ("cat > .git/config <<'EOF'\n"
               "[core]\n\trepositoryformatversion = 0\n"
               "EOF\n")

    _deny_reason(guard, _bash(command, cwd=repo), capsys)


@pytest.mark.parametrize("command", [
    "sed -i '' s/a/b/ .git/config",                   # B3
    "sed -i.bak s/a/b/ .git/config",                  # B3, GNU spelling
    "perl -i -pe s/a/b/ .git/config",                 # B3
    "cat other | tee .git/config",                    # B4
    "truncate -s 0 .git/config",                      # B5
    "rm .git/config",                                 # B6
    "cp /tmp/x .git/config",                          # B7
    "mv x .git/config",                               # B8
    "dd if=/dev/null of=.git/config",
    "ln -sf /tmp/x .git/config",
    "touch .git/config",
    "chmod 000 .git/config",
    "chown me .git/config",
    "install -m 644 /tmp/x .git/config",
])
def test_b3_to_b8_a_mutating_program_with_a_git_dir_path_is_refused(guard, repo, command, capsys):
    """B3-B8 — in-place edit, pipe-to-file, truncation, deletion, copy and move."""
    _deny_reason(guard, _bash(command, cwd=repo), capsys)


def test_b6_a_recursive_delete_of_the_git_dir_is_refused(guard, repo, capsys):
    """B6 — deleting `.git` outright is the loudest version of the same loss."""
    _deny_reason(guard, _bash("rm -rf .git", cwd=repo), capsys)


@pytest.mark.parametrize("command", [
    "python3 -c \"open('.git/config','w').write('')\"",   # B9
    "python -c \"open('.git/config','w')\"",
    "node -e \"require('fs').writeFileSync('.git/config','')\"",
    "ruby -e \"File.write('.git/config','')\"",
])
def test_b9_an_interpreter_one_liner_naming_a_git_dir_path_is_refused(guard, repo, command,
                                                                      capsys):
    """B9 — the write hides inside the code string, where no argv path appears."""
    _deny_reason(guard, _bash(command, cwd=repo), capsys)


def test_b10_the_prescribed_repair_command_is_allowed(guard, repo, capsys):
    """B10 — `git config --unset` is exactly what the deny reason tells the agent to run.

    The row's command names no path at all, so no path-shaped mutation can make it fail. The
    companion below is the discriminating half: it is a legitimate git invocation that DOES
    carry a git-dir path, which is what a "path mentioned anywhere" rule would wrongly refuse.
    """
    _allowed(guard, _bash("git config --unset remote.origin.fetch", cwd=repo), capsys,
             "the guard blocked the repair route it recommends")

    _allowed(guard, _bash(f"git --git-dir={repo / '.git'} config --unset remote.origin.fetch",
                          cwd=repo), capsys,
             "git naming its own git dir is git writing it, not a hand edit")


def test_b11_git_remote_set_url_is_allowed(guard, repo, capsys):
    """B11 — the other half of the repair: git rewrites the remote section atomically."""
    _allowed(guard, _bash("git remote set-url origin https://example.invalid/x.git", cwd=repo),
             capsys, "the guard blocked a plain `git remote` call")


@pytest.mark.parametrize("command", [
    "git config --file .git/config --list",   # B12
    "cat .git/config",                        # B13
    "grep url .git/config",                   # B14
    "git show HEAD:.git/config",
    "less .git/config",
    "echo \"never edit .git/config\"",        # B15
    "echo 'the fix is: git config --unset remote.origin.fetch'",
])
def test_b12_to_b15_reads_and_mere_mentions_are_allowed(guard, repo, command, capsys):
    """B12-B15 — naming the path is not writing it; A3 allows `git ...` unconditionally."""
    _allowed(guard, _bash(command, cwd=repo), capsys,
             f"a read or a mention was refused: {command}")


def test_b16_a_later_segment_is_inspected_too(guard, repo, tmp_path, capsys):
    """B16 — the dangerous half of a `&&` chain is rarely the first one."""
    command = f"cd /tmp && sed -i '' s/a/b/ {repo / '.git' / 'config'}"

    _deny_reason(guard, _bash(command, cwd=tmp_path), capsys)


@pytest.mark.parametrize("command", [
    "cd .git && echo x > config",
    "cd .git; rm config",
    "cd .git && cd worktrees && truncate -s 0 config",
])
def test_b22_a_cd_into_the_git_dir_moves_where_a_later_write_lands(guard, repo, command, capsys):
    """Not in the pre-written list — found by probing the finished guard, and a likely accident.

    `cd .git && echo x > config` is the same hand write as B1 with the path split across two
    segments; resolving every relative path against the call's cwd alone missed all three.
    """
    _deny_reason(guard, _bash(command, cwd=repo), capsys)


def test_b22_a_cd_elsewhere_does_not_arm_the_gate(guard, repo, tmp_path, capsys):
    """The companion: tracking `cd` must not start denying ordinary writes outside a git dir."""
    _allowed(guard, _bash(f"cd {tmp_path} && echo x > config", cwd=repo), capsys,
             "a write to `config` outside any git dir is not git's storage")


def test_b17_a_nested_shell_does_not_evade_the_gate(guard, repo, capsys):
    """B17 — `bash -c` hides the redirect inside a single quoted token."""
    _deny_reason(guard, _bash("bash -c \"echo > .git/config\"", cwd=repo), capsys)

    _deny_reason(guard, _bash("sh -c 'sh -c \"echo > .git/config\"'", cwd=repo), capsys)


def test_b18_an_unlexable_command_makes_no_decision(guard, repo, capsys):
    """B18 — A5: a lexer error must not block every Bash call in the session."""
    _allowed(guard, _bash("echo 'unbalanced > .git/config", cwd=repo), capsys,
             "a command that does not lex must fail open")


def test_b19_an_oversized_command_makes_no_decision(guard, repo, capsys):
    """B19 — the lexer is superlinear; past the cap a payload-sized command outruns the timeout."""
    command = "echo " + ("x" * (guard.MAX_COMMAND + 1)) + " > .git/config"

    _allowed(guard, _bash(command, cwd=repo), capsys,
             "an oversized command must fail open rather than burn the hook timeout")


def test_b20_lefthook_install_is_allowed(guard, repo, capsys):
    """B20 — the one in-repo writer of `.git/hooks`, and it is not a hand edit."""
    _allowed(guard, _bash("lefthook install", cwd=repo), capsys,
             "`install` is a subcommand here, not the install(1) program")


def test_b21_a_non_bash_tool_carrying_a_command_makes_no_decision(guard, repo, capsys):
    """B21 — the Bash rule is scoped to the Bash tool."""
    _allowed(guard, _bash("echo x > .git/config", cwd=repo, tool="Read"), capsys,
             "the Bash rule leaked onto another tool")


def test_the_override_disarms_the_bash_side_too(guard, repo, monkeypatch, capsys):
    """A6 — one override, both halves of the gate."""
    monkeypatch.setenv(OVERRIDE_ENV, "1")

    _allowed(guard, _bash("echo x > .git/config", cwd=repo), capsys,
             "the override left the Bash half armed")


# --------------------------------------------------------------------------------------------
# Fail-open floor, end to end (A5)
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("stdin_text", ["", "not json at all", "[]", "null", '{"tool_name": 7}'])
def test_the_hook_process_exits_zero_on_any_garbage(stdin_text):
    """A5 — measured through the real entry point: a hook that dies blocks the tool it gates."""
    result = subprocess.run([sys.executable, str(GUARD_PATH)], input=stdin_text,
                            capture_output=True, text=True, check=False,
                            env={**os.environ, OVERRIDE_ENV: ""})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", "garbage in produced a decision out"


def test_the_structural_probe_stays_cheap(guard, tmp_path):
    """Abort criterion: rule 3 walks the filesystem, so it must not become the hook's cost.

    Every path here is a worst case for the probe — deep, outside any git dir, and carrying no
    `.git` component — so each of the 100 arguments pays the full bounded ancestor walk. This is
    a coarse ceiling, not a benchmark: measured at 0.04 ms for a typical command and a median
    35 ms for this synthetic one on a loaded machine, against a 400 ms/call bound here.
    """
    import time  # pylint: disable=import-outside-toplevel

    deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    command = " && ".join(f"cp {deep / f'src{i}.txt'} {deep / f'dst{i}.txt'}" for i in range(50))
    assert guard.find_violation(command, str(deep)) is None, "the fixture must not deny"

    start = time.perf_counter()
    for _ in range(5):
        guard.find_violation(command, str(deep))
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"5 passes over a 100-path command took {elapsed:.2f}s"
