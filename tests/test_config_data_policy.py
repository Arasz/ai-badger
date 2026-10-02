"""`dataPolicy` in the project config schema: `local-only`, or the object form carrying an
`allowHosts` list; absent is valid.

A minimal valid config is built here and extended per row. The schema's `oneOf` is compared
against the OpenRouter client's `LOCAL_ONLY` and `HOST_PATTERN`, and one entry matrix is run
through both the schema and the client so the two cannot disagree on what a valid list is.
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


def test_the_object_form_is_a_valid_data_policy():
    assert errors(with_policy(object_policy(["decider.corp.example"]))) == []


@pytest.mark.parametrize("value", ["opt-in", "bogus", "Local-Only", None, 1])
def test_any_other_data_policy_is_rejected(value):
    assert errors(with_policy(value))


def load_client():
    spec = importlib.util.spec_from_file_location("ai_badger_test_data_policy_client", CLIENT)
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    return client


def test_the_schema_enum_is_the_client_local_only_value():
    client = load_client()
    string_form, object_form = SCHEMA["properties"]["dataPolicy"]["oneOf"]
    assert string_form == {"type": "string", "enum": [client.LOCAL_ONLY]}
    assert object_form["type"] == "object"
    assert object_form["additionalProperties"] is False
    assert sorted(object_form["required"]) == ["allowHosts", "mode"]
    assert object_form["properties"]["mode"] == {"const": client.LOCAL_ONLY}
    hosts = object_form["properties"]["allowHosts"]
    assert (hosts["type"], hosts["uniqueItems"]) == ("array", True)
    assert hosts["items"] == {"type": "string", "pattern": client.HOST_PATTERN}


def object_policy(hosts, **extra):
    return {"mode": "local-only", "allowHosts": hosts, **extra}


# (entry, valid): one matrix the schema and the client must both answer the same way.
ENTRIES = [
    ("decider.corp.example", True),
    ("Decider.Corp.Example.", True),
    ("a-b.c0.example", True),
    ("x.io", True),
    ("decider", False),
    ("*.corp.example", False),
    ("decider.corp.example:443", False),
    ("https://decider.corp.example", False),
    ("decider.corp.example/v1", False),
    ("user@decider.corp.example", False),
    ("203.0.113.7", False),
    ("corp.42", False),
    ("decider.corp.example\n", False),
    ("decider.corp.example\nx.io", False),
    ("-lead.example", False),
    ("trail-.example", False),
    ("two..dots.example", False),
    (".lead.example", False),
    ("d\u00e9cider.example", False),
    ("", False),
]


@pytest.mark.parametrize("entry,valid", ENTRIES, ids=[repr(e[0]) for e in ENTRIES])
def test_the_schema_and_the_client_agree_on_each_allow_hosts_entry(tmp_path, entry, valid):
    client = load_client()
    policy = object_policy([entry])
    assert (errors(with_policy(policy)) == []) is valid
    (tmp_path / ".ai-badger").mkdir()
    (tmp_path / ".ai-badger" / "config.json").write_text(json.dumps({"dataPolicy": policy}),
                                                         encoding="utf-8")
    assert bool(client.allowed_hosts(str(tmp_path))) is valid


@pytest.mark.parametrize("policy", [object_policy(["decider.corp.example"], extra=1),
                                    {"mode": "local-only"},
                                    {"allowHosts": ["decider.corp.example"]},
                                    object_policy(["decider.corp.example"], mode="open"),
                                    object_policy("decider.corp.example"),
                                    object_policy(["decider.corp.example"] * 2),
                                    object_policy([7])],
                         ids=["unknown-key", "no-hosts", "no-mode", "other-mode", "not-a-list",
                              "duplicate", "non-string"])
def test_a_malformed_object_form_is_rejected(policy):
    assert errors(with_policy(policy))


def test_the_object_form_with_an_empty_list_is_valid():
    assert errors(with_policy(object_policy([]))) == []
