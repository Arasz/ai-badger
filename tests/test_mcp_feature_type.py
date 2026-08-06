"""The `mcp` catalog feature type: registry, discovery rule, and its two schemas.

Step 1 of the MCP rebuild (ADR-0014). Nothing declares a server yet — these tests pin the
shape the catalog will be authored against.
"""
from __future__ import annotations

import json

import pytest


def _fake_root(tmp_path, root, servers=("code-review-graph",)):
    """A synthetic framework tree carrying one stack's mcp/ directory."""
    import shutil

    shutil.copytree(root / "schemas", tmp_path / "schemas")
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    mcp = tmp_path / "features" / "common" / "mcp"
    for name in servers:
        server = mcp / name
        server.mkdir(parents=True)
        (server / "meta.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return tmp_path


# ── the registry ─────────────────────────────────────────────────────────────

def test_mcp_is_a_registered_feature_type(load_script):
    bl = load_script("engine/badger_lib.py")

    assert "mcp" in bl.FEATURES
    assert bl.feature_type("mcp").index_rule == "mcp"


def test_mcp_items_are_neither_drift_reported_nor_declinable(load_script):
    """Scaffold writes nothing under an mcp item's own name, so both would be unclearable."""
    bl = load_script("engine/badger_lib.py")

    assert "mcp" not in bl.DRIFT_NEW_FEATURES
    assert "mcp" not in bl.EXCLUDABLE_FEATURES
    assert bl.feature_type("mcp").drift_reports_new is False


def test_mcp_is_not_markdown_carrying(load_script):
    bl = load_script("engine/badger_lib.py")

    assert bl.feature_type("mcp").md_carrying is False


def test_iter_feature_dirs_yields_a_stacks_mcp_directory(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    (tmp_path / "features" / "dotnet" / "mcp").mkdir(parents=True)

    found = [(stack, feature) for stack, feature, _ in bl.iter_feature_dirs(tmp_path)]

    assert ("dotnet", "mcp") in found


# ── the discovery rule ───────────────────────────────────────────────────────

def test_mcp_items_are_the_subdirs_carrying_a_meta_json(tmp_path, load_script):
    index_build = load_script("tooling/index_build.py")
    fdir = tmp_path / "features" / "common" / "mcp"
    (fdir / "rider").mkdir(parents=True)
    (fdir / "rider" / "meta.json").write_text("{}", encoding="utf-8")
    (fdir / "not-a-server").mkdir(parents=True)
    (fdir / "not-a-server" / "README.md").write_text("# notes\n", encoding="utf-8")

    items = index_build._mcp_items(fdir, tmp_path)  # pylint: disable=protected-access

    assert items == [{"name": "rider", "path": "features/common/mcp/rider"}]


def test_mcp_items_are_sorted_by_name(tmp_path, load_script):
    index_build = load_script("tooling/index_build.py")
    fdir = tmp_path / "features" / "common" / "mcp"
    for name in ("zulu", "alpha", "mike"):
        (fdir / name).mkdir(parents=True)
        (fdir / name / "meta.json").write_text("{}", encoding="utf-8")

    items = index_build._mcp_items(fdir, tmp_path)  # pylint: disable=protected-access

    assert [i["name"] for i in items] == ["alpha", "mike", "zulu"]


def test_a_loose_file_beside_the_servers_is_not_an_item(tmp_path, load_script):
    """`tags.json` and its kin sit next to the server dirs; only directories are servers."""
    index_build = load_script("tooling/index_build.py")
    fdir = tmp_path / "features" / "common" / "mcp"
    fdir.mkdir(parents=True)
    (fdir / "tags.json").write_text("{}", encoding="utf-8")

    assert index_build._mcp_items(fdir, tmp_path) == []  # pylint: disable=protected-access


def test_build_index_puts_mcp_servers_in_their_stacks_bucket(tmp_path, root, load_script):
    index_build = load_script("tooling/index_build.py")
    fake_root = _fake_root(tmp_path, root, servers=("code-review-graph",))

    index = index_build.build_index(fake_root)

    assert index["stacks"]["common"]["mcp"] == [
        {"name": "code-review-graph", "path": "features/common/mcp/code-review-graph"}
    ]


def test_the_generated_index_with_an_mcp_bucket_passes_its_own_schema(tmp_path, root,
                                                                      load_script):
    """index.schema.json closes `additionalProperties`, so an unlisted bucket blocks the write."""
    bl = load_script("engine/badger_lib.py")
    index_build = load_script("tooling/index_build.py")
    fake_root = _fake_root(tmp_path, root)

    index = index_build.build_index(fake_root)

    schema = bl.load_json(root / "schemas" / "index.schema.json")
    assert bl.validate(index, schema) == []


def test_index_build_writes_a_tree_carrying_mcp_and_then_reports_it_clean(tmp_path, root,
                                                                          load_script, capsys):
    index_build = load_script("tooling/index_build.py")
    fake_root = _fake_root(tmp_path, root)

    assert index_build.main(["--root", str(fake_root)]) == 0
    capsys.readouterr()

    assert index_build.main(["--root", str(fake_root), "--check"]) == 0


def test_the_index_build_docstring_documents_the_mcp_rule(load_script):
    """The module docstring is the --help text; an undocumented rule is an invisible one."""
    index_build = load_script("tooling/index_build.py")

    assert "mcp" in index_build.__doc__


# ── manifest.schema.json ─────────────────────────────────────────────────────

def test_the_manifest_feature_enum_admits_mcp(root, load_script):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "manifest.schema.json")

    assert "mcp" in schema["properties"]["entries"]["items"]["properties"]["feature"]["enum"]


# ── stack-mcp.schema.json ────────────────────────────────────────────────────

class TestStackMcpSchema:
    """`features/<stack>/stack-mcp.json` — which servers a stack wants, and how to launch them."""

    def _schema(self, root, load_script):
        bl = load_script("engine/badger_lib.py")
        return bl, bl.load_json(root / "schemas" / "stack-mcp.schema.json")

    def test_the_schema_ships(self, root):
        assert (root / "schemas" / "stack-mcp.schema.json").is_file()

    def test_a_describe_only_entry_needs_only_a_name(self, root, load_script):
        """A stack may name a server it can never launch — `rider` arrives user-global."""
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": [{"name": "rider"}]}, schema) == []

    def test_an_empty_server_list_is_valid(self, root, load_script):
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": []}, schema) == []

    def test_a_full_declaration_validates(self, root, load_script):
        bl, schema = self._schema(root, load_script)
        instance = {"servers": [{
            "name": "code-review-graph",
            "command": "python3 -m code_review_graph serve",
            "declare": True,
            "scope": "project",
            "env": {"GRAPH_HOME": "${HOME}/.graph"},
            "agentOverrides": {"hermes": {"command": "code-review-graph"}},
        }]}

        assert bl.validate(instance, schema) == []

    def test_declaring_a_server_without_a_command_is_refused(self, root, load_script):
        """`declare` writes a launch config; there is nothing to write without a command."""
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": [{"name": "x", "declare": True}]}, schema) != []

    def test_an_unknown_field_is_refused(self, root, load_script):
        bl, schema = self._schema(root, load_script)

        instance = {"servers": [{"name": "x", "generate_mcp_json": True}]}
        assert bl.validate(instance, schema) != []

    def test_the_removed_target_agents_field_is_not_carried_over(self, root, load_script):
        """`targetAgents` validated and was read by nothing (docs/authoring-a-feature.md)."""
        bl, schema = self._schema(root, load_script)

        instance = {"servers": [{"name": "x", "targetAgents": ["claude"]}]}
        assert bl.validate(instance, schema) != []

    def test_the_user_scope_is_accepted(self, root, load_script):
        """The one scope ai-badger proposes rather than writes (ADR-0014 decision 6)."""
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": [{"name": "x", "scope": "user"}]}, schema) == []

    def test_an_unknown_scope_is_refused(self, root, load_script):
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": [{"name": "x", "scope": "global"}]}, schema) != []

    def test_an_env_value_that_is_not_a_string_is_refused(self, root, load_script):
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": [{"name": "x", "env": {"KEY": 123}}]}, schema) != []

    def test_a_missing_servers_key_is_refused(self, root, load_script):
        bl, schema = self._schema(root, load_script)

        assert bl.validate({}, schema) != []

    def test_an_unnamed_server_is_refused(self, root, load_script):
        bl, schema = self._schema(root, load_script)

        assert bl.validate({"servers": [{"command": "x"}]}, schema) != []

    @pytest.mark.parametrize("agent", ["claude", "hermes", "copilot"])
    def test_every_agent_may_override_the_command(self, root, load_script, agent):
        bl, schema = self._schema(root, load_script)
        instance = {"servers": [{"name": "x", "agentOverrides": {agent: {"command": "y"}}}]}

        assert bl.validate(instance, schema) == []


def test_validate_all_has_a_coverage_decision_for_the_new_schema(root, load_script):
    """A schema validating nothing is the failure `undecided_schemas` exists to catch."""
    validate = load_script("tooling/validate.py")

    assert "stack-mcp.schema.json" in validate.SCHEMA_INSTANCES
    assert validate.undecided_schemas(root) == []
