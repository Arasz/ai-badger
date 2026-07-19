"""Tests for scripts/version_sync.py: VERSION -> plugin.json / marketplace.json / index.json."""
from __future__ import annotations

import json
import shutil


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _make_synced_root(tmp_path, root, load_script, version="0.2.0"):
    """A synthetic framework tree where all four version literals already agree at `version`."""
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    (tmp_path / "features").mkdir()
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")

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

    index_build = load_script("scripts/index_build.py")
    rc = index_build.main(["--root", str(tmp_path)])
    assert rc == 0
    return tmp_path


def test_check_passes_when_all_targets_agree(tmp_path, root, load_script, capsys):
    version_sync = load_script("scripts/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.3.0")
    capsys.readouterr()

    rc = version_sync.main(["--root", str(fake_root), "--check"])

    assert rc == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_when_plugin_json_desynced(tmp_path, root, load_script, capsys):
    version_sync = load_script("scripts/version_sync.py")
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
    version_sync = load_script("scripts/version_sync.py")
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
    version_sync = load_script("scripts/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.1.0")
    (fake_root / "VERSION").write_text("0.2.0\n", encoding="utf-8")

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
    version_sync = load_script("scripts/version_sync.py")
    fake_root = _make_synced_root(tmp_path, root, load_script, version="0.1.0")
    (fake_root / "VERSION").write_text("0.5.0\n", encoding="utf-8")

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
    version_sync = load_script("scripts/version_sync.py")
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
    (fake_root / "VERSION").write_text("0.5.0\n", encoding="utf-8")

    version_sync.main(["--root", str(fake_root)])

    mdata = json.loads(mp_path.read_text(encoding="utf-8"))
    by_name = {p["name"]: p["version"] for p in mdata["plugins"]}
    assert by_name["ai-badger"] == "0.5.0"
    assert by_name["other-plugin"] == "9.9.9"
