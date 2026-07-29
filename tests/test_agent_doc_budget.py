"""This repo dogfoods the agent-doc budget it ships (#130): nothing enforced it before this
test, and the moved changelog convention must still reach this repo's own agent files.
"""
from __future__ import annotations


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
    import json

    config = json.loads((root / ".ai-badger" / "config.json").read_text(encoding="utf-8"))

    assert "changelog" in config["stacks"]


def test_this_repos_agent_files_still_carry_the_concrete_convention(root):
    for rel in ("CLAUDE.md", "HERMES.md", ".hermes.md", ".github/copilot-instructions.md",
               ".ai-badger/CLAUDE.md", ".ai-badger/HERMES.md",
               ".ai-badger/copilot-instructions.md"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "docs/changelog/{version}-{slug}.md" in text, rel
