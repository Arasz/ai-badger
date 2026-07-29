"""Tests for the mcp-servers.schema.json schema.

Validates that the schema correctly accepts/rejects various mcp-servers.json payloads.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "mcp-servers.schema.json"


@pytest.fixture
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(data, schema):
    jsonschema.validate(data, schema)


# ── valid payloads ────────────────────────────────────────────────────────────

def test_valid_mcp_servers_json_passes(schema):
    data = {
        "servers": [
            {"name": "pyright", "command": "uvx mcp-server-pyright"},
        ]
    }
    _validate(data, schema)


def test_empty_servers_array_valid(schema):
    _validate({"servers": []}, schema)


def test_scope_defaults_to_project(schema):
    """A server without scope is valid — defaults to 'project'."""
    data = {"servers": [{"name": "x", "command": "echo hi"}]}
    _validate(data, schema)


def test_scope_accepts_user(schema):
    data = {"servers": [{"name": "x", "command": "echo hi", "scope": "user"}]}
    _validate(data, schema)


def test_scope_accepts_project(schema):
    data = {"servers": [{"name": "x", "command": "echo hi", "scope": "project"}]}
    _validate(data, schema)


def test_agent_override_valid(schema):
    data = {
        "servers": [{
            "name": "fs",
            "command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
            "agentOverrides": {
                "hermes": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
            },
        }]
    }
    _validate(data, schema)


def test_env_valid(schema):
    data = {
        "servers": [{
            "name": "github",
            "command": "npx -y @modelcontextprotocol/server-github",
            "env": {"GITHUB_TOKEN": ""},
        }]
    }
    _validate(data, schema)


def test_description_valid(schema):
    data = {
        "servers": [{
            "name": "pyright",
            "command": "uvx mcp-server-pyright",
            "description": "Python type checking",
        }]
    }
    _validate(data, schema)


# ── invalid payloads ──────────────────────────────────────────────────────────

def test_missing_name_fails(schema):
    data = {"servers": [{"command": "echo hi"}]}
    with pytest.raises(jsonschema.ValidationError):
        _validate(data, schema)


def test_missing_command_fails(schema):
    data = {"servers": [{"name": "x"}]}
    with pytest.raises(jsonschema.ValidationError):
        _validate(data, schema)


def test_unknown_fields_rejected(schema):
    data = {"servers": [{"name": "x", "command": "echo", "bogus": True}]}
    with pytest.raises(jsonschema.ValidationError):
        _validate(data, schema)


def test_env_must_be_string_values(schema):
    data = {"servers": [{"name": "x", "command": "echo", "env": {"KEY": 123}}]}
    with pytest.raises(jsonschema.ValidationError):
        _validate(data, schema)


def test_scope_rejects_invalid_value(schema):
    data = {"servers": [{"name": "x", "command": "echo", "scope": "global"}]}
    with pytest.raises(jsonschema.ValidationError):
        _validate(data, schema)


def test_missing_servers_key_fails(schema):
    data = {"other": True}
    with pytest.raises(jsonschema.ValidationError):
        _validate(data, schema)
