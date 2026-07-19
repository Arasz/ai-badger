"""Tests for scripts/validate.py: --kind/--schema single-file validation and --all."""
from __future__ import annotations

import json
import shutil


def _copy_real_schemas(tmp_path, root):
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    return tmp_path


def test_kind_config_valid_instance_returns_zero(tmp_path, root, load_script, capsys):
    validate = load_script("scripts/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    instance = tmp_path / "config.json"
    instance.write_text(json.dumps({
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "pluginScope": "default",
        "docs": {},
    }), encoding="utf-8")

    rc = validate.main(["--kind", "config", "--root", str(fake_root), str(instance)])

    assert rc == 0
    assert "ok" in capsys.readouterr().out


def test_kind_config_invalid_instance_returns_one(tmp_path, root, load_script, capsys):
    validate = load_script("scripts/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    instance = tmp_path / "config.json"
    instance.write_text(json.dumps({"not": "a valid config"}), encoding="utf-8")

    rc = validate.main(["--kind", "config", "--root", str(fake_root), str(instance)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "INVALID" in out


def test_explicit_schema_path_is_used_over_kind(tmp_path, load_script, capsys):
    validate = load_script("scripts/validate.py")
    schema_path = tmp_path / "s.schema.json"
    schema_path.write_text(json.dumps({"type": "object", "required": ["x"]}), encoding="utf-8")
    instance = tmp_path / "i.json"
    instance.write_text(json.dumps({"x": 1}), encoding="utf-8")

    rc = validate.main(["--schema", str(schema_path), str(instance)])

    assert rc == 0
    assert "ok" in capsys.readouterr().out


def test_missing_instance_and_missing_all_flag_is_a_usage_error(load_script):
    validate = load_script("scripts/validate.py")

    import pytest
    with pytest.raises(SystemExit) as exc_info:
        validate.main([])

    assert exc_info.value.code == 2


def test_instance_without_schema_or_kind_is_a_usage_error(tmp_path, load_script):
    validate = load_script("scripts/validate.py")
    instance = tmp_path / "i.json"
    instance.write_text("{}", encoding="utf-8")

    import pytest
    with pytest.raises(SystemExit) as exc_info:
        validate.main([str(instance)])

    assert exc_info.value.code == 2


def test_all_flag_validates_the_real_framework_tree_and_reports_ok(root, load_script, capsys):
    validate = load_script("scripts/validate.py")

    rc = validate.main(["--all", "--root", str(root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "schemas self-check" in out


def test_all_flag_reports_invalid_when_a_plugins_json_fails_its_schema(tmp_path, root, load_script, capsys):
    validate = load_script("scripts/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    plugins_dir = fake_root / "features" / "dotnet" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "plugins.json").write_text(json.dumps({"not": "matching the schema"}),
                                                encoding="utf-8")

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "INVALID" in out


def test_all_flag_skips_index_json_when_absent(tmp_path, root, load_script, capsys):
    validate = load_script("scripts/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "index.json" not in out
