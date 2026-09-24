"""Every vendored badger_store.py copy on disk matches the canonical module (D16).

The report finds copies by globbing the working tree (features/** and skills/**), never
from a hand list or from git, so a new copy is checked the moment it exists — in a git
checkout, a non-git tmp root and the plugin cache alike.

Designed failure modes, each with the mutation that proves the test real:
  - a copy the report cannot see (a hand list instead of the glob -> red): an unguarded copy;
  - a landed copy drifting from the canonical module (edit the copy -> red): copy skew;
  - verify() flagging healthy copies or missing skew (flip the comparison -> red).
"""
from __future__ import annotations

import shutil

import badger_store
from conftest import ROOT


def test_the_report_finds_an_unlisted_copy_in_a_non_git_root(tmp_path):
    """A copy nobody registered, in a root with no .git, is still compared: the working
    tree is the only inventory there is (the plugin cache has no git either)."""
    copy = tmp_path / "features/common/skills/x/scripts/badger_store.py"
    copy.parent.mkdir(parents=True)
    copy.write_bytes((ROOT / "engine/badger_store.py").read_bytes() + b"\n# drifted\n")
    plugin_copy = tmp_path / "skills/x/scripts/badger_store.py"
    plugin_copy.parent.mkdir(parents=True)
    shutil.copy(ROOT / "engine/badger_store.py", plugin_copy)

    assert not (tmp_path / ".git").exists()
    assert badger_store.vendored_copies_report(tmp_path) == [
        "features/common/skills/x/scripts/badger_store.py differs from badger_store.py"]


def test_landed_copies_are_byte_identical_to_the_canonical():
    """Copies that have landed must be byte-equal to engine/badger_store.py — no skew (D16)."""
    assert badger_store.vendored_copies_report(ROOT) == []


def test_verify_flags_a_skewed_landed_copy_and_stays_silent_on_a_matching_one(tmp_path):
    """The byte-equality check must see skew on a landed copy and nothing on a matching one."""
    landed = tmp_path / "features/common/skills/task/scripts/badger_store.py"
    landed.parent.mkdir(parents=True)
    shutil.copy(ROOT / "engine/badger_store.py", landed)

    assert badger_store.vendored_copies_report(tmp_path) == []

    landed.write_text(landed.read_text() + "\n# drifted\n")
    report = badger_store.vendored_copies_report(tmp_path)
    assert report == ["features/common/skills/task/scripts/badger_store.py differs from"
                      " badger_store.py"]


def test_a_root_without_copies_has_no_findings(tmp_path):
    """A skill directory with no copy in it is not a finding: only files on disk are checked."""
    (tmp_path / "features/common/skills/task/scripts").mkdir(parents=True)
    assert badger_store.vendored_copies_report(tmp_path) == []
