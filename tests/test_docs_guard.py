"""Tests for gates/docs_guard.py: documentation that still points at the tree it describes.

The docs refactor of 2026-07-27 moved files and broke links that no gate could catch, because
no gate existed (deferred-work plan, Wave 19). The guard checks the three things a machine can
prove offline: relative links resolve, backticked repo paths exist, and the changelog set is
reachable from its own index.
"""
from __future__ import annotations

import pytest


def _repo(tmp_path, version="1.2.3"):
    """A minimal tree the guard considers clean: one changelog entry, indexed, at VERSION."""
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (tmp_path / "tooling").mkdir()
    (tmp_path / "tooling" / "real.py").write_text("x = 1\n", encoding="utf-8")
    # Present so `.ai-badger/…` proves the framework-surface whitelist, not mere absence.
    (tmp_path / ".ai-badger").mkdir()
    changelog = tmp_path / "docs" / "changelog"
    changelog.mkdir(parents=True)
    (changelog / f"{version}-thing.md").write_text("# thing\n", encoding="utf-8")
    (changelog / "README.md").write_text(
        f"| Version | Entry |\n|---|---|\n| {version} | [thing]({version}-thing.md) |\n",
        encoding="utf-8")
    return tmp_path


def _doc(repo, relpath, text):
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(name="guard")
def _guard(load_script):
    return load_script("gates/docs_guard.py")


def test_a_clean_tree_passes(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "see [the entry](changelog/1.2.3-thing.md)\n")

    assert guard.main(["--root", str(repo)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_a_broken_relative_link_is_reported_with_file_and_line(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "intro\n\nsee [the design](design/gone.md) for details\n")

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "docs/index.md:3" in out
    assert "design/gone.md" in out


def test_a_broken_link_in_a_root_markdown_file_is_reported(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "README.md", "[gone](docs/nope.md)\n")

    assert guard.main(["--root", str(repo)]) == 1
    assert "README.md:1" in capsys.readouterr().out


def test_anchor_only_and_external_links_are_ignored(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md",
         "[top](#heading) [web](https://example.com/x.md) [plain](http://example.com)\n"
         "[mail](mailto:nobody@example.com)\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_a_fragment_is_stripped_before_resolving(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "[entry](changelog/1.2.3-thing.md#a-heading)\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_link_syntax_inside_a_code_span_is_not_a_link(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "write `[text](target)` or `[label]: target` to link\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_a_link_whose_text_is_a_code_span_is_still_checked(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "see [`gone.md`](gone.md)\n")

    assert guard.main(["--root", str(repo)]) == 1
    assert "docs/index.md:1" in capsys.readouterr().out


def test_a_code_span_naming_a_real_path_passes(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "run `tooling/real.py` to do the thing\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_a_code_span_naming_a_missing_path_fails(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "run\n`tooling/does_not_exist.py`\n")

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "docs/index.md:2" in out
    assert "tooling/does_not_exist.py" in out


@pytest.mark.parametrize("span", [
    "tooling/<name>.py",
    "tooling/{version}-{slug}.md",
    "tooling/*.py",
    "tooling/**/*.md",
    "tooling/$NAME.py",
    "tooling/some file.py",
    "not-a-repo-root/thing.py",
    ".ai-badger/config.json",
    "docs/changelog",
    "https://example.com/x.md",
])
def test_a_placeholder_or_glob_span_is_never_flagged(tmp_path, guard, span):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", f"see `{span}` for the shape\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_paths_inside_fenced_code_blocks_are_ignored(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md",
         "example:\n\n```\ncp tooling/does_not_exist.py .\n[gone](nowhere.md)\n```\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_an_exempted_path_is_not_flagged(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/index.md", "`tooling/does_not_exist.py` and [gone](gone.md)\n")
    (repo / ".docs-guard-ignore").write_text(
        "# deliberately absent\ntooling/does_not_exist.py\ndocs/gone.md\n", encoding="utf-8")

    assert guard.main(["--root", str(repo)]) == 0


def test_an_exempted_document_is_not_scanned(tmp_path, guard):
    repo = _repo(tmp_path)
    _doc(repo, "docs/archive/old.md", "[gone](../nowhere.md) and `tooling/gone.py`\n")

    assert guard.main(["--root", str(repo)]) == 0


def test_a_record_document_keeps_link_checking_but_not_path_checking(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "docs/plans/plan.md", "build `tooling/not_yet.py`\nsee [design](gone.md)\n")

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "tooling/not_yet.py" not in out
    assert "docs/plans/plan.md:2" in out


def test_a_changelog_entry_missing_from_the_index_fails(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    _doc(repo, "docs/changelog/1.2.2-orphan.md", "# orphan\n")

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "1.2.2-orphan.md" in out


def test_the_current_version_without_a_changelog_entry_fails(tmp_path, guard, capsys):
    repo = _repo(tmp_path)
    (repo / "VERSION").write_text("1.3.0\n", encoding="utf-8")

    rc = guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "1.3.0" in out


def test_the_real_repository_passes(root, guard, capsys):
    rc = guard.main(["--root", str(root)])

    assert rc == 0, capsys.readouterr().out
