"""Tests for tooling/install_plugins.py — generic skill installation orchestrator."""
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
        ip = load_script("tooling/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        cmds = [ip.printable(c) for c in result["commands"]]
        assert any("claude plugin marketplace add" in c for c in cmds)
        assert any("skill-a" in c for c in cmds)

    def test_generates_hermes_commands(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["hermes"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        cmds = [ip.printable(c) for c in result["commands"]]
        assert any("hermes skills install" in c for c in cmds)
        assert any("skill-b" in c for c in cmds)

    def test_common_source_for_all_agents(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude", "hermes"], "stacks": ["common"],
                  "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        claude_cmds = [ip.printable(c) for c in result["commands"] if "claude" in ip.printable(c)]
        hermes_cmds = [ip.printable(c) for c in result["commands"] if "hermes" in ip.printable(c)]
        assert len(claude_cmds) >= 2
        assert len(hermes_cmds) >= 2

    def test_skip_unsupported_agent(self, tmp_path, root, load_script):
        """Source with support=['hermes'] is silently skipped for Claude."""
        ip = load_script("tooling/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        hub_warnings = [w for w in result.get("warnings", []) if "hub" in w]
        assert len(hub_warnings) == 0
        assert not any("skill-b" in c for c in result["commands"])

    def test_local_scope_overrides_entry_scope(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "local"}

        result = ip.install_skills(fw, config, dry_run=True)

        name_install_cmds = [ip.printable(c) for c in result["commands"]
                             if "install" in ip.printable(c) and "skill-" in ip.printable(c)]
        assert len(name_install_cmds) >= 1
        for cmd in name_install_cmds:
            assert "--scope local" in cmd

    def test_dry_run_no_execution(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        fw = self._setup_framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": ["common"], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        assert result["dryRun"] is True
        assert len(result["commands"]) > 0

    def test_empty_skills_returns_empty(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
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
        ip = load_script("tooling/install_plugins.py")
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
        ip = load_script("tooling/install_plugins.py")
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


class TestRealCatalog:
    """install_skills must work against the shipped features/ tree, not just fixtures (F-06)."""

    def _real_config(self):
        return {"agents": ["claude"], "stacks": ["python"], "skillScope": "default"}

    def _declared_skills(self, root, stacks):
        names = []
        for stack in stacks:
            path = root / "features" / stack / "skills.json"
            if path.exists():
                names += [s["name"] for s in json.loads(path.read_text())["skills"]]
        return names

    def test_real_catalog_emits_an_install_command_per_declared_skill(self, root, load_script):
        ip = load_script("tooling/install_plugins.py")

        result = ip.install_skills(root, self._real_config(), dry_run=True)

        declared = self._declared_skills(root, ["common", "python"])
        assert declared, "expected the real catalog to declare skills"
        for name in declared:
            assert any(name in ip.printable(cmd) for cmd in result["commands"]), \
                f"no install command mentions '{name}': {result['commands']}"

    def test_common_stack_is_always_resolved(self, root, load_script):
        """config.stacks may not contain 'common' (the schema forbids it), so the resolver
        must add it — otherwise features/common/skills.json is dead catalog data."""
        ip = load_script("tooling/install_plugins.py")

        result = ip.install_skills(root, self._real_config(), dry_run=True)

        assert any("superpowers" in ip.printable(cmd) for cmd in result["commands"]), result["commands"]

    def test_real_catalog_emits_no_warnings(self, root, load_script):
        ip = load_script("tooling/install_plugins.py")

        result = ip.install_skills(root, self._real_config(), dry_run=True)

        assert result["warnings"] == []

    def test_duplicate_stacks_do_not_duplicate_commands(self, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        config = {"agents": ["claude"], "stacks": ["common", "python", "python"],
                  "skillScope": "default"}

        result = ip.install_skills(root, config, dry_run=True)

        assert len(result["commands"]) == len({tuple(c) for c in result["commands"]})


class TestMissingNameTemplate:
    """An agent whose instruction cannot name a skill must say so, not emit a duplicate."""

    def _framework(self, tmp_path, root):
        features = tmp_path / "features" / "common"
        features.mkdir(parents=True)
        (tmp_path / "schemas").symlink_to(root / "schemas")
        (features / "skills-source.json").write_text(json.dumps({
            "sources": [{"name": "by-url", "type": "url",
                         "source": "https://example.com/pack", "support": ["claude"]}]
        }))
        (features / "skills.json").write_text(json.dumps({
            "skills": [{"name": "packaged-skill", "source": "by-url"}]
        }))
        (tmp_path / "features" / "claude").mkdir(parents=True)
        (tmp_path / "features" / "claude" / "plugins-instructions.json").write_text(json.dumps({
            "agent": "claude",
            "instructions": {"url": {"commands": ["claude plugin install {source}"]}},
        }))
        return tmp_path

    def test_warns_instead_of_repeating_the_source_command(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        fw = self._framework(tmp_path, root)
        config = {"agents": ["claude"], "stacks": [], "skillScope": "default"}

        result = ip.install_skills(fw, config, dry_run=True)

        assert [ip.printable(c) for c in result["commands"]] == \
            ["claude plugin install https://example.com/pack"]
        assert any("packaged-skill" in w for w in result["warnings"])


class TestConfigDrivenCommonStack:
    """install_skills takes the always-included stack's name from config (not a literal)."""

    def _framework(self, tmp_path, root, stack_name):
        features = tmp_path / "features" / stack_name
        features.mkdir(parents=True)
        (tmp_path / "schemas").symlink_to(root / "schemas")
        (features / "skills-source.json").write_text(json.dumps({
            "sources": [{"name": "market", "type": "marketplace",
                         "source": "https://example.com/m", "support": ["claude"]}]
        }))
        (features / "skills.json").write_text(json.dumps({
            "skills": [{"name": "house-skill", "source": "market"}]
        }))
        (tmp_path / "features" / "claude").mkdir(parents=True)
        (tmp_path / "features" / "claude" / "plugins-instructions.json").write_text(json.dumps({
            "agent": "claude",
            "instructions": {"marketplace": {"commands": [
                "claude plugin marketplace add {source}",
                "claude plugin install {name}@{sourceName}",
            ]}},
        }))
        return tmp_path

    def test_named_common_stack_is_resolved(self, tmp_path, root, load_script):
        ip = load_script("tooling/install_plugins.py")
        fw = self._framework(tmp_path, root, "house")
        config = {"agents": ["claude"], "commonStacks": "house", "stacks": []}

        result = ip.install_skills(fw, config, dry_run=True)

        assert any("house-skill" in ip.printable(cmd) for cmd in result["commands"]), result


class TestNoShellInterpretation:
    """Install commands are argv lists: a skill name is data, never shell syntax (security I2)."""

    def test_a_command_with_a_shell_metacharacter_is_not_interpreted(self, tmp_path, load_script):
        ip = load_script("tooling/install_plugins.py")
        argv = ip._build_command(  # pylint: disable=protected-access
            "claude plugin install {name}@{sourceName}", "https://example.test",
            "evil; touch pwned", "default", "src")

        assert isinstance(argv, list)
        assert "evil; touch pwned@src" in argv
        assert not any(tok == ";" for tok in argv)

    def test_a_source_url_with_a_space_stays_one_argument(self, load_script):
        ip = load_script("tooling/install_plugins.py")
        argv = ip._build_command(  # pylint: disable=protected-access
            "claude plugin marketplace add {source}", "https://example.test/a b")

        assert argv == ["claude", "plugin", "marketplace", "add", "https://example.test/a b"]

    def test_printable_round_trips_for_display(self, load_script):
        ip = load_script("tooling/install_plugins.py")

        text = ip.printable(["claude", "plugin", "install", "a b"])

        assert text.startswith("claude plugin install ")
        assert "a b" in text

    def test_the_scaffold_executor_never_uses_a_shell(self, tmp_path, load_script, root):
        """The one place these commands actually run must pass argv, not a string."""
        scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
        source = (root / "features" / "common" / "skills" / "welcome-ai-badger"
                  / "scripts" / "scaffold.py").read_text(encoding="utf-8")

        assert "shell=True" not in source
        assert scaffold is not None

    def test_the_scaffold_prints_copy_pasteable_commands(self, tmp_path, load_script, root,
                                                          capsys):
        """WP37 turned commands into argv lists; the printed form must stay a command line."""
        scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
        target = tmp_path / "proj"
        target.mkdir()
        config = target / "config.json"
        config.write_text(json.dumps({
            "$schema": "./schemas/config.schema.json", "frameworkVersion": "0.1.0",
            "project": {"name": "p", "summary": "s", "domain": "d"},
            "stacks": ["python"], "agents": ["claude"],
            "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
            "commands": {}, "personaRouting": [], "skillScope": "default", "docs": {},
        }), encoding="utf-8")

        scaffold.main(["--config", str(config), "--target", str(target), "--root", str(root),
                       "--skills", "task", "--generated-at", "2026-07-27T00:00:00Z"])

        out = capsys.readouterr().out
        assert "$ claude plugin install" in out
        assert "['claude'," not in out


class TestThirdPartyPluginsAreNotAddedSilently:
    """A default-scope external plugin runs on every scaffolded project without being asked for."""

    # Every externally-sourced plugin ai-badger installs by default. Adding a name here is a
    # deliberate act: the plugin runs in the user's agent, and some ship binaries that hook
    # every tool call. See docs/changelog/0.33.0-no-third-party-tool-call-interception.md.
    ALLOWED = {
        ("common", "superpowers"),
        ("common", "pr-review-toolkit"),
        ("python", "pyright-lsp"),
        ("python", "pydantic-ai"),
        # First-party Microsoft/.NET plugins, reviewed 2026-08-01: no tool-call hooks, no
        # external account, and each one verified to install and stay installed.
        ("dotnet", "dotnet-diag"),
        ("dotnet", "dotnet-test"),
        ("dotnet", "dotnet-msbuild"),
        ("aspire", "aspire"),
    }

    @staticmethod
    def _declared(root):
        found = set()
        for path in sorted((root / "features").glob("*/skills.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for skill in data.get("skills", []):
                if skill.get("source"):
                    found.add((path.parent.name, skill["name"]))
        return found

    def test_the_catalog_installs_only_reviewed_third_party_plugins(self, root):
        assert self._declared(Path(root)) == self.ALLOWED

    def test_semgrep_is_not_reinstated(self, root):
        """It hooks PreToolUse/PostToolUse on Write|Edit|Bash and needs an external account."""
        assert not [s for _, s in self._declared(Path(root)) if s == "semgrep"]
