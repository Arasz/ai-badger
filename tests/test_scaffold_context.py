"""The scaffold's shared state is a context; its collaborators need nothing else.

Wave 6 replaces six mixins that could only exist inside a `Scaffolder` with six
collaborators built from one context.
"""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import ast
import json
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
    """Load one welcome-ai-badger script with badger_lib and its siblings importable.

    The same sys.path entries scaffold.py's own bootstrap installs — deployment plumbing,
    not a Scaffolder. `tooling/` is there because agent_files reaches install_plugins.
    """
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


def _hand_built_context(load_script, root, target):
    """A ScaffoldContext assembled by hand — no Scaffolder anywhere in scope."""
    ctx_mod = _load(load_script, root, "scaffold_context")
    bl = load_script("engine/badger_lib.py")
    config = _config(stacks=["python"], agents=["claude"])
    return ctx_mod.ScaffoldContext(
        root=root, target=target, aib=target / ".ai-badger", config=config,
        index=bl.read_index(root), stacks=bl.resolve_stacks(config),
        skills=["task"], excluded=bl.exclusions(config),
    )


# ------------------------------------------------------------------ the Wave 6 entry point
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


# ----------------------------------------------------------- per-collaborator construction
def test_extensions_is_built_from_a_context_alone(load_script, root, make_scaffolder):
    target = make_scaffolder.target
    ctx = _hand_built_context(load_script, root, target)
    extensions = _load(load_script, root, "extensions").Extensions(ctx)

    skill = target / ".ai-badger" / "skills" / "probe"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# probe\n\n<!-- MERGE_EXTENSIONS -->\n", encoding="utf-8")
    ext = skill / "extensions" / "one"
    ext.mkdir(parents=True)
    (ext / "extension.md").write_text("## Added\n\nbody\n", encoding="utf-8")
    extensions.merge_extensions("probe", skill)

    assert "## Added" in (skill / "SKILL.md").read_text(encoding="utf-8")
    assert any("merged 1 extension section" in note for note in ctx.notes)
    assert "scaffold" not in _imported_modules(root, "extensions")


def test_statusline_wiring_is_built_from_a_context_alone(tmp_path, load_script, root):
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    ctx = _hand_built_context(load_script, root, target)
    ctx.config["statusLineCapture"] = {"enabled": True}
    module = _load(load_script, root, "statusline_wiring")
    statusline = module.StatusLineWiring(ctx)

    statusline.wire()
    assert any("the 'task' skill" in note for note in ctx.notes)

    capture = ctx.aib / "skills" / module.CAPTURE_SCRIPT
    capture.parent.mkdir(parents=True)
    capture.write_text("", encoding="utf-8")
    statusline.wire()
    settings = target / ".claude" / "settings.json"
    assert module.is_capture_command(
        json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"])

    ctx.config["statusLineCapture"] = {"enabled": False}
    statusline.unwire()
    assert "statusLine" not in json.loads(settings.read_text(encoding="utf-8"))
    assert "scaffold" not in _imported_modules(root, "statusline_wiring")


def test_hook_wiring_is_built_from_a_context_alone(tmp_path, load_script, root):
    target = tmp_path / "proj"
    (target / ".claude").mkdir(parents=True)
    ctx = _hand_built_context(load_script, root, target)
    hooks = _load(load_script, root, "hook_wiring").HookWiring(ctx)

    hooks.wire()

    # Nothing is scaffolded under this target, so every framework hook is refused by name.
    assert any("is not scaffolded" in note for note in ctx.notes)
    assert not (target / ".claude" / "settings.json").exists()
    assert "scaffold" not in _imported_modules(root, "hook_wiring")


def test_mcp_tools_is_built_from_a_context_alone(load_script, root, make_scaffolder):
    target = make_scaffolder.target
    ctx = _hand_built_context(load_script, root, target)
    ctx.config["externalTools"] = [{"name": "probe", "command": "probe-server",
                                    "generate_mcp_json": True}]
    mcp = _load(load_script, root, "mcp_tools").McpTools(ctx)

    mcp.fill_merged_external_tools()

    assert ctx.external_tools_merged
    assert "probe" in {tool["name"] for tool in ctx.merged_external_tools}
    merged = mcp.merge_mcp_servers(mcp.collect_stack_mcp_servers(), ctx.merged_external_tools)
    assert "probe" in mcp.split_servers_by_scope(merged)[0]
    assert "scaffold" not in _imported_modules(root, "mcp_tools")


def test_mcp_tools_fills_the_cache_the_template_rendering_reads(
        load_script, root, make_scaffolder):
    """The one shared cache lives on the context — neither collaborator names the other."""
    target = make_scaffolder.target
    ctx = _hand_built_context(load_script, root, target)
    mcp = _load(load_script, root, "mcp_tools").McpTools(ctx)

    mcp.fill_merged_external_tools()
    first = list(ctx.merged_external_tools)
    ctx.config["externalTools"] = [{"name": "late", "command": "late"}]
    mcp.fill_merged_external_tools()

    assert ctx.merged_external_tools == first, "filling twice must not re-read the config"


def test_template_rendering_is_built_from_a_context_alone(load_script, root, make_scaffolder):
    target = make_scaffolder.target
    ctx = _hand_built_context(load_script, root, target)
    rendering = _load(load_script, root, "template_rendering").TemplateRendering(ctx)

    doc = rendering.assemble_instructions_doc(["## An invariant"], [])

    assert "probe" in doc and "## An invariant" in doc
    assert "scaffold" not in _imported_modules(root, "template_rendering")
    assert "mcp_tools" not in _imported_modules(root, "template_rendering")


def test_template_rendering_reads_the_external_tools_off_the_context(
        load_script, root, make_scaffolder):
    """Edge 1: it must not reach into McpTools for the merged externalTools."""
    target = make_scaffolder.target
    ctx = _hand_built_context(load_script, root, target)
    ctx.merged_external_tools = [{"name": "probe", "instructions": "Use the probe server."}]
    ctx.external_tools_merged = True
    rendering = _load(load_script, root, "template_rendering").TemplateRendering(ctx)

    assert "Use the probe server." in rendering.assemble_instructions_doc([], [])


def test_agent_files_is_built_from_a_context_and_its_one_collaborator(
        load_script, root, make_scaffolder):
    """Edge 2: the dependency on template rendering is a constructor argument, not `self`."""
    target = make_scaffolder.target
    ctx = _hand_built_context(load_script, root, target)
    rendering = _load(load_script, root, "template_rendering").TemplateRendering(ctx)
    agent_files = _load(load_script, root, "agent_files").AgentFiles(ctx, rendering)

    agent_files.write_agent_files("", [], [])

    assert (target / "CLAUDE.md").is_file()
    assert "probe" in (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "scaffold" not in _imported_modules(root, "agent_files")


def test_agent_files_records_template_provenance_through_the_context(
        load_script, root, make_scaffolder):
    """Edge 3: record_template is manifest bookkeeping carried on the context."""
    target = make_scaffolder.target
    recorded = []
    ctx = _hand_built_context(load_script, root, target)
    ctx.record_template = lambda source, dest: recorded.append((source.name, dest.name))
    rendering = _load(load_script, root, "template_rendering").TemplateRendering(ctx)

    _load(load_script, root, "agent_files").AgentFiles(ctx, rendering).write_agent_files(
        "", [], [])

    assert ("CLAUDE.md.tmpl", "CLAUDE.md") in recorded


# ------------------------------------------------- the context is the only shared channel
COLLABORATORS = ("extensions", "statusline_wiring", "hook_wiring", "mcp_tools",
                 "template_rendering", "agent_files")

# The two edges that are allowed, and why. Everything else has to go through the context.
ALLOWED_EDGES = {
    # Edge 2 (plan §3): AgentFiles takes its renderer as a constructor argument.
    ("agent_files", "template_rendering"),
    # Pre-existing and unrelated to state: two module-level helpers for reading a command.
    ("statusline_wiring", "hook_wiring"),
}


def test_no_collaborator_reaches_another_through_self(root):
    for name in COLLABORATORS:
        reached = _imported_modules(root, name) & set(COLLABORATORS)
        assert {(name, other) for other in reached} <= ALLOWED_EDGES, name


def test_no_collaborator_imports_the_scaffolder(root):
    for name in COLLABORATORS + ("scaffold_context",):
        assert "scaffold" not in _imported_modules(root, name), name


def test_the_scaffolder_is_a_plain_class_over_a_context_and_six_collaborators(
        load_script, root, make_scaffolder):
    scaffold = _load(load_script, root, "scaffold")

    scaf = make_scaffolder(config=_config())

    assert scaffold.Scaffolder.__bases__ == (object,)
    assert scaf.ctx is scaf.extensions.ctx is scaf.statusline.ctx is scaf.hooks.ctx
    assert scaf.ctx is scaf.mcp.ctx is scaf.rendering.ctx is scaf.agent_files.ctx
    assert scaf.agent_files.rendering is scaf.rendering
    assert "Mixin" not in (root / SCRIPTS / "scaffold.py").read_text(encoding="utf-8")


# The nine McpTools methods Scaffolder used to re-expose under a private name.
_RETIRED_MCP_SHIMS = {
    "_collect_stack_mcp_servers", "_collect_external_tools", "_merge_external_tools",
    "_merge_mcp_servers", "_split_servers_by_scope", "_scaffold_hermes_mcp_user",
    "_scaffold_claude_mcp_user", "_generate_copilot_mcp_config", "_generate_mcp_json",
}


def test_the_scaffolder_keeps_no_private_shims_for_its_collaborators(load_script, root):
    """A collaborator's own methods are reached on it, not through a Scaffolder shim."""
    scaffold = _load(load_script, root, "scaffold")

    assert _RETIRED_MCP_SHIMS & set(vars(scaffold.Scaffolder)) == set()


# ----------------------------------------------------------------- step-order golden master
def test_the_scaffold_runs_its_steps_in_the_recorded_order(
        load_script, root, monkeypatch, make_scaffolder):
    """Composition must not reorder run(); completedSteps is the contract."""
    scaffold = _load(load_script, root, "scaffold")
    target = make_scaffolder.target

    recorded = []
    original = scaffold.bl.dump_json

    def _spy(path, data):
        if Path(path).name == scaffold.PARTIAL_MANIFEST:
            recorded.append(list(data["completedSteps"]))
        original(path, data)

    monkeypatch.setattr(scaffold.bl, "dump_json", _spy)
    scaf = make_scaffolder(config=_config(stacks=["python"], agents=["claude"]), skills=["task"])
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert [steps[-1] for steps in recorded] == COMPLETED_STEPS
    assert recorded[-1] == COMPLETED_STEPS
    assert not (target / ".ai-badger" / scaffold.PARTIAL_MANIFEST).exists()


@pytest.mark.parametrize("agents", [["claude"], ["claude", "copilot", "hermes"]])
def test_the_step_order_does_not_depend_on_which_agents_are_configured(agents, make_scaffolder):

    scaf = make_scaffolder(config=_config(stacks=["python"], agents=agents),
                           skills=["task", "prompt-markers"])
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert scaf._completed_steps == COMPLETED_STEPS
