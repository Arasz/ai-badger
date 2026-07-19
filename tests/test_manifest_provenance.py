"""Provenance keys in .ai-badger/manifest.json (ADR-0001 decision 4)."""
from __future__ import annotations

import json

import pytest

SCHEMA_REL = "schemas/manifest.schema.json"


def _manifest(**overrides):
    base = {
        "frameworkVersion": "0.2.0",
        "frameworkCommit": "a" * 40,
        "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [],
    }
    base.update(overrides)
    return base


def _errors(load_script, root, instance):
    bl = load_script("scripts/badger_lib.py")
    schema = bl.load_json(root / SCHEMA_REL)
    return bl.validate(instance, schema)


def test_manifest_with_all_provenance_keys_is_valid(load_script, root):
    assert _errors(load_script, root, _manifest()) == []


def test_manifest_allows_null_commit_for_plugin_cache_scaffold(load_script, root):
    assert _errors(load_script, root, _manifest(frameworkCommit=None)) == []


@pytest.mark.parametrize("missing", ["frameworkCommit", "frameworkDirty"])
def test_manifest_missing_a_provenance_key_is_invalid(load_script, root, missing):
    instance = _manifest()
    del instance[missing]
    errors = _errors(load_script, root, instance)
    assert errors, f"expected {missing} to be required"
    assert any(missing in e for e in errors)


def test_manifest_dirty_must_be_boolean(load_script, root):
    assert _errors(load_script, root, _manifest(frameworkDirty="yes")) != []
