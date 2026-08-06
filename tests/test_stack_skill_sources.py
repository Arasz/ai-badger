"""Cross-file integrity of the per-stack skill catalog (skills-source.json + skills.json).

These run against the shipped features/ tree, not fixtures: a source name that the agent CLI
cannot resolve, or a `support` entry no installer can act on, installs nothing and says nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _stacks_with_skills():
    return sorted(p.parent.name for p in (ROOT / "features").glob("*/skills.json"))


def _sources(stack):
    path = ROOT / "features" / stack / "skills-source.json"
    return _load(path)["sources"] if path.exists() else []


def _skills(stack):
    path = ROOT / "features" / stack / "skills.json"
    return _load(path)["skills"] if path.exists() else []


def _agent_source_types(agent):
    path = ROOT / "features" / agent / "plugins-instructions.json"
    if not path.exists():
        return set()
    return set(_load(path).get("instructions", {}))


class TestEverySkillResolves:
    """A skill whose source is undeclared is skipped with a warning — dead catalog data."""

    @pytest.mark.parametrize("stack", _stacks_with_skills())
    def test_every_skill_names_a_source_declared_in_its_sibling_file(self, stack):
        declared = {s["name"] for s in _sources(stack)}

        for skill in _skills(stack):
            assert skill["source"] in declared, (
                f"features/{stack}/skills.json entry '{skill['name']}' names source "
                f"'{skill['source']}', absent from features/{stack}/skills-source.json")

    @pytest.mark.parametrize("stack", _stacks_with_skills())
    def test_a_stack_that_installs_skills_declares_its_sources(self, stack):
        """The reverse of the above: skills.json without a sibling source file installs nothing."""
        if _skills(stack):
            assert _sources(stack), f"features/{stack}/skills.json has entries but no sources"


class TestDeclaredSupportIsSubstantiated:
    """`support` must name only agents whose plugins-instructions.json can install that type.

    A declared agent with no instruction for the source type warns and installs nothing — the
    failure class this catalog has been bitten by before.
    """

    AGENTS = ("claude", "copilot", "hermes")

    @pytest.mark.parametrize("stack", _stacks_with_skills())
    def test_no_source_claims_an_agent_that_cannot_install_it(self, stack):
        """Scoped to sources a skill actually installs from — an unused source installs
        nothing for anybody, so its `support` cannot mislead an installer."""
        used = {s["source"] for s in _skills(stack)}

        for source in (s for s in _sources(stack) if s["name"] in used):
            support = source["support"]
            claimed = self.AGENTS if support == "common" else support
            for agent in claimed:
                assert source["type"] in _agent_source_types(agent), (
                    f"features/{stack}/skills-source.json source '{source['name']}' claims "
                    f"support for '{agent}', which has no '{source['type']}' instruction in "
                    f"features/{agent}/plugins-instructions.json")

    def test_marketplaces_are_claude_only(self):
        """A plugin marketplace is a Claude Code concept; no other agent installer reads one."""
        for agent in self.AGENTS:
            if agent != "claude":
                assert "marketplace" not in _agent_source_types(agent)


class TestFirstPartyStackMarketplaces:
    """The names below are what the CLI resolves — `dotnet/skills` publishes itself as
    `dotnet-agent-skills`, so a guessed name would fail at install time, not here."""

    EXPECTED = {
        "dotnet": ("dotnet-agent-skills", "https://github.com/dotnet/skills",
                   ["dotnet-diag", "dotnet-test", "dotnet-msbuild"]),
        "aspire": ("aspire-skills", "https://github.com/microsoft/aspire-skills", ["aspire"]),
    }

    @pytest.mark.parametrize("stack", sorted(EXPECTED))
    def test_the_stack_declares_the_marketplace_the_cli_resolves(self, stack):
        name, url, _ = self.EXPECTED[stack]

        declared = {s["name"]: s for s in _sources(stack)}

        assert name in declared, (
            f"features/{stack}/skills-source.json declares "
            f"{sorted(declared)} — the CLI resolves this repository as {name!r}, and "
            f"`claude plugin install …@<anything-else>` fails"
        )
        source = declared[name]
        assert source["type"] == "marketplace"
        assert source["source"] == url
        assert source["support"] == ["claude"]

    @pytest.mark.parametrize("stack", sorted(EXPECTED))
    def test_the_stack_installs_the_expected_plugins(self, stack):
        name, _, plugins = self.EXPECTED[stack]

        entries = [s for s in _skills(stack) if s["source"] == name]

        assert [s["name"] for s in entries] == plugins
        for entry in entries:
            assert entry.get("description", "").strip(), entry["name"]


class TestTheCommandsTheseProduce:
    """install_skills must emit a marketplace add plus one install per plugin, with no warning."""

    def _result(self, load_script, stacks):
        install_plugins = load_script("tooling/install_plugins.py")
        config = {"agents": ["claude", "copilot", "hermes"], "stacks": stacks,
                  "skillScope": "default"}
        result = install_plugins.install_skills(ROOT, config, dry_run=True)
        return install_plugins, result

    @pytest.mark.parametrize("stack", sorted(TestFirstPartyStackMarketplaces.EXPECTED))
    def test_each_stack_adds_its_marketplace_and_installs_each_plugin(self, load_script, stack):
        name, url, plugins = TestFirstPartyStackMarketplaces.EXPECTED[stack]
        install_plugins, result = self._result(load_script, [stack])
        rendered = [install_plugins.printable(c) for c in result["commands"]]

        assert f"claude plugin marketplace add {url}" in rendered
        for plugin in plugins:
            assert f"claude plugin install {plugin}@{name}" in rendered

    def test_no_warnings_for_the_new_stacks(self, load_script):
        _, result = self._result(load_script, ["dotnet", "aspire"])

        assert result["warnings"] == []
