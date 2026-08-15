"""A skill a configured stack delivers must reach the agent's discovery directory.

Delivery and discovery are two steps, and only the second one makes a skill reachable: Claude
Code reads `.claude/skills/*/SKILL.md` and nowhere else. `SkillDelivery.discover_stack_local`
delivers every configured stack's skills into `.ai-badger/skills/`, but the adjustment that
links them was handed a list filtered to the stacks named in a literal — so a `dotnet`, `mcp`
or `ai-raccoon` skill was copied onto disk, recorded in the manifest, and linked nowhere.

This is #261 one stack over: same symptom, same silence, a different hand-maintained list.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scaffold_helpers import _config

BADGER_LIB = "engine/badger_lib.py"


def _stack_local_skills(root: Path, stack: str):
    """The stack's own catalog, read off disk — never a list this file maintains."""
    skills_dir = root / "features" / stack / "skills"
    return sorted(d.name for d in skills_dir.iterdir()
                  if d.is_dir() and (d / "SKILL.md").is_file())


def _scaffolded(make_scaffolder, config, skills=("task",)):
    scaf = make_scaffolder(config=config, skills=list(skills))
    scaf.run(generated_at="2026-08-01T00:00:00Z")
    return make_scaffolder.target


# ------------------------------------------------------------------- delivery vs discovery
@pytest.mark.parametrize("stack", ["dotnet", "mcp", "ai-raccoon"])
def test_every_skill_a_configured_stack_delivers_is_discoverable(make_scaffolder, root, stack):
    """The defect, stated as the invariant it breaks.

    A stack ships its whole catalog (ADR-0010), so `.ai-badger/skills/` and `.claude/skills/`
    must name the same stack skills. Anything in the first and not the second is on disk,
    in `index.json`, and unreachable for its whole life.
    """
    target = _scaffolded(make_scaffolder, _config(stacks=[stack], agents=["claude"]))

    delivered = [n for n in _stack_local_skills(root, stack)
                 if (target / ".ai-badger" / "skills" / n / "SKILL.md").is_file()]
    assert delivered, f"precondition: the {stack} stack delivered nothing to scaffold over"

    undiscoverable = [n for n in delivered
                      if not (target / ".claude" / "skills" / n / "SKILL.md").is_file()]
    assert not undiscoverable, (
        f"{len(undiscoverable)} {stack} skill(s) were delivered to .ai-badger/skills/ and "
        f"linked into no discovery directory, so no agent can reach them: "
        f"{', '.join(undiscoverable)}"
    )


def test_a_common_stack_skill_is_still_discoverable(make_scaffolder):
    """Widening must not be a swap: the case that already worked keeps working."""
    target = _scaffolded(make_scaffolder, _config(stacks=["dotnet"], agents=["claude"]))

    assert (target / ".claude" / "skills" / "task" / "SKILL.md").is_file()


def test_a_stack_the_project_did_not_configure_reaches_nobody(make_scaffolder, root):
    """Widening must not deliver the whole catalog: only configured stacks qualify."""
    target = _scaffolded(make_scaffolder, _config(stacks=["mcp"], agents=["claude"]))

    for name in _stack_local_skills(root, "dotnet"):
        assert not (target / ".claude" / "skills" / name).exists(), name


# ----------------------------------------- the emptiness signal the stack skills used to carry
def test_a_run_that_cannot_vouch_for_the_list_prunes_nothing(tmp_path, load_script, root):
    """A stack that ships skills must not turn "we do not know" into "these and no others".

    An empty `--skills` means "unchanged", not "none" (#129), and `adjust_skills` read that
    off the list being empty. `discover_stack_local` then appends every configured stack's
    skills, so once a stack ships any, the list is never empty and the guard stops firing —
    a run whose manifest could not be read would delete the links it could not account for.
    """
    adjust_skills = load_script("features/claude/adjustments/adjust_skills.py")
    target = tmp_path / "proj"
    for name in ("task", "dotnet-mcp-server"):
        (target / ".ai-badger" / "skills" / name).mkdir(parents=True)
        (target / ".ai-badger" / "skills" / name / "SKILL.md").write_text("x", encoding="utf-8")
    context = {"framework_root": root, "config": {"agents": ["claude"]},
               "target_dir": target / ".ai-badger", "target": target,
               "skills": ["task", "dotnet-mcp-server"]}
    adjust_skills.adjust(context)
    assert (target / ".claude" / "skills" / "task").is_symlink(), "precondition"

    # What the scaffolder passes when the manifest could not be read: the stack still
    # delivers, so the list is non-empty, but it is not evidence.
    adjust_skills.adjust({**context, "skills": ["dotnet-mcp-server"], "prune": False})

    assert (target / ".claude" / "skills" / "task").is_symlink()


# ------------------------------------------------- discovery_stacks_for_agent (the derivation)
def test_the_agents_stacks_are_derived_from_the_config_not_a_literal(load_script):
    """Every stack the project draws from qualifies — the list is read, never written down."""
    bl = load_script(BADGER_LIB)
    config = _config(stacks=["dotnet", "mcp", "ai-raccoon"], agents=["claude"])

    stacks = bl.discovery_stacks_for_agent(config, "claude")

    assert set(stacks) >= {"common", "dotnet", "mcp", "ai-raccoon"}


def test_an_agent_may_discover_its_own_stacks_skills(load_script):
    """`features/claude/skills/` is claude's own catalog; it is not in `config.stacks`."""
    bl = load_script(BADGER_LIB)

    assert "claude" in bl.discovery_stacks_for_agent(
        _config(stacks=["dotnet"], agents=["claude", "copilot"]), "claude")


def test_another_agents_stack_is_not_this_agents_to_discover(load_script):
    """The one exclusion the filter exists for: copilot's skills are not claude's."""
    bl = load_script(BADGER_LIB)
    config = _config(stacks=["dotnet"], agents=["claude", "copilot", "hermes"])

    stacks = bl.discovery_stacks_for_agent(config, "claude")

    assert "copilot" not in stacks
    assert "hermes" not in stacks
