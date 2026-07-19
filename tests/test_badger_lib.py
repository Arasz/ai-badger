"""Tests for scripts/badger_lib.py: root discovery, JSON io, hashing, and jsonschema helpers."""
from __future__ import annotations

import hashlib
import json


def _make_root(tmp_path):
    """Build a minimal fake framework root (schemas/ + features/) under tmp_path."""
    (tmp_path / "schemas").mkdir()
    (tmp_path / "features").mkdir()
    return tmp_path


def test_find_root_walks_up_to_dir_with_schemas_and_features(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    fake_root = _make_root(tmp_path)
    nested = fake_root / "features" / "dotnet" / "skills" / "foo"
    nested.mkdir(parents=True)

    found = bl.find_root(nested)

    assert found == fake_root.resolve()


def test_find_root_raises_when_no_ancestor_has_schemas_and_features(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    lonely = tmp_path / "some" / "unrelated" / "dir"
    lonely.mkdir(parents=True)

    import pytest
    with pytest.raises(RuntimeError):
        bl.find_root(lonely)


def test_find_root_default_start_resolves_the_real_framework_root(load_script, root):
    bl = load_script("scripts/badger_lib.py")

    found = bl.find_root()

    assert found == root.resolve()


def test_load_json_dump_json_roundtrip(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    path = tmp_path / "data.json"
    data = {"b": 2, "a": [1, 2, 3], "nested": {"x": "y"}}

    bl.dump_json(path, data)
    loaded = bl.load_json(path)

    assert loaded == data


def test_dump_json_is_pretty_printed_and_newline_terminated(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    path = tmp_path / "data.json"

    bl.dump_json(path, {"a": 1})
    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert "\n  " in text  # indent=2 produces indented lines for multi-key/nested data


def test_sha256_text_matches_hashlib(load_script):
    bl = load_script("scripts/badger_lib.py")

    assert bl.sha256_text("hello") == hashlib.sha256(b"hello").hexdigest()


def test_sha256_file_matches_hashlib_for_a_file(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    f = tmp_path / "f.txt"
    f.write_bytes(b"some bytes")

    assert bl.sha256_file(f) == hashlib.sha256(b"some bytes").hexdigest()


def test_sha256_file_is_deterministic_for_a_directory(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("A", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_text("B", encoding="utf-8")

    first = bl.sha256_file(d)
    second = bl.sha256_file(d)

    assert first == second


def test_sha256_file_directory_hash_changes_when_content_changes(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("A", encoding="utf-8")
    before = bl.sha256_file(d)

    (d / "a.txt").write_text("A-changed", encoding="utf-8")
    after = bl.sha256_file(d)

    assert before != after


def test_sha256_file_directory_hash_depends_on_relative_names_not_absolute_path(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    d1 = tmp_path / "one" / "d"
    d1.mkdir(parents=True)
    (d1 / "a.txt").write_text("A", encoding="utf-8")

    d2 = tmp_path / "two" / "somewhere" / "d"
    d2.mkdir(parents=True)
    (d2 / "a.txt").write_text("A", encoding="utf-8")

    assert bl.sha256_file(d1) == bl.sha256_file(d2)


def test_read_index_loads_index_json_from_root(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    (tmp_path / "index.json").write_text(json.dumps({"frameworkVersion": "1.0.0", "stacks": {}}),
                                          encoding="utf-8")

    idx = bl.read_index(tmp_path)

    assert idx["frameworkVersion"] == "1.0.0"


def test_validate_returns_empty_list_when_instance_is_valid(load_script):
    bl = load_script("scripts/badger_lib.py")
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}

    errors = bl.validate({"name": "ok"}, schema)

    assert errors == []


def test_validate_returns_readable_sorted_errors_when_instance_is_invalid(load_script):
    bl = load_script("scripts/badger_lib.py")
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
    }

    errors = bl.validate({"age": "not-a-number"}, schema)

    assert len(errors) >= 1
    assert any("age" in e for e in errors)


def test_validate_file_reads_both_json_files_and_validates(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    schema_path = tmp_path / "s.schema.json"
    schema_path.write_text(json.dumps({"type": "object", "required": ["x"]}), encoding="utf-8")
    instance_path = tmp_path / "i.json"
    instance_path.write_text(json.dumps({"x": 1}), encoding="utf-8")

    assert bl.validate_file(instance_path, schema_path) == []

    instance_path.write_text(json.dumps({}), encoding="utf-8")
    assert bl.validate_file(instance_path, schema_path) != []


def test_check_schemas_selfvalid_accepts_the_real_framework_schemas(root, load_script):
    bl = load_script("scripts/badger_lib.py")

    problems = bl.check_schemas_selfvalid(root / "schemas")

    assert problems == []


def test_check_schemas_selfvalid_flags_a_broken_schema(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    (tmp_path / "broken.schema.json").write_text(
        json.dumps({"type": "not-a-real-type"}), encoding="utf-8"
    )

    problems = bl.check_schemas_selfvalid(tmp_path)

    assert len(problems) == 1
    assert "broken.schema.json" in problems[0]


def test_iter_feature_dirs_returns_empty_list_when_no_features_dir(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")

    assert bl.iter_feature_dirs(tmp_path) == []


def test_iter_feature_dirs_yields_stack_feature_dir_tuples_in_sorted_order(tmp_path, load_script):
    bl = load_script("scripts/badger_lib.py")
    features = tmp_path / "features"
    (features / "dotnet" / "skills").mkdir(parents=True)
    (features / "dotnet" / "personas").mkdir(parents=True)
    (features / "azure" / "invariants").mkdir(parents=True)
    # a stray, non-FEATURES subdir must be ignored
    (features / "dotnet" / "not-a-feature").mkdir(parents=True)

    found = bl.iter_feature_dirs(tmp_path)

    stacks_features = [(s, f) for s, f, _ in found]
    # stacks sorted alphabetically; within a stack, features in FEATURES order (skills first)
    assert stacks_features == [
        ("azure", "invariants"),
        ("dotnet", "skills"),
        ("dotnet", "personas"),
    ]
