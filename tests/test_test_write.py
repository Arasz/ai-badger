"""The single write gate and the observer that watches the real checkout.

Every file a test writes must go through `_test_write`, the one chokepoint that refuses
paths inside the real repo or the real home — a write to a module constant a test forgot
to redirect becomes a loud failure instead of silent corruption (#222). The fs observer
(`_checkout_snapshot` + the session fixture) is the floor beneath the gate: anything that
still reaches the repo came from production code, a child interpreter, or an external
daemon, and is reported rather than blamed.

Self-derived constants, never imported from conftest: these tests assert a property of the
environment, and importing the fix's own symbols would make them fail with ImportError
rather than with the leak (same rule as test_suite_isolation.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import _test_write

REAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Evaluated at collection, before the session fixture redirects `$HOME` — the operator's
# real home, exactly as test_suite_isolation derives it.
REAL_HOME = Path.home()


def _write_gate():
    from conftest import _test_write  # pylint: disable=import-outside-toplevel

    return _test_write


class TestTheWriteGate:
    def test_writes_text_into_an_isolated_path(self, tmp_path):
        target = _write_gate()(tmp_path / "note.txt", "hello")

        assert target.read_text(encoding="utf-8") == "hello"

    def test_writes_bytes_when_given_bytes(self, tmp_path):
        _write_gate()(tmp_path / "blob.bin", b"\x00\x01")

        assert (tmp_path / "blob.bin").read_bytes() == b"\x00\x01"

    def test_encoding_is_passed_through(self, tmp_path):
        _write_gate()(tmp_path / "note.txt", "héllo", encoding="utf-8")

        assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "héllo"

    def test_refuses_a_path_inside_the_real_checkout(self):
        with pytest.raises(AssertionError):
            _write_gate()(REAL_PROJECT_ROOT / "probe.txt", "x")

    def test_refuses_a_nested_path_inside_the_real_checkout(self):
        with pytest.raises(AssertionError):
            _write_gate()(REAL_PROJECT_ROOT / "features" / "common" / "x.json", "x")

    def test_refuses_a_path_inside_the_real_home(self):
        with pytest.raises(AssertionError):
            _write_gate()(REAL_HOME / ".ai-badger" / "probe.txt", "x")

    def test_the_gate_returns_the_target_path(self, tmp_path):
        assert _write_gate()(tmp_path / "x.txt", "x") == tmp_path / "x.txt"


class TestTheObserverSeesTheWholeCheckout:
    def test_the_snapshot_lists_a_file_in_the_real_repo(self):
        from conftest import _checkout_snapshot  # pylint: disable=import-outside-toplevel

        assert str(REAL_PROJECT_ROOT / "VERSION") in _checkout_snapshot()

    def test_the_snapshot_skips_bookkeeping_dirs(self, tmp_path):
        from conftest import _checkout_snapshot  # pylint: disable=import-outside-toplevel

        (tmp_path / ".git").mkdir()
        _test_write(tmp_path / ".git" / "config", "x", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        _test_write(tmp_path / "__pycache__" / "m.pyc", b"\x00")
        (tmp_path / ".pytest_cache").mkdir()
        _test_write(tmp_path / ".pytest_cache" / "v", "x", encoding="utf-8")
        _test_write(tmp_path / "real.txt", "x", encoding="utf-8")

        snap = _checkout_snapshot([tmp_path])

        assert str(tmp_path / "real.txt") in snap
        assert str(tmp_path / ".git" / "config") not in snap
        assert str(tmp_path / "__pycache__" / "m.pyc") not in snap
        assert str(tmp_path / ".pytest_cache" / "v") not in snap

    def test_a_new_file_is_seen_as_added(self, tmp_path):
        from conftest import _checkout_snapshot  # pylint: disable=import-outside-toplevel

        before = _checkout_snapshot([tmp_path])
        _test_write(tmp_path / "new.txt", "x", encoding="utf-8")
        after = _checkout_snapshot([tmp_path])

        added = set(after) - set(before)
        assert str(tmp_path / "new.txt") in added

    def test_a_changed_file_is_seen_as_changed(self, tmp_path):
        from conftest import _checkout_snapshot  # pylint: disable=import-outside-toplevel

        target = tmp_path / "same.txt"
        _test_write(target, "one", encoding="utf-8")
        before = _checkout_snapshot([tmp_path])
        _test_write(target, "two", encoding="utf-8")
        after = _checkout_snapshot([tmp_path])

        changed = {p for p in set(after) & set(before) if after[p] != before[p]}
        assert str(target) in changed

    def test_a_deleted_file_is_seen_as_removed(self, tmp_path):
        from conftest import _checkout_snapshot  # pylint: disable=import-outside-toplevel

        target = tmp_path / "gone.txt"
        _test_write(target, "x", encoding="utf-8")
        before = _checkout_snapshot([tmp_path])
        target.unlink()
        after = _checkout_snapshot([tmp_path])

        removed = set(before) - set(after)
        assert str(target) in removed
