"""The vendored-path manifest pins where badger_store.py copies land and that they match (D16).

Designed failure modes, each with the mutation that proves the test real:
  - a lands_in path typo (rename the target dir -> red): a silently-wrong sync destination;
  - a landed copy drifting from the canonical module (edit the copy -> red): copy skew;
  - verify() flagging healthy copies or missing skew (flip the comparison -> red).
Copies that have not landed yet are named but unchecked — vendorin lands with P0.5/P2.2.
"""
from __future__ import annotations

import shutil

import badger_store
from conftest import ROOT


def test_manifest_lands_in_paths_name_existing_repo_locations():
    """Every lands_in parent must exist in the repo: a typo would silently misroute the sync."""
    for entry in badger_store.VENDORED_PATHS:
        assert (ROOT / entry["lands_in"]).parent.is_dir(), entry["lands_in"]
    assert len({entry["lands_in"] for entry in badger_store.VENDORED_PATHS}) == len(
        badger_store.VENDORED_PATHS
    ), "manifest entries must be unique destinations"


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


def test_absent_landed_copies_are_not_findings(tmp_path):
    """A destination that has not landed yet is manifest-named but unchecked, not a failure."""
    (tmp_path / "features/common/skills/task/scripts").mkdir(parents=True)  # dir without the file
    assert badger_store.vendored_copies_report(tmp_path) == []
