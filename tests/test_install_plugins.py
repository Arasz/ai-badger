"""Tests for scripts/install_plugins.py — generic skill installation orchestrator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestInstallSkills:
    """Test the install_skills function."""

    def _setup_framework(self, tmp_path, root):
        """Create a minimal framework structure for testing."""
        features = tmp_path / "features"
        schemas = tmp_path / "schemas"
        schemas.symlink_to(root / "schemas")

        # common stack with skills-source and skills
        common_src = features / "common"
        (common_src / "skills").mkdir(parents=True)
        (common_src / "skills-source.json").write_text(json.dumps({
            "sources": [
                {"name": "test-marketplace", "type": "marketplace",
                 "source": "https://example.com/market", "support": ["claude"]},
                {"name": "test-hub", "type": "hub",
                 "source": "https://hub.example.com", "support": ["hermes"]},
                {"name": "common-source", "type": "url",
                 "source": "https://common.example.com", "support": "common"},
            ]
        }))
        (common_src / "skills.json").write_text(json.dumps({
            "skills": [
                {"name": "skill-a", "source": "test-marketplace", "scope": "default",
                 "description": "Skill A"},
                {"name": "skill-b", "source": "test-hub", "description": "Skill B"},
                {"name": "skill-c", "source": "common-source", "description": "Skill C"},
            ]
        }))

        # Agent plugin instructions
        (features / "claude").mkdir(parents=True)
        (features / "claude" / "plugins-instructions.json").write_text(json.dumps({
            "agent": "claude",
            "instructions": {
                "marketplace": {"commands": [
                    "claude plugin marketplace add {source}",
                    "claude plugin install {name} --scope {scope}"
                ]},
                "url": {"commands": ["claude plugin install {source}"]},
            }
        }))

        (features / "hermes").mkdir(parents=True)
        (features / "hermes" / "plugins-instructions.json").write_text(json.dumps({
            "agent": "hermes",
            "instructions": {
                "hub": {"commands": ["hermes skills install {name} --source {source}"]},
                "url": {"commands": ["hermes skills install {source}"]},
            }
        }))

        return tmp_path

    def test_generates_claude_commands(self, tmp_path, root, load_script):
        ip = load_script("scripts/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        cmds = result["commands"]
        assert any("claude plugin marketplace add" in c for c in cmds)
        assert any("skill-a" in c for c in cmds)

    def test_generates_hermes_commands(self, tmp_path, root, load_script):
        ip = load_script("scripts/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["hermes"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        cmds = result["commands"]
        assert any("hermes skills install" in c for c in cmds)
        assert any("skill-b" in c for c in cmds)

    def test_common_source_for_all_agents(self, tmp_path, root, load_script):
        ip = load_script("scripts/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude", "hermes"], "stacks": ["common"],
                  "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        claude_cmds = [c for c in result["commands"] if "claude" in c]
        hermes_cmds = [c for c in result["commands"] if "hermes" in c]
        assert len(claude_cmds) >= 2
        assert len(hermes_cmds) >= 2

    def test_skip_unsupported_agent(self, tmp_path, root, load_script):
        """Source with support=['hermes'] is silently skipped for Claude."""
        ip = load_script("scripts/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        hub_warnings = [w for w in result.get("warnings", []) if "hub" in w]
        assert len(hub_warnings) == 0
        assert not any("skill-b" in c for c in result["commands"])

    def test_local_scope_overrides_entry_scope(self, tmp_path, root, load_script):
        ip = load_script("scripts/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "local"}

        result = ip.install_skills(fw, config, dry_run=True)

        name_install_cmds = [c for c in result["commands"]
                             if "install" in c and "skill-" in c]
        assert len(name_install_cmds) >= 1
        for cmd in name_install_cmds:
            assert "--scope local" in cmd

    def test_dry_run_no_execution(self, tmp_path, root, load_script):
        ip = load_script("scripts/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        assert result["dryRun"] is True
        assert len(result["commands"]) > 0

    def test_empty_skills_returns_empty(self, tmp_path, root, load_script):
        ip = load_script("scripts/install_plugins.py")
        features = tmp_path / "features" / "common" / "skills"
        features.mkdir(parents=True)
        (tmp_path / "features" / "common" / "skills-source.json").write_text(
            json.dumps({"sources": []}))
        (tmp_path / "features" / "common" / "skills.json").write_text(
            json.dumps({"skills": []}))
        (tmp_path / "schemas").symlink_to(root / "schemas")
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(tmp_path, config, dry_run=True)

        assert result["commands"] == []

    def test_warns_on_unknown_source(self, tmp_path, root, load_script):
        """Skill referencing a source not in skills-source.json generates warning."""
        ip = load_script("scripts/install_plugins.py")
        features = tmp_path / "features" / "common"
        features.mkdir(parents=True)
        (features / "skills").mkdir(parents=True)
        (tmp_path / "schemas").symlink_to(root / "schemas")
        (features / "skills-source.json").write_text(json.dumps({"sources": []}))
        (features / "skills.json").write_text(json.dumps({
            "skills": [{"name": "orphan", "source": "nonexistent"}]
        }))
        (tmp_path / "features" / "claude").mkdir(parents=True)
        (tmp_path / "features" / "claude" / "plugins-instructions.json").write_text(
            json.dumps({"agent": "claude", "instructions": {}}))
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(tmp_path, config, dry_run=True)

        assert any("nonexistent" in w for w in result["warnings"])

    def test_warns_on_missing_instruction(self, tmp_path, root, load_script):
        """Agent with no instruction for a source type generates warning."""
        ip = load_script("scripts/install_plugins.py")
        features = tmp_path / "features" / "common"
        features.mkdir(parents=True)
        (features / "skills").mkdir(parents=True)
        (tmp_path / "schemas").symlink_to(root / "schemas")
        (features / "skills-source.json").write_text(json.dumps({
            "sources": [{"name": "hub", "type": "hub",
                         "source": "https://hub.example.com", "support": ["claude"]}]
        }))
        (features / "skills.json").write_text(json.dumps({
            "skills": [{"name": "x", "source": "hub"}]
        }))
        (tmp_path / "features" / "claude").mkdir(parents=True)
        # Claude has no 'hub' instruction
        (tmp_path / "features" / "claude" / "plugins-instructions.json").write_text(
            json.dumps({"agent": "claude",
                        "instructions": {"marketplace": {"commands": ["cmd"]}}}))
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(tmp_path, config, dry_run=True)

        assert any("hub" in w for w in result["warnings"])
