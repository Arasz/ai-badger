"""Layer-0 tests: the model-groups registry leaf and its canonical seed.

The leaf is `features/common/skills/task/scripts/model_groups.py` (pure, stdlib-only),
exposing `load_groups() / preferred(group) / resolve(level, explicit_model)` with typed
errors `UnknownLevel` and `RegistryInvalid`. The seed is
`features/common/data/model-groups.json`, shaped by `schemas/model-groups.schema.json`.

Fixture rule (plan Layer 0): every invariant test builds its own registry under `tmp_path`
and passes the path explicitly, so a broken canonical file cannot green them. Only L0-11
reads the shipped file. Fixtures assert ORDER + preferred/tail invariants and permute the
middle — never absolute prices — except the verbatim seed pin in L0-11.

Source note: the `model-tiers-research` memory context was unavailable to this lane, so
every fixture below is grounded in the task brief range measured 2026-09-05 and verified
in-session. Each fixture carries that provenance inline.

Extra probes beyond L0-1..L0-11 (QA wave, leaf-applicable only):

  T-MISS      missing/unreadable/unparseable file fails loud, never a silent default
  T-ONEPREF   exactly one preferred per group, and it is index 0
  T-DUP       duplicate id within one group fails; cross-group reuse is legal
  T-ALIAS     aliases are documentary: resolve/preferred return the id verbatim
  T-LEX       the order key is lexicographic (input, output), not a blended sum
  T-ERRSHAPE  UnknownLevel/RegistryInvalid carry the invalid value, the valid set,
              and the source; both stay ValueError-compatible (plan RED shape)
  T-A7        a non-deciding stale level warns but the explicit model still wins verbatim
  T-CASE      levels are case-sensitive lowercase: "Low" is unknown, not low
  T-EMPTY     empty/blank level is absent, not an error
  T-NOPIN     absent level and absent model resolve to no pin (None: inherit)
  T-FAKESHAPE non-object documents and missing groups fail typed, never raw TypeError
  T-CRASH     a wave of malformed members/fields: every one raises RegistryInvalid
"""
from __future__ import annotations

import json
import warnings

import pytest
from conftest import _test_write

LEAF = "features/common/skills/task/scripts/model_groups.py"
SEED = "features/common/data/model-groups.json"

# Provenance stamp every fixture below repeats inline: brief-range grounding, because the
# memory context was unavailable to this lane. See the module docstring.
SOURCE = "task-brief 2026-09-05"


@pytest.fixture()
def mg(load_script):
    """The registry leaf, loaded by path like every other standalone script."""
    return load_script(LEAF)


def _m(id, price_in, price_out, preferred=False, **kw):
    """One registry member. Prices are ordering keys for the permutation tests, never
    pass conditions — except the verbatim seed pin in L0-11. (source: task-brief 2026-09-05)"""
    member = {
        "id": id,
        "preferred": preferred,
        "pricing": {"inputPerM": price_in, "outputPerM": price_out, "currency": "USD"},
        "evidence": f"layer-0 fixture pin for {id} (source: {SOURCE})",
    }
    member.update(kw)
    return member


def _doc(*, low, medium=None, high=None, **top):
    """A registry document around the given low group; medium/high default to a minimal
    valid single-preferred group. (source: task-brief 2026-09-05)"""
    groups = {
        "low": low,
        "medium": medium if medium is not None else [_m("openrouter/m/med", 1, 2, True)],
        "high": high if high is not None else [_m("openrouter/h/high", 1, 2, True)],
    }
    doc = {
        "frameworkVersion": "0.0.0",
        "registryVersion": 1,
        "measuredAt": "2026-09-05",
        "source": SOURCE,
        "groups": groups,
    }
    doc.update(top)
    return doc


def _write_registry(tmp_path, doc, name="model-groups.json"):
    return _test_write(tmp_path / name, json.dumps(doc), encoding="utf-8")


def _load(mg, tmp_path, doc):
    return mg.load_groups(_write_registry(tmp_path, doc))


# ------------------------------------------------------------------ L0-1 closed level set
def test_registry_has_exactly_low_medium_high(mg, tmp_path):
    low = [_m("openrouter/l/low", 1, 2, True)]
    doc = _doc(low=low)
    doc["groups"]["extra"] = list(low)
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "extra" in str(exc_info.value)


def test_registry_missing_a_group_fails_naming_it(mg, tmp_path):
    doc = _doc(low=[_m("openrouter/l/low", 1, 2, True)])
    del doc["groups"]["high"]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert "high" in str(exc_info.value)


# ------------------------------------------------------------------ L0-2 qualified ids only
@pytest.mark.parametrize("bare", ["opus", "sonnet", "haiku"])
def test_every_id_is_openrouter_qualified(mg, tmp_path, bare):
    doc = _doc(low=[_m(bare, 1, 2, True)])
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, doc)
    assert bare in str(exc_info.value)


def test_single_segment_openrouter_id_is_rejected(mg, tmp_path):
    doc = _doc(low=[_m("openrouter/onlyone", 1, 2, True)])
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, doc)


# ------------------------------------------------------------------ L0-3 low prefers glm-5.3-flash
def test_preferred_is_index_zero_low(mg, tmp_path):
    """The preferred id is neither alphabetically first (aaa-model) nor a guess: it is the
    qualified glm-5.3-flash pin. (source: task-brief 2026-09-05)"""
    low = [
        _m("openrouter/z-ai/glm-5.3-flash", 0.075, 0.25, True),
        _m("openrouter/aaa/aaa-model", 0.5, 0.5),
        _m("openrouter/anthropic/claude-haiku-4.5", 1, 5),
    ]
    groups = _load(mg, tmp_path, _doc(low=low))
    assert mg.preferred("low", groups) == "openrouter/z-ai/glm-5.3-flash"


# ------------------------------------------------------------------ L0-4 high prefers deepseek-v4.1-flash
def test_preferred_is_deepseek_v41_flash_high_and_spark_medium(mg, tmp_path):
    """High now prefers the performance-adequate deepseek pin (measured 2026-09-11) while
    medium keeps the contributor; the displaced contributor stays visible as high's demoted
    tail. (source: task-brief 2026-09-11; medium pin per task-brief 2026-09-05)"""
    medium = [
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2, True),
        _m("openrouter/anthropic/claude-sonnet-5", 2, 10,
           status="demoted", revisionWatch=True),
    ]
    high = [
        _m("openrouter/deepseek/deepseek-v4.1-flash", 0.15, 0.6, True,
           evidence="High-tier preferred from 2026-09-11: performance-adequate flash pin "
                    "(source: task-brief 2026-09-11)."),
        _m("openrouter/anthropic/claude-fable-5.1", 10, 50),
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2,
           status="demoted", revisionWatch=True),
    ]
    groups = _load(mg, tmp_path, _doc(
        low=[_m("openrouter/l/low", 1, 2, True)], medium=medium, high=high))
    assert mg.preferred("medium", groups) == "openrouter/meta/muse-spark-1.3-contributor"
    assert mg.preferred("high", groups) == "openrouter/deepseek/deepseek-v4.1-flash"


# ------------------------------------------------------------------ L0-5 sonnet-5 last in medium
def test_sonnet_5_is_last_in_medium(mg, tmp_path):
    medium = [
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2, True),
        _m("openrouter/openai/gpt-5.6-sol", 2, 10),
        _m("openrouter/anthropic/claude-sonnet-5", 2, 10,
           status="demoted", revisionWatch=True),
    ]
    groups = _load(mg, tmp_path, _doc(
        low=[_m("openrouter/l/low", 1, 2, True)], medium=medium))
    assert groups["medium"][-1]["id"].endswith("claude-sonnet-5")


def test_demoted_member_mid_list_is_rejected(mg, tmp_path):
    """The demoted-tail exemption pins position: demoted anywhere but the tail fails load."""
    medium = [
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2, True),
        _m("openrouter/anthropic/claude-sonnet-5", 2, 10,
           status="demoted", revisionWatch=True),
        _m("openrouter/openai/gpt-5.6-terra", 2, 12),
    ]
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, _doc(
            low=[_m("openrouter/l/low", 1, 2, True)], medium=medium))


# ------------------------------------------------------------------ L0-6 fable-5.1 last deciding in high
def test_fable_5_1_is_last_deciding_in_high(mg, tmp_path):
    high = [
        _m("openrouter/deepseek/deepseek-v4.1-flash", 0.15, 0.6, True,
           evidence="High-tier preferred from 2026-09-11 (source: task-brief 2026-09-11)."),
        _m("openrouter/anthropic/claude-opus-5", 5, 25),
        _m("openrouter/anthropic/claude-fable-5.1", 10, 50),
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2,
           status="demoted", revisionWatch=True),
    ]
    groups = _load(mg, tmp_path, _doc(
        low=[_m("openrouter/l/low", 1, 2, True)], high=high))
    deciding = [m for m in groups["high"] if m.get("status") != "demoted"]
    assert deciding[-1]["id"].endswith("claude-fable-5.1")


# ------------------------------------------------------------------ L0-7 preferred-first, price-sorted
def test_list_order_is_preferred_first_then_price_sorted(mg, tmp_path):
    low = [
        _m("openrouter/l/cheap", 0.1, 0.2, True),
        _m("openrouter/l/mid-a", 0.4, 0.8),
        _m("openrouter/l/mid-b", 0.5, 1.0),
    ]
    groups = _load(mg, tmp_path, _doc(low=low))
    assert groups["low"][0]["preferred"] is True


def test_permuted_middle_is_rejected(mg, tmp_path):
    """Two middle entries swapped (prices attached) fail load: order is pinned, not advisory."""
    low = [
        _m("openrouter/l/cheap", 0.1, 0.2, True),
        _m("openrouter/l/mid-b", 0.5, 1.0),
        _m("openrouter/l/mid-a", 0.4, 0.8),
    ]
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, _doc(low=low))


def test_cheapest_first_is_not_enough_without_preferred_first(mg, tmp_path):
    """Preferred-first and price-ordered must hold together: cheapest at [0] without the
    preferred flag still fails."""
    low = [
        _m("openrouter/l/cheap", 0.1, 0.2),
        _m("openrouter/l/other", 0.5, 1.0, True),
    ]
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, _doc(low=low))


# ------------------------------------------------------------------ L0-8 unknown level fails loud
def test_unknown_level_fails_loud(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    with pytest.raises(mg.UnknownLevel) as exc_info:
        mg.resolve("ultra", groups=groups)
    message = str(exc_info.value)
    assert "ultra" in message
    assert "low" in message and "medium" in message and "high" in message


def test_unknown_group_fails_loud_in_preferred(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    with pytest.raises(mg.UnknownLevel):
        mg.preferred("ultra", groups)


# ------------------------------------------------------------------ L0-9 explicit model wins
def test_explicit_model_beats_level(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    assert mg.resolve("low", "openrouter/custom/override-1", groups) == \
        "openrouter/custom/override-1"


# ------------------------------------------------------------------ L0-10 level resolves to preferred verbatim
def test_resolve_level_returns_preferred_verbatim(mg, tmp_path):
    low = [
        _m("openrouter/z-ai/glm-5.3-flash", 0.075, 0.25, True),
        _m("openrouter/l/other", 1, 2),
    ]
    groups = _load(mg, tmp_path, _doc(low=low))
    resolved = mg.resolve("low", groups=groups)
    assert resolved == mg.preferred("low", groups)
    assert resolved == "openrouter/z-ai/glm-5.3-flash"
    assert resolved.startswith("openrouter/")


# ------------------------------------------------------------------ L0-11 the shipped seed satisfies everything
def test_real_registry_satisfies_all_invariants(mg, root):
    """The single integration pin: the shipped seed loads and carries the exact seed ids in
    order, with the exact seed prices. High pins and the deepseek price are from the
    2026-09-11 brief; low/medium carry the 2026-09-05 measurement."""
    seed = root / SEED
    groups = mg.load_groups(seed)
    assert set(groups) == {"low", "medium", "high"}

    assert [m["id"] for m in groups["low"]] == [
        "openrouter/z-ai/glm-5.3-flash",
        "openrouter/deepseek/deepseek-v4-flash-0731",
        "openrouter/xiaomi/mimo-v2.5",
        "openrouter/openai/gpt-5.6-luna",
        "openrouter/anthropic/claude-haiku-4.5",
    ]
    assert [m["id"] for m in groups["medium"]] == [
        "openrouter/meta/muse-spark-1.3-contributor",
        "openrouter/xiaomi/mimo-v2.5-pro",
        "openrouter/deepseek/deepseek-v4-pro-0813",
        "openrouter/deepseek/deepseek-v4-pro",
        "openrouter/meta/muse-spark-1.3",
        "openrouter/z-ai/glm-5.3",
        "openrouter/openai/gpt-5.6-sol",
        "openrouter/openai/gpt-5.6-terra",
        "openrouter/anthropic/claude-sonnet-5",
    ]
    assert [m["id"] for m in groups["high"]] == [
        "openrouter/deepseek/deepseek-v4.1-flash",
        "openrouter/anthropic/claude-opus-5",
        "openrouter/anthropic/claude-fable-5.1",
        "openrouter/meta/muse-spark-1.3-contributor",
    ]

    assert [ (m["pricing"]["inputPerM"], m["pricing"]["outputPerM"])  # noqa: E201
             for m in groups["low"] ] == [
        (0.075, 0.25), (0.0875, 0.175), (0.14, 0.28), (0.2, 1.2), (1, 5),
    ]
    assert [ (m["pricing"]["inputPerM"], m["pricing"]["outputPerM"])  # noqa: E201
             for m in groups["medium"] ] == [
        (0.1, 0.2), (0.435, 0.87), (0.57948, 1.73844), (0.9918, 1.9836),
        (1.25, 4.25), (1.4, 4.4), (2, 10), (2, 12), (2, 10),
    ]
    assert [ (m["pricing"]["inputPerM"], m["pricing"]["outputPerM"])  # noqa: E201
             for m in groups["high"] ] == [(0.15, 0.6), (5, 25), (10, 50), (0.1, 0.2)]

    for level in ("low", "medium", "high"):
        flags = [m["preferred"] for m in groups[level]]
        assert flags == [True] + [False] * (len(flags) - 1), level

    tail = groups["medium"][-1]
    assert tail["id"].endswith("claude-sonnet-5")
    assert tail.get("status") == "demoted"
    assert tail.get("revisionWatch") is True
    high_tail = groups["high"][-1]
    assert high_tail["id"].endswith("muse-spark-1.3-contributor")
    assert high_tail.get("status") == "demoted"
    assert high_tail.get("revisionWatch") is True
    assert groups["high"][2]["id"].endswith("claude-fable-5.1")

    assert mg.preferred("low", groups) == "openrouter/z-ai/glm-5.3-flash"
    assert mg.resolve("medium", groups=groups) == \
        "openrouter/meta/muse-spark-1.3-contributor"
    assert mg.preferred("high", groups) == "openrouter/deepseek/deepseek-v4.1-flash"

    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert json.loads(seed.read_text(encoding="utf-8"))["frameworkVersion"] == version


def test_default_path_resolves_to_the_shipped_seed(mg, root):
    assert mg.load_groups() == mg.load_groups(root / SEED)


# ------------------------------------------------------------------ T-MISS missing/unparseable
def test_missing_registry_file_fails_loud(mg, tmp_path):
    missing = tmp_path / "no-such-registry.json"
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        mg.load_groups(missing)
    assert "no-such-registry.json" in str(exc_info.value)


def test_unparseable_registry_file_fails_typed(mg, tmp_path):
    path = _test_write(tmp_path / "model-groups.json", "{not json", encoding="utf-8")
    with pytest.raises(mg.RegistryInvalid):
        mg.load_groups(path)


# ------------------------------------------------------------------ T-ONEPREF exactly one preferred
def test_two_preferred_members_are_rejected(mg, tmp_path):
    low = [_m("openrouter/l/a", 0.1, 0.2, True), _m("openrouter/l/b", 0.5, 1.0, True)]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "preferred" in str(exc_info.value)


def test_zero_preferred_members_are_rejected(mg, tmp_path):
    low = [_m("openrouter/l/a", 0.1, 0.2), _m("openrouter/l/b", 0.5, 1.0)]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "preferred" in str(exc_info.value)


# ------------------------------------------------------------------ T-DUP per-group uniqueness
def test_duplicate_id_within_one_group_is_rejected(mg, tmp_path):
    low = [_m("openrouter/l/same", 0.1, 0.2, True), _m("openrouter/l/same", 0.5, 1.0)]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(low=low))
    assert "openrouter/l/same" in str(exc_info.value)


def test_cross_group_id_reuse_is_legal(mg, tmp_path):
    """The same id may appear in several groups: uniqueness is per-group, not per-registry.
    The shipped reuse is medium's preferred contributor, reused as high's demoted tail."""
    shared = "openrouter/meta/muse-spark-1.3-contributor"
    groups = _load(mg, tmp_path, _doc(
        low=[_m("openrouter/l/low", 1, 2, True)],
        medium=[_m(shared, 0.1, 0.2, True)],
        high=[_m(shared, 0.1, 0.2, True), _m("openrouter/h/other", 5, 25)],
    ))
    assert mg.preferred("medium", groups) == shared
    assert mg.preferred("high", groups) == shared


# ------------------------------------------------------------------ T-ALIAS aliases never resolve
def test_aliases_are_documentary_not_dereferenced(mg, tmp_path):
    low = [_m("openrouter/l/low", 0.1, 0.2, True, aliases=["l-latest", "low-alias"])]
    groups = _load(mg, tmp_path, _doc(low=low))
    resolved = mg.resolve("low", groups=groups)
    assert resolved == "openrouter/l/low"
    assert resolved not in ("l-latest", "low-alias")


# ------------------------------------------------------------------ T-LEX lexicographic order key
def test_order_key_is_input_then_output_not_a_sum(mg, tmp_path):
    """(1,100) before (2,3) is lexicographic; a blended-sum key would order them the other
    way (101 > 5) and must not pass."""
    low = [
        _m("openrouter/l/cheap", 0.1, 0.2, True),
        _m("openrouter/l/wide", 1, 100),
        _m("openrouter/l/pricey", 2, 3),
    ]
    groups = _load(mg, tmp_path, _doc(low=low))
    assert [m["id"] for m in groups["low"]] == [
        "openrouter/l/cheap", "openrouter/l/wide", "openrouter/l/pricey"]


def test_input_tie_breaks_on_output(mg, tmp_path):
    low = [
        _m("openrouter/l/cheap", 0.1, 0.2, True),
        _m("openrouter/l/ten", 2, 10),
        _m("openrouter/l/twelve", 2, 12),
    ]
    _load(mg, tmp_path, _doc(low=low))
    swapped = [
        _m("openrouter/l/cheap", 0.1, 0.2, True),
        _m("openrouter/l/twelve", 2, 12),
        _m("openrouter/l/ten", 2, 10),
    ]
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, _doc(low=swapped))


# ------------------------------------------------------------------ T-ERRSHAPE typed errors
def test_errors_are_typed_and_value_compatible(mg):
    assert issubclass(mg.UnknownLevel, ValueError)
    assert issubclass(mg.RegistryInvalid, ValueError)
    assert mg.UnknownLevel is not mg.RegistryInvalid


def test_unknown_level_carries_the_invalid_value_and_the_valid_set(mg):
    err = mg.UnknownLevel("ultra")
    assert err.invalid_level == "ultra"
    assert err.valid_levels == ["low", "medium", "high"]
    assert "ultra" in str(err)
    assert "low, medium, high" in str(err)


def test_registry_invalid_carries_errors_and_source(mg, tmp_path):
    path = _test_write(tmp_path / "model-groups.json", "[]", encoding="utf-8")
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        mg.load_groups(path)
    assert exc_info.value.errors
    assert "model-groups.json" in exc_info.value.source


# ------------------------------------------------------------------ T-A7 stale level warns, explicit wins
def test_stale_level_with_explicit_model_warns_but_wins_verbatim(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    with pytest.warns(UserWarning, match="ultra"):
        resolved = mg.resolve("ultra", "openrouter/custom/override-9", groups)
    assert resolved == "openrouter/custom/override-9"


def test_valid_non_deciding_level_is_silent(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = mg.resolve("low", "openrouter/custom/override-9", groups)
    assert resolved == "openrouter/custom/override-9"
    assert [w for w in caught if issubclass(w.category, UserWarning)] == []


# ------------------------------------------------------------------ T-CASE case-sensitive
@pytest.mark.parametrize("level", ["Low", "LOW", "Medium", "HIGH"])
def test_level_matching_is_case_sensitive(mg, tmp_path, level):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    with pytest.raises(mg.UnknownLevel):
        mg.resolve(level, groups=groups)


def test_surrounding_whitespace_is_stripped(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    assert mg.resolve("  low  ", groups=groups) == "openrouter/l/low"


# ------------------------------------------------------------------ T-EMPTY empty is absent
@pytest.mark.parametrize("level", ["", "   "])
def test_blank_level_is_absent_not_an_error(mg, tmp_path, level):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    assert mg.resolve(level, groups=groups) is None


# ------------------------------------------------------------------ T-NOPIN absent means inherit
def test_absent_level_and_model_resolve_to_no_pin(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    assert mg.resolve(None, None, groups) is None
    assert mg.resolve(None, groups=groups) is None


def test_blank_explicit_model_falls_back_to_level(mg, tmp_path):
    groups = _load(mg, tmp_path, _doc(low=[_m("openrouter/l/low", 1, 2, True)]))
    assert mg.resolve("low", "", groups) == "openrouter/l/low"
    assert mg.resolve("low", "   ", groups) == "openrouter/l/low"


# ------------------------------------------------------------------ T-FAKESHAPE non-documents fail typed
@pytest.mark.parametrize("bad", [
    [], "model-groups", None, 42, True,
    {"frameworkVersion": "0.0.0", "registryVersion": 1, "measuredAt": "2026-09-05"},
    {"groups": None}, {"groups": []}, {"groups": "low"},
])
def test_malformed_documents_raise_registry_invalid(mg, tmp_path, bad):
    path = _test_write(tmp_path / "model-groups.json", json.dumps(bad), encoding="utf-8")
    with pytest.raises(mg.RegistryInvalid):
        mg.load_groups(path)


# ------------------------------------------------------------------ T-CRASH the malformed wave, all typed
def _crash_low(**member_kw):
    member = {"id": "openrouter/l/a", "preferred": True,
              "pricing": {"inputPerM": 0.1, "outputPerM": 0.2},
              "evidence": f"crash-wave pin (source: {SOURCE})"}
    member.update(member_kw)
    return [member]


CRASH_WAVE = {
    "member-not-an-object": _crash_low()[:-1] + ["openrouter/l/a"],
    "id-missing": [{k: v for k, v in _crash_low()[0].items() if k != "id"}],
    "id-non-string": _crash_low(id=42),
    "preferred-missing": [{k: v for k, v in _crash_low()[0].items() if k != "preferred"}],
    "preferred-non-bool": _crash_low(preferred="yes"),
    "pricing-missing": [{k: v for k, v in _crash_low()[0].items() if k != "pricing"}],
    "pricing-null": _crash_low(pricing=None),
    "pricing-non-object": _crash_low(pricing=[0.1, 0.2]),
    "input-zero": _crash_low(pricing={"inputPerM": 0, "outputPerM": 0.2}),
    "output-negative": _crash_low(pricing={"inputPerM": 0.1, "outputPerM": -1}),
    "price-non-numeric": _crash_low(pricing={"inputPerM": "cheap", "outputPerM": 0.2}),
    "price-bool": _crash_low(pricing={"inputPerM": True, "outputPerM": 0.2}),
    "evidence-missing": [{k: v for k, v in _crash_low()[0].items() if k != "evidence"}],
    "evidence-empty": _crash_low(evidence=""),
    "aliases-with-empty": _crash_low(aliases=["ok", ""]),
    "aliases-non-list": _crash_low(aliases="latest"),
    "status-bogus": _crash_low(status="retired"),
    "revision-watch-non-bool": _crash_low(revisionWatch="yes"),
    "member-measuredAt-bad-shape": _crash_low(measuredAt="09/05/2026"),
    "unexpected-member-key": _crash_low(vendor="x"),
    "empty-group": [],
}


@pytest.mark.parametrize("label", sorted(CRASH_WAVE))
def test_crash_wave_every_malformation_is_typed(mg, tmp_path, label):
    doc = _doc(low=CRASH_WAVE[label])
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, doc)


@pytest.mark.parametrize("top", [
    {"registryVersion": 0}, {"registryVersion": "1"}, {"registryVersion": True},
    {"frameworkVersion": "1.2"}, {"frameworkVersion": 1},
    {"measuredAt": "09/05/2026"}, {"measuredAt": "2026-13-40"},
    {"currency": "EUR"},
])
def test_crash_wave_top_level_fields_are_typed(mg, tmp_path, top):
    """Top-level (and misplaced pricing-level) malformations fail typed too. `currency` is a
    pricing-level key: at the top level it is an unexpected key."""
    doc = _doc(low=[_m("openrouter/l/a", 0.1, 0.2, True)])
    doc.update(top)
    with pytest.raises(mg.RegistryInvalid):
        _load(mg, tmp_path, doc)


def test_demoted_tail_without_revision_watch_is_rejected(mg, tmp_path):
    medium = [
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2, True),
        _m("openrouter/anthropic/claude-sonnet-5", 2, 10, status="demoted"),
    ]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(
            low=[_m("openrouter/l/low", 1, 2, True)], medium=medium))
    assert "revisionWatch" in str(exc_info.value)


def test_shared_weights_id_requires_shared_evidence(mg, tmp_path):
    """Entries sharing a weightsId must say so in evidence (the contributor-vs-full twin)."""
    medium = [
        _m("openrouter/meta/muse-spark-1.3-contributor", 0.1, 0.2, True,
           weightsId="muse-spark-1.3-weights",
           evidence="contributor twin; identical weights (weightsId muse-spark-1.3-weights)"),
        _m("openrouter/meta/muse-spark-1.3", 1.25, 4.25,
           weightsId="muse-spark-1.3-weights",
           evidence="full twin, no relationship note"),
    ]
    with pytest.raises(mg.RegistryInvalid) as exc_info:
        _load(mg, tmp_path, _doc(
            low=[_m("openrouter/l/low", 1, 2, True)], medium=medium))
    assert "weightsId" in str(exc_info.value)


# ------------------------------------------------------------------ 1b: validate wiring
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


# ------------------------------------------------------------------ 1b: scaffold delivery
def test_scaffold_delivers_the_registry_verbatim(make_scaffolder, root):
    result = make_scaffolder(skills=["task"]).run(
        generated_at="2026-09-05T00:00:00Z")
    delivered = make_scaffolder.target / ".ai-badger" / "model-groups.json"
    assert delivered.is_file()
    assert delivered.read_bytes() == (root / SEED).read_bytes()
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
    import re
    make_scaffolder(skills=["task"]).run(generated_at="2026-09-05T00:00:00Z")
    delivered = json.loads(
        (make_scaffolder.target / ".ai-badger" / "model-groups.json"
         ).read_text(encoding="utf-8"))
    ids = [m["id"] for members in delivered["groups"].values() for m in members]
    assert ids
    pattern = re.compile(r"^openrouter/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    assert all(pattern.match(i) for i in ids), ids
