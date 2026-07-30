"""A host's decorated server name must still reach the catalog's key (issue #203).

`claude mcp list` names a plugin-provided server `plugin:<plugin>:<server>` and a claude.ai
connector `claude.ai <Name>`, while the mcp catalog is keyed on the server itself. Every name
below is verbatim from `claude mcp list` on a 2026-07-30 install.
"""

from __future__ import annotations

import pytest

SCRIPT = "features/common/skills/mcp-index/scripts/tool_descriptions.py"

# Verbatim `claude mcp list` names: bare, plugin-provided, and a claude.ai connector.
BARE = ("code-review-graph", "hermes", "rider")
PLUGIN_PREFIXED = (
    ("plugin:github:github", "github"),
    ("plugin:playwright:playwright", "playwright"),
    ("plugin:microsoft-docs:microsoft-learn", "microsoft-learn"),
    ("plugin:dotnet-claude-kit:cwm-roslyn-navigator", "cwm-roslyn-navigator"),
    ("plugin:ai-badger:code-review-graph", "code-review-graph"),
)
CONNECTORS = (
    ("claude.ai Google Drive", "Google Drive", "google-drive"),
    ("claude.ai Microsoft 365", "Microsoft 365", "microsoft-365"),
)


@pytest.fixture(name="td")
def _td(load_script):
    return load_script(SCRIPT)


def _entry(intent: str) -> dict:
    return {"name": "a_tool", "intent": intent, "tags": ["search"]}


# ── which keys a listing name may match ──────────────────────────────────────

@pytest.mark.parametrize("name", BARE)
def test_an_undecorated_name_is_its_own_only_key(td, name):
    """Nothing to strip: a bare listing name matches exactly the catalog key it already is."""
    assert td.catalog_keys(name) == [name]


@pytest.mark.parametrize("listed,server", PLUGIN_PREFIXED)
def test_a_plugin_prefixed_name_also_offers_the_bare_server(td, listed, server):
    """`plugin:<plugin>:<server>` reaches `<server>` — the plugin is routing, not identity."""
    assert td.catalog_keys(listed) == [listed, server]


def test_a_connector_name_offers_both_the_display_name_and_its_slug(td):
    """A `claude.ai <Name>` connector can be curated under the name or a directory-shaped slug."""
    for listed, display, slug in CONNECTORS:
        assert td.catalog_keys(listed) == [listed, display, slug]


def test_the_decorated_name_always_comes_first(td):
    """Order is precedence: the most specific key the catalog could hold is tried first."""
    assert td.catalog_keys("plugin:ai-badger:code-review-graph")[0] == (
        "plugin:ai-badger:code-review-graph")


def test_a_plugin_segment_containing_no_server_is_left_whole(td):
    """`plugin:x` is not the two-segment shape, so there is nothing to strip."""
    assert td.catalog_keys("plugin:x") == ["plugin:x"]


# ── resolving curation through the alias ─────────────────────────────────────

def test_curation_reaches_a_plugin_prefixed_server(td):
    """The defect in issue #203: the catalog's bare key must serve the decorated listing name."""
    catalog = {"code-review-graph": {"a_tool": _entry("The curated wording.")}}
    resolved = td.catalog_tools(catalog, "plugin:ai-badger:code-review-graph")
    assert resolved["a_tool"]["intent"] == "The curated wording."


def test_an_exactly_keyed_decorated_entry_outranks_the_bare_one(td):
    """A catalog that names the plugin explicitly meant that plugin's server, not the other."""
    catalog = {
        "plugin:ai-badger:code-review-graph": {"a_tool": _entry("Curated for the plugin copy.")},
        "code-review-graph": {"a_tool": _entry("Curated for the project copy.")},
    }
    assert td.catalog_tools(catalog, "plugin:ai-badger:code-review-graph")["a_tool"]["intent"] == (
        "Curated for the plugin copy.")
    assert td.catalog_tools(catalog, "code-review-graph")["a_tool"]["intent"] == (
        "Curated for the project copy.")


def test_two_plugins_shipping_one_server_name_keep_separate_curation(td):
    """Same-named servers from different plugins are different servers; the prefix says which."""
    catalog = {
        "plugin:one:shared": {"a_tool": _entry("The first plugin's tool.")},
        "plugin:two:shared": {"a_tool": _entry("The second plugin's tool.")},
    }
    assert td.catalog_tools(catalog, "plugin:one:shared")["a_tool"]["intent"] == (
        "The first plugin's tool.")
    assert td.catalog_tools(catalog, "plugin:two:shared")["a_tool"]["intent"] == (
        "The second plugin's tool.")


def test_a_bare_listing_name_does_not_borrow_a_decorated_catalog_key(td):
    """Matching widens the listing name, never the catalog key: `foo` is not `plugin:a:foo`."""
    catalog = {"plugin:ai-badger:code-review-graph": {"a_tool": _entry("Plugin curation.")}}
    assert td.catalog_tools(catalog, "code-review-graph") == {}


def test_an_unknown_server_resolves_to_no_curation(td):
    """No key matches, so the heuristics carry the server — not a KeyError."""
    assert td.catalog_tools({"code-review-graph": {}}, "plugin:jetbrains:rider") == {}


def test_describe_tool_takes_the_curated_entry_through_the_prefix(td):
    """`describe_tool` is where the overlay lands, so it must resolve the name too."""
    catalog = {"code-review-graph": {"a_tool": _entry("The curated wording.")}}
    described = td.describe_tool("plugin:ai-badger:code-review-graph", "a_tool",
                                 "The host's own description.", catalog, {"search"})
    assert described["intent"] == "The curated wording."
    assert described["origin"] == "catalog"
