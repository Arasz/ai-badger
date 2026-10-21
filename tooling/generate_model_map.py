#!/usr/bin/env python3
"""Regenerate the model map from the leaderboard CSV, pi's model store and the OpenRouter
catalogue snapshot.

Usage:
    tooling/generate_model_map.py                 # write the map
    tooling/generate_model_map.py --check         # report drift, write nothing
    tooling/generate_model_map.py --refresh-catalogue   # re-fetch the catalogue snapshot

The refresh rule, one pass over the leaderboard rows:
  tier    a row's tier is its input price against the rungs 0.1 / 2 / 4 USD per 1M
          tokens; the top tier takes the rest. A zero price is a price of zero, so it
          lands in low.
  id      the id is a verbatim OpenRouter listing this key may route. pi's model store
          carries the per-key list (OpenRouter's guardrails and provider restrictions
          are already applied), so a model the key cannot route has no id: a model pi
          lists only under a native vendor (anthropic, openai, google) stays out, with
          its reason, even when the public OpenRouter catalogue lists it. A row with no
          admissible id stays out, with its reason, and a row that resolves only to a
          free listing while the leaderboard prices it above zero stays out too.
  newest  a tier keeps the newest model of each model line - the display name without
          its version tokens - the newest being the lowest leaderboard rank.
  family  the family a member belongs to: the line word for the anchored vendors
          (opus, sonnet, haiku, fable, luna, sol, astra, terra) and the product name
          for the rest (muse, glm, deepseek, mimo, gemini, step, dots3-note, gpt).
  order   the group leads with the model the ladder's anchor names, when this key can
          route a member of that family; a group whose ladder families are all out of
          reach leads with the best member of a declared family instead. The rest follow
          in ascending (input, output) price; the zero-priced open-weight members come
          last, because a zero price has no position in the order.
  price   the leaderboard prices the map. A row it leaves unpriced is reported by name
          and stays out of the map: the gap is in the leaderboard, not in the map.

The map's source block carries the excluded rows with their reasons and the unpriced
rows by name, so the decision is checkable from the data and not only from a chat
message.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
LEADERBOARD_PATH = ROOT / "features" / "common" / "data" / "leaderboard.csv"
CATALOGUE_PATH = ROOT / "features" / "common" / "data" / "openrouter-models.json"
MAP_PATH = ROOT / "features" / "common" / "data" / "model-groups.json"
VERSION_PATH = ROOT / "VERSION"
DEFAULT_STORE = Path.home() / ".pi" / "agent" / "models-store.json"
CATALOGUE_URL = "https://openrouter.ai/api/v1/models"

#: The families the map declares, in the order the anchors are written.
FAMILIES = ("anthropic", "openai")

#: The owner's ladder: the family each cost tier anchors on.
ANCHORS = {
    "low": {"anthropic": "haiku", "openai": "luna"},
    "medium": {"anthropic": "sonnet", "openai": "sol"},
    "high": {"anthropic": "opus", "openai": "sol"},
    "top": {"anthropic": "fable", "openai": "astra"},
}

#: The anchor key whose model leads its group. Anthropic decides every tier.
PRIMARY = "anthropic"

#: The price rungs, cheapest first. The top tier takes everything above the last rung.
RUNGS = (("low", 0.1), ("medium", 2.0), ("high", 4.0))

#: The store sections whose listings may carry an OpenRouter id of a native vendor.
NATIVE_VENDORS = ("anthropic", "openai", "google")

#: The creators whose models are named by their line word (opus, sol, terra, ...).
ANCHORED_CREATORS = ("Anthropic", "OpenAI")

#: Words that qualify a model without naming its family.
QUALIFIERS = ("pro", "preview", "adaptive", "free", "batch")

#: A version token: a number, or a letter followed by a number (V4.1).
VERSION_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Za-z]\d[\w.]*)$")

#: The store's own name for a listing: "Vendor: Model", or a bare model name.
VENDOR_PREFIX_RE = re.compile(r"^[^:]{1,24}:\s+")

#: A parenthetical the leaderboard adds to a display name ("Claude Opus 4.7 (Adaptive)").
PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")


# ------------------------------------------------------------------ helpers
def is_version(token: str) -> bool:
    """True when the token carries a version number (5.5, 1017, V4.1)."""
    return bool(VERSION_RE.match(token))


def strip_versions(token: str) -> str:
    """The token without its version parts: GPT-6.1 -> GPT, GLM-5.3 -> GLM."""
    kept = [part for part in token.split("-") if not is_version(part)]
    return "-".join(kept)


def is_qualifier(token: str) -> bool:
    """True when the token qualifies a model without naming its family."""
    return token.strip("()").lower() in QUALIFIERS


def slug(name: str) -> str:
    """The OpenRouter spelling of a display name: lowercase, spaces as dashes."""
    return name.strip().lower().replace(" ", "-")


def plain_name(name: str) -> str:
    """A display name without the store's vendor prefix and without a parenthetical."""
    return PARENTHETICAL_RE.sub("", VENDOR_PREFIX_RE.sub("", name)).strip()


def display_key(name: str) -> str:
    """The matching key of a display name: case, punctuation and spacing aside."""
    text = VENDOR_PREFIX_RE.sub("", name).strip()
    text = re.sub(r"\(free\)\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^0-9a-z]+", " ", text.lower()).strip()


def family_of(name: str, creator: str) -> str:
    """The family a model belongs to: the anchored vendors' line word, the rest's
    product name."""
    tokens = name.split()
    if creator in ANCHORED_CREATORS:
        rest = [token for token in tokens[1:]
                if strip_versions(token) and not is_qualifier(token)]
        return rest[0].lower() if rest else strip_versions(tokens[0]).lower()
    parts = []
    for part in tokens[0].split("-"):
        if is_version(part):
            break
        parts.append(part)
    return "-".join(parts).lower()


def vendor_of(creator: str) -> Optional[str]:
    """The declared family a model belongs to, when its creator is an anchored vendor."""
    return creator.lower() if creator in ANCHORED_CREATORS else None


def line_of(name: str) -> str:
    """The model line: the display name without its version tokens."""
    return " ".join(strip_versions(token) for token in name.split()
                    if strip_versions(token)).lower()


def tier_of(price_in: float) -> str:
    """The cost tier a price falls in."""
    for tier, rung in RUNGS:
        if price_in <= rung:
            return tier
    return "top"


def number(value: float) -> str:
    """A price or score as the map writes it: 2, 0.5, 67.23."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value)


def sha256_of(path: Path) -> str:
    """The sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ inputs
def load_leaderboard(path: Path) -> List[Dict[str, str]]:
    """The leaderboard rows, in rank order."""
    if not path.is_file():
        raise SystemExit(f"the leaderboard CSV is missing: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return sorted(rows, key=lambda row: int(row["rank"]))


def load_store(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """pi's model store: the listings of every provider section."""
    if not path.is_file():
        raise SystemExit(f"the model store is missing: {path}")
    store = json.loads(path.read_text(encoding="utf-8"))
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for provider, body in store.items():
        if isinstance(body, dict) and isinstance(body.get("models"), list):
            sections[provider] = body["models"]
    return sections


def load_catalogue(path: Path) -> Dict[str, Any]:
    """The OpenRouter catalogue snapshot: the ids the catalogue carries."""
    if not path.is_file():
        raise SystemExit(f"the OpenRouter catalogue snapshot is missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    return {"ids": set(document.get("ids") or []),
            "checkedAt": document.get("checkedAt", ""),
            "source": document.get("source", CATALOGUE_URL)}


def fetch_catalogue(path: Path) -> Dict[str, Any]:
    """Refresh the catalogue snapshot from OpenRouter and write it."""
    with urllib.request.urlopen(CATALOGUE_URL, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    ids = sorted({model["id"] for model in payload.get("data", []) if model.get("id")})
    document = {"source": CATALOGUE_URL,
                "checkedAt": datetime.date.today().isoformat(), "ids": ids}
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return document


# ------------------------------------------------------------------ resolution
def index_listings(sections: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """Every listing, by the matching key of its display name."""
    index: Dict[str, List[Dict[str, Any]]] = {}
    for provider, models in sections.items():
        for model in models:
            name = model.get("name") or ""
            if not name:
                continue
            entry = {"provider": provider, "id": model.get("id", ""),
                     "name": name, "cost": model.get("cost") or {}}
            index.setdefault(display_key(name), []).append(entry)
    return index


def free_listing(entry: Dict[str, Any]) -> bool:
    """True when the listing costs nothing to call."""
    cost = entry.get("cost") or {}
    return not cost.get("input") and not cost.get("output")


def match_entries(name: str, index: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The store listings a display name matches.

    A listing matches when its key is the name's key, or when it extends that key with
    a dated release ("Qwen3.8 Max" -> "Qwen3.8 Max (0902)"). The exact match wins.
    """
    key = display_key(name)
    exact = list(index.get(key, []))
    if exact:
        return exact
    extended = []
    for other, entries in index.items():
        suffix = other[len(key) + 1:]
        if not other.startswith(key + " "):
            continue
        if all(token.isdigit() for token in suffix.split()):
            extended.extend(entries)
    return extended


def resolve_id(row: Dict[str, str], index: Dict[str, List[Dict[str, Any]]],
               catalogue_ids: set) -> Tuple[Optional[str], str, List[str]]:
    """The OpenRouter id of a leaderboard row.

    Returns the id (or None), the reason a row is excluded, and the providers pi
    lists the model under. A listing pi carries under the openrouter provider is
    admissible verbatim — that list is the key's own, so every id in it is one this
    key may route. A listing under a native vendor is not: pi routes that model
    through the native provider, and the OpenRouter id the public catalogue lists for
    it is one this key cannot reach (an OpenRouter guardrail blocks the provider).
    """
    name = row["model"]
    entries = match_entries(plain_name(name), index)
    providers = sorted({entry["provider"] for entry in entries})
    openrouter_entries = [entry for entry in entries if entry["provider"] == "openrouter"]
    if openrouter_entries:
        entry = sorted(openrouter_entries, key=lambda item: item["id"])[0]
        return f"openrouter/{entry['id']}", "", providers
    native = [entry for entry in entries if entry["provider"] in NATIVE_VENDORS]
    if native:
        entry = sorted(native, key=lambda item: item["id"])[0]
        candidate = f"openrouter/{entry['provider']}/{slug(plain_name(entry['name']))}"
        if candidate.split("/", 1)[1] in catalogue_ids:
            return None, (f"no routable OpenRouter listing: the catalogue lists "
                          f"{candidate}, but this key's model list does not carry it "
                          f"(pi's store lists the model only under "
                          f"{entry['provider']})"), providers
        return None, (f"no OpenRouter listing: the catalogue does not carry "
                      f"{candidate}"), providers
    if providers:
        return None, ("no OpenRouter listing: pi's store lists it only under "
                      + ", ".join(providers)), providers
    return None, "no OpenRouter listing: no provider in pi's store lists it", providers


# ------------------------------------------------------------------ rendering
def build_map(leaderboard: List[Dict[str, str]],
              sections: Dict[str, List[Dict[str, Any]]],
              catalogue: Dict[str, Any],
              catalogue_path: Path,
              leaderboard_path: Path,
              store_path: Path,
              measured_at: str,
              framework_version: str) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """The map document, and the rows the rule left out."""
    index = index_listings(sections)
    catalogue_ids = catalogue["ids"]
    members: Dict[str, List[Dict[str, Any]]] = {tier: [] for tier in ANCHORS}
    unpriced: List[str] = []
    excluded: List[Dict[str, str]] = []

    for row in leaderboard:
        name = row["model"]
        model = plain_name(name)
        price_in = row.get("inputPrice", "").strip()
        price_out = row.get("outputPrice", "").strip()
        ident, reason, _ = resolve_id(row, index, catalogue_ids)
        if ident is None:
            excluded.append({"model": name, "reason": reason})
            continue
        if not price_in or not price_out:
            unpriced.append(name)
            excluded.append({"model": name,
                             "reason": "the leaderboard prices this row at no cost"})
            continue
        cost_in = float(price_in)
        if cost_in > 0:
            openrouter_entries = [entry for entry in match_entries(plain_name(name), index)
                                  if entry["provider"] == "openrouter"]
            if openrouter_entries and all(free_listing(entry)
                                          for entry in openrouter_entries):
                excluded.append({"model": name,
                                 "reason": f"resolves only to a free listing "
                                           f"({ident}), which the leaderboard prices "
                                           f"above zero"})
                continue
        tier = tier_of(cost_in)
        members[tier].append({
            "id": ident,
            "family": family_of(model, row.get("creator", "")),
            "vendor": vendor_of(row.get("creator", "")),
            "line": line_of(model),
            "rank": int(row["rank"]),
            "pricing": {"inputPerM": float(price_in), "outputPerM": float(price_out),
                        "currency": "USD"},
            "license": row.get("sourceType", ""),
            "score": float(row.get("overallScore") or 0),
        })

    groups: Dict[str, Any] = {}
    for tier, anchors in ANCHORS.items():
        kept: List[Dict[str, Any]] = []
        newest: Dict[str, Dict[str, Any]] = {}
        for member in members[tier]:
            line = member.pop("line")
            current = newest.get(line)
            if current is None or member["rank"] < current["rank"]:
                newest[line] = member
        kept = list(newest.values())
        derived = dict(anchors)
        # The ladder's anchor leads the group when this key can route a member of that
        # family. A group whose ladder families are all out of reach leads with the best
        # member of a declared family, and that member's family becomes the anchor.
        ladder_members = [member for member in kept
                          if member["family"] in set(anchors.values())]
        if ladder_members:
            lead = min(ladder_members, key=lambda member: member["rank"])
            primary = next(key for key, family in anchors.items()
                           if family == lead["family"])
        else:
            own = [member for member in kept if member.get("vendor")]
            if not own:
                raise SystemExit(f"{tier}: no declared family has a member this key "
                                 f"can route")
            lead = min(own, key=lambda member: member["rank"])
            primary = lead["vendor"]
            derived[primary] = lead["family"]
        tail = sorted((member for member in kept if member is not lead),
                       key=lambda member: (member["pricing"]["inputPerM"] <= 0,
                                           member["pricing"]["inputPerM"],
                                           member["pricing"]["outputPerM"]))
        rendered = []
        for member in [lead] + tail:
            rank = member["rank"]
            member.pop("rank")
            member.pop("vendor")
            pricing = member["pricing"]
            rendered.append({
                "id": member["id"],
                "family": member["family"],
                "preferred": member is lead,
                "pricing": pricing,
                "license": member["license"],
                "score": member["score"],
                "evidence": (f"leaderboard rank {rank} (score "
                             f"{number(member['score'])}), priced "
                             f"{number(pricing['inputPerM'])}/"
                             f"{number(pricing['outputPerM'])} USD per 1M tokens; "
                             f"features/common/data/leaderboard.csv"),
            })
        groups[tier] = {"anchors": derived, "primary": primary, "models": rendered}

    document = {
        "$schema": "../../../schemas/model-groups.schema.json",
        "frameworkVersion": framework_version,
        "registryVersion": 3,
        "measuredAt": measured_at,
        "families": list(FAMILIES),
        "source": {
            "leaderboard": {
                "path": "features/common/data/leaderboard.csv",
                "rows": len(leaderboard),
                "sha256": sha256_of(leaderboard_path),
            },
            "modelStore": {
                "path": str(store_path).replace(str(Path.home()), "~"),
                "provider": "openrouter",
            },
            "generator": "tooling/generate_model_map.py",
            "openrouterCatalogue": {
                "path": "features/common/data/openrouter-models.json",
                "checkedAt": catalogue["checkedAt"],
                "models": len(catalogue["ids"]),
                "sha256": sha256_of(catalogue_path),
            },
            "unpriced": sorted(unpriced),
            "excluded": sorted(excluded, key=lambda item: item["model"]),
            "note": (
                "Prices and scores come from the leaderboard CSV; the ids come from "
                "pi's model store, which carries the models this key may route (an "
                "OpenRouter guardrail or a provider restriction is already applied "
                "there), and the OpenRouter catalogue, the public record of what "
                "OpenRouter lists. A tier holds the models whose input price sits "
                "under its rung (low 0.1, medium 2, high 4 USD per 1M tokens; the top "
                "tier takes the rest), keeping the newest model of each model line in "
                "the tier. A group leads with the model its ladder anchor names when "
                "the key can route a member of that family, and with the best member "
                "of a declared family when it cannot; the rest follow in ascending "
                "price; the zero-priced open-weight members come last, because a zero "
                "price has no position in the order. A row the leaderboard leaves "
                "unpriced is reported under unpriced; a row with no id this key may "
                "route is reported under excluded, with its reason."),
        },
        "groups": groups,
    }
    return document, {"unpriced": unpriced, "excluded": excluded}


def render(document: Dict[str, Any]) -> str:
    """The map as a file: two-space indent, trailing newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ entry point
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report drift against the committed map; write nothing")
    parser.add_argument("--leaderboard", type=Path, default=LEADERBOARD_PATH)
    parser.add_argument("--catalogue", type=Path, default=CATALOGUE_PATH)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--out", type=Path, default=MAP_PATH)
    parser.add_argument("--refresh-catalogue", action="store_true",
                        help="re-fetch the OpenRouter catalogue snapshot and stop")
    parser.add_argument("--measured-at", default=None,
                        help="the map's measuredAt date (default: today)")
    args = parser.parse_args(argv)

    if args.refresh_catalogue:
        document = fetch_catalogue(args.catalogue)
        print(f"catalogue refreshed: {len(document['ids'])} ids in {args.catalogue}")
        return 0

    leaderboard = load_leaderboard(args.leaderboard)
    sections = load_store(args.store)
    catalogue = load_catalogue(args.catalogue)
    measured_at = args.measured_at or datetime.date.today().isoformat()
    framework_version = VERSION_PATH.read_text(encoding="utf-8").strip()

    document, report = build_map(leaderboard, sections, catalogue, args.catalogue,
                                  args.leaderboard, args.store, measured_at,
                                  framework_version)
    text = render(document)

    print("unpriced leaderboard rows (a gap in the leaderboard, not in the map):")
    for name in sorted(report["unpriced"]):
        print(f"  {name}")
    print("excluded leaderboard rows:")
    for entry in sorted(report["excluded"], key=lambda item: item["model"]):
        print(f"  {entry['model']}: {entry['reason']}")
    for tier, group in document["groups"].items():
        print(f"{tier}: {group['primary']} -> {group['models'][0]['id']} "
              f"({len(group['models'])} members)")

    if args.check:
        committed = args.out.read_text(encoding="utf-8")
        if committed == text:
            print("map is up to date")
            return 0
        print("map drifted from the sources")
        return 1
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
