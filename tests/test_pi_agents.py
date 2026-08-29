"""Tests for the pi persona arm: `.ai-badger/agents/` -> `<project>/.pi/agents/*.md`.

pi's agent discovery matches `entry.name.endsWith(".md")` and reads `name`/`description`
frontmatter plus the body, so every assertion here is against what a reader actually parses,
not against a convention borrowed from another host.
"""
# pylint: disable=redefined-outer-name  # fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest

import frontmatter as fm

# Self-derived at collection time, before conftest's session fixture redirects $HOME — the same
# idiom as tests/test_pi_adjustments.py, and for the same reason: a test proving the extension
# install went somewhere else must not derive "the real home" from the fixture it is checking.
_REAL_HOME = Path.home()

PERSONA = """---
name: architect
description: >
  Architecture and decomposition specialist. Read-only.
model: opus
disallowedTools: Edit, MultiEdit
tools: Read, Grep
---

# Architect

Body text the subagent extension uses as the system prompt.
"""


@pytest.fixture
def agents_arm(load_script, tmp_path, monkeypatch):
    """The pi persona adjustment, with USER_EXTENSIONS_DIR redirected under tmp_path.

    ``USER_EXTENSIONS_DIR`` is a module-level ``Path.home()``-based constant built once at import
    time, so the redirect has to be applied to the module object ``load_script`` just built. No
    test using this fixture may write to the real ``~/.pi/agent/extensions/``.
    """
    module = load_script("features/pi/adjustments/adjust_agents.py")
    monkeypatch.setattr(
        module, "USER_EXTENSIONS_DIR",
        tmp_path / "home" / ".pi" / "agent" / "extensions" / "ai-badger-subagent")
    return module


def _real_home_extensions_snapshot():
    """Every path under the real ~/.pi/agent/extensions/ with its mtime.

    A bare `does not exist` assertion is not usable here: the machine legitimately carries
    ai-badger's own installed extensions. What must hold is that a test run changes nothing
    there, which is what comparing this snapshot before and after proves.
    """
    root = _REAL_HOME / ".pi" / "agent" / "extensions"
    if not root.is_dir():
        return []
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*"))


@pytest.fixture
def project(tmp_path):
    """A scaffolded project skeleton: `.ai-badger/agents/architect.md` and a project root."""
    aib = tmp_path / ".ai-badger"
    (aib / "agents").mkdir(parents=True)
    (aib / "agents" / "architect.md").write_text(PERSONA, encoding="utf-8")
    return tmp_path


def _context(project_root, **overrides):
    """The adjustment context the scaffolder passes, with per-test overrides."""
    context = {
        "config": {"agents": ["pi"]},
        "target": project_root,
        "target_dir": project_root / ".ai-badger",
        "feature_dir": Path(__file__).resolve().parents[1] / "features" / "pi" / "adjustments",
        "install": True,
    }
    context.update(overrides)
    return context


def test_persona_is_written_as_a_plain_md_file(agents_arm, project):
    """The delivered filename must be `<name>.md`.

    pi's discovery is `entry.name.endsWith(".md")`, so copilot's `.agent.md` convention would
    still be discovered — but under the name `architect.agent`, which no delegation call names.
    """
    result = agents_arm.adjust(_context(project))

    assert result["applied"] is True
    assert (project / ".pi" / "agents" / "architect.md").is_file()
    assert not (project / ".pi" / "agents" / "architect.agent.md").exists()
    assert result["files"] == [".pi/agents/architect.md"]


def test_rendered_frontmatter_carries_only_the_keys_pi_reads(agents_arm, project):
    """`model`, `tools` and `disallowedTools` must not survive the copy.

    Their values are Claude's vocabulary (`opus`, `Read`, `Grep`); the subagent extension turns
    those keys into `--model` / `--tools` arguments, where a Claude alias is not a pi model and
    a capitalised Claude tool name is not one of pi's. Passing them through would break every
    delegation instead of falling back to the session's own model and tool set.
    """
    agents_arm.adjust(_context(project))

    split = fm.split((project / ".pi" / "agents" / "architect.md").read_text(encoding="utf-8"))
    assert split.present
    assert set(split.fields()) == {"name", "description"}
    assert split.fields()["name"] == "architect"
    assert "Body text the subagent extension uses" in split.body


def test_missing_persona_source_is_reported_as_a_loud_error(agents_arm, tmp_path):
    """A missing `.ai-badger/agents/` is an ERROR note naming the path, never a silent skip.

    This is the F6 defect class: an adjustment that returns `[]` when its source is absent
    ships a capability claim with nothing behind it.
    """
    (tmp_path / ".ai-badger").mkdir()

    result = agents_arm.adjust(_context(tmp_path))

    assert result["applied"] is False
    assert result["notes"].startswith("ERROR:")
    assert str(tmp_path / ".ai-badger" / "agents") in result["notes"]


def test_an_empty_persona_source_says_what_it_found(agents_arm, tmp_path):
    """A `.ai-badger/agents/` that exists but holds no persona says so, and does not create
    `.pi/agents/` — a directory of nothing would be scaffolding noise, not a capability."""
    (tmp_path / ".ai-badger" / "agents").mkdir(parents=True)

    result = agents_arm.adjust(_context(tmp_path))

    assert result["applied"] is False
    assert result["files"] == []
    assert "no personas in" in result["notes"]
    assert str(tmp_path / ".ai-badger" / "agents") in result["notes"]
    assert not (tmp_path / ".pi").exists()


def test_no_install_still_writes_the_project_agents(agents_arm, project):
    """`--no-install` must not suppress this arm: `.pi/agents/` is project state, not user state.

    adjust_skills and adjust_cron are no-ops under `--no-install` because they write under
    `~/.pi/`; copying that guard here would leave a scaffolded project with no personas.
    """
    result = agents_arm.adjust(_context(project, install=False))

    assert result["applied"] is True
    assert (project / ".pi" / "agents" / "architect.md").is_file()


def test_a_hand_written_agent_file_is_left_untouched(agents_arm, project):
    """A `.pi/agents/` file ai-badger did not place belongs to the user."""
    dest = project / ".pi" / "agents"
    dest.mkdir(parents=True)
    (dest / "architect.md").write_text("hand written\n", encoding="utf-8")

    result = agents_arm.adjust(_context(project))

    assert (dest / "architect.md").read_text(encoding="utf-8") == "hand written\n"
    assert result["files"] == []
    assert "left .pi/agents/architect.md untouched" in result["notes"]


def test_a_previously_delivered_file_is_refreshed(agents_arm, project):
    """A file carrying ai-badger's managed header is ours, so a re-scaffold updates it."""
    agents_arm.adjust(_context(project))
    (project / ".ai-badger" / "agents" / "architect.md").write_text(
        PERSONA.replace("Body text", "Revised text"), encoding="utf-8")

    agents_arm.adjust(_context(project))

    assert "Revised text" in (project / ".pi" / "agents" / "architect.md").read_text(
        encoding="utf-8")


def test_pi_not_in_config_agents_is_a_no_op(agents_arm, project):
    """No pi in config.agents means no `.pi/` directory appears at all."""
    result = agents_arm.adjust(_context(project, config={"agents": ["claude"]}))

    assert result["applied"] is False
    assert not (project / ".pi").exists()


def test_the_agents_arm_is_registered_in_pi_adjustment_json(root):
    """An unregistered script never runs — the defect support.json's honesty test guards against."""
    adjustment = json.loads(
        (root / "features" / "pi" / "adjustments" / "adjustment.json").read_text(encoding="utf-8"))

    assert "adjust_agents.py" in {arm["script"] for arm in adjustment["adjustments"]}


def test_the_subagent_extension_is_installed_user_scope(agents_arm, project):
    """Scaffolded persona files are inert without a reader; the arm installs ai-badger's own.

    pi core has no custom-agent feature, and its example subagent extension is manual-install
    and reads project agents only under an opt-in scope. Delivering `.pi/agents/` without
    installing a reader ships files nothing loads.
    """
    before = _real_home_extensions_snapshot()

    result = agents_arm.adjust(_context(project))

    assert (agents_arm.USER_EXTENSIONS_DIR / "index.ts").is_file()
    assert (agents_arm.USER_EXTENSIONS_DIR / "package.json").is_file()
    assert str(agents_arm.USER_EXTENSIONS_DIR) in result["notes"]
    assert _real_home_extensions_snapshot() == before


def test_no_install_leaves_the_user_scope_extension_alone(agents_arm, project):
    """`--no-install` is a documented no-op for user-global state, and not an error."""
    result = agents_arm.adjust(_context(project, install=False))

    assert not agents_arm.USER_EXTENSIONS_DIR.exists()
    assert "ERROR" not in result["notes"]
    assert result["applied"] is True


def test_a_missing_subagent_source_is_reported_as_a_loud_error(agents_arm, project, tmp_path):
    """A missing `features/pi/subagent/` is an ERROR note naming the dir, never a silent skip.

    Same F6 defect class as adjust_hooks and adjust_cron: the personas would still be written,
    so `applied` stays true, but the run must say the reader never shipped.
    """
    result = agents_arm.adjust(
        _context(project, feature_dir=tmp_path / "nowhere" / "adjustments"))

    assert result["applied"] is True
    assert "ERROR:" in result["notes"]
    assert str(tmp_path / "nowhere" / "subagent") in result["notes"]
    assert not agents_arm.USER_EXTENSIONS_DIR.exists()
