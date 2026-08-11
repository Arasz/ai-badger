"""Tests for features/copilot/adjustments/adjust_agents.py — one frontmatter block, right stacks.

Issue #210: the converter emitted its own `---` block on top of the persona's own, and
iterated every stack in the whole index instead of the configured ones. The stack rule is
the same one `scaffold_personas` applies: resolved stacks minus `config.exclude.personas`,
and it reaches the adjuster through the context rather than being re-derived there.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from conftest import _test_write

ADJUSTER = "features/copilot/adjustments/adjust_agents.py"
AGENTS_DIR = Path(".github") / "agents"

PERSONA_WITH_FRONTMATTER = """---
name: api-engineer
description: >
  HTTP API design and implementation specialist.
tools: Read, Grep, WebFetch
---

# API engineer

Design the API surface first.
"""

PERSONA_PLAIN = """# Reviewer

Review the diff.
"""


def _persona(fw: Path, stack: str, name: str, text: str) -> dict:
    rel = f"features/{stack}/personas/{name}.md"
    path = fw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, text, encoding="utf-8")
    return {"name": name, "path": rel}


def _context(fw: Path, target: Path, personas) -> dict:
    return {
        "framework_root": fw,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "target_dir": target / ".ai-badger",
        "target": target,
        "personas": list(personas),
    }


def _agent_file(target: Path, name: str) -> str:
    return (target / AGENTS_DIR / f"{name}.agent.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    """Parse the leading YAML block of an emitted agent file."""
    assert text.startswith("---\n")
    block, _, _ = text[4:].partition("\n---\n")
    return yaml.safe_load(block)


def _proj(tmp_path: Path) -> Path:
    target = tmp_path / "proj"
    target.mkdir(exist_ok=True)
    return target


def test_an_emitted_agent_carries_exactly_one_frontmatter_block(tmp_path, load_script):
    """The whole point of #210's first defect: the persona's own block must not survive."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "node", "api-engineer", PERSONA_WITH_FRONTMATTER)
    target = _proj(tmp_path)

    result = adjust_agents.adjust(_context(fw, target, [item]))

    assert result["applied"]
    text = _agent_file(target, "api-engineer")
    assert [l for l in text.splitlines() if l.strip() == "---"] == ["---", "---"]
    assert "# API engineer" in text


def test_source_frontmatter_fields_reach_the_emitted_block(tmp_path, load_script):
    """An unmapped persona's own description and tools are merged, not discarded."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "node", "api-engineer", PERSONA_WITH_FRONTMATTER)
    target = _proj(tmp_path)

    adjust_agents.adjust(_context(fw, target, [item]))

    meta = _frontmatter(_agent_file(target, "api-engineer"))
    assert meta["name"] == "api-engineer"
    assert meta["description"].strip() == "HTTP API design and implementation specialist."
    assert meta["tools"] == ["Read", "Grep", "WebFetch"]
    assert meta["user-invocable"] is True


def test_the_copilot_specific_mapping_still_wins_for_mapped_personas(tmp_path, load_script):
    """PERSONA_MAP is a deliberate Copilot mapping; it overrides the persona's own block."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "common", "architect",
                    "---\nname: architect\ndescription: source text\ntools: Read\n---\n\nBody.\n")
    target = _proj(tmp_path)

    adjust_agents.adjust(_context(fw, target, [item]))

    meta = _frontmatter(_agent_file(target, "architect"))
    assert meta["description"] == adjust_agents.PERSONA_MAP["architect"]["description"]
    assert meta["tools"] == adjust_agents.PERSONA_MAP["architect"]["tools"]


def test_the_personas_model_is_dropped_because_copilot_reads_other_model_names(
        tmp_path, load_script):
    """`model: sonnet` is a Claude alias; Copilot picks its own model, so the key is dropped."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "node", "api-engineer",
                    "---\nname: api-engineer\ndescription: d\nmodel: sonnet\n---\n\nBody.\n")
    target = _proj(tmp_path)

    adjust_agents.adjust(_context(fw, target, [item]))

    text = _agent_file(target, "api-engineer")
    assert "model" not in _frontmatter(text)
    assert "sonnet" not in text


def test_a_persona_without_frontmatter_still_converts(tmp_path, load_script):
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "python", "plain-reviewer", PERSONA_PLAIN)
    target = _proj(tmp_path)

    result = adjust_agents.adjust(_context(fw, target, [item]))

    assert result["applied"]
    text = _agent_file(target, "plain-reviewer")
    assert "# Reviewer" in text
    assert _frontmatter(text)["description"] == "AI agent persona: plain-reviewer"


def test_the_adjuster_delivers_exactly_the_personas_the_context_carries(tmp_path, load_script):
    """#210's second defect: the adjuster may not re-derive a persona set of its own."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    picked = _persona(fw, "python", "py-engineer", PERSONA_PLAIN)
    _persona(fw, "dotnet", "dotnet-engineer", PERSONA_PLAIN)
    target = _proj(tmp_path)

    result = adjust_agents.adjust(_context(fw, target, [picked]))

    assert result["applied"]
    assert sorted(p.name for p in (target / AGENTS_DIR).iterdir()) == ["py-engineer.agent.md"]


def test_a_stale_agent_file_from_a_prior_run_is_removed(tmp_path, load_script):
    """A wrong-stack file the manifest attributes to this adjuster is deleted, and noted."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "common", "architect", PERSONA_PLAIN)
    target = _proj(tmp_path)
    stale = target / AGENTS_DIR / "dotnet-engineer.agent.md"
    stale.parent.mkdir(parents=True)
    _test_write(stale, "stale\n", encoding="utf-8")
    (target / ".ai-badger").mkdir()
    _test_write(target / ".ai-badger" / "manifest.json", json.dumps({"entries": [{
        "feature": "adjustments", "stack": "copilot",
        "name": "adjustments/.github/agents/dotnet-engineer.agent.md",
        "source": "features/copilot/adjustments/adjust_agents.py",
        "target": ".github/agents/dotnet-engineer.agent.md", "hash": "0" * 64,
    }]}), encoding="utf-8")

    result = adjust_agents.adjust(_context(fw, target, [item]))

    assert not stale.exists()
    assert "removed" in result["notes"]
    assert ".github/agents/dotnet-engineer.agent.md" not in result["files"]


def test_an_agent_file_the_manifest_does_not_own_is_left_alone(tmp_path, load_script):
    """A hand-authored .agent.md has no manifest entry and must never be deleted."""
    adjust_agents = load_script(ADJUSTER)
    fw = tmp_path / "framework"
    item = _persona(fw, "common", "architect", PERSONA_PLAIN)
    target = _proj(tmp_path)
    mine = target / AGENTS_DIR / "my-own.agent.md"
    mine.parent.mkdir(parents=True)
    _test_write(mine, "hand-authored\n", encoding="utf-8")

    adjust_agents.adjust(_context(fw, target, [item]))

    assert mine.read_text(encoding="utf-8") == "hand-authored\n"


def test_the_stack_rule_is_the_scaffolds_own(load_script):
    """`applicable_feature_items` filters by resolved stacks minus exclusions — issue #210."""
    bl = load_script("engine/badger_lib.py")
    index = {"stacks": {
        "common": {"personas": [{"name": "architect", "path": "a"}]},
        "python": {"personas": [{"name": "py-engineer", "path": "b"},
                                {"name": "declined", "path": "c"}]},
        "dotnet": {"personas": [{"name": "dotnet-engineer", "path": "d"}]},
    }}
    config = {"stacks": ["python"], "exclude": {"personas": ["declined"]}}

    picked = bl.applicable_feature_items(index, config, "personas")

    assert [(stack, item["name"]) for stack, item in picked] == [
        ("common", "architect"), ("python", "py-engineer")]


# -- the wiring: what the scaffolder hands the adjustment ----------------------------

def _fake_framework(tmp_path: Path, root: Path, personas, exclude=None) -> dict:
    """A framework root carrying only the agents adjustment, plus the index it needs."""
    for stack, name in personas:
        _persona(tmp_path, stack, name, PERSONA_PLAIN)
    adjustments = tmp_path / "features" / "copilot" / "adjustments"
    adjustments.mkdir(parents=True, exist_ok=True)
    _test_write(adjustments / "adjustment.json", json.dumps({"agent": "copilot", "adjustments": [
        {"feature": "agents", "description": "personas", "script": "adjust_agents.py"}]}), encoding="utf-8")
    shutil.copyfile(root / ADJUSTER, adjustments / "adjust_agents.py")

    index = {"frameworkVersion": "0.1.0", "stacks": {}}
    for stack, name in personas:
        index["stacks"].setdefault(stack, {}).setdefault("personas", []).append(
            {"name": name, "path": f"features/{stack}/personas/{name}.md"})
    _test_write(tmp_path / "index.json", json.dumps(index), encoding="utf-8")

    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": ["copilot"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if exclude is not None:
        config["exclude"] = exclude
    return config


def test_only_the_configured_stacks_personas_reach_the_copilot_agents_dir(
        make_scaffolder, tmp_path, root):
    """End to end: a dotnet persona must not land in `.github/agents/` of a python project."""
    config = _fake_framework(tmp_path, root, [
        ("common", "architect"), ("python", "py-engineer"), ("dotnet", "dotnet-engineer")])
    scaf = make_scaffolder(root=tmp_path, config=config)

    scaf.run_adjustments()

    delivered = sorted(p.name for p in (make_scaffolder.target / AGENTS_DIR).iterdir())
    assert delivered == ["architect.agent.md", "py-engineer.agent.md"]


def test_a_declined_persona_never_reaches_the_copilot_agents_dir(
        make_scaffolder, tmp_path, root):
    """`config.exclude.personas` reaches the Copilot delivery like it reaches the scaffold."""
    config = _fake_framework(
        tmp_path, root, [("common", "architect"), ("common", "code-reviewer")],
        exclude={"personas": ["architect"]})
    scaf = make_scaffolder(root=tmp_path, config=config)

    scaf.run_adjustments()

    agents_dir = make_scaffolder.target / AGENTS_DIR
    assert not (agents_dir / "architect.agent.md").exists()
    assert (agents_dir / "code-reviewer.agent.md").exists()
