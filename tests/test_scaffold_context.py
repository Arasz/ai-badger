"""The scaffold's shared state is a context; its collaborators need nothing else.

Wave 6 (docs/plans/2026-07-28-wave-6-scaffold-collaborators.md) replaces six mixins that
could only exist inside a `Scaffolder` with six collaborators built from one context.
"""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scaffold_helpers import _config

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"

# The step order run() records into manifest.json.partial, captured from a real run on main
# before Wave 6 began. Asserted after every work package: composition must not reorder run().
COMPLETED_STEPS = [
    "start", "personas-and-instructions", "skills", "agent-files", "hooks", "config-and-mcp",
]


def _load(load_script, root, name):
    """Load one welcome-ai-badger script with its siblings importable, as scaffold.py does."""
    scripts_dir = str(root / SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return load_script(f"{SCRIPTS}/{name}.py")


def _hand_built_context(load_script, root, target):
    """A ScaffoldContext assembled by hand — no Scaffolder anywhere in scope."""
    ctx_mod = _load(load_script, root, "scaffold_context")
    bl = load_script("scripts/badger_lib.py")
    config = _config(stacks=["python"], agents=["claude"])
    return ctx_mod.ScaffoldContext(
        root=root, target=target, aib=target / ".ai-badger", config=config,
        index=bl.read_index(root), stacks=bl.resolve_stacks(config),
        skills=["task"], excluded=bl.exclusions(config),
    )


# ------------------------------------------------------------------ the Wave 6 entry point
# Strict: the marker must be removed by the work package that composes the last collaborator.
@pytest.mark.xfail(strict=True, reason="Wave 6 in flight — the mixins still need a Scaffolder")
def test_each_collaborator_works_with_no_scaffolder_in_scope(tmp_path, load_script, root):
    """A collaborator takes a context and nothing else; today the mixins need a Scaffolder."""
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    ctx = _hand_built_context(load_script, root, target)

    extensions = _load(load_script, root, "extensions").Extensions(ctx)
    statusline = _load(load_script, root, "statusline_wiring").StatusLineWiring(ctx)
    hooks = _load(load_script, root, "hook_wiring").HookWiring(ctx)
    mcp = _load(load_script, root, "mcp_tools").McpTools(ctx)
    rendering = _load(load_script, root, "template_rendering").TemplateRendering(ctx)
    agent_files = _load(load_script, root, "agent_files").AgentFiles(ctx, rendering)

    skill = target / ".ai-badger" / "skills" / "probe"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# probe\n", encoding="utf-8")
    (skill / "project-local.md").write_text("## local\n", encoding="utf-8")
    extensions.append_project_local("probe", skill)
    assert "## local" in (skill / "SKILL.md").read_text(encoding="utf-8")

    ctx.config["statusLineCapture"] = {"enabled": True}
    statusline.wire()
    assert any("statusline capture not wired" in n for n in ctx.notes)

    hooks.wire()
    assert any("is not scaffolded" in n for n in ctx.notes)

    assert mcp.collect_stack_mcp_servers() == mcp.collect_stack_mcp_servers()
    mcp.fill_merged_external_tools()
    assert ctx.external_tools_merged

    assert "# probe" in rendering.assemble_instructions_doc([], [])

    agent_files.write_agent_files("", [], [])
    assert (target / "CLAUDE.md").is_file()


# ----------------------------------------------------------------- step-order golden master
def test_the_scaffold_runs_its_steps_in_the_recorded_order(
        tmp_path, load_script, root, monkeypatch):
    """Composition must not reorder run(); completedSteps is the contract."""
    scaffold = _load(load_script, root, "scaffold")
    target = tmp_path / "proj"
    target.mkdir()

    recorded = []
    original = scaffold.bl.dump_json

    def _spy(path, data):
        if Path(path).name == scaffold.PARTIAL_MANIFEST:
            recorded.append(list(data["completedSteps"]))
        original(path, data)

    monkeypatch.setattr(scaffold.bl, "dump_json", _spy)
    scaf = scaffold.Scaffolder(root=root, target=target,
                               config=_config(stacks=["python"], agents=["claude"]),
                               skills=["task"], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert [steps[-1] for steps in recorded] == COMPLETED_STEPS
    assert recorded[-1] == COMPLETED_STEPS
    assert not (target / ".ai-badger" / scaffold.PARTIAL_MANIFEST).exists()


@pytest.mark.parametrize("agents", [["claude"], ["claude", "copilot", "hermes"]])
def test_the_step_order_does_not_depend_on_which_agents_are_configured(
        tmp_path, load_script, root, agents):
    scaffold = _load(load_script, root, "scaffold")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target,
                               config=_config(stacks=["python"], agents=agents),
                               skills=["task", "prompt-markers"], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert scaf._completed_steps == COMPLETED_STEPS
