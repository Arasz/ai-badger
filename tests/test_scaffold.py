"""Tests for skills/welcome-ai-badger/scripts/scaffold.py: Scaffolder behavior.

test_scaffold_no_test_leak.py already covers the test-file anti-leak guarantee; this file
exercises preserve-vs-managed file handling, no-stack-leakage, manifest shape, and the
GitHub extension embed gate.
"""
from __future__ import annotations


def _config(stacks=None, source_control=None, commands=None, agents=None) -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": stacks if stacks is not None else ["dotnet"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": source_control if source_control is not None else
            {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": commands if commands is not None else {},
        "personaRouting": [],
        "pluginScope": "default",
        "docs": {},
    }


# --------------------------------------------------------- preserve-by-default / overwrite
def test_scaffold_preserves_hand_authored_claude_md_by_default(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    hand_authored = "# My Curated Guidance\n\nDo not touch this.\n"
    (target / "CLAUDE.md").write_text(hand_authored, encoding="utf-8")

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == hand_authored
    assert (target / ".ai-badger" / "CLAUDE.md").exists()  # source of truth still written
    assert any("preserved hand-authored" in n for n in result["notes"])


def test_scaffold_overwrite_replaces_hand_authored_claude_md(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    (target / "CLAUDE.md").write_text("# My Curated Guidance\n", encoding="utf-8")

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=[], install=False, overwrite=True)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    content = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert content.startswith(scaffold._MANAGED_PREFIX)


def test_scaffold_managed_file_refreshes_on_second_run_without_overwrite(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf1 = scaffold.Scaffolder(root=root, target=target,
                                 config=_config(commands={"build": "dotnet build"}),
                                 skills=[], install=False)
    scaf1.run(generated_at="2026-07-19T00:00:00Z")
    first = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "dotnet build" in first
    assert first.startswith(scaffold.MANAGED_HEADER.split("{name}", 1)[0])

    scaf2 = scaffold.Scaffolder(root=root, target=target,
                                 config=_config(commands={"build": "dotnet build -c Release"}),
                                 skills=[], install=False)
    scaf2.run(generated_at="2026-07-19T00:05:00Z")
    second = (target / "CLAUDE.md").read_text(encoding="utf-8")

    assert "dotnet build -c Release" in second


# ------------------------------------------------------------------------- new-file creation
def test_scaffold_creates_new_skill_dir_on_first_run(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    assert not (target / ".ai-badger").exists()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / ".ai-badger" / "skills" / "task").is_dir()
    skill_entries = [e for e in result["manifest"]["entries"]
                     if e["feature"] == "skills" and e["name"] == "task"]
    assert len(skill_entries) == 1


# ------------------------------------------------------------------------------- no leakage
def test_scaffold_no_stack_leakage(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    aib = target / ".ai-badger"
    assert (aib / "instructions" / "csharp.instructions.md").exists()
    assert (aib / "agents" / "dotnet-engineer.md").exists()  # personas land under agents/

    all_instruction_names = {p.name for p in (aib / "instructions").glob("*")}
    assert "python.instructions.md" not in all_instruction_names
    assert "react.instructions.md" not in all_instruction_names

    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "frontend-engineer.md" not in all_persona_names


def test_scaffold_no_stack_leakage_react_excludes_dotnet(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target,
                                config=_config(stacks=["react", "ts", "node"]),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    aib = target / ".ai-badger"
    assert (aib / "agents" / "frontend-engineer.md").exists()
    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "dotnet-engineer.md" not in all_persona_names


# -------------------------------------------------------------------------- manifest shape
def test_scaffold_manifest_entries_have_expected_shape(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    entries = result["manifest"]["entries"]
    assert entries, "expected at least one manifest entry"
    expected_keys = {"feature", "stack", "name", "source", "target",
                      "frameworkVersion", "hash"}
    for entry in entries:
        assert set(entry.keys()) == expected_keys
        assert entry["source"].startswith("features/") or entry["source"].startswith("skills/")
        assert len(entry["hash"]) == 64
        int(entry["hash"], 16)  # must be valid hex
        assert entry["frameworkVersion"] == result["manifest"]["frameworkVersion"]

    manifest_on_disk = (target / ".ai-badger" / "manifest.json")
    assert manifest_on_disk.exists()


# ------------------------------------------------------------------- github extension gate
def test_scaffold_github_extension_embedded_when_platform_github(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(source_control={
        "platform": "github", "repoUrl": "https://github.com/foo/bar", "projectUrl": None,
    })

    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    ext_dir = target / ".ai-badger" / "skills" / "task" / "extensions" / "github"
    assert ext_dir.is_dir()
    assert any("embedded extension 'github'" in n for n in result["notes"])


def test_scaffold_github_extension_not_embedded_when_platform_none(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(source_control={"platform": "none", "repoUrl": None, "projectUrl": None})

    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    ext_dir = target / ".ai-badger" / "skills" / "task" / "extensions" / "github"
    assert not ext_dir.exists()
    assert any("skipped (config requirements not met)" in n for n in result["notes"])
