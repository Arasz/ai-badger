"""Tests for gates/shipped_paths_guard.py: no machine-specific path in a shipped file.

`.claude-plugin/plugin.json` carries no file allowlist, so every tracked file ships in the
plugin payload (issue #173). `.mcp.json` shipped a `cwd` and a hand-added server command that
only resolved on the maintainer's machine, and nothing inspected the payload for content that
only makes sense there. The guard walks `git ls-files` and fails on a real `/Users/`, `/home/`
or `C:\\Users\\` path, while staying quiet in `docs/`, root `*.md` and `tests/` — where such a
path is either a documented incident or a fabricated test fixture, never a shipped default.
"""
from __future__ import annotations

import subprocess

import pytest


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                           capture_output=True, text=True).stdout


def _init_repo(path):
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


def _track(repo, relpath, text):
    """Write *text* to *relpath* and stage it — `git ls-files` needs no commit."""
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    return path


@pytest.fixture(name="guard")
def _guard(load_script):
    return load_script("gates/shipped_paths_guard.py")


def test_a_clean_tree_passes(tmp_path, guard, capsys):
    repo = _init_repo(tmp_path)
    _track(repo, "features/common/thing.json", '{"cwd": "${CLAUDE_PROJECT_DIR}"}\n')

    rc = guard.main(["--root", str(repo)])

    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_an_absolute_users_path_in_a_shipped_config_file_fails(tmp_path, guard, capsys):
    repo = _init_repo(tmp_path)
    _track(repo, ".mcp.json", '{"mcpServers": {"hermes": {"command": "/Users/arasz/.local/bin/hermes"}}}\n')

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert ".mcp.json:1" in out
    assert "/Users/arasz" in out


def test_a_home_path_in_a_shipped_hook_script_fails(tmp_path, guard, capsys):
    repo = _init_repo(tmp_path)
    _track(repo, "features/common/hooks/run.sh", 'python3 "/home/rafal/ai-badger/hook.py"\n')

    rc = guard.main(["--root", str(repo)])

    assert rc == 1
    assert "/home/rafal" in capsys.readouterr().out


def test_a_windows_users_path_fails(tmp_path, guard, capsys):
    repo = _init_repo(tmp_path)
    _track(repo, ".claude/settings.json", '{"cmd": "C:\\\\Users\\\\rafal\\\\tool.exe"}\n')

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "rafal" in out and "Users" in out


def test_a_backup_file_with_a_real_path_fails(tmp_path, guard, capsys):
    """The exact shape found in the repo: a stray `.bak-<ts>` carrying a real absolute path."""
    repo = _init_repo(tmp_path)
    _track(repo, ".claude/settings.json.bak-20260727-162318",
           '{"command": "python3 \\"/Users/arasz/RiderProjects/ai-badger/hook.py\\""}\n')

    rc = guard.main(["--root", str(repo)])

    assert rc == 1
    assert ".claude/settings.json.bak-20260727-162318" in capsys.readouterr().out


# ── false-positive handling ──────────────────────────────────────────────────

def test_a_changelog_entry_quoting_a_real_leaked_path_is_exempt(tmp_path, guard, capsys):
    """docs/ is a record: this repo's own changelog quotes a real leaked path as history."""
    repo = _init_repo(tmp_path)
    _track(repo, "docs/changelog/0.22.0-portability-and-truth.md",
           "the statusline leaked `/Users/arasz/.claude/statusline.sh`\n")

    rc = guard.main(["--root", str(repo)])

    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_a_root_markdown_file_quoting_a_path_is_exempt(tmp_path, guard, capsys):
    repo = _init_repo(tmp_path)
    _track(repo, "CONTRIBUTING.md", "e.g. a checkout at `/Users/someone/ai-badger`\n")

    rc = guard.main(["--root", str(repo)])

    assert rc == 0


def test_a_test_fixture_with_a_fabricated_path_is_exempt(tmp_path, guard, capsys):
    """tests/ fabricates `/Users/foo/...` on purpose to exercise path-handling code."""
    repo = _init_repo(tmp_path)
    _track(repo, "tests/test_something.py", 'assert cmd == "/Users/foo/.venv/bin/python"\n')

    rc = guard.main(["--root", str(repo)])

    assert rc == 0


def test_an_ellipsis_placeholder_does_not_match_the_pattern(tmp_path, guard, capsys):
    """A doc illustrating a path shape with `…` is not a real path, even outside docs/tests/."""
    repo = _init_repo(tmp_path)
    _track(repo, "features/common/skills/task/references/file-schemas.md",
           '"transcriptPath": "/Users/…/.claude/projects/…/9fce6c84-….jsonl"\n')

    rc = guard.main(["--root", str(repo)])

    assert rc == 0


def test_the_ignore_file_exempts_a_named_prefix(tmp_path, guard, capsys):
    repo = _init_repo(tmp_path)
    _track(repo, "features/vendor/pinned.json", '{"cwd": "/Users/arasz/vendor"}\n')
    _track(repo, ".shipped-paths-guard-ignore", "features/vendor/\n")

    rc = guard.main(["--root", str(repo)])

    assert rc == 0


def test_the_real_repository_passes(root, guard, capsys):
    """If this fails, something in the tree leaked a real machine path — untrack it, don't relax the gate."""
    rc = guard.main(["--root", str(root)])

    assert rc == 0, capsys.readouterr().out
