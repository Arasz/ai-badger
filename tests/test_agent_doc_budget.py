"""This repo dogfoods the agent-doc budget it ships (#130): nothing enforced it before this
test, and the moved changelog convention must still reach this repo's own agent files.

The repo-level test measures this repo against this repo's own `agentDocs` override, so it stays
green by raising the override whenever catalog content grows. It says nothing about the default
every consumer inherits — that is the second test's job.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config


def test_the_shipped_default_budget_fits_a_single_stack_project_on_every_stack(
        make_scaffolder, load_script, root, tmp_path):
    """The default has to be reachable by the generator's own minimum output, whichever stack.

    One stack, one agent, no `agentDocs` override is the floor. A default the floor exceeds puts
    every freshly scaffolded project over budget on day one with nothing to compact, and the
    stop-hook reminder then fires forever and means nothing. Stacks vary — dotnet renders ~60 lines
    more than the rest — so the floor is the worst single stack, not a representative one.

    Both lists are derived: the stacks come from index.json and the sizes from what the scaffolder
    actually renders, so a new stack or a new common invariant is measured rather than assumed.
    """
    stacks = json.loads((root / "index.json").read_text(encoding="utf-8"))["stacks"]
    assert set(stacks) == {p.name for p in (root / "features").iterdir() if p.is_dir()}, \
        "index.json and features/ disagree, so this loop is not covering the catalog"

    lib = load_script("features/common/skills/task/scripts/tracker_lib.py")
    over = []
    for stack in stacks:
        target = tmp_path / f"proj-{stack}"
        target.mkdir()
        make_scaffolder(config=_config(stacks=[stack], agents=["claude"]), target=target).run()
        lib.PROJECT_ROOT = target
        lib.CONFIG_JSON = target / ".ai-badger" / "config.json"
        lib.CLAUDE_MD = target / "CLAUDE.md"
        assert "agentDocs" not in lib.CONFIG_JSON.read_text(encoding="utf-8"), \
            "the probe must inherit the shipped default, not an override the scaffolder wrote"
        over.extend(dict(s, stack=stack) for s in lib.over_budget_docs())

    assert over == [], (
        "a one-stack project is already over the budget ai-badger ships in tracker_lib "
        f"(CLAUDE_MD_MAX_CHARS/CLAUDE_MD_MAX_LINES): {over}. Raise the default to fit the floor, "
        "or shrink what common content renders — a default the generator cannot meet makes every "
        "consumer over budget from day one."
    )


def test_every_agent_discovery_file_is_within_this_repos_budget(load_script, root):
    lib = load_script("features/common/skills/task/scripts/tracker_lib.py")
    lib.PROJECT_ROOT = root
    lib.CONFIG_JSON = root / ".ai-badger" / "config.json"
    lib.CLAUDE_MD = root / "CLAUDE.md"

    over = lib.over_budget_docs()

    assert over == [], (
        "an agent discovery file is over the budget in .ai-badger/config.json "
        f"(agentDocs): {over}. Either shorten catalog content or raise agentDocs.maxLines."
    )


def test_this_repo_declares_the_changelog_stack(root):
    config = json.loads((root / ".ai-badger" / "config.json").read_text(encoding="utf-8"))

    assert "changelog" in config["stacks"]


def test_this_repos_agent_files_still_carry_the_concrete_convention(root):
    for rel in ("CLAUDE.md", "HERMES.md", ".hermes.md", ".github/copilot-instructions.md",
               ".ai-badger/CLAUDE.md", ".ai-badger/HERMES.md",
               ".ai-badger/copilot-instructions.md"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "docs/changelog/{version}-{slug}.md" in text, rel
