"""`dataPolicy` in the project config schema: `local-only` is the one value, absent is valid.

A minimal valid config is built here and extended per row; the schema's enum is compared against
the OpenRouter client's `LOCAL_ONLY`, the value it documents.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "config.schema.json").read_text(encoding="utf-8"))
CLIENT = ROOT / "features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py"


def minimal_config():
    """The schema's required keys and nothing else."""
    return {"frameworkVersion": "1.0.0", "project": {"name": "probe"}, "stacks": ["python"],
            "agents": ["claude"]}


def errors(config):
    validator = jsonschema.Draft202012Validator(SCHEMA)
    return [error.message for error in validator.iter_errors(config)]


def with_policy(value):
    config = minimal_config()
    config["dataPolicy"] = value
    return config


def test_a_config_without_a_data_policy_validates():
    assert errors(minimal_config()) == []


def test_local_only_is_a_valid_data_policy():
    assert errors(with_policy("local-only")) == []


@pytest.mark.parametrize("value", ["opt-in", "bogus", "Local-Only", None, 1])
def test_any_other_data_policy_is_rejected(value):
    assert errors(with_policy(value))


def test_the_schema_enum_is_the_client_local_only_value():
    spec = importlib.util.spec_from_file_location("ai_badger_test_data_policy_client", CLIENT)
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    assert SCHEMA["properties"]["dataPolicy"]["enum"] == [client.LOCAL_ONLY]
