"""config_guard.py: backup naming and the atomic write it shares the contract with badger_lib."""
from __future__ import annotations

import os

CONFIG_GUARD = "features/common/skills/welcome-ai-badger/scripts/config_guard.py"


# --------------------------------------------------------------------- backup naming (L3-7)
def test_three_backups_in_one_second_never_collide(tmp_path, load_script, monkeypatch):
    """One scaffold writes settings.json up to three times within a second (statusline wiring,
    hook wiring, the claude adjustment): each write_with_backup must not clobber the last."""
    cg = load_script(CONFIG_GUARD)
    monkeypatch.setattr(cg.time, "strftime", lambda *_a, **_kw: "20260101-000000")
    path = tmp_path / "settings.json"

    cg.write_with_backup(path, "one\n")
    cg.write_with_backup(path, "two\n")
    cg.write_with_backup(path, "three\n")
    cg.write_with_backup(path, "four\n")

    backups = sorted(tmp_path.glob("settings.json.bak-*"))
    assert len(backups) == 3, backups
    bodies = {b.read_text(encoding="utf-8") for b in backups}
    assert bodies == {"one\n", "two\n", "three\n"}, "an earlier backup was overwritten"


def test_the_first_backup_of_a_run_keeps_the_plain_stamp(tmp_path, load_script, monkeypatch):
    cg = load_script(CONFIG_GUARD)
    monkeypatch.setattr(cg.time, "strftime", lambda *_a, **_kw: "20260101-000000")
    path = tmp_path / "settings.json"

    cg.write_with_backup(path, "one\n")
    cg.write_with_backup(path, "two\n")

    assert (tmp_path / "settings.json.bak-20260101-000000").read_text(
        encoding="utf-8") == "one\n"


# ---------------------------------------------------------------- new-file mode (L1-4 class)
def test_atomic_write_gives_a_new_file_the_umask_adjusted_default_mode(tmp_path, load_script):
    """Same contract as badger_lib.atomic_write_text: a brand-new file must not inherit
    mkstemp's 0600 — it never existed to preserve."""
    cg = load_script(CONFIG_GUARD)
    path = tmp_path / "new.json"
    old_umask = os.umask(0o022)
    try:
        cg._atomic_write(path, "{}\n")  # pylint: disable=protected-access
    finally:
        os.umask(old_umask)

    assert path.stat().st_mode & 0o777 == 0o666 & ~0o022 & 0o777


def test_atomic_write_preserves_an_existing_files_mode(tmp_path, load_script):
    cg = load_script(CONFIG_GUARD)
    path = tmp_path / "existing.json"
    path.write_text("{}\n", encoding="utf-8")
    path.chmod(0o600)

    cg._atomic_write(path, '{"a": 1}\n')  # pylint: disable=protected-access

    assert path.stat().st_mode & 0o777 == 0o600
