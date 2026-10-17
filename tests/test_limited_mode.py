"""Tests for limited_mode: hook replay and the CLAUDE.local.md block."""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "features" / "common" / "skills" / "task" / "scripts" / "limited_mode.py"
)
BEGIN = "<!-- BEGIN ai-badger limited mode -->"
END = "<!-- END ai-badger limited mode -->"

ECHO_CODE = (
    "import sys,os,json;"
    "d=sys.stdin.read();"
    "print(json.dumps({'hookSpecificOutput':{'additionalContext':"
    "'GOT '+d+' PD='+os.environ.get('CLAUDE_PROJECT_DIR','')}}))"
)


def echo_stdin_command():
    """Shell command that returns its own stdin and project dir as context."""
    return f"{sys.executable} -c \"{ECHO_CODE}\""


def say_context(text):
    """Shell command printing an additionalContext hook reply."""
    payload = json.dumps({"hookSpecificOutput": {"additionalContext": text}})
    return f"echo '{payload}'"


def say_block(text):
    """Shell command printing a Stop-hook block reply."""
    return f"echo '{json.dumps({'decision': 'block', 'reason': text})}'"


def write_hooks(root, session=(), stop=()):
    """Write a fake hooks.json under root and return its path."""
    folder = root / ".ai-badger" / "hooks"
    folder.mkdir(parents=True)
    spec = {"hooks": {
        "SessionStart": [{"matcher": "x", "hooks": [
            {"type": "command", "command": c} for c in session]}],
        "Stop": [{"hooks": [{"type": "command", "command": c} for c in stop]}],
    }}
    path = folder / "hooks.json"
    path.write_text(json.dumps(spec))
    return path


def run(tmp_path, *args, env_extra=None):
    """Run limited_mode.py in tmp_path with a sandboxed HOME."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID")}
    env["HOME"] = str(tmp_path / "home")
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
        cwd=tmp_path, env=env, check=False)


def test_default_runs_session_start_only(tmp_path):
    write_hooks(tmp_path, [say_context("START-A")], [say_block("STOP-A")])
    out = run(tmp_path, "checkin", "--root", str(tmp_path)).stdout
    assert "START-A" in out
    assert "STOP-A" not in out


def test_end_runs_stop_only(tmp_path):
    write_hooks(tmp_path, [say_context("START-A")], [say_block("STOP-A")])
    out = run(tmp_path, "checkin", "--end", "--root", str(tmp_path)).stdout
    assert "STOP-A" in out
    assert "START-A" not in out


def test_payload_carries_event_and_session(tmp_path):
    write_hooks(tmp_path, [echo_stdin_command()], [echo_stdin_command()])
    start = run(tmp_path, "checkin", "--session", "S1",
                "--root", str(tmp_path)).stdout
    assert '"hook_event_name": "SessionStart"' in start
    assert '"session_id": "S1"' in start
    end = run(tmp_path, "checkin", "--end", "--session", "S2",
              "--root", str(tmp_path)).stdout
    assert '"hook_event_name": "Stop"' in end
    assert '"session_id": "S2"' in end


def test_project_dir_env_is_root(tmp_path):
    write_hooks(tmp_path, [echo_stdin_command()])
    out = run(tmp_path, "checkin", "--root", str(tmp_path)).stdout
    assert f"PD={tmp_path}" in out


def test_failing_command_reported_and_later_runs(tmp_path):
    write_hooks(tmp_path, ["exit 3", say_context("AFTER-FAIL")])
    out = run(tmp_path, "checkin", "--root", str(tmp_path)).stdout
    assert "exit 3" in out
    assert "AFTER-FAIL" in out


def test_child_session_runs_nothing(tmp_path):
    marker = tmp_path / "ran"
    write_hooks(tmp_path, [f"touch {marker}"])
    res = run(tmp_path, "checkin", "--root", str(tmp_path),
              env_extra={"CLAUDE_CODE_CHILD_SESSION": "1"})
    assert res.returncode == 0
    assert not marker.exists()
    assert "subagent" in res.stdout.lower()


def test_on_twice_one_block(tmp_path):
    run(tmp_path, "on", "--root", str(tmp_path))
    run(tmp_path, "on", "--root", str(tmp_path))
    text = (tmp_path / "CLAUDE.local.md").read_text()
    assert text.count(BEGIN) == 1
    assert text.count(END) == 1


def test_off_keeps_user_text(tmp_path):
    (tmp_path / "CLAUDE.local.md").write_text("mine before\n")
    run(tmp_path, "on", "--root", str(tmp_path))
    run(tmp_path, "off", "--root", str(tmp_path))
    text = (tmp_path / "CLAUDE.local.md").read_text()
    assert "mine before" in text
    assert BEGIN not in text


def test_off_deletes_block_only_file(tmp_path):
    run(tmp_path, "on", "--root", str(tmp_path))
    run(tmp_path, "off", "--root", str(tmp_path))
    assert not (tmp_path / "CLAUDE.local.md").exists()


def test_off_without_file_is_noop(tmp_path):
    res = run(tmp_path, "off", "--root", str(tmp_path))
    assert res.returncode == 0
    assert not (tmp_path / "CLAUDE.local.md").exists()


def test_checkin_without_hooks_file_reports_and_exits_zero(tmp_path):
    result = run(tmp_path, "checkin", "--root", str(tmp_path))
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "no hooks.json" in result.stdout


def test_on_from_a_linked_worktree_writes_the_main_checkout(tmp_path):
    """Every worktree nests under the main checkout, so its CLAUDE.local.md reaches them all."""
    main = tmp_path / "main"
    main.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q", str(main)], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    linked = main / ".ai-badger" / "worktrees" / "lane"
    subprocess.run([*git, "-C", str(main), "worktree", "add", "-q", str(linked)], check=True)

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HOME"] = str(tmp_path / "home")
    subprocess.run([sys.executable, str(SCRIPT), "on"], cwd=linked, env=env, check=True,
                   capture_output=True)

    assert BEGIN in (main / "CLAUDE.local.md").read_text(encoding="utf-8")
    assert not (linked / "CLAUDE.local.md").exists()


def _git_repo(path, fetch_refspec):
    """A committed repo with an origin whose fetch refspec is present or unset."""
    def git(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("commit", "-q", "--allow-empty", "-m", "init")
    git("branch", "-M", "main")
    git("remote", "add", "origin", "https://example.com/repo.git")
    if not fetch_refspec:
        git("config", "--unset", "remote.origin.fetch")


def test_checkin_replays_the_scaffolded_git_config_health_hook(make_scaffolder, tmp_path,
                                                               monkeypatch):
    """End to end: a real scaffold's hooks.json and its real hook, broken repo vs healthy."""
    from scaffold_helpers import _config

    scratch = tmp_path / "gitcfg"
    scratch.mkdir()
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        (scratch / name).write_text("", encoding="utf-8")
        monkeypatch.setenv(name, str(scratch / name))
    target = make_scaffolder.target
    make_scaffolder(config=_config(agents=["claude"]), skills=["git-work"]).run(
        generated_at="2026-10-17T00:00:00Z")
    hooks = json.loads((target / ".ai-badger" / "hooks" / "hooks.json").read_text())
    assert any("git_config_health_hook.py" in h["command"]
               for e in hooks["hooks"]["SessionStart"] for h in e["hooks"])

    outputs = {}
    for healthy in (False, True):
        repo = tmp_path / f"repo-{healthy}"
        repo.mkdir()
        _git_repo(repo, fetch_refspec=healthy)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "checkin", "--root", str(target)],
            cwd=repo, capture_output=True, text=True, check=False,
            env={**{k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_CHILD_SESSION"},
                 "HOME": str(tmp_path / "home")})
        assert result.returncode == 0, result.stderr
        outputs[healthy] = result.stdout

    assert "remote.origin.fetch is unset" in outputs[False]
    assert "remote.origin.fetch is unset" not in outputs[True]
