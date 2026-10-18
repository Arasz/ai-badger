"""Describe-only catalog: curated intents for servers ai-badger does not install.

`features/<stack>/mcp/<server>/` (with `meta.json`) is a server ai-badger delivers;
`features/<stack>/mcp-catalog/<slug>/tools.json` only describes tools a host already exposes
(figma, tinyfish, claude.ai connectors). It must reach `load_catalog` and never anything that
offers or installs a server.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import ROOT

TD = "features/common/skills/mcp-index/scripts/tool_descriptions.py"
DESCRIBE_ONLY = sorted(ROOT.glob("features/*/mcp-catalog/*/tools.json"))
SHIPPED = {"plugin:figma:figma", "tinyfish", "claude.ai Exa", "claude.ai Hugging Face",
           "plugin:huggingface-skills:huggingface-skills", "plugin:context7:context7"}
VALID = {"read", "write", "run", "search"}


def _servers():
    return {json.loads(p.read_text(encoding="utf-8"))["server"]: p for p in DESCRIBE_ONLY}


def test_the_host_only_servers_are_described():
    assert set(_servers()) == SHIPPED


@pytest.mark.parametrize("path", DESCRIBE_ONLY, ids=lambda p: p.parent.name)
def test_each_describe_only_file_meets_the_tools_schema_and_taxonomy(path):
    import badger_lib as bl  # pylint: disable=import-outside-toplevel,import-error
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "mcp-server-tools.schema.json").read_text())
    tags = {t for c in json.loads((ROOT / "features/common/mcp-tags.json").read_text())[
        "categories"].values() for t in c["tags"]}

    assert bl.validate(data, schema) == []
    assert not (path.parent / "meta.json").exists()
    for tool in data["tools"]:
        assert set(tool["tags"]) <= tags, tool["name"]
        assert "source" not in tool


def test_load_catalog_reads_describe_only_entries(load_script):
    td = load_script(TD)

    catalog = td.load_catalog(ROOT)

    assert SHIPPED <= set(catalog)
    described = td.describe_tool("plugin:figma:figma", "get_design_context", "", catalog, VALID)
    assert described["origin"] == "catalog"


def test_a_plugin_listing_picks_up_a_bare_describe_only_entry(load_script, tmp_path):
    """Decorated name first, bare server second (SKILL.md gotcha 8)."""
    td = load_script(TD)
    entry = tmp_path / "features" / "common" / "mcp-catalog" / "foo"
    entry.mkdir(parents=True)
    (entry / "tools.json").write_text(json.dumps({"server": "foo", "tools": [
        {"name": "get_x", "intent": "Fetch an x from foo by id.", "tags": ["read"]}]}))

    catalog = td.load_catalog(tmp_path)

    assert td.describe_tool("plugin:p:foo", "get_x", "", catalog, VALID)["origin"] == "catalog"


def test_an_installable_entry_outranks_a_describe_only_one(load_script, tmp_path):
    td = load_script(TD)
    for kind, intent in (("mcp", "Installed server's curated intent."),
                         ("mcp-catalog", "Describe-only intent text.")):
        entry = tmp_path / "features" / "common" / kind / "foo"
        entry.mkdir(parents=True)
        (entry / "tools.json").write_text(json.dumps({"server": "foo", "tools": [
            {"name": "t", "intent": intent, "tags": ["read"]}]}))
        if kind == "mcp":
            (entry / "meta.json").write_text("{}")

    assert td.load_catalog(tmp_path)["foo"]["t"]["intent"] == "Installed server's curated intent."


def test_describe_only_servers_are_never_offered_or_delivered():
    """index.json lists the installable mcp servers; a describe-only one must not appear."""
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    text = json.dumps(index)

    assert "mcp-catalog" not in text
    for path in DESCRIBE_ONLY:
        assert not (ROOT / "features" / path.parts[-4] / "mcp" / path.parent.name).exists()


def test_schema_validation_covers_the_describe_only_files():
    validate = (ROOT / "tooling" / "validate.py").read_text(encoding="utf-8")

    assert '"features/*/mcp-catalog/*/tools.json"' in validate
    assert Path(ROOT / "features/common/mcp-catalog").is_dir()
