"""Every document has a legal home, and every home is on the map.

`scaffold-documentation/references/structure.md` binds the tree. Before this guard the repo had
no `work/`, so dated work records — review forms, research notes, incident writeups — had nowhere
legal to go. Two of them ended up in `.tmp/`: gitignored, and hidden, which the same reference
calls out by name ("ripgrep skips it; the default search of every agent misses it").

The map half matters as much as the tree half. The failure this guards against was observed live
and is recorded in `structure.md`: a docs root README tabling ten entries while the directory held
seventeen. A partial map is worse than none, because it is read as complete.
"""
from __future__ import annotations

import functools
import subprocess

import pytest

# The canonical tree, minus `legacy/` — that one exists only while a wholesale migration is in
# flight and drains to empty, so its absence is the healthy state, not a gap.
CANONICAL_DIRS = (
    "tutorials",
    "how-to",
    "reference",
    "explanation",
    "adr",
    "work",
    "assets",
    "meta",
)

# `changelog/` is frozen build input, not a quadrant: `tooling/changelog_index.py --check`
# generates its index and a CLAUDE.md invariant pins its filenames. It is on the map but its
# contents are not governed by the naming rules below.
FROZEN_DIRS = ("changelog",)


def _docs(root):
    return root / "docs"


@functools.lru_cache(maxsize=None)
def _committed_entries(root, subpath):
    """Direct children of HEAD:<subpath> as (name, is_dir) pairs, read from the committed tree."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", f"HEAD:{subpath}"],
        capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ()
    entries = []
    for line in result.stdout.splitlines():
        meta, name = line.split("\t", 1)
        _mode, kind, _sha = meta.split()
        entries.append((name, kind == "tree"))
    return tuple(entries)


class TestTheTreeExists:
    """A legal home exists before any document is written."""

    @pytest.mark.parametrize("name", CANONICAL_DIRS)
    def test_the_directory_is_present(self, root, name):
        assert (_docs(root) / name).is_dir(), f"docs/{name}/ is missing from the canonical tree"

    @pytest.mark.parametrize("name", CANONICAL_DIRS + FROZEN_DIRS)
    def test_the_directory_has_a_readme(self, root, name):
        assert (_docs(root) / name / "README.md").is_file(), \
            f"docs/{name}/README.md is missing — the directory has no map"


class TestEveryMapIsComplete:
    """A README lists every file beside it. An unlisted file is one nobody will find."""

    def test_the_root_readme_names_every_directory(self, root):
        readme = (_docs(root) / "README.md").read_text(encoding="utf-8")
        present = sorted(name for name, is_dir in _committed_entries(root, "docs")
                         if is_dir and not name.startswith("."))

        missing = [name for name in present if f"{name}/" not in readme]

        assert not missing, f"docs/README.md omits: {', '.join(missing)}"

    @pytest.mark.parametrize("name", CANONICAL_DIRS)
    def test_a_directory_readme_names_every_file_beside_it(self, root, name):
        """Subdirectories answer for themselves; files do not."""
        directory = _docs(root) / name
        readme = (directory / "README.md").read_text(encoding="utf-8")
        beside = sorted(entry_name for entry_name, is_dir in _committed_entries(root, f"docs/{name}")
                        if not is_dir and entry_name != "README.md")

        missing = [f for f in beside if f not in readme]

        assert not missing, f"docs/{name}/README.md omits: {', '.join(missing)}"

    def test_the_checks_ignore_an_untracked_file_and_directory(self, root):
        """A concurrent write into docs/ mid-run must not flip these checks red — only commits count."""
        scratch_dir = _docs(root) / "zz_scratch_untracked_dir"
        scratch_file = _docs(root) / "reference" / "zz-scratch-untracked.md"
        scratch_dir.mkdir()
        scratch_file.write_text("scratch", encoding="utf-8")
        try:
            self.test_the_root_readme_names_every_directory(root)
            self.test_a_directory_readme_names_every_file_beside_it(root, "reference")
        finally:
            scratch_file.unlink()
            scratch_dir.rmdir()


class TestTheGateFreezesOnlyRealPaths:
    """A gate naming a directory nobody has is dead config that reads as a live rule."""

    def test_every_record_dir_exists(self, root, load_script):
        guard = load_script("gates/docs_guard.py")

        absent = [d for d in guard.RECORD_DIRS if not (root / d).is_dir()]

        assert not absent, f"docs_guard.RECORD_DIRS names directories that do not exist: {absent}"

    def test_every_builtin_exemption_exists(self, root, load_script):
        """An exemption for a directory nobody has is dead config that reads as a live rule.

        `docs/archive/` was exempt long after the directory was removed (#268 review). Had it
        ever come back, its documents would have been skipped by both checks without anyone
        deciding that.
        """
        guard = load_script("gates/docs_guard.py")

        absent = [d for d in guard.BUILTIN_EXEMPT if not (root / d).is_dir()]

        assert not absent, f"docs_guard.BUILTIN_EXEMPT names directories that do not exist: {absent}"

    def test_work_is_a_record_dir(self, root, load_script):
        """Work records describe a tree as it was; their dead paths are the record working.

        Without this, check 2 would flag every repo path in an archived review as rot.
        """
        guard = load_script("gates/docs_guard.py")

        assert "docs/work/" in guard.RECORD_DIRS


class TestNoProseHidesFromRipgrep:
    """The reason `work/` had to exist: `.tmp/` is hidden, and every agent's search is ripgrep."""

    def test_no_review_form_is_left_in_a_hidden_directory(self, root):
        # .tmp/ is gitignored, so it cannot be read from git — the working tree is the only source.
        hidden = root / ".tmp"
        if not hidden.is_dir():
            return

        stranded = sorted(p.name for p in hidden.rglob("*-review.html"))

        assert not stranded, \
            f".tmp/ still holds review forms with a legal home in docs/work/: {stranded}"


class TestTheGuardCouldFail:
    """Each assertion above must be able to go red; a check that cannot fail proves nothing."""

    def test_the_map_check_catches_an_omission(self, tmp_path):
        readme = "# Docs\n\n- [work](work/) — records\n"
        present = ["work", "reference"]

        missing = [name for name in present if f"{name}/" not in readme]

        assert missing == ["reference"]

    def test_the_record_dir_check_catches_a_dead_path(self, tmp_path):
        (tmp_path / "docs" / "work").mkdir(parents=True)
        record_dirs = ("docs/work/", "docs/plans/")

        absent = [d for d in record_dirs if not (tmp_path / d).is_dir()]

        assert absent == ["docs/plans/"]