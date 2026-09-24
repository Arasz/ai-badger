"""Tests for tooling/version_sync.py: VERSION -> plugin.json / marketplace.json / index.json."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
from conftest import _test_write


def _write_json(path, data):
    _test_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _make_synced_root(tmp_path, root, load_script, version="0.2.0"):
    """A synthetic framework tree where all four version literals already agree at `version`."""
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    (tmp_path / "features").mkdir()
    _test_write(tmp_path / "VERSION", f"{version}\n", encoding="utf-8")

    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    _write_json(plugin_dir / "plugin.json", {
        "name": "ai-badger",
        "version": version,
        "description": "d",
        "author": {"name": "a", "url": "u"},
        "license": "MIT",
    })
    _write_json(plugin_dir / "marketplace.json", {
        "name": "ai-badger",
        "owner": {"name": "a", "url": "u"},
        "metadata": {"description": "d"},
        "plugins": [{
            "name": "ai-badger",
            "source": "./",
            "description": "d",
            "version": version,
            "license": "MIT",
            "keywords": [],
        }],
    })

    index_build = load_script("tooling/index_build.py")
    rc = index_build.main(["--root", str(tmp_path)])
    assert rc == 0
    return tmp_path


def test_check_passes_when_all_targets_agree(tmp_path, root, load_script, capsys):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    assert rc == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_when_plugin_json_desynced(tmp_path, root, load_script, capsys):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    plugin_path = fake_root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    data["version"] = "0.1.0"
    _write_json(plugin_path, data)
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "plugin.json" in out
    assert "0.1.0" in out
    assert "0.3.0" in out


def test_check_fails_when_marketplace_json_desynced(tmp_path, root, load_script, capsys):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    mp_path = fake_root / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    data["plugins"][0]["version"] = "0.1.0"
    _write_json(mp_path, data)
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "marketplace.json" in out
    assert "0.1.0" in out
    assert "0.3.0" in out


def test_check_fails_when_index_json_not_regenerated_after_version_bump(tmp_path, root, load_script):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.1.0")
    _test_write(fake_root / "VERSION", "0.2.0\n", encoding="utf-8")

    plugin_path = fake_root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    data["version"] = "0.2.0"
    _write_json(plugin_path, data)

    mp_path = fake_root / ".claude-plugin" / "marketplace.json"
    mdata = json.loads(mp_path.read_text(encoding="utf-8"))
    mdata["plugins"][0]["version"] = "0.2.0"
    _write_json(mp_path, mdata)

    # plugin.json + marketplace.json are now hand-synced to 0.2.0; index.json is the only
    # target still stale (still says 0.1.0) — proves version_sync actually gates on it via
    # delegation to index_build rather than leaving a silent gap.
    rc = version_sync.main(["--root", str(fake_root), "--check"])

    assert rc == 1


def test_sync_writes_all_targets_correctly_from_version(tmp_path, root, load_script):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.1.0")
    _test_write(fake_root / "VERSION", "0.5.0\n", encoding="utf-8")

    rc = version_sync.main(["--root", str(fake_root)])

    assert rc == 0
    plugin_data = json.loads((fake_root / ".claude-plugin" / "plugin.json")
                              .read_text(encoding="utf-8"))
    assert plugin_data["version"] == "0.5.0"

    mp_data = json.loads((fake_root / ".claude-plugin" / "marketplace.json")
                          .read_text(encoding="utf-8"))
    assert mp_data["plugins"][0]["version"] == "0.5.0"

    index_data = json.loads((fake_root / "index.json").read_text(encoding="utf-8"))
    assert index_data["frameworkVersion"] == "0.5.0"

    check_rc = version_sync.main(["--root", str(fake_root), "--check"])
    assert check_rc == 0


def test_sync_only_writes_matching_marketplace_entries_by_name(tmp_path, root, load_script):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.1.0")
    mp_path = fake_root / ".claude-plugin" / "marketplace.json"
    mdata = json.loads(mp_path.read_text(encoding="utf-8"))
    mdata["plugins"].append({
        "name": "other-plugin",
        "source": "./other",
        "description": "unrelated",
        "version": "9.9.9",
        "license": "MIT",
        "keywords": [],
    })
    _write_json(mp_path, mdata)
    _test_write(fake_root / "VERSION", "0.5.0\n", encoding="utf-8")

    version_sync.main(["--root", str(fake_root)])

    mdata = json.loads(mp_path.read_text(encoding="utf-8"))
    by_name = {p["name"]: p["version"] for p in mdata["plugins"]}
    assert by_name["ai-badger"] == "0.5.0"
    assert by_name["other-plugin"] == "9.9.9"


def test_version_sync_loads_without_tooling_already_on_sys_path(load_script, monkeypatch, root):
    """The script must reach its own sibling `index_build`, not rely on another test.

    Loading it in isolation failed with ModuleNotFoundError until it put its own directory
    on sys.path: it inserted `engine/` for badger_lib and nothing for the sibling. The whole
    file then passed only inside the full suite, where test_index_build.py sorts earlier and
    had already done it — six tests that could not pass on their own.
    """
    import sys as _sys
    tooling_dir = str((root / "tooling").resolve())
    monkeypatch.setattr(_sys, "path", [p for p in _sys.path if p != tooling_dir])
    monkeypatch.delitem(_sys.modules, "index_build", raising=False)
    monkeypatch.delitem(_sys.modules, "tooling.version_sync", raising=False)

    assert load_script("tooling/version_sync.py") is not None


# ── the release ritual's last step: the scaffold stamps must agree with VERSION ──────

def _stamp_the_scaffold(tmp_path, version):
    """A manifest and a stamped agent file, as the scaffolder would leave them."""
    aib = tmp_path / ".ai-badger"
    aib.mkdir(exist_ok=True)
    _write_json(aib / "manifest.json", {"frameworkVersion": version, "entries": []})
    _test_write(tmp_path / "CLAUDE.md", f"# p\n\n> Scaffolded by ai-badger {version}. Source of truth: `.ai-badger/CLAUDE.md`.\n", encoding="utf-8")


def test_a_manifest_left_at_the_previous_release_is_reported(tmp_path, root, load_script, capsys):
    """Three of fourteen tags shipped a manifest one release behind; no lane could see it.

    The freshness guard exempts version stamps by design, and version_sync did not read the
    manifest at all, so a release that skipped the re-scaffold passed every check.
    """
    version_sync = load_script("tooling/version_sync.py")
    _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    _stamp_the_scaffold(tmp_path, "0.2.0")

    rc = version_sync.check(tmp_path, "0.3.0")

    out = capsys.readouterr().out
    assert rc == 1
    assert "manifest" in out and "0.2.0" in out


def test_a_stale_scaffolded_by_line_is_reported(tmp_path, root, load_script, capsys):
    """The stamp in every generated agent file is the other half of the same skipped step."""
    version_sync = load_script("tooling/version_sync.py")
    _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    _stamp_the_scaffold(tmp_path, "0.3.0")
    _test_write(tmp_path / "CLAUDE.md", "# p\n\n> Scaffolded by ai-badger 0.2.0. Source of truth: `.ai-badger/CLAUDE.md`.\n", encoding="utf-8")

    rc = version_sync.check(tmp_path, "0.3.0")

    assert rc == 1
    assert "CLAUDE.md" in capsys.readouterr().out


def test_agreeing_scaffold_stamps_are_silent(tmp_path, root, load_script):
    version_sync = load_script("tooling/version_sync.py")
    _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    _stamp_the_scaffold(tmp_path, "0.3.0")

    assert version_sync.check(tmp_path, "0.3.0") == 0


def test_sync_never_forges_the_scaffold_stamp(tmp_path, root, load_script):
    """Writing frameworkVersion here would claim a scaffold that never ran."""
    version_sync = load_script("tooling/version_sync.py")
    _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    _stamp_the_scaffold(tmp_path, "0.2.0")

    version_sync.sync(tmp_path, "0.3.0")

    manifest = json.loads((tmp_path / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frameworkVersion"] == "0.2.0"


def test_prose_describing_the_stamp_is_not_mistaken_for_one(tmp_path, root, load_script):
    """CONTRIBUTING.md documents the stamp as `Scaffolded by ai-badger <v>`; that is not a version."""
    version_sync = load_script("tooling/version_sync.py")
    _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    _stamp_the_scaffold(tmp_path, "0.3.0")
    _test_write(tmp_path / "CONTRIBUTING.md", "The scaffolder writes `Scaffolded by ai-badger <v>` into every generated file.\n", encoding="utf-8")

    assert version_sync.check(tmp_path, "0.3.0") == 0


# ── N-1: derived stamp targets ───────────────────────────────────────────────────────
#
# version_sync had no notion of features/common/data/model-groups.json at all: its targets
# were a hand list (plugin.json, marketplace.json, index.json, the scaffold stamps). The fix
# is a derivation — every tracked-or-present *.json under the shipped roots
# (tooling/release_paths.py) whose top level has a string frameworkVersion, except
# index.json — not one more entry appended to the hand list.


def _seed_model_groups(fake_root, root, version=None):
    """Copy the REAL model-groups.json into the fixture tree ("real tree" gate row).

    Using the actual shipped file (not a hand-crafted stand-in) proves the derivation
    reaches production's real path and shape, not just a lookalike fixture.
    """
    data_dir = fake_root / "features" / "common" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "model-groups.json"
    shutil.copy(root / "features" / "common" / "data" / "model-groups.json", target)
    if version is not None:
        data = json.loads(target.read_text(encoding="utf-8"))
        data["frameworkVersion"] = version
        _write_json(target, data)
    return target


def test_check_names_a_stale_model_groups_registry(tmp_path, root, load_script, capsys):
    """The coordinator's gate: a stale features/common/data/model-groups.json is named."""
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.172.5")
    _seed_model_groups(fake_root, root, version="0.172.1")
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "features/common/data/model-groups.json" in out


def test_sync_stamps_the_model_groups_registry(tmp_path, root, load_script):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.172.5")
    target = _seed_model_groups(fake_root, root, version="0.172.1")

    version_sync.sync(fake_root, "0.172.5")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["frameworkVersion"] == "0.172.5"
    assert version_sync.check(fake_root, "0.172.5") == 0


def test_a_novel_shipped_json_file_is_found_by_derivation_alone(tmp_path, root, load_script):
    """A hand list that merely gained `model-groups.json` would still miss this one (R42).

    Only a derivation over the shipped roots finds a brand-new, never-named JSON file that
    happens to carry the same frameworkVersion shape.
    """
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.172.5")
    _seed_model_groups(fake_root, root, version="0.172.5")  # this one is already in sync
    novel = fake_root / "features" / "x" / "data" / "other.json"
    novel.parent.mkdir(parents=True, exist_ok=True)
    _write_json(novel, {"frameworkVersion": "0.1.0", "anything": True})

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = version_sync.check(fake_root, "0.172.5")
    assert rc == 1
    assert "features/x/data/other.json" in buf.getvalue()

    version_sync.sync(fake_root, "0.172.5")
    data = json.loads(novel.read_text(encoding="utf-8"))
    assert data["frameworkVersion"] == "0.172.5"


def test_index_json_is_excluded_from_the_derived_targets(tmp_path, root, load_script):
    """index.json is index_build's own target, explicitly excepted from the N-1 derivation."""
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.172.5")

    targets = version_sync.stamp_targets(fake_root)

    assert all(t.name != "index.json" for t in targets)


def test_ai_badger_json_stamp_is_reported_never_rewritten(tmp_path, root, load_script, capsys):
    """.ai-badger/*.json files of this shape are scaffold output: reported, never rewritten."""
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.172.5")
    _stamp_the_scaffold(fake_root, "0.172.5")
    aib_model_groups = fake_root / ".ai-badger" / "model-groups.json"
    shutil.copy(root / "features" / "common" / "data" / "model-groups.json", aib_model_groups)
    data = json.loads(aib_model_groups.read_text(encoding="utf-8"))
    data["frameworkVersion"] = "0.172.1"
    _write_json(aib_model_groups, data)
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    out = capsys.readouterr().out
    assert rc == 1
    assert ".ai-badger/model-groups.json" in out

    version_sync.sync(fake_root, "0.172.5")
    data = json.loads(aib_model_groups.read_text(encoding="utf-8"))
    assert data["frameworkVersion"] == "0.172.1", "never rewritten by sync()"


# ── L8-8: an empty (or non-matching) marketplace must fail, not silently pass ────────────


def test_check_fails_when_no_marketplace_entry_names_the_plugin(tmp_path, root, load_script, capsys):
    version_sync = load_script("tooling/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    mp_path = fake_root / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    data["plugins"] = []
    _write_json(mp_path, data)
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "marketplace" in out.lower()
