"""A closed schema must still permit the ``$schema`` editor hint on the files it validates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = ("schemas", "features")


def _json_schema_documents():
    found = []
    for base in SEARCH_ROOTS:
        for path in sorted((ROOT / base).rglob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(document, dict) and "json-schema.org" in str(document.get("$schema")):
                found.append(pytest.param(path, document,
                                          id=path.relative_to(ROOT).as_posix()))
    return found


def test_the_sweep_finds_the_schemas_it_is_meant_to_guard():
    ids = {p.id for p in _json_schema_documents()}
    assert "schemas/model.schema.json" in ids
    assert "features/common/templates/agent-instructions/schema.json" in ids
    assert len(ids) >= 18


def test_an_agent_instruction_model_carrying_the_editor_hint_still_validates(load_script):
    """The hint that makes the file self-describing must not be what invalidates it."""
    badger_lib = load_script("engine/badger_lib.py")
    schema = badger_lib.load_json(ROOT / "schemas" / "model.schema.json")
    instance = json.loads(
        (ROOT / ".ai-badger" / "agent-instructions" / "model.json").read_text(encoding="utf-8"))
    instance["$schema"] = "./schema.json"

    assert badger_lib.validate(instance, schema) == []


@pytest.mark.parametrize("path,document", _json_schema_documents())
def test_a_closed_schema_permits_the_schema_key(path, document):
    if document.get("additionalProperties") is not False:
        pytest.skip("schema is not closed at the root")

    assert "$schema" in document.get("properties", {}), (
        f"{path.relative_to(ROOT)} sets additionalProperties: false without declaring "
        "'$schema', so adding the editor hint to a valid file makes it invalid")
