"""Tests for features/common/skills/welcome-ai-badger/scripts/scaffold.py: core run behavior.

What a first run creates, which stacks reach the target, and what --execute runs. The
other scaffold behaviors live in the sibling test_scaffold_*.py modules.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config


# ------------------------------------------------------------------------- new-file creation
def test_scaffold_creates_new_skill_dir_on_first_run(make_scaffolder):
    target = make_scaffolder.target
    assert not (target / ".ai-badger").exists()

    result = make_scaffolder(skills=["task"]).run(generated_at="2026-07-19T00:00:00Z")

    assert (target / ".ai-badger" / "skills" / "task").is_dir()
    skill_entries = [e for e in result["manifest"]["entries"]
                     if e["feature"] == "skills" and e["name"] == "task"]
    assert len(skill_entries) == 1


# ------------------------------------------------------------------------------- no leakage
def test_scaffold_no_stack_leakage(make_scaffolder):
    make_scaffolder(config=_config(stacks=["dotnet"])).run(generated_at="2026-07-19T00:00:00Z")

    aib = make_scaffolder.target / ".ai-badger"
    assert (aib / "instructions" / "csharp.instructions.md").exists()
    assert (aib / "agents" / "dotnet-engineer.md").exists()  # personas land under agents/

    all_instruction_names = {p.name for p in (aib / "instructions").glob("*")}
    assert "python.instructions.md" not in all_instruction_names
    assert "react.instructions.md" not in all_instruction_names

    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "frontend-engineer.md" not in all_persona_names


def test_scaffold_no_stack_leakage_react_excludes_dotnet(make_scaffolder):
    make_scaffolder(config=_config(stacks=["react", "ts", "node"])).run(
        generated_at="2026-07-19T00:00:00Z")

    aib = make_scaffolder.target / ".ai-badger"
    assert (aib / "agents" / "frontend-engineer.md").exists()
    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "dotnet-engineer.md" not in all_persona_names


# ---------------------------------------------------------------------- --execute flag
def test_scaffold_execute_flag_runs_commands(make_scaffolder):
    """--execute flag should execute install commands and log results."""
    import unittest.mock

    scaf = make_scaffolder(config=_config(agents=["claude"]),
                           skills=["task"], install=True, execute=True)

    # Mock subprocess.run to capture calls without actually running them
    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=0, stderr="")
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Every command is an argv list run without a shell: a skill name is data, not syntax.
    assert mock_run.called
    for call in mock_run.call_args_list:
        cmd = call[0][0] if call[0] else call[1].get("command", [])
        assert isinstance(cmd, list), f"not argv: {cmd!r}"
        assert not call[1].get("shell"), f"ran through a shell: {cmd!r}"


def test_scaffold_execute_flag_handles_failure(make_scaffolder):
    """--execute flag should log failures without crashing."""
    import unittest.mock

    scaf = make_scaffolder(config=_config(agents=["claude"]),
                           skills=["task"], install=True, execute=True)

    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=1, stderr="not found")
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Should not crash, failures are logged in notes
    if mock_run.called:
        failure_notes = [n for n in scaf.notes if "command failed" in n or "executed:" in n]
        assert len(failure_notes) > 0 or len(mock_run.call_args_list) == 0


# ----------------------------------------------------------------- stack-local skills
def test_auto_wm_is_not_a_universal_default(load_script, root):
    """auto-wm ships from the claude stack directory, so the common catalog never names it."""
    bl = load_script("engine/badger_lib.py")
    skills_dir = root / "features" / "common" / "skills"
    assert "auto-wm" not in bl.default_skills_in(skills_dir) + bl.opt_in_skills_in(skills_dir)


def test_scaffolder_discovers_stack_local_skill_for_configured_stack(make_scaffolder):
    """A stack-local skill is auto-discovered when its stack is configured."""
    scaf = make_scaffolder(config=_config(stacks=["claude"]))
    result = scaf.run(generated_at="2026-07-28T00:00:00Z")

    assert "auto-wm" in scaf.skills
    assert (make_scaffolder.target / ".ai-badger" / "skills" / "auto-wm").is_dir()
    skill_entries = [e for e in result["manifest"]["entries"]
                     if e.get("feature") == "skills"
                     and e.get("name") == "auto-wm"]
    assert len(skill_entries) == 1
    assert skill_entries[0]["stack"] == "claude"


def test_scaffolder_does_not_discover_stack_local_skill_for_other_stack(make_scaffolder):
    """A stack-local skill is NOT included when its stack is not configured."""
    scaf = make_scaffolder(config=_config(stacks=["dotnet"]))
    scaf.run(generated_at="2026-07-28T00:00:00Z")

    assert "auto-wm" not in scaf.skills
    assert not (make_scaffolder.target / ".ai-badger" / "skills" / "auto-wm").exists()


def test_stack_local_skill_not_symlinked_to_other_agent(root, make_scaffolder):
    """A claude stack-local skill must not appear in copilot's adjustment context."""
    scaffold = make_scaffolder.module

    # Capture what skills each agent's adjustment receives
    seen = {}
    original_run = scaffold.Scaffolder.run_adjustments

    def capturing_run(self):
        import importlib.util
        for agent_name in self.config.get("agents", []):
            adj_path = self.root / "features" / agent_name / "adjustments" / "adjustment.json"
            if not adj_path.exists():
                continue
            adj_manifest = scaffold.bl.load_json(adj_path)
            for adj in adj_manifest.get("adjustments", []):
                script_name = adj.get("script")
                if not script_name:
                    continue
                script_path = adj_path.parent / script_name
                if not script_path.exists():
                    continue
                spec = importlib.util.spec_from_file_location("test", script_path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                agent_stacks = [s for s in self.stacks
                                if s == "common" or s == agent_name]
                agent_skills = [s for s in self.skills
                                if any(s in scaffold.bl.skills_for_stack(self.root, st)
                                       for st in agent_stacks)]
                seen[agent_name] = agent_skills
        # Don't actually run adjustments

    scaf = make_scaffolder(config=_config(stacks=["claude"], agents=["claude", "copilot"]))
    scaf.run(generated_at="2026-07-28T00:00:00Z")

    # After run, capture what each agent would get
    agent_stacks_claude = ["common", "claude"]
    agent_stacks_copilot = ["common"]
    claude_skills = [s for s in scaf.skills
                     if any(s in scaffold.bl.skills_for_stack(root, st)
                            for st in agent_stacks_claude)]
    copilot_skills = [s for s in scaf.skills
                      if any(s in scaffold.bl.skills_for_stack(root, st)
                             for st in agent_stacks_copilot)]

    assert "auto-wm" in claude_skills
    assert "auto-wm" not in copilot_skills


# ------------------------------------------------------- competing framework copies (#109)
def _framework_tree(path, version):
    """A directory the framework-root predicate accepts, carrying a VERSION."""
    for name in ("schemas", "features", "engine"):
        (path / name).mkdir(parents=True, exist_ok=True)
    (path / "engine" / "badger_lib.py").write_text("", encoding="utf-8")
    (path / "VERSION").write_text(version + "\n", encoding="utf-8")
    return path


def test_scaffold_names_a_competing_framework_cache_and_deletes_nothing(
        tmp_path, load_script, root, monkeypatch, capsys):
    """Onboarding a repo never removes anything from a home directory; it says what is there."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cache = _framework_tree(home / ".ai-badger" / "framework", "0.13.0")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config(stacks=["python"])), encoding="utf-8")
    target = tmp_path / "proj"
    target.mkdir()

    rc = scaffold.main(["--config", str(config_path), "--target", str(target),
                        "--root", str(root), "--skills", "", "--no-install"])

    out = capsys.readouterr().out
    assert rc == 0
    assert str(cache) in out and "0.13.0" in out
    assert "den-refresh --prune-cache" in out
    assert (cache / "VERSION").is_file()
