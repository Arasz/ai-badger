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

import re

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

# `brand/` and `screenshots/` predate `assets/` and are pinned by the root README and by
# `skills.md`. They are on the map by name, not by quadrant.
PINNED_DIRS = ("brand", "screenshots")

# An index row's first cell, as a backticked filename or a relative markdown link. `adr/` and
# `work/` index their contents in a table; the other READMEs use prose the forward check covers.
INDEX_ROW_RE = re.compile(r"^\|\s*(?:`([^`|]+)`|\[[^\]]*\]\(([^)|]+)\))\s*\|")

# Directories that index their files in a table, and the least they must index — a regex that
# stopped matching would let the reverse check pass by finding nothing at all.
INDEXED_DIRS = {"adr": 15, "work": 10}


def _docs(root):
    return root / "docs"


def _indexed_files(readme_text: str):
    """Filenames a README's index table claims exist beside it."""
    named = []
    for line in readme_text.splitlines():
        row = INDEX_ROW_RE.match(line)
        if row:
            named.append(row.group(1) or row.group(2))
    return named


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

    def test_no_directory_sits_outside_the_map(self, root):
        """`plans/` outlived PR #111: the map check matched the prose explaining its removal."""
        known = set(CANONICAL_DIRS) | set(FROZEN_DIRS) | set(PINNED_DIRS)
        present = sorted(d.name for d in _docs(root).iterdir()
                         if d.is_dir() and not d.name.startswith("."))

        residue = [name for name in present if name not in known]

        assert not residue, (
                "docs/ holds directories the canonical tree does not name: " + ", ".join(residue)
        )

    def test_the_root_readme_names_every_directory(self, root):
        readme = (_docs(root) / "README.md").read_text(encoding="utf-8")
        present = sorted(d.name for d in _docs(root).iterdir()
                         if d.is_dir() and not d.name.startswith("."))

        missing = [name for name in present if f"{name}/" not in readme]

        assert not missing, f"docs/README.md omits: {', '.join(missing)}"

    @pytest.mark.parametrize("name", CANONICAL_DIRS)
    def test_a_directory_readme_names_every_file_beside_it(self, root, name):
        """Subdirectories answer for themselves; files do not."""
        directory = _docs(root) / name
        readme = (directory / "README.md").read_text(encoding="utf-8")
        beside = sorted(f.name for f in directory.iterdir()
                        if f.is_file() and f.name != "README.md")

        missing = [f for f in beside if f not in readme]

        assert not missing, f"docs/{name}/README.md omits: {', '.join(missing)}"

    @pytest.mark.parametrize("name", CANONICAL_DIRS)
    def test_a_directory_readme_indexes_nothing_that_is_absent(self, root, name):
        """The other half of the map: a row for a file that never merged reads as a real record."""
        directory = _docs(root) / name
        readme = (directory / "README.md").read_text(encoding="utf-8")

        dangling = sorted({f for f in _indexed_files(readme) if not (directory / f).exists()})

        assert not dangling, (
            f"docs/{name}/README.md indexes files that do not exist: {', '.join(dangling)}"
        )

    @pytest.mark.parametrize("name,least", sorted(INDEXED_DIRS.items()))
    def test_an_index_table_is_actually_read(self, root, name, least):
        """A reverse check that parses no rows passes vacuously and guards nothing."""
        readme = (_docs(root) / name / "README.md").read_text(encoding="utf-8")

        assert len(_indexed_files(readme)) >= least, \
            f"docs/{name}/README.md yielded too few index rows — the row pattern has drifted"


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

    def test_the_index_check_catches_a_row_for_a_file_that_never_merged(self, tmp_path):
        (tmp_path / "2026-08-07-real.md").write_text("record", encoding="utf-8")
        readme = ("| File | What it records |\n|---|---|\n"
                  "| `2026-08-07-real.md` | A record that exists |\n"
                  "| `2026-08-07-imagined.md` | A record that never merged |\n")

        dangling = sorted({f for f in _indexed_files(readme) if not (tmp_path / f).exists()})

        assert dangling == ["2026-08-07-imagined.md"]

    def test_the_residue_check_catches_a_directory_off_the_map(self, tmp_path):
        for name in ("work", "plans"):
            (tmp_path / name).mkdir()
        known = {"work", "adr"}

        residue = [d.name for d in sorted(tmp_path.iterdir()) if d.name not in known]

        assert residue == ["plans"]

    def test_the_record_dir_check_catches_a_dead_path(self, tmp_path):
        (tmp_path / "docs" / "work").mkdir(parents=True)
        record_dirs = ("docs/work/", "docs/plans/")

        absent = [d for d in record_dirs if not (tmp_path / d).is_dir()]

        assert absent == ["docs/plans/"]