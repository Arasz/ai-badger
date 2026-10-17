"""The `tools` catalog feature type: registry, discovery rule, index/manifest buckets and
the tool.schema.json that describes `features/<stack>/tools/<tool>/meta.json`.

A tool is an external CLI (rtk first). Its meta.json names the agents it can hook and how;
each harness's adjust_tools.py owns the file format it writes.
"""
from __future__ import annotations

import json
import shutil

import pytest
from conftest import _test_write


def _fake_root(tmp_path, root, tools=("rtk",)):
    """A synthetic framework tree carrying one stack's tools/ directory."""
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    _test_write(tmp_path / "VERSION", "1.2.3\n", encoding="utf-8")
    for name in tools:
        tool = tmp_path / "features" / "common" / "tools" / name
        tool.mkdir(parents=True)
        _test_write(tool / "meta.json", json.dumps(_meta(name)), encoding="utf-8")
    return tmp_path


def _meta(name="rtk", **extra):
    meta = {
        "name": name,
        "description": "CLI output compression proxy.",
        "prerequisite": {"summary": "the rtk CLI, 1.0.1 or later",
                         "check": "rtk --version"},
        "hooks": {
            "claude": {"mode": "native", "arg": "claude"},
            "codex": {"mode": "native", "arg": "codex"},
            "copilot": {"mode": "native", "arg": "copilot"},
            "pi": {"mode": "init", "arg": "pi"},
            "hermes": {"mode": "propose"},
        },
    }
    meta.update(extra)
    return meta


def _tool_errors(bl, root, meta):
    return bl.validate(meta, bl.load_json(root / "schemas" / "tool.schema.json"))


# ── the registry ─────────────────────────────────────────────────────────────

def test_tools_is_a_registered_feature_type(load_script):
    bl = load_script("engine/badger_lib.py")

    assert "tools" in bl.FEATURES
    assert bl.feature_type("tools").index_rule == "tools"


def test_tools_are_neither_drift_reported_nor_declinable_nor_source_hashed(load_script):
    """Nothing is written under a tool's own name, so a "new" report could never clear."""
    bl = load_script("engine/badger_lib.py")
    tools = bl.feature_type("tools")

    assert tools.drift_reports_new is False
    assert tools.hashes_source is False
    assert tools.md_carrying is False
    assert "tools" not in bl.DRIFT_NEW_FEATURES
    assert "tools" not in bl.EXCLUDABLE_FEATURES
    assert bl.INCLUDABLE_FEATURES == ("skills",)


def test_iter_feature_dirs_yields_a_stacks_tools_directory(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    (tmp_path / "features" / "common" / "tools").mkdir(parents=True)

    found = [(stack, feature) for stack, feature, _ in bl.iter_feature_dirs(tmp_path)]

    assert ("common", "tools") in found


# ── the discovery rule ───────────────────────────────────────────────────────

def test_tools_items_are_only_the_subdirs_carrying_a_meta_json(tmp_path, load_script):
    index_build = load_script("tooling/index_build.py")
    fdir = tmp_path / "features" / "common" / "tools"
    for name in ("zulu", "alpha"):
        (fdir / name).mkdir(parents=True)
        _test_write(fdir / name / "meta.json", "{}", encoding="utf-8")
    (fdir / "notes").mkdir()
    _test_write(fdir / "notes" / "tool.md", "# notes\n", encoding="utf-8")
    _test_write(fdir / "meta.json", "{}", encoding="utf-8")

    items = index_build._tools_items(fdir, tmp_path)  # pylint: disable=protected-access

    assert items == [{"name": "alpha", "path": "features/common/tools/alpha"},
                     {"name": "zulu", "path": "features/common/tools/zulu"}]


def test_build_index_puts_tools_in_their_stacks_bucket_and_passes_its_schema(tmp_path, root,
                                                                             load_script):
    bl = load_script("engine/badger_lib.py")
    index_build = load_script("tooling/index_build.py")
    fake_root = _fake_root(tmp_path, root)

    index = index_build.build_index(fake_root)

    assert index["stacks"]["common"]["tools"] == [
        {"name": "rtk", "path": "features/common/tools/rtk"}]
    assert bl.validate(index, bl.load_json(root / "schemas" / "index.schema.json")) == []


def test_the_index_schema_refuses_an_unknown_bucket_but_admits_tools(root, load_script):
    """The tools bucket passes because it is listed, not because the stack object is open."""
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "index.schema.json")
    item = [{"name": "rtk", "path": "features/common/tools/rtk"}]

    def index(bucket):
        return {"frameworkVersion": "1.2.3", "stacks": {"common": {bucket: item}}}

    assert bl.validate(index("tools"), schema) == []
    assert bl.validate(index("gadgets"), schema)


def test_index_build_writes_a_tree_carrying_tools_and_then_reports_it_clean(tmp_path, root,
                                                                            load_script, capsys):
    index_build = load_script("tooling/index_build.py")
    fake_root = _fake_root(tmp_path, root)

    assert index_build.main(["--root", str(fake_root)]) == 0
    capsys.readouterr()

    assert index_build.main(["--root", str(fake_root), "--check"]) == 0


def test_the_index_build_docstring_documents_the_tools_rule(load_script):
    index_build = load_script("tooling/index_build.py")

    assert "tools         -> each subdir containing meta.json" in index_build.__doc__


def test_the_manifest_feature_enum_admits_tools(root, load_script):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "manifest.schema.json")

    assert "tools" in schema["properties"]["entries"]["items"]["properties"]["feature"]["enum"]


# ── tool.schema.json ─────────────────────────────────────────────────────────

def test_a_complete_tool_meta_is_valid(root, load_script):
    bl = load_script("engine/badger_lib.py")

    assert _tool_errors(bl, root, _meta()) == []


def test_every_mode_is_accepted_and_arg_is_optional(root, load_script):
    bl = load_script("engine/badger_lib.py")
    hooks = {"claude": {"mode": "native"}, "pi": {"mode": "init", "arg": "pi"},
             "hermes": {"mode": "propose"}}

    assert _tool_errors(bl, root, _meta(hooks=hooks)) == []


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda m: m["prerequisite"].pop("summary"), id="missing-prerequisite-summary"),
    pytest.param(lambda m: m.pop("prerequisite"), id="missing-prerequisite"),
    pytest.param(lambda m: m.pop("name"), id="missing-name"),
    pytest.param(lambda m: m["hooks"].update(cursor={"mode": "native"}), id="unknown-agent"),
    pytest.param(lambda m: m["hooks"]["claude"].update(mode="patch"), id="unknown-mode"),
    pytest.param(lambda m: m["hooks"]["pi"].pop("mode"), id="hook-without-mode"),
    pytest.param(lambda m: m["hooks"]["claude"].update(matcher="Bash"), id="extra-hook-key"),
    pytest.param(lambda m: m["hooks"]["claude"].update(arg=""), id="empty-arg"),
    pytest.param(lambda m: m.update(installer="brew"), id="extra-top-level-key"),
    pytest.param(lambda m: m["prerequisite"].update(floor="1.0.1"), id="extra-prerequisite-key"),
])
def test_tool_schema_refuses(root, load_script, mutate):
    bl = load_script("engine/badger_lib.py")
    meta = _meta()
    mutate(meta)

    assert _tool_errors(bl, root, meta)


# ── validate.py coverage ─────────────────────────────────────────────────────

def test_validate_maps_tool_schema_onto_every_tool_meta(load_script):
    validate = load_script("tooling/validate.py")

    assert validate.SCHEMA_INSTANCES["tool.schema.json"] == ["features/*/tools/*/meta.json"]


def test_validate_all_reports_a_broken_tool_meta(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _fake_root(tmp_path, root)
    meta_path = fake_root / "features" / "common" / "tools" / "rtk" / "meta.json"
    _test_write(meta_path, json.dumps(_meta(hooks={"cursor": {"mode": "native"}})),
                encoding="utf-8")

    validate.validate_all(fake_root)

    out = capsys.readouterr().out
    assert "INVALID  features/common/tools/rtk/meta.json" in out
