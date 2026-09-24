"""Tests for gates/tdd_guard.py: shipped-code change without a test change.

"TDD is mandatory" is the only non-negotiable invariant with no mechanical backing, while
its siblings have release_guard, version_sync --check and index_build --check (review F-41).
This gate is a signal, not a proof: it cannot tell a real test from an empty one, so it
checks the one thing a machine can — that the change touched tests at all.
"""
from __future__ import annotations

import subprocess
from conftest import _test_write


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                           capture_output=True, text=True).stdout


def _repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "engine").mkdir()
    (tmp_path / "features").mkdir()
    (tmp_path / "tests").mkdir()
    _test_write(tmp_path / "README.md", "start\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _commit(repo, files, message="change"):
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        _test_write(path, text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_code_change_without_a_test_change_fails(tmp_path, load_script, capsys):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"engine/thing.py": "x = 1\n"})

    rc = guard.main(["--root", str(repo), "--base", "main~1"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "engine/thing.py" in out


def test_code_change_with_a_test_change_passes(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"engine/thing.py": "x = 1\n", "tests/test_thing.py": "def test_x(): pass\n"})

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 0


def test_documentation_only_change_passes(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"features/common/skills/task/SKILL.md": "# task\n", "README.md": "docs\n"})

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 0


def test_catalog_json_change_without_tests_passes(tmp_path, load_script):
    """Catalog data is covered by validate.py --all, not by unit tests."""
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"features/python/stack.json": "{}\n"})

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 0


def test_javascript_change_without_tests_fails(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"features/common/skills/x/scripts/tool.mjs": "export const a = 1;\n"})

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 1


def test_js_change_with_a_js_test_passes(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {
        "features/common/skills/x/scripts/tool.mjs": "export const a = 1;\n",
        "tests/js/tool.test.mjs": "// covered\n",
    })

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 0


def test_an_explicit_marker_in_the_commit_message_is_honoured(tmp_path, load_script, capsys):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"engine/thing.py": "x = 1\n"}, message="mechanical rename [no-tests]")

    rc = guard.main(["--root", str(repo), "--base", "main~1"])

    assert rc == 0
    assert "[no-tests]" in capsys.readouterr().out


def test_no_changes_at_all_passes(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)

    assert guard.main(["--root", str(repo), "--base", "main"]) == 0


def test_a_missing_base_ref_is_reported_not_silently_passed(tmp_path, load_script, capsys):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)

    rc = guard.main(["--root", str(repo), "--base", "origin/does-not-exist"])

    assert rc == 1
    assert "does-not-exist" in capsys.readouterr().out


def test_a_new_untracked_code_file_counts_as_a_change(tmp_path, load_script, capsys):
    """`git diff` does not list untracked files; a brand-new script must still count."""
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _test_write(repo / "engine" / "brand_new.py", "x = 1\n", encoding="utf-8")

    rc = guard.main(["--root", str(repo), "--base", "main"])

    assert rc == 1
    assert "engine/brand_new.py" in capsys.readouterr().out


def test_a_new_untracked_test_file_satisfies_the_gate(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _test_write(repo / "engine" / "brand_new.py", "x = 1\n", encoding="utf-8")
    _test_write(repo / "tests" / "test_brand_new.py", "def test_x(): pass\n", encoding="utf-8")

    assert guard.main(["--root", str(repo), "--base", "main"]) == 0


# ── merge-base fix (L8-2): the base ref can move ahead of the branch point ──────────────


def test_moved_main_with_its_own_test_change_no_longer_hides_a_missing_test(
    tmp_path, load_script,
):
    """main *modified* a shared test after the branch point; the branch changed only code.

    A modification, not an add or a delete, so `--diff-filter=AMR` alone cannot exclude it —
    only comparing against `git merge-base main HEAD` (rather than main's moved tip directly)
    isolates what the branch itself did: diffed against the merge-base, the shared test is
    identical to the branch's copy, so the guard correctly sees a code-only change.
    """
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"tests/test_shared.py": "def test_x(): pass\n"}, message="seed a shared test")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, {"engine/thing.py": "x = 1\n"}, message="feature: code only")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"tests/test_shared.py": "def test_x(): pass\ndef test_y(): pass\n"},
            message="main moves on, unrelated edit to the shared test")
    _git(repo, "checkout", "-q", "feature")

    rc = guard.main(["--root", str(repo), "--base", "main"])

    assert rc == 1


def test_merge_base_helper_finds_the_common_ancestor(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    base_sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, {"engine/thing.py": "x = 1\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"tests/test_unrelated.py": "def test_x(): pass\n"})
    _git(repo, "checkout", "-q", "feature")

    assert guard.merge_base(repo, "main") == base_sha


# ── --diff-filter=AMR (R43): a delete does not count, a rename-and-edit does ────────────


def test_deleting_a_test_alongside_a_code_change_still_fails(tmp_path, load_script, capsys):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"tests/test_old.py": "def test_x(): pass\n"}, message="seed a test")

    (repo / "tests" / "test_old.py").unlink()
    _commit(repo, {"engine/thing.py": "x = 1\n"}, message="delete the test, add code")

    rc = guard.main(["--root", str(repo), "--base", "main~1"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "engine/thing.py" in out


def test_a_renamed_and_edited_test_alongside_a_code_change_passes(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"tests/test_old.py": "def test_x(): pass\n"}, message="seed a test")

    _git(repo, "mv", "tests/test_old.py", "tests/test_renamed.py")
    _test_write(repo / "tests" / "test_renamed.py", "def test_x(): pass\ndef test_y(): pass\n",
                encoding="utf-8")
    _test_write(repo / "engine" / "thing.py", "x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "rename + edit the test, add code")

    rc = guard.main(["--root", str(repo), "--base", "main~1"])

    assert rc == 0


# ── D6: shipped pi TypeScript is code, features/pi/tests/*.test.ts is a test ────────────


def test_pi_adapter_ts_change_without_a_pi_test_fails(tmp_path, load_script, capsys):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"features/pi/adjustments/adapter/index.ts": "export const a = 1;\n"})

    rc = guard.main(["--root", str(repo), "--base", "main~1"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "features/pi/adjustments/adapter/index.ts" in out


def test_pi_adapter_ts_change_with_a_pi_test_ts_passes(tmp_path, load_script):
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {
        "features/pi/adjustments/adapter/index.ts": "export const a = 1;\n",
        "features/pi/tests/adapter-entry.test.ts": "// covered\n",
    })

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 0


def test_non_pi_ts_is_not_treated_as_shipped_code(tmp_path, load_script):
    """Scope is deliberately `features/pi/adjustments/`, not every `.ts` in the repo."""
    guard = load_script("gates/tdd_guard.py")
    repo = _repo(tmp_path)
    _commit(repo, {"features/pi/instructions/notes.ts": "export const a = 1;\n"})

    assert guard.main(["--root", str(repo), "--base", "main~1"]) == 0
