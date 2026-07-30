"""Tests for features/copilot/adjustments/adjust_agents.py — one frontmatter block, right stacks.

Issue #210: the converter emitted its own `---` block on top of the persona's own, and
iterated every stack in the whole index instead of the configured ones. The stack rule is
the same one `scaffold_personas` applies: resolved stacks minus `config.exclude.personas`.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

ADJUSTER = "features/copilot/adjustments/adjust_agents.py"

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


def _framework(tmp_path: Path, root: Path) -> Path:
    """A minimal framework root: engine/badger_lib.py plus whatever personas tests add."""
    fw = tmp_path / "framework"
    (fw / "engine").mkdir(parents=True)
    shutil.copyfile(root / "engine" / "badger_lib.py", fw / "engine" / "badger_lib.py")
    return fw


def _persona(fw: Path, stack: str, name: str, text: str) -> dict:
    rel = f"features/{stack}/personas/{name}.md"
    path = fw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"name": name, "path": rel}


def _context(fw: Path, target: Path, *, index, stacks=("python",), exclude=None) -> dict:
    config = {"agents": ["copilot"], "stacks": list(stacks)}
    if exclude is not None:
        config["exclude"] = exclude
    return {
        "framework_root": fw,
        "config": config,
        "target_dir": target / ".ai-badger",
        "target": target,
        "index": index,
    }


def _agent_file(target: Path, name: str) -> str:
    return (target / ".github" / "agents" / f"{name}.agent.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    """Parse the leading YAML block of an emitted agent file."""
    assert text.startswith("---\n")
    block, _, _ = text[4:].partition("\n---\n")
    return yaml.safe_load(block)


def test_an_emitted_agent_carries_exactly_one_frontmatter_block(tmp_path, root, load_script):
    """The whole point of #210's first defect: the persona's own block must not survive."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    item = _persona(fw, "node", "api-engineer", PERSONA_WITH_FRONTMATTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_agents.adjust(_context(
        fw, target, index={"stacks": {"node": {"personas": [item]}}}, stacks=("node",)))

    assert result["applied"]
    text = _agent_file(target, "api-engineer")
    assert [l for l in text.splitlines() if l.strip() == "---"] == ["---", "---"]
    assert "# API engineer" in text


def test_source_frontmatter_fields_reach_the_emitted_block(tmp_path, root, load_script):
    """An unmapped persona's own description and tools are merged, not discarded."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    item = _persona(fw, "node", "api-engineer", PERSONA_WITH_FRONTMATTER)
    target = tmp_path / "proj"
    target.mkdir()

    adjust_agents.adjust(_context(
        fw, target, index={"stacks": {"node": {"personas": [item]}}}, stacks=("node",)))

    meta = _frontmatter(_agent_file(target, "api-engineer"))
    assert meta["name"] == "api-engineer"
    assert meta["description"].strip() == "HTTP API design and implementation specialist."
    assert meta["tools"] == ["Read", "Grep", "WebFetch"]
    assert meta["user-invocable"] is True


def test_the_copilot_specific_mapping_still_wins_for_mapped_personas(tmp_path, root, load_script):
    """PERSONA_MAP is a deliberate Copilot mapping; it overrides the persona's own block."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    item = _persona(fw, "common", "architect",
                    "---\nname: architect\ndescription: source text\ntools: Read\n---\n\nBody.\n")
    target = tmp_path / "proj"
    target.mkdir()

    adjust_agents.adjust(_context(
        fw, target, index={"stacks": {"common": {"personas": [item]}}}))

    meta = _frontmatter(_agent_file(target, "architect"))
    assert meta["description"] == adjust_agents.PERSONA_MAP["architect"]["description"]
    assert meta["tools"] == adjust_agents.PERSONA_MAP["architect"]["tools"]


def test_a_persona_without_frontmatter_still_converts(tmp_path, root, load_script):
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    item = _persona(fw, "python", "plain-reviewer", PERSONA_PLAIN)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_agents.adjust(_context(
        fw, target, index={"stacks": {"python": {"personas": [item]}}}))

    assert result["applied"]
    text = _agent_file(target, "plain-reviewer")
    assert "# Reviewer" in text
    assert _frontmatter(text)["description"] == "AI agent persona: plain-reviewer"


def test_only_configured_stacks_deliver_personas(tmp_path, root, load_script):
    """Issue #210's second defect: a dotnet persona must not land in a python project."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    index = {"stacks": {
        "common": {"personas": [_persona(fw, "common", "architect", PERSONA_PLAIN)]},
        "python": {"personas": [_persona(fw, "python", "py-engineer", PERSONA_PLAIN)]},
        "dotnet": {"personas": [_persona(fw, "dotnet", "dotnet-engineer", PERSONA_PLAIN)]},
    }}
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_agents.adjust(_context(fw, target, index=index))

    assert result["applied"]
    delivered = sorted(p.name for p in (target / ".github" / "agents").iterdir())
    assert delivered == ["architect.agent.md", "py-engineer.agent.md"]


def test_a_declined_persona_is_not_delivered(tmp_path, root, load_script):
    """`config.exclude.personas` reaches the Copilot delivery like it reaches the scaffold."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    index = {"stacks": {"common": {"personas": [
        _persona(fw, "common", "architect", PERSONA_PLAIN),
        _persona(fw, "common", "code-reviewer", PERSONA_PLAIN),
    ]}}}
    target = tmp_path / "proj"
    target.mkdir()

    adjust_agents.adjust(_context(
        fw, target, index=index, exclude={"personas": ["architect"]}))

    agents_dir = target / ".github" / "agents"
    assert not (agents_dir / "architect.agent.md").exists()
    assert (agents_dir / "code-reviewer.agent.md").exists()


def test_a_stale_agent_file_from_a_prior_run_is_removed(tmp_path, root, load_script):
    """A wrong-stack file the manifest attributes to this adjuster is deleted, and noted."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    item = _persona(fw, "common", "architect", PERSONA_PLAIN)
    target = tmp_path / "proj"
    stale = target / ".github" / "agents" / "dotnet-engineer.agent.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale\n", encoding="utf-8")
    (target / ".ai-badger").mkdir()
    (target / ".ai-badger" / "manifest.json").write_text(json.dumps({"entries": [{
        "feature": "adjustments", "stack": "copilot",
        "name": "adjustments/.github/agents/dotnet-engineer.agent.md",
        "source": "features/copilot/adjustments/adjust_agents.py",
        "target": ".github/agents/dotnet-engineer.agent.md", "hash": "0" * 64,
    }]}), encoding="utf-8")

    result = adjust_agents.adjust(_context(
        fw, target, index={"stacks": {"common": {"personas": [item]}}}))

    assert not stale.exists()
    assert "removed" in result["notes"]
    assert ".github/agents/dotnet-engineer.agent.md" not in result["files"]


def test_an_agent_file_the_manifest_does_not_own_is_left_alone(tmp_path, root, load_script):
    """A hand-authored .agent.md has no manifest entry and must never be deleted."""
    adjust_agents = load_script(ADJUSTER)
    fw = _framework(tmp_path, root)
    item = _persona(fw, "common", "architect", PERSONA_PLAIN)
    target = tmp_path / "proj"
    mine = target / ".github" / "agents" / "my-own.agent.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("hand-authored\n", encoding="utf-8")

    adjust_agents.adjust(_context(
        fw, target, index={"stacks": {"common": {"personas": [item]}}}))

    assert mine.read_text(encoding="utf-8") == "hand-authored\n"


def test_the_stack_rule_is_the_scaffolds_own(root, load_script):
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
