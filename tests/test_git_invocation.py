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

import pytest

CODE_ROOTS = ("engine", "tooling", "gates")

# The helper itself, and the one invocation that names no repository: cloning a release tag
# into a directory that is not a checkout yet.
EXEMPT = {("engine/badger_lib.py", "run_git"), ("engine/badger_lib.py", "_clone_pinned")}


# Every way stdlib subprocess starts a process. Matching only `run` let a `Popen(["git", ...])`
# through, and matching only `ast.List` let a tuple argv through — both inherit GIT_DIR exactly
# as a `run([...])` would, so a scanner that sees one shape and not the other reports a clean
# tree for the same defect written differently.
SPAWNERS = ("run", "call", "check_call", "check_output", "Popen")


def _git_calls(root, rel: str):
    """(enclosing function, node) for every subprocess spawn whose argv starts with git."""
    tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(parent):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if getattr(node.func, "attr", "") not in SPAWNERS:
                continue
            argv = node.args[0]
            if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
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
    """Every name in the tuple, not the two the first draft happened to spell.

    Naming two of nine let `GIT_WORK_TREE` — the variable that most directly overrides the
    work-tree root, and so the closest match to the failure in this module's docstring — be
    deleted from the tuple with these tests still green.
    """
    bl = load_script("engine/badger_lib.py")
    exported = {name: "/elsewhere" for name in bl.GIT_LOCATION_ENV}

    env = bl.git_env(dict(exported, PATH=os.environ.get("PATH", "")))

    assert bl.GIT_LOCATION_ENV, "the tuple is empty, so this proves nothing"
    assert "GIT_WORK_TREE" in bl.GIT_LOCATION_ENV, \
        "the work-tree override is the one this module exists for"
    assert [name for name in exported if name in env] == []
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


BYPASSES = {
    "run with a list": 'subprocess.run(["git", "-C", str(d), "status"], check=False)',
    "run with a tuple": 'subprocess.run(("git", "-C", str(d), "status"), check=False)',
    "Popen": 'subprocess.Popen(["git", "-C", str(d), "status"])',
    "check_output": 'subprocess.check_output(["git", "status"])',
}


@pytest.mark.parametrize("shape", sorted(BYPASSES), ids=sorted(BYPASSES))
def test_the_scanner_sees_every_spelling_of_a_raw_git_call(tmp_path, shape):
    """The scanner is the check; a spelling it cannot see is a stray it will never report.

    It matched `subprocess.run` with a list literal and nothing else, so the same defect
    written as a tuple argv or as `Popen` scanned clean — measured against a real stray file
    dropped into gates/, which the whole-tree test passed with.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(f"import subprocess\n\n\ndef stray(d):\n    {BYPASSES[shape]}\n",
                     encoding="utf-8")

    assert [name for name, _ in _git_calls(tmp_path, "probe.py")] == ["stray"]


def test_the_scanner_ignores_a_spawn_that_is_not_git(tmp_path):
    """Otherwise the whole-tree test above would fail on every subprocess in the repo."""
    probe = tmp_path / "probe.py"
    probe.write_text('import subprocess\n\n\ndef fine(d):\n'
                     '    subprocess.Popen(["python3", "-c", "pass"])\n', encoding="utf-8")

    assert list(_git_calls(tmp_path, "probe.py")) == []
