"""Layer-1 tests: the model map — four cost-tier groups, family anchors, and the
open-weight price rule (ADR-0043, docs/adr/0043-model-group-and-thinking-level-split.md).

The map is one data file, `features/common/data/model-groups.json`, in a new shape: four
cost-tier groups (low, medium, high, top), each carrying an `anchors` object naming the
version-less family name that anchors that group for every declared family, a `primary`
naming the anchor whose model decides the group, and a `models` array of the concrete
provider-qualified ids that belong to the group (id, family, preferred, pricing, license,
score, evidence). The map rules join the registry leaf
(`features/common/skills/task/scripts/model_groups.py`) and the shipped schema
(`schemas/model-groups.schema.json`).

Fixture rule: every rule is exercised on a document built by the helpers below — the
shipped file's envelope (so no top-level key is guessed) with the groups the rule is
about. The shipped file itself is read by the `shipped_map_*` tests and by the shipped-price
test, because those rules are about the shipped data.

Price-rule rule (the reading these tests encode): the price rule applies per member. A
member's price is "above zero" when both price fields are above zero; the zero-price
relaxation is granted to a member whose license marks it open weight, and to nothing else.
A zero-priced member has no price position, so it does not take part in the price order —
which is why the price fixtures give the group a single member: then the only thing a
validator can refuse is the price rule itself.

Anchor rule: the anchors are read as family-key -> version-less-family-name, the shape the
design sketches (`{"anthropic": "haiku", "openai": "luna"}`). The family keys are anthropic
and openai (ADR-0043, decision 4); the assertions compare anchor *values* (haiku, sonnet,
opus, fable, luna, sol, astra), so they do not depend on how a family is keyed.

Primary rule: a group names one `primary` anchor key, and that anchor's model leads the
group. The group's preferred member is the member whose `family` is the primary anchor's
name, so a group resolves to the model it stands for rather than to the cheapest one it
happens to hold. The rest of the members follow in ascending price.

API note: these tests assert behaviour, not names. The map validator is looked up where it
lives (a dedicated map module beside the registry leaf, or the leaf itself), and the
resolver is the map's own resolver. A validator that refuses by raising counts as a
refusal; a validator that does not take a map document is an API mismatch and fails the
test loudly rather than masquerading as a refusal.

Vocabulary note: `Open Weight` and `Proprietary` are the leaderboard CSV's own sourceType
values (features/common/data/leaderboard.csv), so a fixture's license says what the CSV
says. A license naming an open-weight release (the string mentions open weight, or an
open-source license) counts as open weight for the price rule.
"""
from __future__ import annotations

import inspect
import json

import pytest

LEAF = "features/common/skills/task/scripts/model_groups.py"
SEED = "features/common/data/model-groups.json"
SCHEMA = "schemas/model-groups.schema.json"

GROUPS = ("low", "medium", "high", "top")
FAMILIES = ("anthropic", "openai")

# The anchors the owner's rulings fix (ADR-0043, decision 4): one per family per group,
# anthropic first and openai second.
OWNER_ANCHORS = {
    "low": ("haiku", "luna"),
    "medium": ("sonnet", "sol"),
    "high": ("opus", "sol"),
    "top": ("fable", "astra"),
}

# The leaderboard price of each anchored family per group, per 1M tokens
# (~/Downloads/benchlm-leaderboard.csv, the pricing source of record).
PRICE_BY_GROUP_ANCHOR = {
    "low": {"haiku": (0.1, 0.5), "luna": (0.1, 0.5)},
    "medium": {"sonnet": (2, 10), "sol": (2, 10)},
    "high": {"opus": (4, 20), "sol": (4, 20)},
    "top": {"fable": (10, 50), "astra": (10, 50)},
}
PRICE_BY_ANCHOR = {"haiku": (0.1, 0.5), "luna": (0.1, 0.5), "sonnet": (2, 10),
                   "sol": (2, 10), "opus": (4, 20), "fable": (10, 50),
                   "astra": (10, 50)}

# A concrete id per anchored family per group, so a fixture's member belongs to the
# family the group anchors and no id is reused across groups (the sol family spans two
# price bands with two different models).
ID_BY_GROUP_ANCHOR = {
    ("low", "haiku"): "openrouter/anthropic/claude-haiku-5.5",
    ("low", "luna"): "openrouter/openai/gpt-6-luna",
    ("medium", "sonnet"): "openrouter/anthropic/claude-sonnet-5.5",
    ("medium", "sol"): "openrouter/openai/gpt-6.1-sol",
    ("high", "opus"): "openrouter/anthropic/claude-opus-5.5",
    ("high", "sol"): "openrouter/openai/gpt-5.6-sol",
    ("top", "fable"): "openrouter/anthropic/claude-fable-5.1",
    ("top", "astra"): "openrouter/openai/gpt-6-astra",
}

# A license naming an open-weight release: the leaderboard's own "Open Weight" and the
# common open-source licenses.
OPEN_LICENSE_MARKERS = ("open", "apache", "mit", "bsd", "gpl", "free", "public domain")

# Names outside the four cost tiers, used to probe the resolver's closed vocabulary.
OUTSIDE_THE_FOUR = ("ultra", "off", "minimal", "xhigh", "max")

# The words a refusal of the price rule may use: the price, the license, or the open-weight
# mark it did not carry.
PRICE_RULE_MARKERS = ("pric", "licen", "open", "weight")

# A validator lives either in a module named after the map or in the registry leaf.
VALIDATOR_NAMES = ("validate_map", "validate_model_map", "validate_groups",
                   "validate_registry")
# The map's resolver, group-specific names first so a legacy level resolver does not win.
RESOLVER_NAMES = ("resolve_group", "resolve_map", "resolve_model_group", "resolve")

# The resolver's group parameter, under any of the names it may carry.
GROUP_PARAM_NAMES = ("group", "level", "group_name", "cost_group", "model_group", "tier")


# ------------------------------------------------------------------ helpers
def _shipped_map(root):
    """The shipped map document."""
    return json.loads((root / SEED).read_text(encoding="utf-8"))


def _groups_key(doc):
    """The top-level key that holds the groups: the shipped map's own, whatever it is
    called."""
    if isinstance(doc.get("groups"), dict):
        return "groups"
    shaped = [key for key, value in doc.items()
              if isinstance(value, dict) and any(isinstance(entry, dict)
                                                and "anchors" in entry
                                                for entry in value.values())]
    if len(shaped) == 1:
        return shaped[0]
    dicts = [key for key, value in doc.items() if isinstance(value, dict)]
    return dicts[0] if dicts else "groups"


def _pricing_template(doc):
    """The pricing key names the shipped map uses, so a fixture never hard-codes a
    spelling the implementation may have renamed."""
    for group in (doc.get(_groups_key(doc)) or {}).values():
        members = group.get("models") if isinstance(group, dict) else group
        for member in members or []:
            if isinstance(member, dict) and isinstance(member.get("pricing"), dict):
                return dict(member["pricing"])
    return {"inputPerM": 0, "outputPerM": 0}


def _with_prices(template, price_in, price_out):
    """A pricing block on the shipped map's spelling, with the two prices set."""
    pricing = dict(template)
    for key in list(pricing):
        if "input" in key:
            pricing[key] = price_in
        elif "output" in key:
            pricing[key] = price_out
    if not any("input" in key for key in pricing):
        pricing["inputPerM"] = price_in
        pricing["outputPerM"] = price_out
    return pricing


def _member(pricing, ident, price_in, price_out, *, family=None, preferred=False,
            lic="Proprietary", score=50.0):
    """One map member: id, family, preferred, pricing, license, score, evidence."""
    return {
        "id": ident,
        "family": family,
        "preferred": preferred,
        "pricing": _with_prices(pricing, price_in, price_out),
        "license": lic,
        "score": score,
        "evidence": f"fixture member {ident}: priced for the model-map fixture.",
    }


def _is_map_shape(doc):
    """True when the document carries the map shape: four groups, each an object with an
    `anchors` object and a non-empty `models` array."""
    groups = doc.get(_groups_key(doc))
    if not isinstance(groups, dict) or set(groups) != set(GROUPS):
        return False
    for entry in groups.values():
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("anchors"), dict):
            return False
        if not isinstance(entry.get("models"), list) or not entry["models"]:
            return False
    return True


def _base_anchors(root):
    """The per-group anchors a fixture should carry: the shipped map's own once it is in
    the map shape, the owner's rulings until then."""
    doc = _shipped_map(root)
    if _is_map_shape(doc):
        return {group: dict(entry["anchors"])
                for group, entry in doc[_groups_key(doc)].items()}
    return {group: dict(zip(FAMILIES, anchors))
            for group, anchors in OWNER_ANCHORS.items()}


def _group(root, group_name, anchors, models, primary=None):
    """One map group: the family anchors, the primary anchor and the concrete members
    that belong to it.

    The shipped group's own keys are kept (only `anchors`, `primary` and `models` are
    replaced), so a fixture does not trip a rule about a key the shipped map carries.
    """
    doc = _shipped_map(root)
    shipped = doc.get(_groups_key(doc)) or {}
    base = shipped.get(group_name) if isinstance(shipped, dict) else None
    entry = dict(base) if isinstance(base, dict) else {}
    entry["anchors"] = dict(anchors)
    entry["primary"] = primary if primary is not None else next(iter(anchors), None)
    entry["models"] = list(models)
    return entry


def _family_members(pricing, group_name, anchors, primary=None):
    """One member per anchored family, priced at that family's leaderboard price in that
    group, the primary anchor's member first and preferred."""
    members = []
    prices = PRICE_BY_GROUP_ANCHOR.get(group_name, {})
    order = list(anchors.items())
    if primary is not None and primary in anchors:
        order.sort(key=lambda item: item[0] != primary)
    for index, (family, anchor) in enumerate(order):
        price_in, price_out = prices.get(
            anchor, PRICE_BY_ANCHOR.get(anchor, (1 + index, 2 + index)))
        ident = ID_BY_GROUP_ANCHOR.get(
            (group_name, anchor), f"openrouter/{family}/model-{anchor}")
        members.append(_member(pricing, ident, price_in, price_out, family=anchor,
                               preferred=index == 0))
    return members


def _valid_groups(root, pricing):
    """Four groups that satisfy the ADR's own ladder: one anchor per family, one
    preferred member each, the primary anchor's model first.

    The anchors come from the shipped map once it is in the map shape, so a fixture never
    guesses a family the map has grown past anthropic and openai; until then they are the
    anchors the owner's rulings fix.
    """
    anchors = _base_anchors(root)
    return {group: _group(root, group, anchors[group],
                          _family_members(pricing, group, anchors[group],
                                          primary=next(iter(anchors[group]), None)),
                          primary=next(iter(anchors[group]), None))
            for group in GROUPS}


def _map_doc(root, groups):
    """A map document: the shipped file's envelope (frameworkVersion, measuredAt, the
    family declaration — whatever the map carries besides its groups) with the given
    groups swapped in."""
    doc = _shipped_map(root)
    doc[_groups_key(doc)] = groups
    return doc


def _price_pair(pricing):
    """(input, output) out of a pricing block, whatever the key spelling is."""
    price_in = price_out = None
    if not isinstance(pricing, dict):
        return price_in, price_out
    for key, value in pricing.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if "input" in key:
            price_in = value
        elif "output" in key:
            price_out = value
    return price_in, price_out


def _is_open_weight(member):
    """True when the member's license marks it as an open-weight release."""
    lic = member.get("license")
    if not isinstance(lic, str):
        return False
    lowered = lic.lower()
    return any(marker in lowered for marker in OPEN_LICENSE_MARKERS)


def _preferred_id(doc, group):
    """The id of the group's preferred member, per the map's new shape."""
    entry = doc[_groups_key(doc)][group]
    assert isinstance(entry, dict) and isinstance(entry.get("models"), list), (
        f"the shipped map's {group!r} group does not carry a models array yet")
    preferred = [member["id"] for member in entry["models"]
                 if isinstance(member, dict) and member.get("preferred") is True]
    assert len(preferred) == 1, f"{group!r} carries {len(preferred)} preferred members"
    return preferred[0]


def _map_modules(root, load_script):
    """The modules that may hold the map rules: one named after the map, then the
    registry leaf the map rules join."""
    scripts = root / "features" / "common" / "skills" / "task" / "scripts"
    paths = sorted(path for path in scripts.glob("*.py") if "map" in path.name)
    paths.append(root / LEAF)
    return [load_script(str(path.relative_to(root))) for path in paths]


def _map_validator(root, load_script):
    """The callable that validates a map document.

    The map rules join the registry leaf (ADR-0043), so the leaf's validator is the
    expected home; a dedicated map module beside it is accepted too.
    """
    for module in _map_modules(root, load_script):
        for name in VALIDATOR_NAMES:
            fn = getattr(module, name, None)
            if callable(fn):
                return fn
        for name in sorted(dir(module)):
            if name.startswith("validate") and not name.startswith("_") \
                    and callable(getattr(module, name)):
                return getattr(module, name)
    raise AssertionError("no map validator found: the map rules do not exist yet")


def _errors(validator, doc):
    """Every error the validator reports for `doc`; an empty list means valid.

    A validator that refuses by raising counts as a refusal; a validator that does not
    take a map document is an API mismatch and fails the test loudly.
    """
    try:
        result = validator(doc)
    except TypeError as exc:
        raise AssertionError(f"the map validator takes no map document: {exc}") from exc
    except Exception as exc:  # a refusal by exception is still a refusal
        return [str(exc)]
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return [str(item) for item in result]
    return [str(result)]


def _resolver(root, load_script):
    """The map's resolver: a group name in, a model id out, nothing in, nothing out.

    A group-specific name wins over the plain one, so a legacy level resolver does not
    answer for the map.
    """
    for module in _map_modules(root, load_script):
        candidates = [name for name in dir(module)
                      if "resolve" in name and not name.startswith("_")
                      and callable(getattr(module, name))]
        for preferred in RESOLVER_NAMES:
            if preferred in candidates:
                return getattr(module, preferred)
        if candidates:
            return getattr(module, sorted(candidates)[0])
    raise AssertionError("no resolver found: the resolver does not exist yet")


def _resolve(root, load_script, group):
    """Resolve one group name through whatever resolver the map exposes.

    The group is bound by parameter name when the resolver names it, so an
    explicit-model parameter never swallows the group. A resolver that demands the map
    as a second argument gets it.
    """
    resolver = _resolver(root, load_script)
    doc = _shipped_map(root)
    try:
        parameters = inspect.signature(resolver).parameters
    except (TypeError, ValueError):  # pragma: no cover - a builtin without a signature
        parameters = {}
    param = _group_param(parameters)
    attempts = [lambda: resolver(**{param: group})]
    attempts.append(lambda: resolver(group))
    attempts.append(lambda: resolver(group, doc))
    attempts.append(lambda: resolver(group, doc[_groups_key(doc)]))
    last = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:  # the call shape did not fit; try the next one
            last = exc
    raise AssertionError(f"the resolver takes no group name: {last}")


def _group_param(parameters):
    """The resolver's group parameter, under any of the names it may carry."""
    for name in GROUP_PARAM_NAMES:
        if name in parameters:
            return name
    return next(iter(parameters)) if parameters else None


def _schema_errors(root, doc):
    """Every error the shipped schema reports for `doc`."""
    import jsonschema

    schema = json.loads((root / SCHEMA).read_text(encoding="utf-8"))
    return [error.message
            for error in jsonschema.Draft202012Validator(schema).iter_errors(doc)]


@pytest.fixture(name="pricing")
def pricing_template(root):
    """The pricing spelling the shipped map uses."""
    return _pricing_template(_shipped_map(root))


# ------------------------------------------------------------------ 1 the shipped map
def test_shipped_map_has_the_four_cost_tier_groups(root):
    doc = _shipped_map(root)
    groups = doc.get(_groups_key(doc)) or {}
    assert set(groups) == set(GROUPS), sorted(groups)


def test_shipped_map_group_anchors_every_declared_family(root):
    """Every group anchors the same families: the family set is what the map declares,
    and no group may leave one out."""
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    groups = doc[_groups_key(doc)]
    anchor_keys = {group: set(entry["anchors"]) for group, entry in groups.items()}
    declared = set().union(*anchor_keys.values())
    assert set(FAMILIES) <= declared, f"declared families are {sorted(declared)}"
    for group, keys in anchor_keys.items():
        assert keys == declared, f"{group} anchors {sorted(keys)}, not {sorted(declared)}"
        for name in groups[group]["anchors"].values():
            assert isinstance(name, str) and name, f"{group} has an empty anchor"


def test_shipped_map_group_has_exactly_one_preferred_member(root):
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    for group, entry in doc[_groups_key(doc)].items():
        preferred = [member for member in entry["models"]
                     if isinstance(member, dict) and member.get("preferred") is True]
        assert len(preferred) == 1, f"{group} has {len(preferred)} preferred members"


def test_shipped_map_group_leads_with_its_primary_anchor_then_ascends_by_price(root):
    """The group's first member is the model its primary anchor names, and the rest follow
    in ascending price. A zero-priced open-weight member has no price position, so it does
    not take part in the order."""
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    for group, entry in doc[_groups_key(doc)].items():
        models = entry["models"]
        anchors = entry.get("anchors") or {}
        primary = entry.get("primary")
        assert primary in anchors, f"{group} names no primary anchor key"
        anchor_name = anchors[primary]
        first = models[0]
        assert first.get("family") == anchor_name, (
            f"{group} leads with {first.get('family')!r}, not its primary anchor "
            f"{anchor_name!r}")
        last = None
        for member in models[1:]:
            price_in, price_out = _price_pair(member.get("pricing", {}))
            if price_in is None or price_out is None or price_in <= 0 or price_out <= 0:
                continue
            key = (price_in, price_out)
            if last is not None:
                assert key >= last, f"{group}: {key} sorts before {last}"
            last = key


def test_shipped_map_preferred_member_is_the_primary_anchors_model(root):
    """One preferred member per group, and it is the model the primary anchor names."""
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    for group, entry in doc[_groups_key(doc)].items():
        preferred = [member for member in entry["models"]
                     if isinstance(member, dict) and member.get("preferred") is True]
        assert len(preferred) == 1, f"{group} has {len(preferred)} preferred members"
        anchors = entry.get("anchors") or {}
        primary = entry.get("primary")
        assert primary in anchors, f"{group} names no primary anchor key"
        assert preferred[0].get("family") == anchors[primary], (
            f"{group}'s preferred member is {preferred[0].get('family')!r}, not the "
            f"primary anchor {anchors[primary]!r}")


def test_shipped_map_anchors_the_owner_rulings(root):
    """The owner's rulings fix the ladder: low haiku/luna, medium sonnet/sol,
    high opus/sol, top fable/astra."""
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    for group, expected in OWNER_ANCHORS.items():
        anchors = set(doc[_groups_key(doc)][group]["anchors"].values())
        assert anchors == set(expected), f"{group} anchors {sorted(anchors)}"


def test_shipped_map_validates_under_the_map_validator_and_the_shipped_schema(
        root, load_script):
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    assert _errors(_map_validator(root, load_script), doc) == []
    assert _schema_errors(root, doc) == []


# ------------------------------------------------------------------ 2 an anchor is required
def test_group_missing_an_anchor_for_a_declared_family_is_refused(root, load_script,
                                                                   pricing):
    """The refusal names the group that lost the anchor and the family it lost."""
    groups = _valid_groups(root, pricing)
    family = sorted(groups["low"]["anchors"])[-1]
    anchor = groups["low"]["anchors"][family]
    del groups["low"]["anchors"][family]
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a group without an anchor for a declared family was accepted"
    assert any("low" in error and (family in error or anchor in error)
               for error in errors), errors


# ------------------------------------------------------------------ 3 a family may hold two groups
def test_a_family_may_anchor_more_than_one_group(root, load_script, pricing):
    """The sol family spans two price bands, so one family anchoring two groups is legal."""
    groups = _valid_groups(root, pricing)
    medium = groups["medium"]["anchors"]
    high = groups["high"]["anchors"]
    shared = [family for family in medium
              if family in high and medium[family] == high[family]]
    assert shared, "no family anchors two groups in the fixture"
    doc = _map_doc(root, groups)
    assert _errors(_map_validator(root, load_script), doc) == []


def test_shipped_map_anchors_the_sol_family_in_high_and_medium(root):
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    groups = doc[_groups_key(doc)]
    assert "sol" in set(groups["medium"]["anchors"].values())
    assert "sol" in set(groups["high"]["anchors"].values())


# ------------------------------------------------------------------ 4 the open-weight price rule
def test_zero_priced_open_weight_member_is_accepted(root, load_script, pricing):
    """The leaderboard prices the open-weight releases at 0/0, so a zero-priced member is
    legal when its license says it is open weight."""
    groups = _valid_groups(root, pricing)
    groups["low"] = _group(root, "low", groups["low"]["anchors"], [
        _member(pricing, "openrouter/z-ai/glm-5.3", 0, 0, family="haiku", preferred=True,
                lic="Open Weight", score=67.96),
    ])
    doc = _map_doc(root, groups)
    assert _errors(_map_validator(root, load_script), doc) == []


def test_zero_priced_member_without_an_open_weight_license_is_refused(root, load_script,
                                                                       pricing):
    """The same member with a proprietary license is refused: the relaxation follows the
    license, not the price alone."""
    groups = _valid_groups(root, pricing)
    groups["low"] = _group(root, "low", groups["low"]["anchors"], [
        _member(pricing, "openrouter/anthropic/claude-haiku-5.5", 0, 0, preferred=True,
                lic="Proprietary"),
    ])
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a zero-priced proprietary member was accepted"
    assert any(any(marker in error.lower() for marker in PRICE_RULE_MARKERS)
               for error in errors), errors


# ------------------------------------------------------------------ 5 the price-above-zero rule
def test_member_that_is_not_open_weight_is_accepted_with_a_price_above_zero(
        root, load_script, pricing):
    """The relaxation is narrow: a member that is not open weight still pays a price."""
    groups = _valid_groups(root, pricing)
    groups["top"] = _group(root, "top", groups["top"]["anchors"], [
        _member(pricing, "openrouter/anthropic/claude-fable-5.1", 10, 50, family="fable",
                preferred=True, lic="Proprietary"),
    ])
    doc = _map_doc(root, groups)
    assert _errors(_map_validator(root, load_script), doc) == []


def test_shipped_map_prices_every_member_that_is_not_open_weight_above_zero(root):
    """A price above zero is still required for a member that is not open weight, and
    every member declares the license the rule reads."""
    doc = _shipped_map(root)
    assert _is_map_shape(doc), "the shipped map is not in the map shape yet"
    for group, entry in doc[_groups_key(doc)].items():
        for member in entry["models"]:
            ident = member.get("id")
            assert member.get("license"), f"{ident} declares no license"
            if _is_open_weight(member):
                continue
            price_in, price_out = _price_pair(member.get("pricing", {}))
            assert price_in is not None and price_in > 0, f"{ident} has no input price"
            assert price_out is not None and price_out > 0, f"{ident} has no output price"


# ------------------------------------------------------------------ 6 a preferred member per group
def test_group_without_a_preferred_member_is_refused(root, load_script, pricing):
    groups = _valid_groups(root, pricing)
    for member in groups["low"]["models"]:
        member["preferred"] = False
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a group with no preferred member was accepted"
    assert any("preferred" in error for error in errors), errors


# ------------------------------------------------------------------ 6b the primary anchor decides
def test_member_without_a_family_is_refused(root, load_script, pricing):
    """A member that names no family cannot be matched to an anchor."""
    groups = _valid_groups(root, pricing)
    del groups["low"]["models"][0]["family"]
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a member without a family was accepted"
    assert any("family" in error for error in errors), errors


def test_group_whose_primary_anchor_has_no_member_is_refused(root, load_script, pricing):
    """A primary anchor with no model behind it cannot decide anything, so it is refused."""
    groups = _valid_groups(root, pricing)
    groups["low"] = _group(root, "low", groups["low"]["anchors"], [
        _member(pricing, "openrouter/some/other-model", 1, 2, family="other", preferred=True),
    ], primary="anthropic")
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a primary anchor with no member behind it was accepted"
    assert any("low" in error and ("primary" in error or "anchor" in error
                                    or "anthropic" in error)
               for error in errors), errors


def test_group_whose_members_name_no_family_is_refused(root, load_script, pricing):
    """A group whose members name no family at all cannot stand behind its anchor."""
    groups = _valid_groups(root, pricing)
    groups["low"] = _group(root, "low", groups["low"]["anchors"], [
        _member(pricing, "openrouter/some/nameless-model", 1, 2, family=None,
                preferred=True),
    ], primary="anthropic")
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a group with no member behind its primary anchor was accepted"
    assert any("low" in error and ("primary" in error or "anchor" in error
                                    or "anthropic" in error)
               for error in errors), errors


# ------------------------------------------------------------------ 7 ids are provider-qualified
def test_model_id_that_is_not_provider_qualified_is_refused(root, load_script, pricing):
    groups = _valid_groups(root, pricing)
    groups["low"]["models"][0]["id"] = "haiku"
    doc = _map_doc(root, groups)
    errors = _errors(_map_validator(root, load_script), doc)
    assert errors, "a bare model id was accepted"
    assert any("haiku" in error or "provider" in error for error in errors), errors


# ------------------------------------------------------------------ 8 the level vocabulary
def test_resolver_accepts_exactly_the_four_cost_tier_groups(root, load_script):
    """The resolver's vocabulary is the four cost tiers and nothing else."""
    accepted = set()
    for candidate in ("low", "medium", "high", "top") + OUTSIDE_THE_FOUR:
        try:
            resolved = _resolve(root, load_script, candidate)
        except ValueError:
            continue
        if resolved:
            accepted.add(candidate)
    assert accepted == {"low", "medium", "high", "top"}


@pytest.mark.parametrize("level", OUTSIDE_THE_FOUR)
def test_resolver_refuses_a_level_outside_the_four_groups(root, load_script, level):
    """A name outside the vocabulary fails loud and names the accepted set."""
    with pytest.raises(ValueError) as exc_info:
        _resolve(root, load_script, level)
    message = str(exc_info.value)
    assert level in message
    for accepted in ("low", "medium", "high", "top"):
        assert accepted in message, f"{accepted} missing from {message!r}"


# ------------------------------------------------------------------ 9 what the resolver returns
@pytest.mark.parametrize("level", ["low", "medium", "high", "top"])
def test_resolver_returns_the_groups_preferred_member_id(root, load_script, level):
    doc = _shipped_map(root)
    assert _resolve(root, load_script, level) == _preferred_id(doc, level)


def test_resolver_without_a_level_resolves_to_nothing(root, load_script):
    assert _resolve(root, load_script, None) is None
