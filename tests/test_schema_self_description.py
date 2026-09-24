"""A closed schema must still permit the ``$schema`` editor hint on the files it validates."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from badger_lib import is_vendored_packet as _vendored_packet

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = ("schemas", "features")


def _is_json_schema(document: object) -> bool:
    """True when `$schema` names the JSON Schema dialect by parsed hostname.

    Not a substring test: `https://evil.example/?x=json-schema.org` must not qualify, and a
    relative `$schema` (a sibling file) is not the dialect declaration this sweep looks for.
    """
    if not isinstance(document, dict):
        return False
    dialect = document.get("$schema")
    if not isinstance(dialect, str):
        return False
    host = urlsplit(dialect).hostname or ""
    return host == "json-schema.org" or host.endswith(".json-schema.org")


def _json_schema_documents():
    found = []
    for base in SEARCH_ROOTS:
        for path in sorted((ROOT / base).rglob("*.json")):
            if _vendored_packet(path):
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if _is_json_schema(document):
                found.append(pytest.param(path, document,
                                          id=path.relative_to(ROOT).as_posix()))
    return found


def test_the_dialect_predicate_rejects_lookalike_urls():
    """The hostname rule is load-bearing, so prove both directions."""
    assert _is_json_schema({"$schema": "https://json-schema.org/draft/2020-12/schema"})
    assert not _is_json_schema({"$schema": "https://evil.example/?x=json-schema.org"})
    assert not _is_json_schema({"$schema": "./schema.json"})
    assert not _is_json_schema({"type": "object"})


def test_the_vendored_exclusion_is_bounded_and_real():
    """The exclusion must skip the vendored schemas and nothing else."""
    assert _vendored_packet(
        ROOT / "features" / "common" / "skills" / "archify" / "schemas"
        / "architecture.schema.json")
    assert not _vendored_packet(ROOT / "schemas" / "model.schema.json")


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
