"""The .ai-badger/skills/ tree is delivered by a collaborator, not by the Scaffolder itself.

Issue #194 part 1: scaffold.py sat one line under pylint's too-many-lines ceiling, so the
skills seam moved out whole — copying, seed-once preservation, and Hermes publication.
"""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import patch

from scaffold_helpers import _config
from conftest import _test_write

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"

# pylint's too-many-lines (C0302) refuses at 1000. Three consecutive releases paid rent on
# that ceiling before #194; this budget is the headroom the split bought.
MODULE_LINE_BUDGET = 850


def _load(load_script, root, name):
    """Load one welcome-ai-badger script with badger_lib and its siblings importable."""
    for entry in (str(root / SCRIPTS), str(root / "engine"), str(root / "tooling")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/{name}.py")


def _imported_modules(root, name):
    """Every module name *name*.py imports, at any nesting depth."""
    tree = ast.parse((root / SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _delivery(load_script, root, target, config=None, skills=("task",)):
    """A SkillDelivery over a hand-built context — no Scaffolder anywhere in scope."""
    ctx_mod = _load(load_script, root, "scaffold_context")
    bl = load_script("engine/badger_lib.py")
    config = config or _config(stacks=["python"], agents=["claude"])
    ctx = ctx_mod.ScaffoldContext(
        root=root, target=target, aib=target / ".ai-badger", config=config,
        index=bl.read_index(root), stacks=bl.resolve_stacks(config),
        skills=list(skills), excluded=bl.exclusions(config),
    )
    extensions = _load(load_script, root, "extensions").Extensions(ctx)
    return _load(load_script, root, "skill_delivery").SkillDelivery(ctx, extensions), ctx


# ------------------------------------------------------------------ the collaborator itself
def test_skill_delivery_is_built_from_a_context_and_extensions_alone(
        tmp_path, load_script, root):
    """It takes a context plus the one collaborator it really depends on, and nothing else."""
    delivery, ctx = _delivery(load_script, root, tmp_path / "proj")

    delivery.scaffold_skills()

    assert (ctx.aib / "skills" / "task" / "SKILL.md").is_file()
    assert "scaffold" not in _imported_modules(root, "skill_delivery")
    reached = _imported_modules(root, "skill_delivery") & {
        "statusline_wiring", "hook_wiring", "mcp_tools", "template_rendering", "agent_files"}
    assert reached == set()


def test_skill_delivery_records_every_skill_through_the_context(tmp_path, load_script, root):
    """Manifest bookkeeping is a context callable, exactly as record_template is."""
    recorded = []
    delivery, ctx = _delivery(load_script, root, tmp_path / "proj")
    ctx.record = lambda feature, stack, name, source, dest, **extra: recorded.append(
        (feature, name, extra))

    delivery.scaffold_skills()

    assert ("skills", "task", {"projectOwned": ["project-local.md"]}) in recorded


def test_skill_delivery_preserves_a_project_owned_seed_once_file(tmp_path, load_script, root):
    """markers-context.json belongs to the project once written (#15)."""
    delivery, ctx = _delivery(load_script, root, tmp_path / "proj", skills=("prompt-markers",))
    delivery.scaffold_skills()
    marker = ctx.aib / "skills" / "prompt-markers" / "markers-context.json"
    _test_write(marker, '{"mine": true}\n', encoding="utf-8")

    delivery.scaffold_skills()

    assert marker.read_text(encoding="utf-8") == '{"mine": true}\n'
    assert any("preserved seed-once" in note for note in ctx.notes)


def test_skill_delivery_publishes_the_hermes_namespace(tmp_path, load_script, root):
    """The delivered tree is republished where Hermes resolves skills (ADR-0003)."""
    home = tmp_path / "home"
    home.mkdir()
    delivery, _ctx = _delivery(load_script, root, tmp_path / "proj",
                               config=_config(stacks=["python"], agents=["hermes"]))
    delivery.scaffold_skills()

    with patch("pathlib.Path.home", return_value=home):
        delivery.symlink_hermes_skills()

    assert (home / ".hermes" / "skills" / "probe" / "task").is_symlink()


def test_skill_delivery_adds_the_stack_local_skills_to_the_context(tmp_path, load_script, root):
    """auto-wm ships from the claude stack, not from the universal defaults."""
    delivery, ctx = _delivery(load_script, root, tmp_path / "proj",
                              config=_config(stacks=["claude"], agents=["claude"]))

    delivery.discover_stack_local()

    assert "auto-wm" in ctx.skills


def test_stack_local_discovery_never_reaches_into_the_common_catalog(tmp_path, load_script, root):
    """`resolve_stacks` always puts `common` first, and its optIn skills ship only when asked.

    Before ADR-0018 the exclusion inside `stack_local_skills` was what kept them out; the
    scope declaration replaced the list it filtered on, and this is the behaviour that had to
    survive the swap.
    """
    bl = load_script("engine/badger_lib.py")
    delivery, ctx = _delivery(load_script, root, tmp_path / "proj",
                              config=_config(stacks=["claude"], agents=["claude"]))
    opt_in = set(bl.opt_in_skills_in(root / "features" / "common" / "skills"))

    delivery.discover_stack_local()

    assert "common" in ctx.stacks, "the fixture stopped exercising the hazard"
    assert opt_in, "no optIn skill in the catalog leaves nothing to leak"
    assert not opt_in & set(ctx.skills), sorted(opt_in & set(ctx.skills))


# ------------------------------------------------------------- what the Scaffolder keeps
def test_the_scaffolder_delivers_its_skills_through_the_collaborator(load_script, root,
                                                                    make_scaffolder):
    scaffold = _load(load_script, root, "scaffold")
    scaf = make_scaffolder(config=_config())

    assert scaf.skill_delivery.ctx is scaf.ctx
    assert scaf.skill_delivery.extensions is scaf.extensions
    assert "scaffold_skills" not in vars(scaffold.Scaffolder)


def test_scaffold_py_keeps_headroom_under_the_too_many_lines_ceiling(root):
    """#194: a module one line under C0302 blocks the next feature that has to touch it."""
    lines = len((root / SCRIPTS / "scaffold.py").read_text(encoding="utf-8").splitlines())

    assert lines <= MODULE_LINE_BUDGET, (
        f"scaffold.py is {lines} lines; pylint refuses at 1000 and the budget is "
        f"{MODULE_LINE_BUDGET}. Extract a collaborator instead of compressing a comment.")


def test_the_hermes_relink_stays_reachable_where_its_callers_look(tmp_path, load_script, root):
    """den-refresh's refresh.py loads scaffold.py by path and calls this by name."""
    scaffold = _load(load_script, root, "scaffold")
    target = tmp_path / "proj"
    skill = target / ".ai-badger" / "skills" / "task"
    skill.mkdir(parents=True)
    _test_write(skill / "SKILL.md", "# task\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        created = scaffold.relink_hermes_skills(target, _config(agents=["hermes"]), ["task"])

    assert created["created"] == ["task"]
    assert Path(scaffold.SkillDelivery.__module__.replace(".", "/")).name == "skill_delivery"
