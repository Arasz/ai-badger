"""Route-by-level persona emission: `personaModelPins` decides whether pins survive a refresh.

ADR-0033: a project may drop every `model:` pin and route by `level:` alone, with tier taste
in model-groups.json. The knob makes that intent survive den-refresh — without it the catalog
copy re-adds the pin on every scaffold, the churn that keeps undoing a deliberate drop.

ADR-0027's dual-key default is untouched: knob absent (or true) and the pin lands beside
`level:` exactly as before. The off-case and the on-case are a provocation pair — the strip
test can only fail while the default test still sees pins.
"""
from __future__ import annotations

import re

import frontmatter as fm

from scaffold_helpers import _config


def _agents(target):
    return target / ".ai-badger" / "agents"


def _fields(path):
    return fm.fields(path.read_text(encoding="utf-8"))


def _level_only_config():
    config = _config(stacks=["dotnet"])
    config["personaModelPins"] = False
    return config


def test_personas_land_without_model_pins_when_route_by_level_is_on(make_scaffolder, root):
    """The strip removes the `model:` line and nothing else — the rest lands as shipped."""
    make_scaffolder(config=_level_only_config()).run(generated_at="2026-09-29T00:00:00Z")

    scaffolded = sorted(_agents(make_scaffolder.target).glob("*.md"))
    assert scaffolded, "expected the catalog to scaffold at least one persona"
    for path in scaffolded:
        text = path.read_text(encoding="utf-8")
        fields = fm.fields(text)
        assert "model" not in fields, f"{path.name} still carries a model: pin"
        assert fields.get("name") and fields.get("level"), (
            f"{path.name} lost frontmatter the strip must not touch: {fields}")
        source = next(root.glob(f"features/*/personas/{path.name}"), None)
        assert source is not None, f"{path.name} scaffolded from outside the persona catalog"
        expected = re.sub(r"^model: .*\n", "", source.read_text(encoding="utf-8"),
                          count=1, flags=re.MULTILINE)
        assert text == expected, f"{path.name} changed beyond the removed model: line"


def test_a_refresh_does_not_re_add_a_dropped_pin(make_scaffolder):
    """The churn itself: a second scaffold (den-refresh) must not resurrect the pin."""
    config = _level_only_config()
    make_scaffolder(config=config).run(generated_at="2026-09-29T00:00:00Z")
    first = {p.name: p.read_text(encoding="utf-8")
             for p in _agents(make_scaffolder.target).glob("*.md")}

    make_scaffolder(config=config).run(generated_at="2026-09-30T00:00:00Z")

    refreshed = {p.name: p.read_text(encoding="utf-8")
                 for p in _agents(make_scaffolder.target).glob("*.md")}
    assert refreshed == first, "the refresh rewrote persona copies it should have left alone"
    assert all("model" not in _fields(p)
               for p in _agents(make_scaffolder.target).glob("*.md")), \
        "a refresh re-added a model: pin"


def test_the_model_pin_stays_beside_the_level_by_default(make_scaffolder):
    """ADR-0027 dual-key, grandfathered: with the knob absent, emission is unchanged."""
    make_scaffolder(config=_config(stacks=["dotnet"])).run(generated_at="2026-09-29T00:00:00Z")

    fields = _fields(_agents(make_scaffolder.target) / "architect.md")
    assert fields.get("model") == "opus"
    assert fields.get("level") == "high"
