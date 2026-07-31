"""Tests for features/claude/adjustments/adjust_agents.py — personas reach .claude/agents/.

Every frontmatter key asserted here is documented Claude Code subagent surface (issue #190,
step 2 verification): `name`/`description` are required, `tools` is an allowlist that also
removes Bash and every MCP tool, `disallowedTools` accepts plain tool names as well as
`mcp__<server>` patterns, and a file whose frontmatter does not start at line 1 is not a
subagent definition at all (code.claude.com/docs/en/sub-agents).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scaffold_helpers import _config

ADJUSTER = "features/claude/adjustments/adjust_agents.py"

ARCHITECT = """---
name: architect
description: >
  Design and decomposition specialist — architecture decisions, ADR authoring.
  Read-only: hands finished blueprints to an implementation persona.
disallowedTools: Write, Edit, MultiEdit, NotebookEdit
---

# Architect

## Mandatory gates

Write the ADR before the code.
"""

TEST_ENGINEER = """---
name: test-engineer
description: >
  Testing specialist — designs test strategy, writes failing tests first.
---

# Test Engineer

Red before green.
"""


def _context(root: Path, target: Path, *, agents=("claude",)) -> dict:
    return {
        "framework_root": root,
        "config": {"agents": list(agents)},
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": [],
        "index": {},
        "mcp_servers": [],
    }


def _persona(target: Path, name: str, body: str) -> Path:
    path = target / ".ai-badger" / "agents" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _project(tmp_path: Path) -> Path:
    target = tmp_path / "proj"
    target.mkdir()
    _persona(target, "architect", ARCHITECT)
    _persona(target, "test-engineer", TEST_ENGINEER)
    return target


def _delivered(target: Path, name: str) -> str:
    return (target / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    """The frontmatter block of a delivered file, without its fences."""
    assert text.startswith("---\n"), "frontmatter must start at line 1"
    return text.split("---\n", 2)[1]


def _write_manifest(target: Path, targets) -> None:
    path = target / ".ai-badger" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": [{"target": t} for t in targets]}), encoding="utf-8")


# ── delivery ──────────────────────────────────────────────────────────────────

def test_every_scaffolded_persona_reaches_claudes_agents_directory(tmp_path, root, load_script):
    """The whole point of #190: a scaffolded persona becomes a dispatchable subagent."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    result = adjust_agents.adjust(_context(root, target))

    assert result["applied"]
    delivered = sorted(p.name for p in (target / ".claude" / "agents").glob("*.md"))
    assert delivered == ["architect.md", "test-engineer.md"]


def test_the_delivered_file_carries_exactly_one_frontmatter_block(tmp_path, root, load_script):
    """The persona's own `---` block is stripped, not stacked under a second one (#210)."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    adjust_agents.adjust(_context(root, target))

    text = _delivered(target, "architect")
    assert text.count("\n---\n") == 1, text
    assert text.startswith("---\nname: architect\n")


def test_name_and_description_survive_delivery(tmp_path, root, load_script):
    """Both are required fields; the description is what Claude matches a task against."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    adjust_agents.adjust(_context(root, target))

    front = _frontmatter(_delivered(target, "architect"))
    assert "name: architect\n" in front
    assert "description: >\n" in front
    assert "Design and decomposition specialist" in front


def test_the_managed_header_sits_below_the_frontmatter_never_above_it(tmp_path, root, load_script):
    """Frontmatter must start at line 1, so the header goes on the first body line."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    adjust_agents.adjust(_context(root, target))

    text = _delivered(target, "architect")
    header_at = text.index("<!-- Managed by ai-badger.")
    assert header_at > text.index("\n---\n")
    assert ".ai-badger/agents/architect.md" in text
    assert text.index("# Architect") > header_at


def test_the_body_survives_delivery(tmp_path, root, load_script):
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    adjust_agents.adjust(_context(root, target))

    assert "Write the ADR before the code." in _delivered(target, "architect")


def test_a_read_only_persona_ships_its_own_disallowed_tools_verbatim(tmp_path, root, load_script):
    """`disallowedTools` comes from the persona file, in Claude's native key (decision 5)."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    adjust_agents.adjust(_context(root, target))

    assert "disallowedTools: Write, Edit, MultiEdit, NotebookEdit\n" in _delivered(
        target, "architect")


def test_a_persona_that_restricts_nothing_gets_neither_tools_key(tmp_path, root, load_script):
    """Omitting `tools` is how a persona inherits every tool available to subagents."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    adjust_agents.adjust(_context(root, target))

    front = _frontmatter(_delivered(target, "test-engineer"))
    assert "tools:" not in front
    assert "disallowedTools:" not in front


def test_a_tools_allowlist_a_persona_does_declare_is_carried_through(tmp_path, root, load_script):
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)
    _persona(target, "narrow", "---\nname: narrow\ndescription: n\ntools: Read, Grep\n---\n\nBody\n")

    adjust_agents.adjust(_context(root, target))

    assert "tools: Read, Grep\n" in _frontmatter(_delivered(target, "narrow"))


def test_a_persona_key_claude_does_not_understand_is_not_re_emitted(tmp_path, root, load_script):
    """The re-emitted set is an allowlist: an ai-badger-only key must not leak into the file."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)
    _persona(target, "odd", "---\nname: odd\ndescription: d\nroutingHint: internal\n---\n\nBody\n")

    adjust_agents.adjust(_context(root, target))

    assert "routingHint" not in _delivered(target, "odd")


def test_a_persona_without_frontmatter_is_skipped_and_reported(tmp_path, root, load_script):
    """No frontmatter, no name — there is nothing to build a subagent definition from."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)
    _persona(target, "bare", "# Bare\n\nNo frontmatter here.\n")

    result = adjust_agents.adjust(_context(root, target))

    assert not (target / ".claude" / "agents" / "bare.md").exists()
    assert "bare" in result["notes"]


# ── ownership ─────────────────────────────────────────────────────────────────

def test_a_hand_written_agent_file_is_left_untouched_and_reported(tmp_path, root, load_script):
    """`.claude/agents/` is Claude Code's own convention; a file we never placed is the user's."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)
    mine = target / ".claude" / "agents" / "architect.md"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text("---\nname: architect\ndescription: mine\n---\n\nHand written.\n",
                    encoding="utf-8")
    original = mine.read_bytes()

    result = adjust_agents.adjust(_context(root, target))

    assert mine.read_bytes() == original
    assert ".claude/agents/architect.md" in result["notes"]
    assert ".claude/agents/architect.md" not in result["files"]
    assert (target / ".claude" / "agents" / "test-engineer.md").exists()


def test_a_file_recorded_in_the_prior_manifest_is_ours_to_rewrite(tmp_path, root, load_script):
    """Adjustments run before the manifest is rewritten, so it names the prior run's targets."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)
    _write_manifest(target, [".claude/agents/architect.md"])
    stale = target / ".claude" / "agents" / "architect.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale\n", encoding="utf-8")

    result = adjust_agents.adjust(_context(root, target))

    assert "stale" not in stale.read_text(encoding="utf-8")
    assert ".claude/agents/architect.md" in result["files"]


def test_delivered_files_are_returned_so_the_manifest_records_them(tmp_path, root, load_script):
    """Ownership lives in manifest `entries`; scaffold records whatever `files` names."""
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    result = adjust_agents.adjust(_context(root, target))

    assert sorted(result["files"]) == [
        ".claude/agents/architect.md", ".claude/agents/test-engineer.md"]


# ── not applied ───────────────────────────────────────────────────────────────

def test_not_applied_when_claude_is_not_configured(tmp_path, root, load_script):
    adjust_agents = load_script(ADJUSTER)
    target = _project(tmp_path)

    result = adjust_agents.adjust(_context(root, target, agents=("hermes",)))

    assert not result["applied"]
    assert not (target / ".claude").exists()


def test_not_applied_when_there_are_no_scaffolded_personas(tmp_path, root, load_script):
    adjust_agents = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_agents.adjust(_context(root, target))

    assert not result["applied"]
    assert not (target / ".claude" / "agents").exists()


# ── through the scaffolder ────────────────────────────────────────────────────

def test_a_declined_persona_is_never_delivered(make_scaffolder):
    """`config.exclude.personas` is the documented opt-out, and it reaches .claude/agents/."""
    target = make_scaffolder.target
    config = _config(stacks=["dotnet"])
    config["exclude"] = {"personas": ["code-reviewer"]}

    make_scaffolder(config=config, skills=[]).run(generated_at="2026-07-19T00:00:00Z")

    delivered = sorted(p.name for p in (target / ".claude" / "agents").glob("*.md"))
    assert "architect.md" in delivered
    assert "code-reviewer.md" not in delivered


def test_the_scaffolder_records_every_delivered_agent_file(make_scaffolder):
    target = make_scaffolder.target

    result = make_scaffolder(config=_config(stacks=["dotnet"]), skills=[]).run(generated_at=None)

    recorded = {e["target"] for e in result["manifest"]["entries"]}
    assert ".claude/agents/architect.md" in recorded
    assert (target / ".claude" / "agents" / "architect.md").is_file()


# ── the catalog personas the delivery makes live ──────────────────────────────

@pytest.mark.parametrize("persona,denied", [
    # architect files an ADR (its gate 3) but never edits code (its scope boundary), so Write
    # stays and only the edit tools go. code-reviewer reports findings and writes nothing.
    ("architect", "Edit, MultiEdit, NotebookEdit"),
    ("code-reviewer", "Write, Edit, MultiEdit, NotebookEdit"),
])
def test_a_read_only_catalog_persona_keeps_bash_and_mcp(root, persona, denied):
    """A `tools:` allowlist amputates Bash, Skill and *every MCP tool* — read-only is a denylist.

    code-reviewer's own Step 0 needs `git diff` and CLAUDE.md tells agents to prefer the
    code-review-graph MCP tools over Grep; an allowlist would have taken both away.
    """
    front = _frontmatter((root / "features" / "common" / "personas" / f"{persona}.md")
                         .read_text(encoding="utf-8"))

    assert "\ntools:" not in f"\n{front}"
    assert f"disallowedTools: {denied}\n" in front
