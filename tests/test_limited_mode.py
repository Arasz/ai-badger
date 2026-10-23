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
           if k not in ("CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID")
           and not k.startswith("GIT_")}
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_CODE_SESSION_ID"] = "S-DEFAULT"
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
    assert '"source": "resume"' in end


def test_project_dir_env_is_root(tmp_path):
    write_hooks(tmp_path, [echo_stdin_command()])
    out = run(tmp_path, "checkin", "--root", str(tmp_path)).stdout
    assert f"PD={tmp_path}" in out


def test_failing_command_reported_and_later_runs(tmp_path):
    write_hooks(tmp_path, ["echo BOOM-ERR >&2; exit 3", say_context("AFTER-FAIL")])
    res = run(tmp_path, "checkin", "--root", str(tmp_path))
    assert res.returncode == 1
    assert "exit 3" in res.stderr
    assert "BOOM-ERR" in res.stderr
    assert "AFTER-FAIL" in res.stdout


def test_explicit_subagent_runs_nothing(tmp_path):
    marker = tmp_path / "ran"
    write_hooks(tmp_path, [f"touch {marker}"])
    res = run(tmp_path, "checkin", "--subagent", "--root", str(tmp_path))
    assert res.returncode == 0
    assert not marker.exists()
    assert "NOT checked in" in res.stderr


def test_inherited_child_session_marker_does_not_skip_top_level_checkin(tmp_path):
    marker = tmp_path / "ran"
    write_hooks(tmp_path, [f"touch {marker}"])
    res = run(tmp_path, "checkin", "--root", str(tmp_path),
              env_extra={"CLAUDE_CODE_CHILD_SESSION": "1"})
    assert res.returncode == 0
    assert marker.exists()


def test_windows_hook_command_uses_configured_git_bash():
    import importlib.util
    spec = importlib.util.spec_from_file_location("limited_mode_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = 'if [ -f "${CLAUDE_PROJECT_DIR}/marker" ]; then echo ok; fi'
    args, shell = module.command_invocation(
        command, windows=True,
        env={"CLAUDE_CODE_GIT_BASH_PATH": r"C:\Program Files\Git\bin\bash.exe"})
    assert args == [r"C:\Program Files\Git\bin\bash.exe", "-c", command]
    assert shell is False


def test_run_command_passes_windows_invocation_without_shell(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("limited_mode_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = 'if [ -f "${CLAUDE_PROJECT_DIR}/marker" ]; then echo ok; fi'
    calls = {}

    def fake_run(invocation, **kwargs):
        calls["invocation"] = invocation
        calls["shell"] = kwargs["shell"]
        return subprocess.CompletedProcess(invocation, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "command_invocation",
                        lambda value, env=None: (["bash", "-c", value], False))
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.run_command(command, "payload", tmp_path, {})
    assert calls == {"invocation": ["bash", "-c", command], "shell": False}


def test_on_twice_one_block(tmp_path):
    run(tmp_path, "on", "--root", str(tmp_path))
    run(tmp_path, "on", "--root", str(tmp_path))
    text = (tmp_path / "CLAUDE.local.md").read_text()
    assert text.count(BEGIN) == 1
    assert text.count(END) == 1


def test_user_text_before_and_after_the_block_survives_on_and_off(tmp_path):
    local = tmp_path / "CLAUDE.local.md"
    local.write_text("mine before\n")
    run(tmp_path, "on", "--root", str(tmp_path))
    local.write_text(local.read_text() + "mine after\n")
    for verb, blocks in (("on", 1), ("off", 0)):
        run(tmp_path, verb, "--root", str(tmp_path))
        text = local.read_text()
        assert "mine before" in text and "mine after" in text, verb
        assert text.count(BEGIN) == blocks, verb


def test_off_deletes_block_only_file(tmp_path):
    run(tmp_path, "on", "--root", str(tmp_path))
    run(tmp_path, "off", "--root", str(tmp_path))
    assert not (tmp_path / "CLAUDE.local.md").exists()


def test_off_without_file_is_noop(tmp_path):
    res = run(tmp_path, "off", "--root", str(tmp_path))
    assert res.returncode == 0
    assert not (tmp_path / "CLAUDE.local.md").exists()


def test_checkin_without_hooks_file_is_reported(tmp_path):
    result = run(tmp_path, "checkin", "--root", str(tmp_path))
    assert result.returncode == 1
    assert "no hooks.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_on_from_a_linked_worktree_writes_the_main_checkout(tmp_path):
    """Every worktree nests under the main checkout, so its CLAUDE.local.md reaches them all."""
    main = tmp_path / "main"
    main.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        (tmp_path / name).write_text("", encoding="utf-8")
    git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    git_env.update({n: str(tmp_path / n) for n in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")})
    git_run = lambda *a: subprocess.run(a, check=True, env=git_env, capture_output=True)  # noqa: E731
    git_run(*git, "init", "-q", str(main))
    git_run(*git, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "x")
    linked = main / ".ai-badger" / "worktrees" / "lane"
    git_run(*git, "-C", str(main), "worktree", "add", "-q", str(linked))

    env = dict(git_env, HOME=str(tmp_path / "home"))
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
            env={**{k: v for k, v in os.environ.items()
                    if k != "CLAUDE_CODE_CHILD_SESSION" and not k.startswith("GIT_CONFIG_")
                    and k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")},
                 "GIT_CONFIG_GLOBAL": os.environ["GIT_CONFIG_GLOBAL"],
                 "GIT_CONFIG_SYSTEM": os.environ["GIT_CONFIG_SYSTEM"],
                 "HOME": str(tmp_path / "home"), "CLAUDE_CODE_SESSION_ID": "S-E2E"})
        assert result.returncode == 0, result.stderr
        outputs[healthy] = result.stdout

    assert "remote.origin.fetch is unset" in outputs[False]
    assert "remote.origin.fetch is unset" not in outputs[True]


def test_system_message_plain_text_and_unknown_json_are_printed(tmp_path):
    payload = json.dumps({"systemMessage": "SYS-X"})
    write_hooks(tmp_path, [f"echo '{payload}'", "echo PLAIN-X", "echo '[1]'",
                           "echo '{\"other\": \"OTHER-X\"}'"])
    out = run(tmp_path, "checkin", "--root", str(tmp_path)).stdout
    lines = out.splitlines()
    assert "SYS-X" in lines, "systemMessage must print as its own text, not as raw JSON"
    for text in ("PLAIN-X", "[1]", "OTHER-X"):
        assert text in out


def test_a_stop_block_is_labelled_as_a_block(tmp_path):
    write_hooks(tmp_path, stop=[say_block("FINISH-IT")])
    out = run(tmp_path, "checkin", "--end", "--root", str(tmp_path)).stdout
    assert "BLOCK: FINISH-IT" in out


def test_session_id_comes_from_env_and_the_flag_wins(tmp_path):
    write_hooks(tmp_path, [echo_stdin_command()])
    from_env = run(tmp_path, "checkin", "--root", str(tmp_path),
                   env_extra={"CLAUDE_CODE_SESSION_ID": "ENV-S"}).stdout
    assert '"session_id": "ENV-S"' in from_env
    flagged = run(tmp_path, "checkin", "--session", "FLAG-S", "--root", str(tmp_path),
                  env_extra={"CLAUDE_CODE_SESSION_ID": "ENV-S"}).stdout
    assert '"session_id": "FLAG-S"' in flagged


def test_empty_session_id_is_refused(tmp_path):
    marker = tmp_path / "ran"
    write_hooks(tmp_path, [f"touch {marker}"])
    res = run(tmp_path, "checkin", "--root", str(tmp_path),
              env_extra={"CLAUDE_CODE_SESSION_ID": ""})
    assert res.returncode == 1
    assert "session id" in res.stderr
    assert not marker.exists()


def test_transcript_path_is_found_by_session_id(tmp_path):
    projects = tmp_path / "home" / ".claude" / "projects" / "-launch-dir"
    projects.mkdir(parents=True)
    (projects / "S9.jsonl").write_text("")
    write_hooks(tmp_path, [echo_stdin_command()])
    out = run(tmp_path, "checkin", "--session", "S9", "--root", str(tmp_path)).stdout
    assert json.dumps(str(projects / "S9.jsonl")) in out


def test_transcript_path_falls_back_to_the_cwd_slug(tmp_path):
    write_hooks(tmp_path, [echo_stdin_command()])
    out = run(tmp_path, "checkin", "--session", "S8", "--root", str(tmp_path)).stdout
    slug = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
    expected = tmp_path / "home" / ".claude" / "projects" / slug / "S8.jsonl"
    assert json.dumps(str(expected)) in out


def test_malformed_hooks_json_is_reported(tmp_path):
    folder = tmp_path / ".ai-badger" / "hooks"
    folder.mkdir(parents=True)
    for body in ("{not json", '{"hooks": []}', '{"hooks": {"SessionStart": ["x"]}}'):
        (folder / "hooks.json").write_text(body)
        res = run(tmp_path, "checkin", "--root", str(tmp_path))
        assert res.returncode == 2, body
        assert "malformed" in res.stderr and "Traceback" not in res.stderr, body


def test_no_commands_for_the_event_is_reported(tmp_path):
    write_hooks(tmp_path, stop=[say_block("x")])
    res = run(tmp_path, "checkin", "--root", str(tmp_path))
    assert res.returncode == 1
    assert "no SessionStart hooks" in res.stderr


def test_a_timed_out_command_is_reported_and_later_commands_run(tmp_path, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("limited_mode_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 1)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "S-T")
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    write_hooks(tmp_path, ["sleep 5", say_context("AFTER-SLOW")])
    rc = module.main(["checkin", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "timed out" in captured.err
    assert "AFTER-SLOW" in captured.out


def test_unbalanced_markers_are_refused_not_rewritten(tmp_path):
    local = tmp_path / "CLAUDE.local.md"
    for body in (f"{BEGIN}\nmine\n", f"{END}\nmine\n{BEGIN}\nx\n{END}\n{BEGIN}\n"):
        local.write_text(body)
        for verb in ("on", "off"):
            res = run(tmp_path, verb, "--root", str(tmp_path))
            assert res.returncode == 1, (verb, body)
            assert "marker" in res.stderr, (verb, body)
            assert local.read_text() == body, (verb, body)


def test_a_separate_git_dir_resolves_to_the_work_tree(tmp_path):
    work, gitdir = tmp_path / "work", tmp_path / "store.git"
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        (tmp_path / name).write_text("", encoding="utf-8")
        env[name] = str(tmp_path / name)
    subprocess.run(["git", "init", "-q", "--separate-git-dir", str(gitdir), str(work)],
                   check=True, env=env, capture_output=True)
    env["HOME"] = str(tmp_path / "home")
    subprocess.run([sys.executable, str(SCRIPT), "on"], cwd=work, env=env, check=True,
                   capture_output=True)
    assert (work / "CLAUDE.local.md").exists()
    assert not (tmp_path / "CLAUDE.local.md").exists()
