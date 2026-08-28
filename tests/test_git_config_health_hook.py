"""Tests for git_config_health_hook.py (test-list.md rows H1-H7 + a detached-HEAD row).

Builds real git repos under tmp_path (git init, a real remote URL, a real linked worktree)
rather than mocking subprocess -- the hook's whole job is reading real git state, matching the
convention in tests/test_release_guard.py. GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM are pointed at
scratch files (on top of the session-wide $HOME redirect in conftest.py) so a developer's real
~/.gitconfig can never leak into a result.
"""
from __future__ import annotations

import io
import json
import subprocess

import pytest


@pytest.fixture(autouse=True)
def _isolated_git_config(tmp_path_factory, monkeypatch):
    scratch = tmp_path_factory.mktemp("gitconfig")
    global_cfg = scratch / "gitconfig-global"
    system_cfg = scratch / "gitconfig-system"
    global_cfg.write_text("", encoding="utf-8")
    system_cfg.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(system_cfg))


@pytest.fixture()
def hook(load_script):
    return load_script("features/common/skills/git-work/scripts/git_config_health_hook.py")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                           capture_output=True, text=True).stdout


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "f.txt").write_text("hi\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    _git(path, "branch", "-M", "main")
    return path


def _add_origin(repo, url="https://example.com/repo.git"):
    """`git remote add` sets remote.origin.fetch by default -- callers that want it absent
    must unset it afterward, reproducing the truncated-config incident exactly."""
    _git(repo, "remote", "add", "origin", url)


def _unset_fetch_refspec(repo):
    _git(repo, "config", "--unset", "remote.origin.fetch")


def _set_upstream(repo, branch="main"):
    _git(repo, "config", f"branch.{branch}.remote", "origin")
    _git(repo, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")


# --- H1: origin present, fetch refspec absent -> warning naming the repair ---

def test_h1_warns_with_repair_command_when_fetch_refspec_is_unset(tmp_path, hook):
    repo = _init_repo(tmp_path)
    _add_origin(repo)
    _unset_fetch_refspec(repo)
    _set_upstream(repo)  # keep B2 healthy so this test isolates B1

    notice = hook.config_health_notice(str(repo))

    assert notice is not None
    assert "remote.origin.fetch" in notice
    assert "git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'" in notice
    assert "git fetch origin" in notice
    assert "branch." not in notice  # B2 must not fire alongside a healthy upstream


# --- H2: origin present, refspec present -> SILENT ---

def test_h2_silent_when_origin_and_fetch_refspec_and_upstream_are_healthy(tmp_path, hook):
    repo = _init_repo(tmp_path)
    _add_origin(repo)  # leaves the default fetch refspec in place
    _set_upstream(repo)

    notice = hook.config_health_notice(str(repo))

    assert notice is None


# --- H3: origin present, branch.<cur>.merge absent -> warning ---

def test_h3_warns_with_repair_command_when_branch_merge_is_unset(tmp_path, hook):
    repo = _init_repo(tmp_path)
    _add_origin(repo)  # fetch refspec stays healthy so this test isolates B2

    notice = hook.config_health_notice(str(repo))

    assert notice is not None
    assert "branch.main.merge" in notice
    assert "git branch --set-upstream-to=origin/main" in notice
    assert "remote.origin.fetch" not in notice  # B1 must not fire alongside a healthy refspec


def test_h3_and_h1_can_both_fire_as_one_notice(tmp_path, hook):
    """Property intersection: both symptoms present at once must stay ONE combined notice."""
    repo = _init_repo(tmp_path)
    _add_origin(repo)
    _unset_fetch_refspec(repo)
    # branch.main.merge is left unset too -- both symptoms present

    notice = hook.config_health_notice(str(repo))

    assert notice is not None
    assert notice.count("git config health:") == 1  # one notice, not two
    assert "remote.origin.fetch" in notice
    assert "branch.main.merge" in notice
    # the two findings must stay visibly separate, not run together into one sentence
    assert "git fetch origin | branch.main.merge" in notice


# --- H4: no remote at all (fresh local repo) -> SILENT ---

def test_h4_silent_when_repo_has_no_remote_at_all(tmp_path, hook):
    repo = _init_repo(tmp_path)  # no `git remote add` at all

    notice = hook.config_health_notice(str(repo))

    assert notice is None


# --- H5: cwd is not a git repo -> SILENT, exit 0 ---

def test_h5_silent_when_cwd_is_not_a_git_repo(tmp_path, hook):
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()

    notice = hook.config_health_notice(str(plain_dir))

    assert notice is None


def test_h5_main_exits_zero_and_prints_nothing_outside_a_repo(tmp_path, hook, monkeypatch,
                                                                capsys):
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(plain_dir))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(plain_dir)})))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


# --- H6: git binary unavailable -> SILENT, exit 0 ---

def test_h6_silent_when_git_binary_is_unavailable(tmp_path, hook, monkeypatch):
    repo = _init_repo(tmp_path)
    _add_origin(repo)
    _unset_fetch_refspec(repo)  # would otherwise warn -- proves this is silenced by no-git,
    # not by an accidentally-healthy repo
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    notice = hook.config_health_notice(str(repo))

    assert notice is None


# --- H7: run inside a linked worktree -> correct verdict ---

def test_h7_correct_verdict_inside_a_linked_worktree(tmp_path, hook):
    main_repo = _init_repo(tmp_path / "main")
    _add_origin(main_repo)
    _unset_fetch_refspec(main_repo)  # B1 broken -- shared, visible from any worktree
    worktree = tmp_path / "wt"
    _git(main_repo, "worktree", "add", "-q", str(worktree), "-b", "feature")
    # branch.feature.merge is left unset -- B2 broken too, and must name "feature", not "main"

    notice = hook.config_health_notice(str(worktree))

    assert notice is not None
    assert "remote.origin.fetch" in notice  # config read via --git-common-dir resolves
    assert "branch.feature.merge" in notice  # branch read from the worktree's own HEAD
    assert "branch.main.merge" not in notice  # not the main checkout's branch


def test_h7_healthy_worktree_stays_silent(tmp_path, hook):
    """Same worktree shape as above, but every check healthy -- proves H7 isn't silent by
    accident (e.g. a crash swallowed into None)."""
    main_repo = _init_repo(tmp_path / "main")
    _add_origin(main_repo)
    worktree = tmp_path / "wt"
    _git(main_repo, "worktree", "add", "-q", str(worktree), "-b", "feature")
    _set_upstream(main_repo, "feature")

    notice = hook.config_health_notice(str(worktree))

    assert notice is None


# --- regression: main() must resolve cwd from the payload, not CLAUDE_PROJECT_DIR --
# --- CLAUDE_PROJECT_DIR names the MAIN checkout even in a linked-worktree session ---

def test_main_uses_payload_cwd_not_claude_project_dir_inside_a_worktree_session(
    tmp_path, hook, monkeypatch, capsys,
):
    """A real worktree session: CLAUDE_PROJECT_DIR (set by the harness) points at the main
    checkout, whose branch.main.merge is healthy; the payload cwd is the worktree, on a
    branch whose branch.feature.merge is missing. The notice must name the worktree's own
    branch -- naming main's would be the exact bug this hook exists to catch."""
    main_repo = _init_repo(tmp_path / "main")
    _add_origin(main_repo)
    _set_upstream(main_repo, "main")  # main's own branch is healthy
    worktree = tmp_path / "wt"
    _git(main_repo, "worktree", "add", "-q", str(worktree), "-b", "feature")
    # branch.feature.merge left unset -- the worktree's branch is the broken one

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(main_repo))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(worktree)})))

    rc = hook.main()

    out = capsys.readouterr().out
    assert rc == 0
    additional_context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "branch.feature.merge" in additional_context
    assert "branch.main.merge" not in additional_context


# --- B5: detached HEAD -> the branch.<name>.merge check is skipped, not crashed ---

def test_b5_detached_head_skips_branch_check_without_crashing(tmp_path, hook):
    repo = _init_repo(tmp_path)
    _add_origin(repo)
    _unset_fetch_refspec(repo)  # B1 stays broken -- proves detached HEAD didn't silence B1 too
    sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", sha)  # detached HEAD

    notice = hook.config_health_notice(str(repo))

    assert notice is not None
    assert "remote.origin.fetch" in notice
    assert "branch." not in notice  # the merge check never ran -- no crash, no false claim


# --- B3/B4/B1/B2 combined shape check on the real SessionStart contract ---

def test_main_emits_session_start_additional_context_shape(tmp_path, hook, monkeypatch,
                                                              capsys):
    repo = _init_repo(tmp_path)
    _add_origin(repo)
    _unset_fetch_refspec(repo)
    _set_upstream(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo)})))

    rc = hook.main()

    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "remote.origin.fetch" in payload["hookSpecificOutput"]["additionalContext"]


def test_main_exit_code_is_zero_on_malformed_stdin(hook, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_every_git_invocation_strips_git_location_env(hook):
    """git_env() must drop every variable that could redirect discovery to another repo --
    a worktree `git commit` exports GIT_DIR to hooks it runs (see test_git_invocation.py)."""
    poisoned = dict(GIT_DIR="/somewhere/else", GIT_WORK_TREE="/somewhere/else", PATH="/usr/bin")

    cleaned = hook.git_env(poisoned)

    for name in hook.GIT_LOCATION_ENV:
        assert name not in cleaned
    assert cleaned["PATH"] == "/usr/bin"
