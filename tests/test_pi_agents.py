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
    """The pi persona adjustment module, loaded fresh.

    The adjustment no longer installs anything at user scope — the subagent reader extension is
    canonical in pi-badger-integration and installed by its publish flow — so there is no
    user-scope path to redirect. No test using this fixture may write to the real
    ``~/.pi/agent/extensions/``.
    """
    return load_script("features/pi/adjustments/adjust_agents.py")



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


def test_an_unparseable_persona_source_is_skipped_with_a_note(agents_arm, project):
    """A source file with no frontmatter is skipped and named, never a silent hole."""
    (project / ".ai-badger" / "agents" / "broken.md").write_text(
        "no frontmatter at all\n", encoding="utf-8")

    result = agents_arm.adjust(_context(project))

    assert (project / ".pi" / "agents" / "architect.md").is_file()
    assert "skipped broken.md" in result["notes"]


def test_the_manifest_record_makes_a_delivered_file_ours(agents_arm, project):
    """A delivered file recorded in the previous run's manifest.json is refreshed even if a
    later edit removed its managed header — ownership comes from the manifest too."""
    agents_arm.adjust(_context(project))
    dst = project / ".pi" / "agents" / "architect.md"
    dst.write_text(
        dst.read_text(encoding="utf-8").replace(
            "<!-- Managed by ai-badger. Source of truth: .ai-badger/agents/architect.",
            "<!-- different banner. Source: .ai-badger/agents/architect."),
        encoding="utf-8")
    assert "Managed by ai-badger" not in dst.read_text(encoding="utf-8")
    # The previous run's manifest records the delivered target — that record, not the
    # header, is what keeps the file ours once the header is gone.
    (project / ".ai-badger" / "manifest.json").write_text(
        json.dumps({"entries": [
            {"feature": "adjustments", "stack": "pi",
             "name": "adjustments/.pi/agents/architect.md",
             "source": "features/pi/adjustments/adjust_agents.py",
             "target": ".pi/agents/architect.md"}]}),
        encoding="utf-8")

    result = agents_arm.adjust(_context(project))

    assert ".pi/agents/architect.md" in result["files"]
    assert "Managed by ai-badger" in dst.read_text(encoding="utf-8")


def test_a_corrupt_manifest_is_tolerated_not_fatal(agents_arm, project):
    """A manifest.json that does not parse degrades to header-based ownership detection."""
    (project / ".ai-badger" / "manifest.json").write_text("{not json", encoding="utf-8")

    result = agents_arm.adjust(_context(project))

    assert (project / ".pi" / "agents" / "architect.md").is_file()


def test_no_install_still_writes_the_project_agents(agents_arm, project):
    """`--no-install` must not suppress this arm: `.pi/agents/` is project state, not user state.

    adjust_skills is a no-op under `--no-install` because it writes under
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


# ---------------------------------------------------------------------------
# L1-C — dual-key (level:/model:) delivery halves, ADR-0027 G-3.
#
# Claude half (C1 single, C2 matrix): `level:` is gate-only vocabulary — the CLAUDE_KEYS
# allowlist strips it at .claude/agents/ delivery — while `model:` passes verbatim, bare
# lanes included (Claude routes on them). These load the claude adjuster read-only: that
# file belongs to another lane, so C1/C2 pin its behavior without changing it.
#
# Pi half (C3 strip, C4 bare-never matrix): `level:` passes through to .pi/agents/ (the pi
# reader resolves it against the model-groups registry); `model:` passes iff
# openrouter/-qualified — a bare Claude lane is not a pi --model argument and pi would
# reject it. A bare model therefore never survives pi delivery, whatever level sits beside
# it. Grandfather (no level: at all) is pinned by
# test_rendered_frontmatter_carries_only_the_keys_pi_reads above.
# ---------------------------------------------------------------------------

CLAUDE_ADJUSTER = "features/claude/adjustments/adjust_agents.py"

_LEVELS = ("low", "medium", "high")


def _dual_persona(name: str, level, model) -> str:
    """A persona carrying one dual-key combination the C-matrix ranges over."""
    lines = ["---\n", f"name: {name}\n", "description: d\n"]
    if level is not None:
        lines.append(f"level: {level}\n")
    if model is not None:
        lines.append(f"model: {model}\n")
    return "".join(lines) + "---\n\nBody for %s.\n" % name


def _front(text: str) -> str:
    """The frontmatter block of a rendered file, without its fences."""
    assert text.startswith("---\n"), "frontmatter must start at line 1"
    return text.split("---\n", 2)[1]


def test_l1_c1_claude_delivery_strips_level_but_keeps_the_bare_lane(load_script):
    """Single-group claude half: level: is gate-only; the bare model: lane still routes."""
    claude = load_script(CLAUDE_ADJUSTER)

    rendered = claude.render(_dual_persona("lane", "high", "opus"), "lane.md")

    front = _front(rendered)
    assert "model: opus\n" in front
    assert "level" not in front


@pytest.mark.parametrize("level", _LEVELS)
@pytest.mark.parametrize("model", ["opus", "openrouter/anthropic/claude-sonnet-4.5", None])
def test_l1_c2_claude_delivery_never_carries_level(load_script, level, model):
    """Matrix claude half: no level survives; any declared model passes verbatim."""
    claude = load_script(CLAUDE_ADJUSTER)

    rendered = claude.render(_dual_persona("m", level, model), "m.md")

    front = _front(rendered)
    assert "level" not in front
    if model is None:
        assert "model:" not in front
    else:
        assert f"model: {model}\n" in front


def test_l1_c3_pi_delivery_passes_level_but_strips_the_bare_lane(agents_arm, project):
    """Single-group pi half, end to end: level: passes through, bare model: never lands."""
    (project / ".ai-badger" / "agents" / "architect.md").write_text(
        _dual_persona("architect", "high", "opus"), encoding="utf-8")

    result = agents_arm.adjust(_context(project))

    assert result["applied"] is True
    text = (project / ".pi" / "agents" / "architect.md").read_text(encoding="utf-8")
    split = fm.split(text)
    assert split.present
    assert text.startswith("---\n"), "frontmatter must start at line 1"
    assert split.fields()["level"] == "high"
    assert "model" not in split.fields()
    assert "Body for architect." in split.body


@pytest.mark.parametrize("level", _LEVELS)
@pytest.mark.parametrize("model", ["opus", "openrouter/anthropic/claude-sonnet-4.5", None],
                         ids=["explicit-bare", "explicit-qualified", "level-only"])
def test_l1_c4_pi_delivery_passes_level_and_only_qualified_models(agents_arm, level, model):
    """Bare-never matrix: every level passes; only an openrouter/-qualified model joins it."""
    rendered = agents_arm.render(_dual_persona("m", level, model), "m.md")

    front = _front(rendered)
    assert f"level: {level}\n" in front
    if model is None:
        assert "model:" not in front
    elif model.startswith("openrouter/"):
        assert f"model: {model}\n" in front
    else:
        assert "model:" not in front, f"bare lane {model!r} must never reach pi"

