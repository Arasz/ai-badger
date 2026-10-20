"""The model-id grammar, checked against an independent table of shapes.

`tests/fixtures/model-id-conformance.json` lists every id shape the framework has to
accept or refuse, with the verdict each one carries. The table is the oracle; this file
runs it against the two places an id is judged, so both have to agree with it:

  1. the shipped schema (`schemas/model-groups.schema.json`), which judges a member's id
     while the map document is validated;
  2. the map leaf's own id pattern (`model_groups.MODEL_ID_RE`), which judges an id again
     before the resolver emits it.

The table is a fixture of shapes, not of a map shape: each case is checked in a document
built from the shipped map, with one member's id replaced, so the verdict under test is the
id's and not the document's.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "model-id-conformance.json"
LEAF = "features/common/skills/task/scripts/model_groups.py"
SCHEMA = "schemas/model-groups.schema.json"
SEED = "features/common/data/model-groups.json"


def _cases() -> list:
    """The conformance table: every id shape and the verdict it carries."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _document_with_id(root: Path, ident: str) -> dict:
    """The shipped map with one member's id replaced."""
    document = json.loads((root / SEED).read_text(encoding="utf-8"))
    document["groups"]["low"]["models"][0]["id"] = ident
    return document


@pytest.mark.parametrize("case", _cases(), ids=lambda case: repr(case["id"]))
def test_the_schema_accepts_and_refuses_the_shapes_the_table_names(root, case):
    """The shipped schema's verdict on an id is the table's verdict."""
    schema = json.loads((root / SCHEMA).read_text(encoding="utf-8"))
    document = _document_with_id(root, case["id"])
    errors = [error for error in jsonschema.Draft202012Validator(schema).iter_errors(document)
              if list(error.path)[:2] == ["groups", "low"]]
    assert bool(errors) is not case["valid"], (
        f"{case['id']!r}: the schema says {'valid' if not errors else 'invalid'}, "
        f"the table says {'valid' if case['valid'] else 'invalid'}")


@pytest.mark.parametrize("case", _cases(), ids=lambda case: repr(case["id"]))
def test_the_leaf_accepts_and_refuses_the_shapes_the_table_names(root, load_script, case):
    """The leaf's id pattern agrees with the table, so the resolver emits the same set."""
    leaf = load_script(LEAF)
    assert bool(leaf.MODEL_ID_RE.fullmatch(case["id"])) is case["valid"], (
        f"{case['id']!r}: the leaf says "
        f"{'valid' if leaf.MODEL_ID_RE.fullmatch(case['id']) else 'invalid'}, "
        f"the table says {'valid' if case['valid'] else 'invalid'}")
