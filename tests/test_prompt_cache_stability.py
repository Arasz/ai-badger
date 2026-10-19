"""Scaffolded agent-facing files stay byte-stable, so harness prompt caches keep hitting.

Harnesses (Claude Code, pi) place cache breakpoints after the system prompt and tools; any byte
that changes between two requests invalidates the cached prefix from that point on. Every
file a scaffold writes for an agent to read must therefore be a pure function of the catalog
and the config — never of when the scaffold ran.
"""
from __future__ import annotations

import re

from scaffold_helpers import _config

ALL_AGENTS = ["claude", "copilot", "hermes", "pi", "codex"]

# Provenance and identity, read by tooling — never pasted into a prompt.
NOT_PROMPT_INPUT = {".ai-badger/manifest.json", ".ai-badger/project-id", ".codex/hooks.json"}

DISCOVERY_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "AGENTS.override.md",
    "HERMES.md",
    ".hermes.md",
    ".github/copilot-instructions.md",
)

TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _scaffold(make_scaffolder, tmp_path, name, generated_at):
    target = tmp_path / name
    target.mkdir()
    config = _config(stacks=["python"], agents=ALL_AGENTS)
    make_scaffolder(target=target, config=config).run(generated_at=generated_at)
    return target


def _files(target):
    return {
        p.relative_to(target).as_posix(): p.read_bytes()
        for p in target.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(target).parts
    }


def test_agent_facing_files_do_not_depend_on_scaffold_time(make_scaffolder, tmp_path):
    first = _files(_scaffold(make_scaffolder, tmp_path, "a", "2026-01-01T00:00:00Z"))
    second = _files(_scaffold(make_scaffolder, tmp_path, "b", "2027-06-30T23:59:59Z"))

    assert first.keys() == second.keys()
    changed = sorted(
        path for path in first
        if path not in NOT_PROMPT_INPUT and first[path] != second[path]
    )
    assert not changed, (
        f"these files change with the scaffold time, so every re-scaffold breaks the prompt "
        f"cache of every agent that loads them: {changed}"
    )


def test_discovery_files_carry_no_timestamp(make_scaffolder, tmp_path):
    target = _scaffold(make_scaffolder, tmp_path, "a", "2026-01-01T00:00:00Z")

    offenders = {}
    for name in DISCOVERY_FILES:
        path = target / name
        assert path.is_file(), f"{name}: not generated for agents={ALL_AGENTS}"
        hits = TIMESTAMP.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"discovery files load at the head of every session; a timestamp there invalidates "
        f"the cached prefix: {offenders}"
    )


def test_claude_stack_ships_the_cache_stability_instructions(make_scaffolder, tmp_path):
    target = tmp_path / "c"
    target.mkdir()
    make_scaffolder(target=target, config=_config(stacks=["claude"], agents=["claude"])).run()

    text = (target / ".ai-badger" / "instructions" / "claude.instructions.md").read_text(
        encoding="utf-8")
    assert "byte-stable" in text
    assert "`.ai-badger/instructions/claude.instructions.md`" in (target / "CLAUDE.md").read_text(
        encoding="utf-8")
