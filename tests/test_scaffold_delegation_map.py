"""`.ai-badger/delegation.md`: the briefing a session reads before it hands work to a persona."""
from __future__ import annotations

from scaffold_helpers import _config

PERSONA_WITH_LANE = """---
name: lane-probe
description: >
  Probe persona for the delegation map. Never routed to, never delegated to.
model: opus
---

Body.
"""


def _routed_config():
    """A project that configures routing, verifiers and the personas the catalog ships."""
    config = _config(stacks=["dotnet"],
                     commands={"test": "pytest -q", "lint": "pylint ."})
    config["personaRouting"] = [{"work": "design", "agent": "architect"},
                                {"work": "review", "agent": "code-reviewer"}]
    return config


def _delegation(make_scaffolder, config=None, **kwargs):
    make_scaffolder(config=config, **kwargs).run(generated_at="2026-07-31T00:00:00Z")
    return (make_scaffolder.target / ".ai-badger" / "delegation.md").read_text(encoding="utf-8")


def _section(doc: str, title: str) -> str:
    """The body of one `## title` section, without its heading."""
    assert f"## {title}\n" in doc, f"no '## {title}' section in:\n{doc}"
    return doc.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0].strip()


def _line_for(doc: str, name: str) -> str:
    """The single rendered line naming `name`."""
    matches = [ln for ln in doc.splitlines() if ln.startswith(f"- `{name}`")]
    assert len(matches) == 1, f"expected one line for {name}, got {matches}\n{doc}"
    return matches[0]


# ------------------------------------------------------------------ what the map carries
def test_the_delegation_map_names_the_stacks_the_routing_and_the_verifiers(make_scaffolder):
    doc = _delegation(make_scaffolder, _routed_config())

    assert doc.startswith("# Delegation map — probe\n")
    # The wording the freshness guard exempts as a stamp — a version bump alone is not staleness.
    assert "Scaffolded by ai-badger" in doc
    assert _section(doc, "Stacks") == "dotnet"
    assert _section(doc, "Routing (config.json personaRouting)") == (
        "- design → `architect`\n- review → `code-reviewer`")
    assert _section(doc, "Verifiers") == "- `test`: `pytest -q`\n- `lint`: `pylint .`"


def test_the_delegation_map_lists_every_scaffolded_persona_once(make_scaffolder):
    doc = _delegation(make_scaffolder, _routed_config())

    scaffolded = sorted(p.stem for p in
                        (make_scaffolder.target / ".ai-badger" / "agents").glob("*.md"))
    assert scaffolded, "expected the catalog to scaffold at least one persona"
    listed = [ln.split("`")[1] for ln in _section(doc, "Personas available here").splitlines()]
    assert listed == scaffolded
    assert _line_for(doc, "architect").startswith(
        "- `architect` — Design and decomposition specialist")


def test_the_delegation_map_names_the_mcp_servers_the_project_gets(make_scaffolder):
    doc = _delegation(make_scaffolder, _routed_config())

    assert _line_for(doc, "code-review-graph") == (
        "- `code-review-graph` — This project has a knowledge graph")


# ------------------------------------------------------------------------------- lanes
def test_a_persona_lane_comes_from_its_model_frontmatter(make_scaffolder):
    agents = make_scaffolder.target / ".ai-badger" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "lane-probe.md").write_text(PERSONA_WITH_LANE, encoding="utf-8")

    doc = _delegation(make_scaffolder, _routed_config())

    assert _line_for(doc, "lane-probe") == (
        "- `lane-probe` — Probe persona for the delegation map. Lane: opus.")


def test_a_persona_without_a_model_runs_on_the_session_default(make_scaffolder):
    # An explicit lane-less probe: since WP-A every catalog persona names a lane, so the
    # degrade path can no longer be observed on a shipped persona.
    agents = make_scaffolder.target / ".ai-badger" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    laneless = PERSONA_WITH_LANE.replace("model: opus\n", "").replace("lane-probe", "no-lane-probe")
    (agents / "no-lane-probe.md").write_text(laneless, encoding="utf-8")

    doc = _delegation(make_scaffolder, _routed_config())

    assert _line_for(doc, "no-lane-probe").endswith("Lane: session default.")


# --------------------------------------------------------------------------- degrading
def test_the_delegation_map_still_renders_when_nothing_is_configured(make_scaffolder):
    config = _config(stacks=["dotnet"], commands={})
    config["mcp"] = {"decline": ["code-review-graph"]}

    doc = _delegation(make_scaffolder, config)

    assert "None configured" in _section(doc, "Routing (config.json personaRouting)")
    assert _section(doc, "Verifiers") == "_None configured._"
    servers = _section(doc, "MCP servers reachable here")
    assert servers == "_None indexed._" or "`hermes`" in servers


def test_the_delegation_map_is_recorded_in_the_manifest(make_scaffolder):
    result = make_scaffolder(config=_routed_config()).run(generated_at="2026-07-31T00:00:00Z")

    recorded = [e for e in result["manifest"]["entries"]
                if e["target"] == ".ai-badger/delegation.md"]
    assert len(recorded) == 1
    assert recorded[0]["source"] == "features/common/templates/delegation.md.tmpl"
