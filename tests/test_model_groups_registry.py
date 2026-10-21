"""Layer-0 tests: the model-groups registry leaf and the map it reads.

The leaf is `features/common/skills/task/scripts/model_groups.py` (pure, stdlib-only):
`load_groups(path)` / `preferred(group, groups)` / `resolve(level, explicit_model, groups)`,
the typed errors `UnknownLevel` and `RegistryInvalid`, and `validate_map(doc)` as the single
writer of the machine invariants (`validate_registry` is its alias). The map is
`features/common/data/model-groups.json`: four cost-tier groups, each an object with
`anchors` (family key -> version-less family name), `primary` (the anchor key whose model
leads the group) and `models` (the members).

Fixture rule: every invariant test builds its own document under `tmp_path` and passes the
path explicitly, so a broken canonical file cannot green them. Only the tests whose subject
is the shipped data read the shipped file.

The rules the leaf enforces, one per test:
  - the level vocabulary is exactly low, medium, high, top
  - a group is an object with anchors, a primary and a non-empty models array
  - every group anchors every declared family, and names no family the map does not declare
  - the primary anchor's model is the group's preferred member, and it leads the group
  - the tail follows in ascending (input, output) price; a zero price has no position, so
    a zero-priced member comes last
  - a zero price is legal only on a member whose license names an open-weight release
  - exactly one preferred member per group, listed first
  - ids are provider-qualified, and unique within a group
  - the top level carries the release lineage, the declared families and the provenance
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import warnings
from pathlib import Path

import pytest
from conftest import _test_write

LEAF = "features/common/skills/task/scripts/model_groups.py"
SEED = "features/common/data/model-groups.json"

# The level vocabulary the leaf accepts, and nothing else.
GROUPS = ("low", "medium", "high", "top")

# The families the map declares: every group anchors each of them.
FAMILIES = ("anthropic", "openai")

# The anchors each group carries: family key -> version-less family name.
ANCHORS = {
    "low": {"anthropic": "haiku", "openai": "luna"},
    "medium": {"anthropic": "sonnet", "openai": "sol"},
    "high": {"anthropic": "opus", "openai": "sol"},
    "top": {"anthropic": "fable", "openai": "astra"},
}

# A provenance block the leaf accepts: the leaderboard the prices came from.
SOURCE_BLOCK = {
    "leaderboard": {
        "path": "features/common/data/leaderboard.csv",
        "rows": 50,
        "sha256": "8" * 64,
    },
}

# The open-weight license markers the leaf accepts.
OPEN_LICENSES = ("Open Weight", "open", "Apache 2.0", "MIT", "BSD-3-Clause",
                  "GPL-3.0", "free", "public domain")


@pytest.fixture(name="mg")
def model_groups_fixture(load_script):
    """The registry leaf, loaded by path like every other standalone script."""
    return load_script(LEAF)


def _member(ident, family, price_in, price_out, *, preferred=False, lic="Proprietary",
            score=50.0, **kw):
    """One map member: id, family, preferred, pricing, license, score, evidence."""
    member = {
        "id": ident,
        "family": family,
        "preferred": preferred,
        "pricing": {"inputPerM": price_in, "outputPerM": price_out, "currency": "USD"},
        "license": lic,
        "score": score,
        "evidence": f"fixture pin for {ident}",
    }
    member.update(kw)
    return member


def _lead(level, *, ident=None, family=None, price_in=1.0, price_out=2.0, **kw):
    """The member behind a group's primary anchor: the one that leads and is preferred."""
    family = family if family is not None else ANCHORS[level]["anthropic"]
    if ident is None:
        ident = f"openrouter/{family}/model-{family}"
    member = _member(ident, family, price_in, price_out, **kw)
    if "preferred" not in kw:
        member["preferred"] = True
    return member


def _group(level, models, *, anchors=None, primary="anthropic"):
    """One map group: its anchors, the primary anchor key and its members."""
    return {
        "anchors": dict(anchors if anchors is not None else ANCHORS[level]),
        "primary": primary,
        "models": list(models),
    }


def _doc(**groups):
    """A map document with the four groups; each keyword overrides one group."""
    doc = {
        "frameworkVersion": "0.0.0",
        "registryVersion": 1,
        "measuredAt": "2026-09-05",
        "families": list(FAMILIES),
        "groups": {level: _group(level, [_lead(level)]) for level in GROUPS},
    }
    doc["groups"].update(groups)
    return doc


def _write_map(tmp_path, doc, name="model-groups.json"):
    return _test_write(tmp_path / name, json.dumps(doc), encoding="utf-8")


def _load(mg, tmp_path, doc):
    return mg.load_groups(_write_map(tmp_path, doc))


# ------------------------------------------------------------------ the leaf's surface
def test_validate_registry_is_an_alias_of_validate_map(mg):
    """The old validator name still resolves to the map's validator."""
    assert mg.validate_registry is mg.validate_map


# ------------------------------------------------------------------ the level vocabulary
def test_registry_refuses_a_group_outside_the_four_levels(mg, tmp_path):
    doc = _doc()
    doc["groups"]["extra"] = doc["groups"]["low"]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "extra" in str(exc_info.value)


def test_registry_missing_a_group_fails_naming_it(mg, tmp_path):
    doc = _doc()
    del doc["groups"]["top"]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "top" in str(exc_info.value)


def test_unknown_level_fails_loud(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    with pytest.raises(mg.UnknownLevel) as exc_info:
        mg.resolve("ultra", groups=groups)
    message = str(exc_info.value)
    assert "ultra" in message
    for level in GROUPS:
        assert level in message


def test_unknown_group_fails_loud_in_preferred(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    with pytest.raises(mg.UnknownLevel):
        mg.preferred("ultra", groups)


@pytest.mark.parametrize("level", ["Low", "LOW", "Medium", "HIGH", "TOP"])
def test_level_matching_is_case_sensitive(mg, tmp_path, level):
    groups = _load(mg, tmp_path, _doc())
    with pytest.raises(mg.UnknownLevel):
        mg.resolve(level, groups=groups)


def test_surrounding_whitespace_is_stripped(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    assert mg.resolve("  low  ", groups=groups) == _lead("low")["id"]


@pytest.mark.parametrize("level", ["", "   "])
def test_blank_level_is_absent_not_an_error(mg, tmp_path, level):
    groups = _load(mg, tmp_path, _doc())
    assert mg.resolve(level, groups=groups) is None


def test_absent_level_and_model_resolve_to_no_pin(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    assert mg.resolve(None, None, groups) is None
    assert mg.resolve(None, groups=groups) is None


def test_explicit_model_beats_level(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    assert mg.resolve("low", "openrouter/custom/override-1", groups) == \
        "openrouter/custom/override-1"


def test_blank_explicit_model_falls_back_to_level(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    assert mg.resolve("low", "", groups) == _lead("low")["id"]
    assert mg.resolve("low", "   ", groups) == _lead("low")["id"]


def test_stale_level_with_explicit_model_warns_but_wins_verbatim(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    with pytest.warns(UserWarning, match="ultra"):
        resolved = mg.resolve("ultra", "openrouter/custom/override-9", groups)
    assert resolved == "openrouter/custom/override-9"


def test_valid_non_deciding_level_is_silent(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = mg.resolve("low", "openrouter/custom/override-9", groups)
    assert resolved == "openrouter/custom/override-9"
    assert [w for w in caught if issubclass(w.category, UserWarning)] == []


# ------------------------------------------------------------------ the shape of a group
@pytest.mark.parametrize("key", ["anchors", "primary", "models"])
def test_group_missing_a_required_key_fails_naming_it(mg, tmp_path, key):
    doc = _doc()
    del doc["groups"]["low"][key]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert key in str(exc_info.value)


def test_group_missing_an_anchor_for_a_declared_family_is_refused(mg, tmp_path):
    doc = _doc()
    del doc["groups"]["low"]["anchors"]["openai"]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "openai" in str(exc_info.value)


def test_group_anchoring_a_family_the_map_does_not_declare_is_refused(mg, tmp_path):
    doc = _doc()
    doc["groups"]["low"]["anchors"]["mistral"] = "mistral"
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "mistral" in str(exc_info.value)


def test_group_naming_a_primary_anchor_it_does_not_anchor_is_refused(mg, tmp_path):
    doc = _doc()
    doc["groups"]["low"]["primary"] = "google"
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "google" in str(exc_info.value)


def test_primary_anchor_with_no_member_behind_it_is_refused(mg, tmp_path):
    doc = _doc()
    doc["groups"]["low"]["models"] = [
        _member("openrouter/openai/model-luna", "luna", 1, 2, preferred=True)]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "no member carries" in str(exc_info.value)


def test_preferred_member_must_be_the_primary_anchors_model(mg, tmp_path):
    """The group's preferred member is the model its primary anchor names."""
    low = _group("low", [_lead("low"),
                          _member("openrouter/openai/model-luna", "luna", 0.5, 1.0)],
                 primary="openai")
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "luna" in str(exc_info.value)


def test_group_with_two_preferred_members_is_rejected(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/meta/muse", "muse", 0.5, 1.0, preferred=True)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "preferred" in str(exc_info.value)


def test_group_with_no_preferred_member_is_rejected(mg, tmp_path):
    low = _group("low", [_member("openrouter/anthropic/model-haiku", "haiku", 1, 2)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "preferred" in str(exc_info.value)


def test_group_must_list_its_preferred_member_first(mg, tmp_path):
    low = _group("low", [_member("openrouter/meta/muse", "muse", 0.5, 1.0), _lead("low")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "first" in str(exc_info.value)


def test_group_leads_with_the_primary_anchors_model_not_the_cheapest(mg, tmp_path):
    """The lead stands where the anchor puts it; the price order governs the tail only."""
    lead = _lead("low", price_in=5.0, price_out=10.0)
    low = _group("low", [lead, _member("openrouter/meta/muse", "muse", 0.1, 0.2)])
    groups = _load(mg, tmp_path, _doc(low=low))
    assert [member["id"] for member in groups["low"]["models"]] == \
        [lead["id"], "openrouter/meta/muse"]
    assert mg.preferred("low", groups) == lead["id"]


# ------------------------------------------------------------------ the price order
def test_tail_follows_in_ascending_price(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/xiaomi/mimo", "mimo", 0.4, 0.8),
                          _member("openrouter/meta/muse", "muse", 0.5, 1.0)])
    groups = _load(mg, tmp_path, _doc(low=low))
    assert [member["id"] for member in groups["low"]["models"]] == \
        [_lead("low")["id"], "openrouter/xiaomi/mimo", "openrouter/meta/muse"]


def test_permuted_tail_is_rejected(mg, tmp_path):
    """Two tail entries swapped (prices attached) fail load: the order is pinned."""
    low = _group("low", [_lead("low"),
                          _member("openrouter/meta/muse", "muse", 0.5, 1.0),
                          _member("openrouter/xiaomi/mimo", "mimo", 0.4, 0.8)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "price order" in str(exc_info.value)


def test_order_key_is_input_then_output_not_a_sum(mg, tmp_path):
    """(1,100) before (2,3) is lexicographic; a blended-sum key would order them the other
    way (101 > 5) and must not pass."""
    low = _group("low", [_lead("low"),
                          _member("openrouter/meta/muse", "muse", 1, 100),
                          _member("openrouter/google/gemini", "gemini", 2, 3)])
    groups = _load(mg, tmp_path, _doc(low=low))
    assert [member["id"] for member in groups["low"]["models"]] == \
        [_lead("low")["id"], "openrouter/meta/muse", "openrouter/google/gemini"]


def test_a_blended_sum_order_is_refused(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/google/gemini", "gemini", 2, 3),
                          _member("openrouter/meta/muse", "muse", 1, 100)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "price order" in str(exc_info.value)


def test_input_tie_breaks_on_output(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/openai/sol", "sol", 2, 10),
                          _member("openrouter/openai/terra", "terra", 2, 12)])
    groups = _load(mg, tmp_path, _doc(low=low))
    assert [member["id"] for member in groups["low"]["models"]] == \
        [_lead("low")["id"], "openrouter/openai/sol", "openrouter/openai/terra"]


def test_output_order_within_one_input_price_is_pinned(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/openai/terra", "terra", 2, 12),
                          _member("openrouter/openai/sol", "sol", 2, 10)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "price order" in str(exc_info.value)


def test_a_zero_priced_open_weight_member_may_sit_last(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/z-ai/glm", "glm", 0, 0, lic="Open Weight")])
    groups = _load(mg, tmp_path, _doc(low=low))
    assert [member["id"] for member in groups["low"]["models"]] == \
        [_lead("low")["id"], "openrouter/z-ai/glm"]


def test_a_priced_member_after_a_zero_priced_one_is_refused(mg, tmp_path):
    low = _group("low", [_lead("low"),
                          _member("openrouter/z-ai/glm", "glm", 0, 0, lic="Open Weight"),
                          _member("openrouter/meta/muse", "muse", 0.5, 1.0)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "zero-priced members come last" in str(exc_info.value)


# ------------------------------------------------------------------ the price rule
@pytest.mark.parametrize("lic", OPEN_LICENSES)
def test_a_license_naming_an_open_weight_release_relaxes_the_zero_price(mg, tmp_path, lic):
    low = _group("low", [_lead("low", price_in=0, price_out=0, lic=lic)])
    groups = _load(mg, tmp_path, _doc(low=low))
    assert groups["low"]["models"][0]["license"] == lic


@pytest.mark.parametrize("price", [(0, 0), (0, 0.2), (0.2, 0)])
def test_a_member_that_is_not_open_weight_needs_a_price_above_zero(mg, tmp_path, price):
    low = _group("low", [_lead("low", price_in=price[0], price_out=price[1])])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "open-weight" in str(exc_info.value)


# ------------------------------------------------------------------ the shape of a member
@pytest.mark.parametrize("key", ["id", "family", "preferred", "pricing", "license", "score",
                                 "evidence"])
def test_member_missing_a_required_key_fails_naming_it(mg, tmp_path, key):
    member = _lead("low")
    del member[key]
    low = _group("low", [member])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert key in str(exc_info.value)


def test_member_with_an_unexpected_key_is_refused(mg, tmp_path):
    low = _group("low", [_lead("low", vendor="x")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "unexpected key" in str(exc_info.value)


@pytest.mark.parametrize("bare", ["opus", "sonnet", "haiku"])
def test_a_bare_alias_is_rejected(mg, tmp_path, bare):
    low = _group("low", [_lead("low", ident=bare)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert bare in str(exc_info.value)


def test_member_family_must_be_a_non_empty_string(mg, tmp_path):
    low = _group("low", [_lead("low", family="")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "non-empty family name" in str(exc_info.value)


def test_member_preferred_must_be_a_boolean(mg, tmp_path):
    low = _group("low", [_lead("low", preferred="yes")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "preferred must be a boolean" in str(exc_info.value)


def test_member_license_must_be_a_non_empty_string(mg, tmp_path):
    low = _group("low", [_lead("low", lic="")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "license must be a non-empty string" in str(exc_info.value)


def test_member_score_must_be_a_number(mg, tmp_path):
    low = _group("low", [_lead("low", score="high")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "score must be a number" in str(exc_info.value)


def test_member_evidence_must_be_a_non_empty_string(mg, tmp_path):
    low = _group("low", [_lead("low", evidence="")])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "evidence must be a non-empty string" in str(exc_info.value)


def test_member_pricing_must_be_an_object(mg, tmp_path):
    low = _group("low", [_lead("low", pricing=None)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "pricing must be an object" in str(exc_info.value)


@pytest.mark.parametrize("pricing", [
    {"inputPerM": "cheap", "outputPerM": 0.2, "currency": "USD"},
    {"inputPerM": 0.1, "outputPerM": -1, "currency": "USD"},
    {"inputPerM": True, "outputPerM": 0.2, "currency": "USD"},
])
def test_member_prices_must_be_numbers_at_or_above_zero(mg, tmp_path, pricing):
    low = _group("low", [_lead("low", pricing=pricing)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "must be a number >= 0" in str(exc_info.value)


def test_member_pricing_currency_must_be_usd(mg, tmp_path):
    low = _group("low", [_lead("low", pricing={"inputPerM": 0.1, "outputPerM": 0.2,
                                               "currency": "EUR"})])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "USD" in str(exc_info.value)


def test_member_pricing_rejects_an_unexpected_key(mg, tmp_path):
    low = _group("low", [_lead("low", pricing={"inputPerM": 0.1, "outputPerM": 0.2,
                                               "perM": 1})])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "unexpected key" in str(exc_info.value)


# ------------------------------------------------------------------ the id grammar
CONFORMANCE = json.loads((Path(__file__).parent / "fixtures" / "model-id-conformance.json")
                         .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CONFORMANCE, ids=lambda case: repr(case["id"]))
def test_model_id_conformance_at_registry_and_emit(mg, tmp_path, case):
    """Oracle: provider/segment grammar in the provider research spec, not the regex."""
    ident = case["id"]
    low = _group("low", [_lead("low", ident=ident)])
    doc = _doc(low=low)
    if case["valid"]:
        groups = _load(mg, tmp_path, doc)
        assert mg.preferred("low", groups) == ident
        assert mg.resolve("low", None, groups) == ident
    else:
        with pytest.raises(mg.RegistryInvalid, match="id"):
            _load(mg, tmp_path, doc)
        # Caller-supplied groups still pass through the emission guard.
        with pytest.raises(mg.RegistryInvalid, match="refusing to emit id"):
            mg.preferred("low", doc["groups"])


@pytest.mark.parametrize("case", CONFORMANCE, ids=lambda case: repr(case["id"]))
def test_model_id_schema_conformance(case):
    """Exercise the shipped schema with the same independent grammar oracle."""
    import jsonschema

    schema = json.loads((Path(__file__).parents[1] / "schemas" / "model-groups.schema.json")
                        .read_text(encoding="utf-8"))
    document = _doc(low=_group("low", [_lead("low", ident=case["id"])]))
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(document))
    assert bool(errors) is not case["valid"], [error.message for error in errors]


# ------------------------------------------------------------------ the top level
def test_an_unexpected_top_level_key_is_refused(mg, tmp_path):
    doc = _doc()
    doc["currency"] = "EUR"
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "unexpected top-level key" in str(exc_info.value)


@pytest.mark.parametrize("top", [
    {"registryVersion": 0}, {"registryVersion": "1"}, {"registryVersion": True},
    {"frameworkVersion": "1.2"}, {"frameworkVersion": 1},
    {"measuredAt": "09/05/2026"}, {"measuredAt": "2026-13-40"},
])
def test_top_level_malformations_fail_typed(mg, tmp_path, top):
    doc = _doc()
    doc.update(top)
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, doc)


def test_families_must_be_a_non_empty_array_of_names(mg, tmp_path):
    doc = _doc()
    doc["families"] = []
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "families" in str(exc_info.value)


def test_a_family_declared_twice_is_refused(mg, tmp_path):
    doc = _doc()
    doc["families"] = ["anthropic", "anthropic"]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "anthropic" in str(exc_info.value)


def test_a_source_block_with_a_complete_leaderboard_is_accepted(mg, tmp_path):
    doc = _doc()
    doc["source"] = SOURCE_BLOCK
    groups = _load(mg, tmp_path, doc)
    assert set(groups) == set(GROUPS)


def test_a_source_leaderboard_without_a_checksum_is_refused(mg, tmp_path):
    doc = _doc()
    doc["source"] = {"leaderboard": {"path": "features/common/data/leaderboard.csv", "rows": 50}}
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "sha256" in str(exc_info.value)


# ------------------------------------------------------------------ ids are unique per group
def test_duplicate_id_within_one_group_is_rejected(mg, tmp_path):
    lead = _lead("low")
    low = _group("low", [lead, _member(lead["id"], "haiku", 0.5, 1.0)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert lead["id"] in str(exc_info.value)


def test_cross_group_id_reuse_is_legal(mg, tmp_path):
    """The same id may appear in several groups: uniqueness is per-group."""
    shared = "openrouter/meta/muse-spark"
    doc = _doc(
        low=_group("low", [_lead("low", ident=shared)]),
        medium=_group("medium", [_lead("medium", ident=shared)]),
    )
    groups = _load(mg, tmp_path, doc)
    assert mg.preferred("low", groups) == shared
    assert mg.preferred("medium", groups) == shared


# ------------------------------------------------------------------ the typed errors
def test_errors_are_typed_and_value_compatible(mg):
    assert issubclass(mg.UnknownLevel, ValueError)
    assert issubclass(mg.RegistryInvalid, ValueError)
    assert mg.UnknownLevel is not mg.RegistryInvalid


def test_unknown_level_carries_the_invalid_value_and_the_valid_set(mg):
    err = mg.UnknownLevel("ultra")
    assert err.invalid_level == "ultra"
    assert err.valid_levels == ["low", "medium", "high", "top"]
    assert "ultra" in str(err)
    assert "low, medium, high, top" in str(err)


def test_registry_invalid_carries_errors_and_source(mg, tmp_path):
    path = _test_write(tmp_path / "model-groups.json", "[]", encoding="utf-8")
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        mg.load_groups(path)
    assert exc_info.value.errors
    assert "model-groups.json" in exc_info.value.source


# ------------------------------------------------------------------ a missing or broken file
def test_missing_registry_file_fails_loud(mg, tmp_path):
    missing = tmp_path / "no-such-registry.json"
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        mg.load_groups(missing)
    assert "no-such-registry.json" in str(exc_info.value)


def test_unparseable_registry_file_fails_typed(mg, tmp_path):
    path = _test_write(tmp_path / "model-groups.json", "{not json", encoding="utf-8")
    with pytest.raises(mg.RegistryInvalid):
        mg.load_groups(path)


@pytest.mark.parametrize("bad", [
    [], "model-groups", None, 42, True,
    {"frameworkVersion": "0.0.0", "registryVersion": 1, "measuredAt": "2026-09-05"},
    {"groups": None}, {"groups": []}, {"groups": "low"},
])
def test_malformed_documents_raise_registry_invalid(mg, tmp_path, bad):
    path = _test_write(tmp_path / "model-groups.json", json.dumps(bad), encoding="utf-8")
    with pytest.raises(mg.RegistryInvalid):
        mg.load_groups(path)


# ------------------------------------------------------------------ the shipped map
def test_shipped_map_has_the_four_groups_with_their_anchors_and_primaries(root):
    doc = json.loads((root / SEED).read_text(encoding="utf-8"))
    assert set(doc["groups"]) == set(GROUPS)
    for level, group in doc["groups"].items():
        assert group["primary"] in group["anchors"], level
        assert set(group["anchors"]) == set(doc["families"]), level


def test_shipped_map_group_leads_with_its_primary_anchor(root):
    doc = json.loads((root / SEED).read_text(encoding="utf-8"))
    for level, group in doc["groups"].items():
        anchor = group["anchors"][group["primary"]]
        lead = group["models"][0]
        assert lead["family"] == anchor, level
        assert lead["preferred"] is True, level


def test_shipped_map_tail_ascends_in_price_and_ends_with_the_zero_priced_members(root):
    doc = json.loads((root / SEED).read_text(encoding="utf-8"))
    for level, group in doc["groups"].items():
        last = None
        unpriced_seen = False
        for member in group["models"][1:]:
            price_in = member["pricing"]["inputPerM"]
            price_out = member["pricing"]["outputPerM"]
            if price_in <= 0 or price_out <= 0:
                unpriced_seen = True
                continue
            assert not unpriced_seen, f"{level}: a priced member follows a zero-priced one"
            key = (price_in, price_out)
            assert last is None or key >= last, f"{level}: {key} sorts before {last}"
            last = key


@pytest.mark.parametrize("level,expected", [
    ("low", "openrouter/openai/gpt-6-luna"),
    ("medium", "openrouter/openai/gpt-6.1-sol"),
    ("high", "openrouter/openai/gpt-5.4"),
    ("top", "openrouter/openai/gpt-5.5"),
])
def test_shipped_map_group_resolves_to_its_anchored_model(mg, root, level, expected):
    groups = mg.load_groups(root / SEED)
    assert mg.resolve(level, groups=groups) == expected


def test_shipped_map_records_the_sources_it_measured(root):
    """The map names the leaderboard it priced from, and the checksum and row count
    prove it."""
    source = json.loads((root / SEED).read_text(encoding="utf-8"))["source"]
    leaderboard = source["leaderboard"]
    assert leaderboard["path"] == "features/common/data/leaderboard.csv"
    digest = hashlib.sha256((root / leaderboard["path"]).read_bytes()).hexdigest()
    assert digest == leaderboard["sha256"]
    with io.StringIO((root / leaderboard["path"]).read_text(encoding="utf-8")) as handle:
        assert leaderboard["rows"] == len(list(csv.DictReader(handle)))
    assert source["modelStore"]["provider"] == "openrouter"
    assert source["generator"] == "tooling/generate_model_map.py"
    assert source["openrouterCatalogue"]["models"] >= 1


def test_shipped_map_reports_the_rows_it_left_out(root):
    """A row the map leaves out is reported with its reason; an unpriced row is named
    under unpriced and is one of the excluded rows too."""
    source = json.loads((root / SEED).read_text(encoding="utf-8"))["source"]
    assert source["unpriced"], "the map names no unpriced row"
    assert all(entry["model"] and entry["reason"] for entry in source["excluded"])
    excluded = {entry["model"] for entry in source["excluded"]}
    assert set(source["unpriced"]) <= excluded


def test_shipped_map_framework_version_equals_the_release_version(root):
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    doc = json.loads((root / SEED).read_text(encoding="utf-8"))
    assert doc["frameworkVersion"] == version
    assert doc["registryVersion"] == 3


def test_default_path_resolves_to_the_shipped_seed(mg, root):
    assert mg.load_groups() == mg.load_groups(root / SEED)


def test_resolve_without_a_path_reads_the_shipped_map(mg):
    assert mg.resolve("low") == "openrouter/openai/gpt-6-luna"


# ------------------------------------------------------------------ validate wiring
def test_schema_has_a_coverage_decision(root, load_script):
    """The new schema validates something: SCHEMA_INSTANCES maps it, the glob hits the
    canonical seed, and no schema is left undecided."""
    validate = load_script("tooling/validate.py")
    assert "model-groups.schema.json" in validate.SCHEMA_INSTANCES
    matched = [p for pattern in validate.SCHEMA_INSTANCES["model-groups.schema.json"]
               for p in sorted(root.glob(pattern))]
    assert root / SEED in matched
    assert validate.undecided_schemas(root) == []


def test_canonical_seed_validates_against_its_schema(root, load_script):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "model-groups.schema.json")
    assert bl.validate(bl.load_json(root / SEED), schema) == []


def test_registry_invariants_hold_on_the_real_root(root, load_script):
    """validate.py is the single enforcer of the machine invariants: the leaf loads from
    validate's own tree and the real root reports no gaps."""
    validate = load_script("tooling/validate.py")
    assert validate.model_groups_leaf() is not None
    assert validate.model_registry_gaps(root) == []


def test_broken_registry_is_a_gap(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    demo = tmp_path / "features" / "demo" / "data"
    demo.mkdir(parents=True)
    _test_write(demo / "model-groups.json", json.dumps({"groups": {}}),
                encoding="utf-8")
    gaps = validate.model_registry_gaps(tmp_path)
    assert gaps
    assert all("model-groups.json" in gap for gap in gaps)


def test_absent_registry_is_no_gap_for_stub_trees(tmp_path, load_script):
    """A tree with no registry instance (a stub tree, a skill-only fixture) passes: the
    check is unconditional on present files, not a presence requirement."""
    validate = load_script("tooling/validate.py")
    assert validate.model_registry_gaps(tmp_path) == []


# ------------------------------------------------------------------ scaffold delivery
def test_scaffold_delivers_the_registry_with_a_local_schema_reference(make_scaffolder, root):
    result = make_scaffolder(skills=["task"]).run(
        generated_at="2026-09-05T00:00:00Z")
    delivered = make_scaffolder.target / ".ai-badger" / "model-groups.json"
    assert delivered.is_file()
    source = json.loads((root / SEED).read_text(encoding="utf-8"))
    copy = json.loads(delivered.read_text(encoding="utf-8"))
    assert copy.pop("$schema") == "./schemas/model-groups.schema.json"
    source.pop("$schema")
    assert copy == source
    recorded = [entry for entry in result["manifest"]["entries"]
                if entry.get("target") == ".ai-badger/model-groups.json"]
    assert len(recorded) == 1
    assert recorded[0]["source"] == "features/common/data/model-groups.json"
    assert recorded[0]["seedOnce"] is False


def test_rescaffold_leaves_registry_and_manifest_byte_identical(make_scaffolder):
    aib = make_scaffolder.target / ".ai-badger"
    make_scaffolder(skills=["task"]).run(generated_at="2026-09-05T00:00:00Z")
    first_registry = (aib / "model-groups.json").read_bytes()
    first_manifest = (aib / "manifest.json").read_bytes()
    make_scaffolder(skills=["task"]).run(generated_at="2026-09-05T00:00:00Z")
    assert (aib / "model-groups.json").read_bytes() == first_registry
    assert (aib / "manifest.json").read_bytes() == first_manifest


def test_no_bare_id_in_the_scaffolded_registry(make_scaffolder, mg):
    make_scaffolder(skills=["task"]).run(generated_at="2026-09-05T00:00:00Z")
    delivered = json.loads(
        (make_scaffolder.target / ".ai-badger" / "model-groups.json"
         ).read_text(encoding="utf-8"))
    ids = [member["id"] for group in delivered["groups"].values()
           for member in group["models"]]
    assert ids
    assert all("/" in ident for ident in ids), ids
    assert all(mg.MODEL_ID_RE.fullmatch(ident) for ident in ids), ids
