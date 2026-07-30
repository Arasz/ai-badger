"""Tests for tooling/changelog_index.py: the generated release table and its --check mode."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

WIRING = (".pre-commit-config.yaml", ".lefthook/pre-push/verify.sh",
          ".github/workflows/pylint.yml")


@pytest.fixture
def changelog_index(load_script):
    return load_script("tooling/changelog_index.py")


def _readme(directory: Path, body: str = "") -> Path:
    """A minimal README carrying the generated region between its markers."""
    path = directory / "README.md"
    path.write_text(
        "# Changelog\n\nprose above\n\n"
        "<!-- changelog-index:start -->\n"
        f"{body}"
        "<!-- changelog-index:end -->\n\n"
        "prose below\n",
        encoding="utf-8",
    )
    return path


def _entry(directory: Path, name: str, h1: str, body: str = "") -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {h1}\n\n{body}", encoding="utf-8")
    return path


def _tree(tmp_path: Path) -> Path:
    directory = tmp_path / "docs" / "changelog"
    directory.mkdir(parents=True)
    _readme(directory)
    return tmp_path


def _rows(text: str):
    """Every generated row (version, cell) from a rendered README, in order."""
    region = text.split("<!-- changelog-index:start -->")[1].split(
        "<!-- changelog-index:end -->")[0]
    out = []
    for line in region.splitlines():
        match = re.match(r"^\| (\d+\.\d+\.\d+) \| (.*) \|$", line)
        if match:
            out.append((match.group(1), match.group(2)))
    return out


def test_versions_are_ordered_by_semver_not_lexicographically(changelog_index, tmp_path):
    """0.9.0 > 0.43.1 lexicographically; the release timeline says otherwise."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    for name in ("0.9.0-nine.md", "0.10.0-ten.md", "0.43.1-patch.md", "0.51.2-two.md",
                 "0.51.10-ten.md"):
        _entry(directory, name, name[: name.index("-")] + " — title")

    changelog_index.main(["--root", str(root)])

    versions = [version for version, _ in _rows((directory / "README.md").read_text("utf-8"))]
    assert versions == ["0.51.10", "0.51.2", "0.43.1", "0.10.0", "0.9.0"]


def test_the_title_is_the_h1_with_its_version_prefix_stripped(changelog_index, tmp_path):
    """The Version column already carries the version; the cell must not repeat it."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a thing that happened")

    changelog_index.main(["--root", str(root)])

    assert _rows((directory / "README.md").read_text("utf-8")) == [
        ("0.1.0", "[a thing that happened](0.1.0-a-thing.md)")]


def test_an_h1_that_does_not_repeat_its_version_is_used_whole(changelog_index, tmp_path):
    """Two entries authored without the prefix exist; nothing may be truncated off them."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "A build is not a dotnet")

    changelog_index.main(["--root", str(root)])

    assert _rows((directory / "README.md").read_text("utf-8")) == [
        ("0.1.0", "[A build is not a dotnet](0.1.0-a-thing.md)")]


def test_entries_at_one_version_join_in_filename_order(changelog_index, tmp_path):
    """The declared ordering rule: filename ascending, so the row is content-determined."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.2.0-zebra.md", "0.2.0 — zebra")
    _entry(directory, "0.2.0-apple.md", "0.2.0 — apple")

    changelog_index.main(["--root", str(root)])

    assert _rows((directory / "README.md").read_text("utf-8")) == [
        ("0.2.0", "[apple](0.2.0-apple.md) · [zebra](0.2.0-zebra.md)")]


def test_an_index_note_in_an_entry_is_appended_to_its_link(changelog_index, tmp_path):
    """0.7.1's row says the mechanism was later reverted; that fact lives in the entry."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a thing",
           "<!-- index-note: later reverted; see [ADR-0003](../adr/0003.md) -->\n")

    changelog_index.main(["--root", str(root)])

    assert _rows((directory / "README.md").read_text("utf-8")) == [
        ("0.1.0", "[a thing](0.1.0-a-thing.md) — *later reverted; "
                  "see [ADR-0003](../adr/0003.md)*")]


def test_an_index_note_written_about_in_prose_is_not_a_declaration(changelog_index, tmp_path):
    """Found by firing it in anger: 0.53.0's own entry documents the marker in a code span."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a thing",
           "- **`<!-- index-note: … -->`** — an optional line in an entry.\n")

    changelog_index.main(["--root", str(root)])

    assert _rows((directory / "README.md").read_text("utf-8")) == [
        ("0.1.0", "[a thing](0.1.0-a-thing.md)")]


def test_a_pipe_in_a_title_cannot_break_the_table(changelog_index, tmp_path):
    """An unescaped `|` would silently split the row into extra columns."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a | b")

    changelog_index.main(["--root", str(root)])

    assert _rows((directory / "README.md").read_text("utf-8")) == [
        ("0.1.0", r"[a \| b](0.1.0-a-thing.md)")]


def test_the_prose_around_the_table_survives_regeneration(changelog_index, tmp_path):
    """The README documents the convention; only the marked region is generated."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a thing")

    changelog_index.main(["--root", str(root)])

    text = (directory / "README.md").read_text("utf-8")
    assert text.startswith("# Changelog\n\nprose above\n")
    assert text.endswith("prose below\n")


def test_regeneration_is_idempotent(changelog_index, tmp_path):
    """A second run must not append a second table or drift by a byte."""
    root = _tree(tmp_path)
    _entry(root / "docs" / "changelog", "0.1.0-a-thing.md", "0.1.0 — a thing")

    changelog_index.main(["--root", str(root)])
    once = (root / "docs" / "changelog" / "README.md").read_text("utf-8")
    changelog_index.main(["--root", str(root)])

    assert (root / "docs" / "changelog" / "README.md").read_text("utf-8") == once


def test_check_passes_on_a_freshly_generated_index(changelog_index, tmp_path):
    root = _tree(tmp_path)
    _entry(root / "docs" / "changelog", "0.1.0-a-thing.md", "0.1.0 — a thing")
    changelog_index.main(["--root", str(root)])

    assert changelog_index.main(["--root", str(root), "--check"]) == 0


def test_check_fails_when_an_entry_has_no_row(changelog_index, tmp_path, capsys):
    """The silent-omission hole from issue #160: a shipped entry nothing indexes."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a thing")
    changelog_index.main(["--root", str(root)])
    _entry(directory, "0.1.0-another-thing.md", "0.1.0 — another thing")

    rc = changelog_index.main(["--root", str(root), "--check"])

    assert rc == 1
    assert "stale" in capsys.readouterr().out


def test_check_fails_when_the_markers_are_missing(changelog_index, tmp_path, capsys):
    """Without the region there is nothing to generate into; that is a failure, not a pass."""
    root = _tree(tmp_path)
    directory = root / "docs" / "changelog"
    (directory / "README.md").write_text("# Changelog\n\nno markers here\n", encoding="utf-8")
    _entry(directory, "0.1.0-a-thing.md", "0.1.0 — a thing")

    rc = changelog_index.main(["--root", str(root), "--check"])

    assert rc == 1
    assert "marker" in capsys.readouterr().out


def test_an_entry_with_no_h1_is_reported_rather_than_indexed_blank(changelog_index, tmp_path,
                                                                  capsys):
    root = _tree(tmp_path)
    (root / "docs" / "changelog" / "0.1.0-a-thing.md").write_text("no heading\n",
                                                                  encoding="utf-8")

    rc = changelog_index.main(["--root", str(root)])

    assert rc == 1
    assert "0.1.0-a-thing.md" in capsys.readouterr().out


# --------------------------------------------------------------- the repository's own index


def test_the_committed_index_is_what_the_generator_produces(root, changelog_index):
    """The end-to-end claim: this repo's README needs no hand edit to pass."""
    assert changelog_index.main(["--root", str(root), "--check"]) == 0


def test_every_entry_file_appears_exactly_once_in_the_committed_index(root):
    """A dropped row is the silent failure; count links, do not trust the eye.

    Scoped to the generated region: the prose below the table cites two entries as examples
    of the house style, and those citations are not index rows.
    """
    directory = root / "docs" / "changelog"
    text = (directory / "README.md").read_text(encoding="utf-8")
    region = text.split("<!-- changelog-index:start -->")[1].split(
        "<!-- changelog-index:end -->")[0]
    for entry in sorted(directory.glob("*.md")):
        if entry.name == "README.md":
            continue
        assert region.count(f"]({entry.name})") == 1, f"{entry.name} is indexed 0 or 2+ times"


@pytest.mark.parametrize("relpath", WIRING)
def test_the_check_runs_wherever_the_other_generated_artifacts_are_checked(root, relpath):
    """A generator nothing runs is a generator that goes stale silently."""
    text = (root / relpath).read_text(encoding="utf-8")
    assert "changelog_index.py" in text, f"{relpath} does not run changelog_index.py"


def test_the_script_runs_as_a_cli_from_the_repository_root(root):
    """Fired in anger, not just imported: the shipped entry point must exit 0 here."""
    proc = subprocess.run([sys.executable, str(root / "tooling" / "changelog_index.py"),
                           "--check"], cwd=str(root), capture_output=True, text=True, check=False)

    assert proc.returncode == 0, proc.stdout + proc.stderr
