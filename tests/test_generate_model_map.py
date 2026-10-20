"""Tests for tooling/generate_model_map.py: the refresh rule that re-renders the model map.

The generator writes the map, so its rules are pinned here rather than only in its
docstring: the tier a price lands in, the family a model belongs to, the model line a tier
keeps, the order a group lists its members in, and what the rule reports about a row it
leaves out.

Every fixture is a miniature source set built under tmp_path (a leaderboard CSV, a model
store, a catalogue snapshot); nothing here reads the machine's own model store, the
repository's map, or the network. The CLI end to end (the `--check` drift path) is covered
by the meta-gate's provocation in tests/test_every_check_can_fail.py.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from conftest import ROOT

GENERATOR = "tooling/generate_model_map.py"

LEADERBOARD_HEADER = [
    "rank", "model", "creator", "sourceType", "overallScore", "evidenceStatus",
    "interval90Lower", "interval90Upper", "coding", "agentic", "reasoning", "knowledge",
    "math", "multimodalGrounded", "multilingual", "instructionFollowing", "inputPrice",
    "outputPrice", "intervalScope", "intervalCoverageValidated", "orderingMeaning",
]

#: One anchor row per group, so every group has the member its primary anchor names and
#: the map the generator renders is a valid one.
ANCHOR_ROWS = [
    _row := None,
]


def _row(rank: int, model: str, creator: str, price_in: str, price_out: str,
         score: str = "80", source_type: str = "Proprietary") -> dict:
    """One leaderboard row. The empty price pair is how the CSV says unpriced."""
    values = [str(rank), model, creator, source_type, score, "supported", "0", "0", "0",
              "0", "0", "0", "0", "0", "0", "0", price_in, price_out, "", "",
              "Point-estimate order."]
    return dict(zip(LEADERBOARD_HEADER, values))


ANCHOR_ROWS = [
    _row(1, "Claude Haiku 5.5", "Anthropic", "0.1", "0.5"),
    _row(2, "Claude Sonnet 5.5", "Anthropic", "2", "10"),
    _row(3, "Claude Opus 5.5", "Anthropic", "4", "20"),
    _row(4, "Claude Fable 5.1", "Anthropic", "10", "50"),
]

ANCHOR_LISTINGS = [
    {"id": "anthropic/claude-haiku-5-5", "name": "OpenRouter: Claude Haiku 5.5",
     "cost": {"input": 0.1, "output": 0.5}},
    {"id": "anthropic/claude-sonnet-5-5", "name": "OpenRouter: Claude Sonnet 5.5",
     "cost": {"input": 2, "output": 10}},
    {"id": "anthropic/claude-opus-5-5", "name": "OpenRouter: Claude Opus 5.5",
     "cost": {"input": 4, "output": 20}},
    {"id": "anthropic/claude-fable-5-1", "name": "OpenRouter: Claude Fable 5.1",
     "cost": {"input": 10, "output": 50}},
]


def _sources(tmp_path: Path, rows: list, listings: list, catalogue_ids: list) -> Path:
    """A miniature source set: the leaderboard, pi's model store, the catalogue snapshot."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    with (data / "leaderboard.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEADERBOARD_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    (data / "models-store.json").write_text(
        json.dumps({"openrouter": {"models": listings}}, indent=2), encoding="utf-8")
    (data / "openrouter-models.json").write_text(
        json.dumps({"source": "https://openrouter.ai/api/v1/models",
                    "checkedAt": "2026-10-20", "ids": catalogue_ids}, indent=2),
        encoding="utf-8")
    return data


def _listing(ident: str, name: str, price_in: float = 1.0, price_out: float = 2.0) -> dict:
    """One openrouter listing in pi's model store."""
    return {"id": ident, "name": f"OpenRouter: {name}",
            "cost": {"input": price_in, "output": price_out}}


def _generator():
    """The generator module, imported the way a script is."""
    import importlib.util
    path = ROOT / GENERATOR
    spec = importlib.util.spec_from_file_location("generate_model_map", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _render(tmp_path: Path, rows: list, listings: list, catalogue_ids: list | None = None):
    """The map the generator renders from a source set, and what it reports about the rows."""
    generator = _generator()
    data = _sources(tmp_path, rows, listings, catalogue_ids or [])
    return generator.build_map(
        generator.load_leaderboard(data / "leaderboard.csv"),
        generator.load_store(data / "models-store.json"),
        generator.load_catalogue(data / "openrouter-models.json"),
        data / "openrouter-models.json",
        data / "leaderboard.csv",
        data / "models-store.json",
        "2026-10-20", "0.207.4")


def _render_with(tmp_path: Path, rows: list, listings: list, catalogue_ids: list | None = None):
    """The same, on top of the anchor rows every group needs."""
    return _render(tmp_path, ANCHOR_ROWS + rows, ANCHOR_LISTINGS + listings, catalogue_ids)


def _members(document: dict, group: str) -> list:
    """The member ids of one group, in the order the generator lists them."""
    return [member["id"] for member in document["groups"][group]["models"]]


# ------------------------------------------------------------------ 1 the tier rule
@pytest.mark.parametrize("price,group", [
    ("0", "low"), ("0.1", "low"), ("0.14", "medium"), ("2", "medium"),
    ("2.5", "high"), ("4", "high"), ("10", "top"), ("30", "top"),
])
def test_a_row_lands_in_the_tier_its_input_price_reaches(tmp_path, price, group):
    """A tier is the rung its input price sits under: low 0.1, medium 2, high 4, top the rest."""
    rows = [_row(9, "Model One", "Vendor", price, "5")]
    listings = [_listing("vendor/model-one", "Model One")]
    document, _ = _render_with(tmp_path, rows, listings)
    assert "openrouter/vendor/model-one" in _members(document, group)


# ------------------------------------------------------------------ 2 the family rule
def test_the_family_is_the_line_word_for_the_anchored_vendors_and_the_product_name_for_the_rest(
        tmp_path):
    """Anthropic and OpenAI models are named by their line word; the rest by their product."""
    rows = [
        _row(9, "GPT-6.1 Sol", "OpenAI", "2", "10"),
        _row(10, "MiMo-V2.6-Pro", "Xiaomi", "2", "10"),
        _row(11, "dots3-note Preview", "Dots Studio", "2", "10"),
    ]
    listings = [
        _listing("openai/gpt-6.1-sol", "GPT-6.1 Sol"),
        _listing("xiaomi/mimo-v2.6-pro", "MiMo-V2.6-Pro"),
        _listing("dots-studio/dots-3-note-preview", "dots3-note Preview"),
    ]
    document, _ = _render_with(tmp_path, rows, listings)
    families = {member["id"]: member["family"]
                for member in document["groups"]["medium"]["models"]}
    assert families["openrouter/openai/gpt-6.1-sol"] == "sol"
    assert families["openrouter/xiaomi/mimo-v2.6-pro"] == "mimo"
    assert families["openrouter/dots-studio/dots-3-note-preview"] == "dots3-note"
    assert families["openrouter/anthropic/claude-sonnet-5-5"] == "sonnet"


# ------------------------------------------------------------------ 3 the line rule
def test_a_tier_keeps_the_newest_model_of_each_model_line(tmp_path):
    """Two rows of one line (Claude Opus) in one tier: the newer one by rank keeps the slot."""
    rows = [_row(9, "Claude Opus 4.8", "Anthropic", "5", "25"),
            _row(10, "Claude Opus 4.6", "Anthropic", "5", "25")]
    listings = [_listing("anthropic/claude-opus-4-8", "Claude Opus 4.8"),
                _listing("anthropic/claude-opus-4-6", "Claude Opus 4.6")]
    document, _ = _render_with(tmp_path, rows, listings)
    assert "openrouter/anthropic/claude-opus-4-8" in _members(document, "top")
    assert "openrouter/anthropic/claude-opus-4-6" not in _members(document, "top")


# ------------------------------------------------------------------ 4 the order rule
def test_a_group_leads_with_its_primary_anchor_then_ascends_by_price(tmp_path):
    """The primary anchor's model leads; the rest follow in ascending price, the
    zero-priced open-weight members last."""
    rows = [
        _row(9, "Model Cheap", "Vendor", "0.1", "0.5"),
        _row(10, "Model Free", "Vendor", "0", "0", source_type="Open Weight"),
    ]
    listings = [
        _listing("vendor/model-cheap", "Model Cheap"),
        _listing("vendor/model-free", "Model Free", 0.0, 0.0),
    ]
    document, _ = _render_with(tmp_path, rows, listings)
    assert _members(document, "low") == [
        "openrouter/anthropic/claude-haiku-5-5",  # the primary anchor's model leads
        "openrouter/vendor/model-cheap",          # then the ascending tail
        "openrouter/vendor/model-free",           # a zero price has no position, so it is last
    ]


# ------------------------------------------------------------------ 5 the rows left out
def test_a_row_the_leaderboard_leaves_unpriced_is_reported_by_name(tmp_path):
    """The leaderboard prices the map; a row it leaves unpriced is named, not dropped quietly."""
    rows = [_row(9, "Model Unpriced", "Vendor", "", "")]
    listings = [_listing("vendor/model-unpriced", "Model Unpriced")]
    document, report = _render_with(tmp_path, rows, listings)
    assert report["unpriced"] == ["Model Unpriced"]
    assert not any("vendor/model-unpriced" in _members(document, group)
                   for group in document["groups"])


def test_a_row_with_no_openrouter_listing_is_excluded_with_its_reason(tmp_path):
    """A model no provider in pi's store lists has no id, so it stays out with its reason."""
    rows = [_row(9, "Model Unknown", "Vendor", "1", "2")]
    document, report = _render_with(tmp_path, rows, [])
    assert report["unpriced"] == []
    assert [entry["model"] for entry in report["excluded"]] == ["Model Unknown"]
    assert "no OpenRouter listing" in report["excluded"][0]["reason"]
    assert not any("model-unknown" in _members(document, group)
                   for group in document["groups"])


def test_a_row_resolving_only_to_a_free_listing_is_excluded(tmp_path):
    """A free id cannot carry a paid price, so the row stays out with that reason."""
    rows = [_row(9, "Model Free", "Vendor", "1", "2")]
    listings = [_listing("vendor/model-free:free", "Model Free", 0.0, 0.0)]
    document, report = _render_with(tmp_path, rows, listings)
    assert [entry["model"] for entry in report["excluded"]] == ["Model Free"]
    assert "free listing" in report["excluded"][0]["reason"]
    assert not any("model-free" in _members(document, group)
                   for group in document["groups"])


def test_the_source_block_names_the_unpriced_and_the_excluded_rows(tmp_path):
    """The map carries the provenance, so the decision is checkable from the data."""
    rows = [_row(9, "Model Unpriced", "Vendor", "", ""),
            _row(10, "Model Unknown", "Vendor", "1", "2")]
    listings = [_listing("vendor/model-unpriced", "Model Unpriced")]
    document, _ = _render_with(tmp_path, rows, listings)
    source = document["source"]
    assert source["unpriced"] == ["Model Unpriced"]
    excluded = {entry["model"]: entry["reason"] for entry in source["excluded"]}
    assert set(excluded) == {"Model Unknown", "Model Unpriced"}
    assert "no OpenRouter listing" in excluded["Model Unknown"]
    assert "no cost" in excluded["Model Unpriced"]
    assert source["leaderboard"]["rows"] == 6
    assert source["generator"] == GENERATOR
