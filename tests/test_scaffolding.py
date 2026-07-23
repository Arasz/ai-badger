"""Tests for the scaffolding.json concept: schema validation and scaffold.py integration."""
from __future__ import annotations

import json
import shutil


def test_scaffolding_schema_validates_minimal_file(tmp_path, root, load_script):
    """A minimal scaffolding.json with one file entry must pass schema validation."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {
        "agent": "claude",
        "files": [
            {"source": "templates/CLAUDE.md", "target": "CLAUDE.md", "managed": True}
        ],
    }
    errors = badger_lib.validate(instance, schema)
    assert errors == []


def test_scaffolding_schema_rejects_missing_agent(tmp_path, root, load_script):
    """Missing 'agent' field must fail validation."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {
        "files": [
            {"source": "templates/CLAUDE.md", "target": "CLAUDE.md", "managed": True}
        ],
    }
    errors = badger_lib.validate(instance, schema)
    assert len(errors) > 0


def test_scaffolding_schema_rejects_missing_files(tmp_path, root, load_script):
    """Missing 'files' field must fail validation."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {"agent": "claude"}
    errors = badger_lib.validate(instance, schema)
    assert len(errors) > 0


def test_scaffolding_schema_rejects_missing_required_file_fields(tmp_path, root, load_script):
    """Each file entry must have source, target, and managed."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {
        "agent": "claude",
        "files": [
            {"source": "templates/CLAUDE.md"}  # missing target and managed
        ],
    }
    errors = badger_lib.validate(instance, schema)
    assert len(errors) > 0


def test_scaffolding_schema_accepts_optional_seed_once(tmp_path, root, load_script):
    """The seedOnce boolean must be accepted as an optional field."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {
        "agent": "prompt-markers",
        "files": [
            {
                "source": "markers-context.json",
                "target": "markers-context.json",
                "managed": True,
                "seedOnce": True,
            }
        ],
    }
    errors = badger_lib.validate(instance, schema)
    assert errors == []


def test_scaffolding_schema_validates_example_instance(root, load_script):
    """A realistic scaffolding.json must pass validation against its schema."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    scaffolding = {
        "agent": "claude",
        "description": "Claude Code agent discovery files",
        "files": [
            {
                "source": "templates/CLAUDE.md",
                "target": "CLAUDE.md",
                "managed": True,
            }
        ],
    }
    errors = badger_lib.validate(scaffolding, schema)
    assert errors == []
