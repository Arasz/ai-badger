"""Tests for new schemas: skills-source, skills, plugins-instructions, adjustment, hooks-manifest."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


def _copy_real_schemas(tmp_path, root):
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    return tmp_path


# --- skills-source.schema.json ---

class TestSkillsSourceSchema:
    def _schema_path(self, root):
        return root / "schemas" / "skills-source.schema.json"

    def test_schema_file_exists(self, root):
        assert self._schema_path(root).is_file()

    def test_valid_common_source(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": [
            {"name": "test", "type": "marketplace", "source": "https://example.com", "support": "common"}
        ]}
        assert bl.validate(instance, schema) == []

    def test_valid_agent_specific_source(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": [
            {"name": "hermes-hub", "type": "hub", "source": "https://hermes.example.com", "support": ["hermes"]}
        ]}
        assert bl.validate(instance, schema) == []

    def test_valid_multiple_agents(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": [
            {"name": "shared", "type": "tap", "source": "org/repo", "support": ["claude", "hermes"]}
        ]}
        assert bl.validate(instance, schema) == []

    def test_invalid_type_value(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": [
            {"name": "bad", "type": "unknown", "source": "x", "support": "common"}
        ]}
        assert bl.validate(instance, schema) != []

    def test_invalid_support_value(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": [
            {"name": "bad", "type": "hub", "source": "x", "support": "invalid"}
        ]}
        assert bl.validate(instance, schema) != []

    def test_missing_required_fields(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": [{"name": "bad"}]}
        assert bl.validate(instance, schema) != []

    def test_empty_sources_array_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"sources": []}
        assert bl.validate(instance, schema) != []

    def test_missing_sources_key_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        assert bl.validate({}, schema) != []


# --- skills.schema.json ---

class TestSkillsSchema:
    def _schema_path(self, root):
        return root / "schemas" / "skills.schema.json"

    def test_schema_file_exists(self, root):
        assert self._schema_path(root).is_file()

    def test_valid_skills_list(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"skills": [
            {"name": "superpowers", "source": "claude-plugins-official", "scope": "default", "description": "desc"}
        ]}
        assert bl.validate(instance, schema) == []

    def test_valid_empty_skills(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"skills": []}
        assert bl.validate(instance, schema) == []

    def test_valid_minimal_entry(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"skills": [{"name": "x", "source": "y"}]}
        assert bl.validate(instance, schema) == []

    def test_invalid_scope_value(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"skills": [{"name": "x", "source": "y", "scope": "invalid"}]}
        assert bl.validate(instance, schema) != []

    def test_missing_name_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"skills": [{"source": "y"}]}
        assert bl.validate(instance, schema) != []

    def test_missing_skills_key_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        assert bl.validate({}, schema) != []


# --- plugins-instructions.schema.json ---

class TestPluginsInstructionsSchema:
    def _schema_path(self, root):
        return root / "schemas" / "plugins-instructions.schema.json"

    def test_schema_file_exists(self, root):
        assert self._schema_path(root).is_file()

    def test_valid_instructions(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "agent": "hermes",
            "instructions": {
                "hub": {"description": "Install from hub", "commands": ["hermes skills install {source}"]},
                "tap": {"commands": ["hermes skills tap add {source}"]}
            }
        }
        assert bl.validate(instance, schema) == []

    def test_valid_empty_instructions(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"agent": "copilot", "instructions": {}}
        assert bl.validate(instance, schema) == []

    def test_invalid_instruction_key(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "agent": "test",
            "instructions": {"unknown_type": {"commands": ["x"]}}
        }
        assert bl.validate(instance, schema) != []

    def test_missing_commands_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "agent": "test",
            "instructions": {"hub": {"description": "no commands"}}
        }
        assert bl.validate(instance, schema) != []

    def test_missing_agent_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"instructions": {}}
        assert bl.validate(instance, schema) != []


# --- adjustment.schema.json ---

class TestAdjustmentSchema:
    def _schema_path(self, root):
        return root / "schemas" / "adjustment.schema.json"

    def test_schema_file_exists(self, root):
        assert self._schema_path(root).is_file()

    def test_valid_adjustment(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "agent": "hermes",
            "adjustments": [
                {"feature": "hooks", "description": "Install hooks", "script": "adjust_hooks.py"},
                {"feature": "task", "script": "adjust_task.py"}
            ]
        }
        assert bl.validate(instance, schema) == []

    def test_valid_empty_adjustments(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"agent": "test", "adjustments": []}
        assert bl.validate(instance, schema) == []

    def test_missing_script_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"agent": "test", "adjustments": [{"feature": "hooks"}]}
        assert bl.validate(instance, schema) != []

    def test_missing_agent_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"adjustments": []}
        assert bl.validate(instance, schema) != []


# --- hooks-manifest.schema.json ---

class TestHooksManifestSchema:
    def _schema_path(self, root):
        return root / "schemas" / "hooks-manifest.schema.json"

    def test_schema_file_exists(self, root):
        assert self._schema_path(root).is_file()

    def test_valid_manifest(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "hooks": [
                {
                    "name": "drift-notice",
                    "description": "Detect drift",
                    "agents": {
                        "claude": {"type": "hooks-json", "entry": "hooks.json", "event": "SessionStart"},
                        "hermes": {"type": "plugin", "entry": "ai_badger_hooks.py", "method": "on_session_start"}
                    }
                }
            ]
        }
        assert bl.validate(instance, schema) == []

    def test_valid_minimal_hook(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "hooks": [{"name": "test", "agents": {"hermes": {"type": "plugin", "entry": "x.py"}}}]
        }
        assert bl.validate(instance, schema) == []

    def test_invalid_hook_type(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {
            "hooks": [{"name": "bad", "agents": {"claude": {"type": "invalid", "entry": "x"}}}]
        }
        assert bl.validate(instance, schema) != []

    def test_missing_name_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"hooks": [{"agents": {"hermes": {"type": "plugin", "entry": "x.py"}}}]}
        assert bl.validate(instance, schema) != []

    def test_missing_agents_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {"hooks": [{"name": "bad"}]}
        assert bl.validate(instance, schema) != []

    def test_missing_hooks_key_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        assert bl.validate({}, schema) != []


# --- message.schema.json ---

class TestMessageSchema:
    """The message-bus delivery document (P1/F4): the store returns this shape and the
    delivery hooks inject it — the schema is the contract both sides code against."""

    def _schema_path(self, root):
        return root / "schemas" / "message.schema.json"

    def _instance(self):
        return {
            "sender": {"sessionId": "S", "projectId": "P"},
            "content": "found it, see src/bus.py",
            "timestamp": "2026-09-01T12:00:00+00:00",
        }

    def test_schema_file_exists(self, root):
        assert self._schema_path(root).is_file()

    def test_valid_delivery_document(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        assert bl.validate(self._instance(), schema) == []

    def test_valid_with_schema_key(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {**self._instance(), "$schema": "./message.schema.json"}
        assert bl.validate(instance, schema) == []

    def test_missing_sender_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = self._instance()
        del instance["sender"]
        assert bl.validate(instance, schema) != []

    def test_sender_without_project_id_fails(self, tmp_path, root, load_script):
        """Identity is REQUIRED at send (R10): a sender half missing is not a valid document."""
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {**self._instance(), "sender": {"sessionId": "S"}}
        assert bl.validate(instance, schema) != []

    def test_empty_sender_fields_fail(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {**self._instance(), "sender": {"sessionId": "", "projectId": "P"}}
        assert bl.validate(instance, schema) != []

    def test_missing_content_or_timestamp_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        for key in ("content", "timestamp"):
            instance = self._instance()
            del instance[key]
            assert bl.validate(instance, schema) != [], key

    def test_non_string_content_fails(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {**self._instance(), "content": {"verbose": True}}
        assert bl.validate(instance, schema) != []

    def test_additional_properties_fail(self, tmp_path, root, load_script):
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        instance = {**self._instance(), "target": "nobody"}
        assert bl.validate(instance, schema) != []

    def test_store_delivery_documents_conform(self, tmp_path, root, monkeypatch,
                                              load_script):
        """The contract is not aspirational: documents straight from deliver_for_session
        validate against this schema."""
        bl = load_script("engine/badger_lib.py")
        schema = bl.load_json(self._schema_path(root))
        bs = load_script("engine/badger_store.py")

        root_dir = tmp_path / "user-root"
        monkeypatch.setenv("AI_BADGER_USER_ROOT", str(root_dir))
        store = bs.open_user()
        try:
            store.send_message(sender_session="S1", sender_project="P", content="hello",
                               target_project="P")
            documents = store.deliver_for_session("S2", "P")
        finally:
            store.close()
        assert documents, "the fixture must have delivered one document"
        for document in documents:
            assert bl.validate(document, schema) == []
