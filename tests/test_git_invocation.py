"""Every git invocation goes through `badger_lib.run_git`, which strips git's own env vars.

`git commit` inside a worktree exports GIT_DIR (and an absolute GIT_INDEX_FILE) to every hook
it runs. A hook that then shells out with `git -C <subdir>` inherits them: git stops discovering
the repository from <subdir> and reads <subdir> as the work-tree root, so no `.gitignore` above
it is ever consulted. `sync_plugin_skills --check` reported four ignored `__pycache__` entries as
unshipped content under `git commit`, and none of them when the same command was run by hand.
"""
from __future__ import annotations

import ast
import os
import subprocess

CODE_ROOTS = ("engine", "tooling", "gates")

# The helper itself, and the one invocation that names no repository: cloning a release tag
# into a directory that is not a checkout yet.
EXEMPT = {("engine/badger_lib.py", "run_git"), ("engine/badger_lib.py", "_clone_pinned")}


def _git_calls(root, rel: str):
    """(enclosing function, node) for every `subprocess.run([...])` whose argv starts with git."""
    tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(parent):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if getattr(node.func, "attr", "") != "run":
                continue
            argv = node.args[0]
            if not isinstance(argv, ast.List) or not argv.elts:
                continue
            first = argv.elts[0]
            if isinstance(first, ast.Constant) and first.value == "git":
                yield parent.name, node


def test_no_shipped_script_invokes_git_outside_run_git(root):
    """A raw `subprocess.run(["git", ...])` inherits GIT_DIR and answers for another tree."""
    strays = []
    for code_root in CODE_ROOTS:
        for path in sorted((root / code_root).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            for func, node in _git_calls(root, rel):
                if (rel, func) in EXEMPT:
                    continue
                strays.append(f"{rel}:{node.lineno} in {func}()")
    assert not strays, "git invoked outside badger_lib.run_git:\n  " + "\n  ".join(strays)


def test_run_git_drops_the_variables_that_pin_git_to_another_repository(load_script, root):
    bl = load_script("engine/badger_lib.py")
    env = bl.git_env({"GIT_DIR": "/elsewhere/.git", "GIT_INDEX_FILE": "/elsewhere/.git/index",
                      "PATH": os.environ.get("PATH", "")})
    assert "GIT_DIR" not in env and "GIT_INDEX_FILE" not in env
    assert env["PATH"] == os.environ.get("PATH", "")


def test_run_git_answers_for_the_directory_it_was_given_not_the_exported_one(
        tmp_path, load_script, monkeypatch
):
    """The failure in one line: with GIT_DIR exported, a subdirectory becomes its own root."""
    bl = load_script("engine/badger_lib.py")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    nested = tmp_path / "pkg" / "build"
    nested.mkdir(parents=True)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / ".git"))

    raw = subprocess.run(["git", "-C", str(tmp_path / "pkg"), "check-ignore", "build"],
                         capture_output=True, text=True, check=False)
    through_helper = bl.run_git(["check-ignore", "build"], tmp_path / "pkg")

    assert raw.returncode == 1, "the exported GIT_DIR is no longer what breaks discovery"
    assert through_helper.returncode == 0
    assert through_helper.stdout.strip() == "build"
