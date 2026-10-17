"""The `tools` feature across every harness at once (ADR-0039).

Each arm has its own unit tests; these drive the real scaffolder CLI with all five agents opted
in to rtk, in a tmp target, a redirected HOME and a PATH that holds only a stub `rtk` (or
nothing). The stub records any call, so a run that executed it shows in its log.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from scaffold_helpers import _config
from test_scaffold_freshness_guard import _copy_working_tree, _freshen, _git, _run_gate

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
AGENTS = ["claude", "codex", "copilot", "hermes", "pi"]
MARKER = "AI_BADGER_TOOL="
STAMP = "2026-10-17T00:00:00Z"
SKILLS = "git-work,commit-reminder"
STUB = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$STUB_LOG"\n'
MARKED_FILES = (".claude/settings.json", ".codex/hooks.json", ".github/hooks/rtk-rewrite.json")
FORBIDDEN_NAMES = {"pipeline.toml", "RTK.md", ".rtk", "filters.toml"}


class Sandbox:
    """Redirected HOME, a stub-rtk bin dir with a call log, and a scaffold runner."""

    def __init__(self, base: Path):
        self.home, self.hermes = base / "home", base / "hermes"
        self.bin, self.log = base / "bin", base / "stub.log"
        self.target = base / "proj"
        for path in (self.home, self.hermes, self.bin):
            path.mkdir()
        rtk = self.bin / "rtk"
        rtk.write_text(STUB)
        rtk.chmod(rtk.stat().st_mode | stat.S_IEXEC)

    def env(self, stub: bool) -> dict:
        path = f"{self.bin}:/usr/bin:/bin" if stub else "/usr/bin:/bin"
        return {"HOME": str(self.home), "HERMES_HOME": str(self.hermes), "PATH": path,
                "STUB_LOG": str(self.log), "AI_BADGER_MCP_AVAILABILITY": "all"}

    def scaffold(self, tools, *, stub: bool = False) -> str:
        """Scaffold `self.target` with --no-install; return the stdout."""
        config = _config(stacks=["python"], agents=AGENTS)
        if tools is not None:
            config["tools"] = tools
        cfg = self.target.parent / "config.json"
        cfg.write_text(json.dumps(config))
        self.target.mkdir(exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(SCAFFOLD), "--config", str(cfg), "--target", str(self.target),
             "--root", str(ROOT), "--no-install", "--skills", SKILLS,
             "--generated-at", STAMP],
            cwd=str(self.target), env=self.env(stub), capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return proc.stdout

    def reset(self) -> None:
        shutil.rmtree(self.target)

    def tree(self, *, backups: bool = True) -> dict:
        return snapshot(self.target, backups=backups)


def snapshot(path: Path, *, backups: bool = True) -> dict:
    """Every file's bytes by relative path, minus the per-checkout random project id."""
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*"))
            if p.is_file() and p.name != "project-id" and (backups or ".bak-" not in p.name)}


def tool_notes(stdout: str) -> list:
    return [line.strip() for line in stdout.splitlines() if "adjustment 'tools'" in line]


ALL_HOOKS = {"rtk": {"hooks": AGENTS}}


@pytest.fixture(name="box")
def box_fixture(tmp_path) -> Sandbox:
    return Sandbox(tmp_path)


# -- a1: the stub rtk on PATH changes nothing ---------------------------------------------

def test_a_stub_rtk_on_path_leaves_the_generated_tree_and_notes_byte_identical(box):
    """Backups carry a timestamp in their name, so they are compared by count, not bytes."""
    without = box.scaffold(ALL_HOOKS, stub=False)
    tree_without, backups_without = box.tree(backups=False), backup_names(box)
    box.reset()

    with_stub = box.scaffold(ALL_HOOKS, stub=True)

    assert box.tree(backups=False) == tree_without
    assert len(backup_names(box)) == len(backups_without)
    assert tool_notes(with_stub) == tool_notes(without)
    assert tool_notes(with_stub), "no tools note: the arms were not exercised"
    assert not box.log.exists(), "the stub rtk was executed under --no-install"


def backup_names(box: Sandbox) -> list:
    return sorted(set(box.tree()) - set(box.tree(backups=False)))


# -- a2: every arm lands, a rerun is a no-op, removal leaves nothing ----------------------

def test_claude_codex_copilot_write_files_and_pi_hermes_only_note(box):
    stdout = box.scaffold(ALL_HOOKS)

    for rel in MARKED_FILES:
        assert MARKER + "rtk" in (box.target / rel).read_text(), rel
    by_agent = {agent: [n for n in tool_notes(stdout) if f"for '{agent}'" in n] for agent in AGENTS}
    assert all(len(notes) == 1 for notes in by_agent.values()), by_agent
    assert "rtk init --agent pi" in by_agent["pi"][0]
    assert "rtk init -g --agent hermes --auto-patch" in by_agent["hermes"][0]
    assert not (box.target / ".pi/extensions/rtk.ts").exists()
    assert snapshot(box.home) == {} and snapshot(box.hermes) == {}
    assert not box.log.exists()


def test_a_second_scaffold_is_byte_identical(box):
    box.scaffold(ALL_HOOKS)
    first = box.tree()

    box.scaffold(ALL_HOOKS)

    assert box.tree() == first


def test_removing_tools_from_config_removes_every_marked_artefact(box):
    box.scaffold(ALL_HOOKS)
    extension = box.target / ".pi/extensions/rtk.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text("// RTK Pi extension\n")

    stdout = box.scaffold(None)

    leftovers = [rel for rel, data in box.tree(backups=False).items()
                 if MARKER.encode() in data or b"## Tools: rtk" in data]
    assert leftovers == []
    assert not (box.target / ".github/hooks/rtk-rewrite.json").exists()
    assert not any("rtk" in note for note in tool_notes_for(stdout, "hermes"))
    [pi_note] = tool_notes_for(stdout, "pi")
    assert "rtk init --agent pi --uninstall" in pi_note
    assert extension.exists(), "--no-install must leave the extension for the operator"
    extension.unlink()
    extension.parent.rmdir()
    after_removal = box.tree(backups=False)
    box.reset()  # same path: codex binds the absolute target root into its hook commands
    box.scaffold(None)
    assert after_removal == box.tree(backups=False)


def tool_notes_for(stdout: str, agent: str) -> list:
    return [n for n in tool_notes(stdout) if f"for '{agent}'" in n]


# -- a3: nothing outside the design is generated ------------------------------------------

def test_no_rtk_side_files_or_imports_are_generated(box):
    box.scaffold(ALL_HOOKS, stub=True)

    names = [rel for rel in box.tree() if set(Path(rel).parts) & FORBIDDEN_NAMES]
    imports = [rel for rel, data in box.tree().items() if b"@RTK.md" in data]
    assert names == [] and imports == []


# -- a4: hand-editing the rendered block is caught by the freshness guard -----------------

@pytest.fixture(scope="module", name="fresh_with_rtk")
def fresh_with_rtk_fixture(tmp_path_factory):
    """A copy of this repo, self-scaffolded with rtk enabled for all five agents."""
    base = tmp_path_factory.mktemp("e2e-fresh")
    for name in ("home", "hermes", "bin"):
        (base / name).mkdir()
    stub = base / "bin" / "rtk"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(base / "home"))
        patch.setenv("HERMES_HOME", str(base / "hermes"))
        patch.setenv("STUB_LOG", str(base / "stub.log"))
        patch.setenv("PATH", f"{base / 'bin'}:{os.environ['PATH']}")
        repo = _copy_working_tree(base / "repo")
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        config_path = repo / ".ai-badger/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["tools"] = ALL_HOOKS
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "baseline")
        _freshen(repo)
        yield repo, base
    assert not (base / "stub.log").exists(), "the stub rtk was executed"


def test_a_hand_edited_rtk_block_is_reported_by_the_freshness_guard(fresh_with_rtk, tmp_path):
    fresh, base = fresh_with_rtk
    clone = tmp_path / "repo"
    shutil.copytree(fresh, clone, symlinks=True)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(base / "home"))
        patch.setenv("HERMES_HOME", str(base / "hermes"))
        control = _run_gate(clone)
        assert control.returncode == 0, control.stdout[:2500]
        claude_md = clone / ".ai-badger/CLAUDE.md"
        text = claude_md.read_text(encoding="utf-8")
        assert "## Tools: rtk" in text, "the rtk block was not rendered"
        claude_md.write_text(text.replace("## Tools: rtk", "## Tools: rtk\n\nEdited in place."),
                             encoding="utf-8")

        done = _run_gate(clone)

    assert done.returncode == 1, done.stdout + done.stderr
    assert ".ai-badger/CLAUDE.md" in done.stdout
    assert ".ai-badger/CLAUDE.md  (content differs, regenerates differently)" in done.stdout
