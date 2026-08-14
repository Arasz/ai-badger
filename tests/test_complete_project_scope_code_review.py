"""The project-scope review skill: its extensions gate on config, and its merge is real.

The skill is stack- and agent-neutral by design — every concrete build command, C# trap, model
lane and PR step lives in an extension. These tests are what makes that claim checkable: a
dotnet fragment reaching a python project, or a claude fragment reaching a copilot-only one,
would be the neutrality failing silently.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config

SKILL = "complete-project-scope-code-review"


def _skill_md(target):
    return (target / ".ai-badger" / "skills" / SKILL / "SKILL.md").read_text(encoding="utf-8")


def test_dotnet_and_claude_and_github_all_embed_for_a_dotnet_claude_github_project(
        make_scaffolder):
    """The ai-raccoon/jsaa shape: every extension activates and lands in one SKILL.md."""
    target = make_scaffolder.target
    config = _config(
        stacks=["dotnet"],
        agents=["claude"],
        source_control={"platform": "github", "repoUrl": "https://github.com/foo/bar",
                        "projectUrl": None},
    )

    scaf = make_scaffolder(config=config, skills=[SKILL])
    scaf.run(generated_at="2026-08-14T00:00:00Z")

    content = _skill_md(target)
    # Section titles carry the extension's name; the H1 preamble above them is not merged.
    assert "## dotnet: traps that produced real join defects" in content
    assert "## claude: which model runs which lane" in content
    assert "## github: integrating a base that moves under you" in content
    # The merge consumed the directory rather than leaving a second copy on disk.
    assert not (target / ".ai-badger" / "skills" / SKILL / "extensions").exists()
    assert "<!-- MERGE_EXTENSIONS -->" not in content


def test_a_python_copilot_project_gets_the_neutral_base_only(make_scaffolder):
    """The inverse case — without it the test above passes for a skill that embeds everything."""
    target = make_scaffolder.target
    config = _config(
        stacks=["python"],
        agents=["copilot"],
        source_control={"platform": "none", "repoUrl": None, "projectUrl": None},
    )

    scaf = make_scaffolder(config=config, skills=[SKILL])
    scaf.run(generated_at="2026-08-14T00:00:00Z")

    content = _skill_md(target)
    assert "## dotnet: " not in content
    assert "## claude: " not in content
    assert "## github: " not in content
    # The base is still a usable workflow on its own.
    assert "## Phase 0 — Ground truth before anyone is dispatched" in content
    assert "held-out evaluation by family" in content


def test_the_base_skill_names_no_stack_or_agent_specific_command(root):
    """Neutrality, asserted against the catalog source rather than a scaffolded copy.

    Every token below appeared in the session this skill was distilled from and belongs in an
    extension. A regression here is someone helpfully making the base 'concrete'.
    """
    base = (root / "features" / "common" / "skills" / SKILL / "SKILL.md").read_text(
        encoding="utf-8")
    for token in ("dotnet test", "dotnet build", "npm ", "pytest", "gh pr", "C#", "Dapper",
                  "Opus", "Sonnet", "Haiku", "GitHub"):
        assert token not in base, f"base SKILL.md names {token!r} — it belongs in an extension"


def test_every_extension_declares_the_skill_it_attaches_to(root):
    """extension.json's `skill` must equal the directory it lives in, or the prune misfires."""
    ext_root = root / "features" / "common" / "skills" / SKILL / "extensions"
    found = sorted(d.name for d in ext_root.iterdir() if d.is_dir())
    assert found == ["claude", "dotnet", "github"]
    for name in found:
        descriptor = json.loads((ext_root / name / "extension.json").read_text())
        assert descriptor["skill"] == SKILL
        assert descriptor["extension"] == name
        assert descriptor["requires"]
