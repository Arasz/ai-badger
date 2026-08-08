"""Every check in this repo must have a proven failure path — one executed here, for real.

The recurring defect this guards against is a check whose comparison can only produce one
answer, and that answer looks like success:

  * F-11 (0.21.0)  release_guard compared against an 18-minor-stale baseline: it always found
                   changes AND always found a bump, so it passed for 32 consecutive releases.
  * 0.35.3         release_guard DETECTED untagged releases, printed `UNTAGGED RELEASES`, and
                   returned 0 — reported without failing.
  * 0.34.0         is_instrumented() read a command string still containing the literal
                   `${CLAUDE_PROJECT_DIR}`, so the read always failed and every hook reported
                   `not_instrumented`. One answer, always.
  * #110           drift.compare hashed the scaffolded copy against the hash recorded when that
                   copy was written — both sides the project's own state, so they always match.

Every one was found by a human noticing something downstream, never by a test. So:

  1. REGISTRY maps each check to a provocation — a known-bad state built under tmp_path — plus
     the failure signal the check must produce. The provocation is RUN, not merely described,
     and the same fixture is run again WITHOUT the defect: a check must produce both answers,
     or it is degenerate in the other direction and its provocation proves nothing.
  2. discovered_checks() finds the repo's checks mechanically. Anything it finds that is neither
     registered nor exempt fails this module, so adding a guard without a provocation breaks the
     build (same shape as test_gates_layout.test_every_gate_is_a_pylint_target).
  3. EXEMPTIONS is a visible, shrinking debt list. Each entry carries a reason.
  4. Every discovered gate must be reachable from a lane in verify.sh's `$LANES`. A provably
     failing gate that nothing dispatches proves nothing about a push.

Provocations are hermetic: every fixture is built under tmp_path, and nothing here touches the
real repository, ~/.ai-badger or ~/.hermes. Checks are run the way they really run — a
subprocess for a CLI gate — because this defect class lives in the wiring as much as the logic.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
BEHAVIORIST = "features/common/skills/call-behaviorist/scripts/behaviorist.py"
DRIFT = "features/common/skills/welcome-ai-badger/scripts/drift.py"
VERIFY = ".lefthook/pre-push/verify.sh"

# Checks with no provocation yet. EVERY ENTRY IS A DEBT, not a decision: an empty-by-default
# list that only grows is worthless. Delete an entry by writing its provocation.
EXEMPTIONS: Dict[str, str] = {
    f"{DRIFT}::compare":
        "covered by #110's own framework-mutation test; register once that lands",
}


def _load(relpath: str):
    """Import an ai-badger script by repo-relative path, the way conftest's fixture does."""
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location("aib_meta_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Loaded for its record-key constants only: hardcoding "c"/"e"/"v" would let a rename of the
# wire format turn these provocations into records nothing reads.
DL = _load("features/common/skills/call-behaviorist/scripts/debug_log.py")


class Outcome(NamedTuple):
    """What running a provoked check produced."""

    exit_code: int
    output: str
    findings: Tuple[Dict[str, Any], ...] = ()


class Signal(NamedTuple):
    """The failure a provoked check must report."""

    exit_code: Optional[int] = None
    contains: str = ""
    kind: str = ""
    severity: str = ""

    def unmet(self, outcome: Outcome) -> str:
        """Why `outcome` is not this signal, or "" when it is."""
        if self.exit_code is not None and outcome.exit_code != self.exit_code:
            return f"expected exit {self.exit_code}, got {outcome.exit_code}"
        if self.contains and self.contains not in outcome.output:
            return f"expected {self.contains!r} in the output"
        if self.kind:
            matching = [f for f in outcome.findings if f.get("kind") == self.kind]
            if not matching:
                kinds = sorted({str(f.get("kind")) for f in outcome.findings})
                return f"expected a {self.kind!r} finding, got {kinds}"
            if self.severity and all(f.get("severity") != self.severity for f in matching):
                return f"expected {self.kind!r} at severity {self.severity!r}"
        return ""


class Provocation(NamedTuple):
    """A known-bad state for one check, and the failure it must produce.

    `run(workspace, provoked)` builds the same fixture either way: with the defect when
    `provoked`, without it otherwise. Both runs are asserted — a provocation that fails for a
    setup reason would otherwise prove exactly as much as the degenerate checks it hunts.
    """

    check: str
    label: str
    run: Callable[[Path, bool], Outcome]
    signal: Signal


def _finding(kind: str, severity: str = "") -> Signal:
    return Signal(kind=kind, severity=severity)


# --------------------------------------------------------------------------- running checks


def _run(argv: List[str], env: Optional[Dict[str, str]] = None) -> Outcome:
    proc = subprocess.run([sys.executable, *argv], capture_output=True, text=True, check=False,
                          env=env)
    return Outcome(proc.returncode, proc.stdout + proc.stderr)


def _run_gate(relpath: str, *args: str) -> Outcome:
    return _run([str(ROOT / relpath), *args])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------- gates/release_guard.py


def _release_guard_no_bump(work: Path, provoked: bool) -> Outcome:
    """A shipped-surface change with no VERSION bump — the F-11 case."""
    repo = _repo(work / "repo")
    _write(repo / "VERSION", "0.1.0\n")
    _write(repo / "skills" / "a.md", "a\n")
    _commit(repo, "release 0.1.0")
    _git(repo, "tag", "ai-badger--v0.1.0")

    _write(repo / "skills" / "a.md", "changed\n")
    if not provoked:
        _write(repo / "VERSION", "0.2.0\n")
    _commit(repo, "tweak a skill")
    return _run_gate("gates/release_guard.py", "--root", str(repo))


def _release_guard_untagged_release(work: Path, provoked: bool) -> Outcome:
    """A documented release between the last tag and VERSION that never got tagged.

    Detected and printed since 0.21.0, but returned 0 until 0.35.3 — the exact shape of
    "reported without failing".
    """
    repo = _repo(work / "repo")
    _write(repo / "VERSION", "0.3.0\n")
    _write(repo / "docs" / "changelog" / "0.2.0-shipped-in-the-dark.md", "# 0.2.0\n")
    _commit(repo, "release 0.1.0")
    _git(repo, "tag", "ai-badger--v0.1.0")
    if not provoked:
        _git(repo, "tag", "ai-badger--v0.2.0")
    return _run_gate("gates/release_guard.py", "--root", str(repo))


def _release_guard_git_unavailable(work: Path, provoked: bool) -> Outcome:
    """A tree git cannot answer for at all — the third outcome F-10 added.

    Empty output from a failed git command proves nothing about the shipped surface, so the
    guard must refuse rather than read it as "no changes".
    """
    if provoked:
        root = work / "not-a-repo"
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = _repo(work / "repo")
        _write(root / "VERSION", "0.1.0\n")
        _commit(root, "release 0.1.0")
        _git(root, "tag", "ai-badger--v0.1.0")
    return _run_gate("gates/release_guard.py", "--root", str(root))


# ------------------------------------------------------------------ gates/docs_guard.py


def _docs_guard_broken_link(work: Path, provoked: bool) -> Outcome:
    """A relative Markdown link to a file that does not exist."""
    root = work / "tree"
    _write(root / "README.md", "See [the design](docs/design/one-note.md).\n")
    if not provoked:
        _write(root / "docs" / "design" / "one-note.md", "# a note\n")
    return _run_gate("gates/docs_guard.py", "--root", str(root))


def _docs_guard_missing_repo_path(work: Path, provoked: bool) -> Outcome:
    """A backticked repo path naming a file that is not in the tree.

    The predicate deciding what counts as a repo path has five suppression clauses; an
    always-false one would read exactly like a clean tree (the 0.34.0 shape).
    """
    root = work / "tree"
    named = "gates/never_written_guard.py" if provoked else "gates/real_guard.py"
    _write(root / "gates" / "real_guard.py", "# a gate\n")
    _write(root / "README.md", f"The gate lives in `{named}`.\n")
    return _run_gate("gates/docs_guard.py", "--root", str(root))


def _docs_guard_unindexed_changelog(work: Path, provoked: bool) -> Outcome:
    """A changelog entry no row in docs/changelog/README.md points at."""
    root = work / "tree"
    _write(root / "VERSION", "0.1.0\n")
    listed = "" if provoked else "- 0.1.0-orphan.md\n"
    _write(root / "docs" / "changelog" / "README.md", f"# Changelog\n\n{listed}")
    _write(root / "docs" / "changelog" / "0.1.0-orphan.md", "# 0.1.0\n")
    return _run_gate("gates/docs_guard.py", "--root", str(root))


# ------------------------------------------------------------------ gates/deps_guard.py


def _deps_guard(work: Path, provoked: bool) -> Outcome:
    """Shipped code importing a module engine/requirements.txt never declared."""
    root = work / "tree"
    _write(root / "engine" / "requirements.txt", "jsonschema\n")
    imported = "notarealmodule_zzz" if provoked else "json"
    _write(root / "tooling" / "probe.py", f"import {imported}\n")
    return _run_gate("gates/deps_guard.py", "--root", str(root))


# --------------------------------------------------------------- gates/shipped_paths_guard.py


def _shipped_paths_guard(work: Path, provoked: bool) -> Outcome:
    """A tracked file outside docs/ and tests/ carrying a real machine-specific path."""
    repo = _repo(work / "repo")
    value = "/Users/arasz/RiderProjects/ai-badger" if provoked else "${CLAUDE_PROJECT_DIR}"
    _write(repo / ".mcp.json", f'{{"cwd": "{value}"}}\n')
    _commit(repo, "mcp config")
    return _run_gate("gates/shipped_paths_guard.py", "--root", str(repo))


# ------------------------------------------------- gates/scaffold_freshness_guard.py


def _self_scaffolded_repo(work: Path) -> Path:
    """A git copy of this repo, scaffolded against itself so it is fresh by construction."""
    repo = _repo(work / "repo")
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=str(ROOT),
                         check=True, capture_output=True).stdout
    for rel in (p.decode("utf-8") for p in out.split(b"\0") if p):
        src, dst = ROOT / rel, repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(str(src)), str(dst))
        elif src.is_file():
            shutil.copy2(src, dst)
    _commit(repo, "baseline")
    env = dict(os.environ)
    env["AI_BADGER_MCP_AVAILABILITY"] = "all"
    scaffolded = _run([
        str(repo / "features/common/skills/welcome-ai-badger/scripts/scaffold.py"),
        "--config", str(repo / ".ai-badger/config.json"),
        "--target", str(repo), "--root", str(repo), "--no-install", "--skills", ""],
        env=env)
    assert scaffolded.exit_code == 0, f"fixture setup failed:\n{scaffolded.output}"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "self-scaffold")
    return repo


def _scaffold_freshness_guard(work: Path, provoked: bool) -> Outcome:
    """A skill source that gained a file after the last self-scaffold — the #204 incident."""
    repo = _self_scaffolded_repo(work)
    if provoked:
        _write(repo / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts"
               / "added_after_scaffold.py", '"""Added after the last self-scaffold."""\n')
    return _run_gate("gates/scaffold_freshness_guard.py", "--root", str(repo))


# ------------------------------------------------------------------- gates/tdd_guard.py


def _tdd_guard(work: Path, provoked: bool) -> Outcome:
    """Shipped code changed since the base ref and nothing under tests/ did."""
    repo = _repo(work / "repo")
    _write(repo / "engine" / "thing.py", "VALUE = 1\n")
    _write(repo / "tests" / "test_thing.py", "def test_thing():\n    assert True\n")
    base = _commit(repo, "thing, with its test")

    _write(repo / "engine" / "thing.py", "VALUE = 2\n")
    if not provoked:
        _write(repo / "tests" / "test_thing.py", "def test_thing():\n    assert VALUE == 2\n")
    _commit(repo, "change the behaviour")
    return _run_gate("gates/tdd_guard.py", "--root", str(repo), "--base", base)


# ------------------------------------------------------ tooling/*.py --check (verifiers)


def _framework_fixture(work: Path, version: str = "0.1.0") -> Path:
    """A synthetic framework tree index_build.py can scan: real schemas, one hand-built stack."""
    root = work / "framework"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "schemas", root / "schemas")
    _write(root / "VERSION", f"{version}\n")
    _write(root / "features" / "demo" / "stack.json", json.dumps({
        "name": "demo", "description": "demo stack", "detectionSignals": ["*.demo"],
    }))
    _write(root / "features" / "demo" / "skills" / "greet" / "SKILL.md", "# greet\n")
    built = _run([str(ROOT / "tooling" / "index_build.py"), "--root", str(root)])
    assert built.exit_code == 0, f"fixture setup failed:\n{built.output}"
    return root


def _index_build_check(work: Path, provoked: bool) -> Outcome:
    """index.json left stale by a feature added after it was generated."""
    root = _framework_fixture(work)
    if provoked:
        _write(root / "features" / "demo" / "personas" / "reviewer.md", "# reviewer\n")
    return _run([str(ROOT / "tooling" / "index_build.py"), "--root", str(root), "--check"])


def _version_sync_check(work: Path, provoked: bool) -> Outcome:
    """A version literal that disagrees with VERSION."""
    root = _framework_fixture(work)
    declared = "9.9.9" if provoked else "0.1.0"
    plugin_dir = root / ".claude-plugin"
    _write(plugin_dir / "plugin.json", json.dumps({
        "name": "ai-badger", "version": declared, "description": "d",
        "author": {"name": "a", "url": "u"}, "license": "MIT",
    }))
    _write(plugin_dir / "marketplace.json", json.dumps({
        "name": "ai-badger", "owner": {"name": "a", "url": "u"},
        "metadata": {"description": "d"},
        "plugins": [{"name": "ai-badger", "source": "./", "description": "d",
                     "version": declared, "license": "MIT", "keywords": []}],
    }))
    return _run([str(ROOT / "tooling" / "version_sync.py"), "--root", str(root), "--check"])


def _sync_plugin_skills_check(work: Path, provoked: bool) -> Outcome:
    """A shipped skill copy whose content diverged from the catalog it mirrors.

    The gate has no --root: it anchors on its own location, so the fixture is a miniature
    framework tree with the two files the check needs copied into it. The skill is
    `prompt-markers` rather than `task` because `task` is the one skill with a
    `PLUGIN_EXTRA_FILES` declaration, which a tree this small cannot satisfy — and the
    divergence this provocation is about has nothing to do with that declaration.
    """
    root = work / "framework"
    shutil.copytree(ROOT / "engine", root / "engine",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / "tooling").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tooling" / "sync_plugin_skills.py",
                 root / "tooling" / "sync_plugin_skills.py")
    catalog = "---\nname: prompt-markers\nscope: default\n---\n# prompt-markers\ncatalog\n"
    _write(root / "features" / "common" / "skills" / "prompt-markers" / "SKILL.md", catalog)
    built = _run([str(root / "tooling" / "sync_plugin_skills.py")])
    assert built.exit_code == 0, f"fixture setup failed:\n{built.output}"
    if provoked:
        shipped = root / "skills" / "prompt-markers" / "SKILL.md"
        shipped.write_text(shipped.read_text(encoding="utf-8") + "\nSHIPPED COPY, DIVERGED\n",
                           encoding="utf-8")
    return _run([str(root / "tooling" / "sync_plugin_skills.py"), "--check"])


def _changelog_index_check(work: Path, provoked: bool) -> Outcome:
    """A changelog entry added after the index table in the README was generated (issue #160)."""
    root = work / "tree"
    directory = root / "docs" / "changelog"
    _write(directory / "README.md",
           "# Changelog\n\n<!-- changelog-index:start -->\n<!-- changelog-index:end -->\n")
    _write(directory / "0.1.0-first.md", "# 0.1.0 — first\n")
    built = _run([str(ROOT / "tooling" / "changelog_index.py"), "--root", str(root)])
    assert built.exit_code == 0, f"fixture setup failed:\n{built.output}"

    if provoked:
        _write(directory / "0.1.0-second.md", "# 0.1.0 — second\n")
    return _run([str(ROOT / "tooling" / "changelog_index.py"), "--root", str(root), "--check"])


# ----------------------------------------------- tooling/validate.py --all (five sub-checks)

# Loaded for HOOK_CAPABLE_AGENTS: spelling the agent names here would let the tuple grow
# without the fixture growing with it, and a manifest naming every agent would stop meaning it.
VALIDATE = _load("tooling/validate.py")

CLEAN_SKILL = """---
name: demo-skill
description: >-
  Use when the meta-gate needs a lint-clean skill to stand in for the catalog.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [meta]
    related_skills: []
---
# Demo skill

One paragraph, nothing for the lint to report.

## Gotchas

No environment-specific gotchas known.
"""


def _hooks_manifest(root: Path, agents) -> Path:
    """One hook entry naming `agents`, in the shape hooks-manifest.schema.json requires."""
    return _write(root / "features" / "demo" / "hooks" / "hooks-manifest.json", json.dumps({
        "hooks": [{"name": "demo-hook", "description": "a hook", "agents": {
            agent: {"type": "hooks-json", "entry": "hooks.json", "event": "SessionStart",
                    "script": "demo_hook.py"} for agent in agents}}],
    }))


def _validate_tree(work: Path, manifest: bool = True, skill: str = CLEAN_SKILL) -> Path:
    """A miniature framework tree `validate.py --all` passes clean.

    Real schemas, a hooks manifest reaching every hook-capable agent, one lint-clean skill —
    every sub-check gets something to say `ok` about, so a provocation is the only reason to fail.
    """
    root = work / "framework"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "schemas", root / "schemas")
    if manifest:
        _hooks_manifest(root, VALIDATE.HOOK_CAPABLE_AGENTS)
    _write(root / "features" / "demo" / "skills" / "demo-skill" / "SKILL.md", skill)
    return root


def _validate_all(root: Path) -> Outcome:
    return _run([str(ROOT / "tooling" / "validate.py"), "--all", "--root", str(root)])


def _validate_all_schema_not_self_valid(work: Path, provoked: bool) -> Outcome:
    """A shipped schema that is not itself a valid Draft 2020-12 schema."""
    root = _validate_tree(work)
    if provoked:
        _write(root / "schemas" / "config.schema.json", json.dumps({"type": "not-a-json-type"}))
    return _validate_all(root)


def _validate_all_undecided_schema(work: Path, provoked: bool) -> Outcome:
    """A schema SCHEMA_INSTANCES and the exemption list both ignore — it validates nothing."""
    root = _validate_tree(work)
    if provoked:
        _write(root / "schemas" / "orphan.schema.json", json.dumps({"type": "object"}))
    return _validate_all(root)


def _validate_all_instance_fails_its_schema(work: Path, provoked: bool) -> Outcome:
    """A catalog file that does not match the schema its glob maps it to."""
    root = _validate_tree(work)
    stack = {"nope": True} if provoked else {"name": "demo", "description": "a demo stack"}
    _write(root / "features" / "demo" / "stack.json", json.dumps(stack))
    return _validate_all(root)


def _validate_all_hook_agent_gap(work: Path, provoked: bool) -> Outcome:
    """A hook naming one agent, with no recorded exemption for the others (issue #147)."""
    agents = VALIDATE.HOOK_CAPABLE_AGENTS
    root = _validate_tree(work, manifest=False)
    _hooks_manifest(root, agents[:1] if provoked else agents)
    return _validate_all(root)


def _validate_all_no_hooks_manifest(work: Path, provoked: bool) -> Outcome:
    """A tree whose manifest glob matches nothing — the check ran against no input at all."""
    return _validate_all(_validate_tree(work, manifest=not provoked))


def _validate_all_skills_lint_violation(work: Path, provoked: bool) -> Outcome:
    """A SKILL.md whose frontmatter name breaks the name grammar.

    Kept after the lint moved to gates/: CI runs `validate.py --all` and nothing else, so this
    is what proves the delegation is still wired (the review's D4).
    """
    skill = CLEAN_SKILL.replace("name: demo-skill", "name: Demo-Skill") if provoked \
        else CLEAN_SKILL
    return _validate_all(_validate_tree(work, skill=skill))


def _skills_lint_violation(work: Path, provoked: bool) -> Outcome:
    """The same broken name, run through the gate itself rather than through validate.py."""
    skill = CLEAN_SKILL.replace("name: demo-skill", "name: Demo-Skill") if provoked \
        else CLEAN_SKILL
    root = _validate_tree(work, skill=skill)
    return _run([str(ROOT / "gates" / "skills_lint.py"), "--root", str(root)])


# ------------------------------------------------------- call-behaviorist analyze findings


def _record(component: str, event: str = "start", version: str = "0.39.0",
            project: str = "", ts: str = "2026-07-27T09:00:00+00:00") -> Dict[str, str]:
    return {
        DL.KEY_TS: ts,
        DL.KEY_COMPONENT: component,
        DL.KEY_EVENT: event,
        DL.KEY_VERSION: version,
        DL.KEY_PROJECT: project,
    }


def _analyze(work: Path, project: Path, records: List[Dict[str, str]]) -> Outcome:
    """Run `behaviorist analyze --json` against a throwaway audit log and project."""
    debug = work / "debug"
    debug.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r) + "\n" for r in records)
    (debug / "audit.jsonl").write_text(lines, encoding="utf-8")

    home = work / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({DL.DEBUG_DIR_ENV: str(debug), "HOME": str(home), "USERPROFILE": str(home)})

    outcome = _run([str(ROOT / BEHAVIORIST), "analyze", "--project", str(project), "--json"],
                   env=env)
    assert outcome.exit_code == 0, f"analyze itself failed:\n{outcome.output}"
    report = json.loads(outcome.output)
    return outcome._replace(findings=tuple(report["findings"]))


def _wire(project: Path, relpath: str, body: str) -> Path:
    """Register a hook script in the project's .claude/settings.json, as Claude Code reads it."""
    _write(project / relpath, body)
    _write(project / ".claude" / "settings.json", json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command",
                    "command": f'python3 "${{CLAUDE_PROJECT_DIR}}/{relpath}"'}]}]}}))
    return project


QUIET_HOOK = "print('this hook calls no logger')\n"
LOUD_HOOK = 'import debug_log\ndebug_log.log_event("noisy_hook", "start")\n'
WIRED = "hooks/noisy_hook.py"
COMPONENT = "noisy_hook"


def _unwired_project(work: Path) -> Path:
    """A project directory wiring no hooks: the findings below are about records alone."""
    project = work / "proj"
    project.mkdir(parents=True, exist_ok=True)
    return project


def _not_instrumented(work: Path, provoked: bool) -> Outcome:
    """A wired hook that calls no debug logger — the 0.34.0 always-this-answer finding."""
    project = _wire(work / "proj", WIRED, QUIET_HOOK if provoked else LOUD_HOOK)
    # Clean: the same hook, instrumented and observed. Provoked: silent, and its silence is
    # only reportable because the script cannot log at all.
    observed = [] if provoked else [_record(COMPONENT, project=str(project))]
    return _analyze(work, project, observed)


def _never_observed(work: Path, provoked: bool) -> Outcome:
    """A wired, instrumented hook that produced no record while others did."""
    project = _wire(work / "proj", WIRED, LOUD_HOOK)
    silent = "some_other_hook" if provoked else COMPONENT
    return _analyze(work, project, [_record(silent, project=str(project))])


def _unexpected_component(work: Path, provoked: bool) -> Outcome:
    """Records from a component this project does not wire."""
    project = _wire(work / "proj", WIRED, LOUD_HOOK)
    stranger = "a_stranger" if provoked else COMPONENT
    return _analyze(work, project, [_record(stranger, project=str(project))])


def _version_skew(work: Path, provoked: bool) -> Outcome:
    """Two copies of one component live at once — their observed ranges overlap."""
    project = _unwired_project(work)
    interleaved = "0.39.0" if provoked else "0.38.0"
    return _analyze(work, project, [
        _record("two_copies", version="0.38.0", ts="2026-07-27T09:00:00+00:00",
                project=str(project)),
        _record("two_copies", version=interleaved, ts="2026-07-27T09:05:00+00:00",
                project=str(project)),
        _record("two_copies", version="0.38.0", ts="2026-07-27T09:10:00+00:00",
                project=str(project)),
    ])


def _version_progression(work: Path, provoked: bool) -> Outcome:
    """One component upgraded through disjoint version spans — reported as context, not fault."""
    project = _unwired_project(work)
    later = "0.39.0" if provoked else "0.38.0"
    return _analyze(work, project, [
        _record("upgraded", version="0.38.0", ts="2026-07-27T09:00:00+00:00",
                project=str(project)),
        _record("upgraded", version="0.38.0", ts="2026-07-27T09:01:00+00:00",
                project=str(project)),
        _record("upgraded", version=later, ts="2026-07-27T10:00:00+00:00",
                project=str(project)),
        _record("upgraded", version=later, ts="2026-07-27T10:01:00+00:00",
                project=str(project)),
    ])


def _version_unresolvable(work: Path, provoked: bool) -> Outcome:
    """Records whose copy could name no version at all."""
    project = _unwired_project(work)
    version = DL.VERSION_UNKNOWN if provoked else "0.39.0"
    return _analyze(work, project, [_record("nameless", version=version,
                                            project=str(project))])


def _always_skipped(work: Path, provoked: bool) -> Outcome:
    """A component that fires and exits early every single time — live but doing nothing."""
    project = _unwired_project(work)
    second = "skip" if provoked else "done"
    return _analyze(work, project, [
        _record("idle_hook", event="start", project=str(project)),
        _record("idle_hook", event="skip", project=str(project)),
        _record("idle_hook", event="start", ts="2026-07-27T09:01:00+00:00",
                project=str(project)),
        _record("idle_hook", event=second, ts="2026-07-27T09:01:01+00:00",
                project=str(project)),
    ])


# --------------------------------------------------------------------------- workflow_lint

_WORKFLOW = """name: ci
{permissions}jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{ref}
"""
_SCOPED = "permissions:\n  contents: read\n"


def _workflow(workspace: Path, ref: str, permissions: str) -> Outcome:
    _write(workspace / ".github" / "workflows" / "ci.yml",
           _WORKFLOW.format(ref=ref, permissions=permissions))
    return _run_gate("gates/workflow_lint.py", "--root", str(workspace))


def _workflow_lint_unpinned(workspace: Path, provoked: bool) -> Outcome:
    return _workflow(workspace, "v4" if provoked else "0" * 40, _SCOPED)


def _workflow_lint_default_token_scope(workspace: Path, provoked: bool) -> Outcome:
    return _workflow(workspace, "0" * 40, "" if provoked else _SCOPED)


def _behaviorist(kind: str) -> str:
    return f"{BEHAVIORIST}::{kind}"


REGISTRY: Tuple[Provocation, ...] = (
    Provocation("gates/release_guard.py", "shipped surface changed, VERSION not bumped",
                _release_guard_no_bump, Signal(exit_code=1, contains="bump VERSION")),
    Provocation("gates/release_guard.py", "a documented release between the tag and VERSION",
                _release_guard_untagged_release,
                Signal(exit_code=1, contains="UNTAGGED RELEASES")),
    Provocation("gates/release_guard.py", "a tree git cannot answer for",
                _release_guard_git_unavailable,
                Signal(exit_code=1, contains="GIT COMMAND FAILED")),
    Provocation("gates/docs_guard.py", "a relative link to a file that does not exist",
                _docs_guard_broken_link, Signal(exit_code=1, contains="broken link")),
    Provocation("gates/docs_guard.py", "a backticked repo path naming nothing in the tree",
                _docs_guard_missing_repo_path, Signal(exit_code=1, contains="missing path")),
    Provocation("gates/docs_guard.py", "a changelog entry absent from the index",
                _docs_guard_unindexed_changelog,
                Signal(exit_code=1, contains="no row in docs/changelog/README.md")),
    Provocation("gates/deps_guard.py", "an import no requirements file declares",
                _deps_guard, Signal(exit_code=1, contains="undeclared third-party import")),
    Provocation("gates/shipped_paths_guard.py", "a tracked file carrying a real machine path",
                _shipped_paths_guard,
                Signal(exit_code=1, contains="machine-specific absolute path")),
    Provocation("gates/scaffold_freshness_guard.py",
                "a skill source that gained a file, with no re-scaffold",
                _scaffold_freshness_guard,
                Signal(exit_code=1, contains="SCAFFOLD FRESHNESS GUARD FAILED")),
    Provocation("gates/tdd_guard.py", "shipped code changed with no test change",
                _tdd_guard, Signal(exit_code=1, contains="Write the failing test first")),
    Provocation("tooling/index_build.py --check", "a feature added after index.json was built",
                _index_build_check, Signal(exit_code=1, contains="stale")),
    Provocation("tooling/version_sync.py --check", "plugin.json pinned to a foreign version",
                _version_sync_check, Signal(exit_code=1, contains="disagree with VERSION")),
    Provocation("tooling/sync_plugin_skills.py --check", "a shipped skill copy that diverged",
                _sync_plugin_skills_check, Signal(exit_code=1, contains="diverged")),
    Provocation("tooling/changelog_index.py --check", "an entry added after the index was built",
                _changelog_index_check, Signal(exit_code=1, contains="stale")),
    Provocation("tooling/validate.py --all", "a shipped schema that is not a valid schema",
                _validate_all_schema_not_self_valid,
                Signal(exit_code=1, contains="INVALID  schemas self-check")),
    Provocation("tooling/validate.py --all", "a schema no glob points any instance at",
                _validate_all_undecided_schema,
                Signal(exit_code=1, contains="validates nothing")),
    Provocation("tooling/validate.py --all", "a catalog file that fails its own schema",
                _validate_all_instance_fails_its_schema,
                Signal(exit_code=1, contains="INVALID  features/demo/stack.json")),
    Provocation("tooling/validate.py --all", "a hook reaching one agent, nothing said about "
                                             "the rest",
                _validate_all_hook_agent_gap,
                Signal(exit_code=1, contains="no recorded exemption")),
    Provocation("tooling/validate.py --all", "a tree whose hooks-manifest glob matches nothing",
                _validate_all_no_hooks_manifest,
                Signal(exit_code=1, contains="matched no file")),
    Provocation("tooling/validate.py --all", "a SKILL.md that breaks the name grammar",
                _validate_all_skills_lint_violation, Signal(exit_code=1, contains="rule 1")),
    Provocation("gates/skills_lint.py", "a SKILL.md that breaks the name grammar",
                _skills_lint_violation,
                Signal(exit_code=1, contains="SKILLS LINT FAILED")),
    Provocation("gates/workflow_lint.py", "an action pinned to a tag instead of a commit",
                _workflow_lint_unpinned,
                Signal(exit_code=1, contains="not pinned to a 40-character commit SHA")),
    Provocation("gates/workflow_lint.py", "a job running on the default token scope",
                _workflow_lint_default_token_scope,
                Signal(exit_code=1, contains="default token scope")),
    Provocation(_behaviorist("not_instrumented"), "a wired hook that calls no logger",
                _not_instrumented, _finding("not_instrumented", "low")),
    Provocation(_behaviorist("never_observed"), "an instrumented hook that never logged",
                _never_observed, _finding("never_observed", "high")),
    Provocation(_behaviorist("unexpected_component"), "records from an unwired component",
                _unexpected_component, _finding("unexpected_component", "low")),
    Provocation(_behaviorist("version_skew"), "two copies live at once, ranges overlapping",
                _version_skew, _finding("version_skew", "high")),
    Provocation(_behaviorist("version_progression"), "one component upgraded, spans disjoint",
                _version_progression, _finding("version_progression", "info")),
    Provocation(_behaviorist("version_unresolvable"), "records that could name no version",
                _version_unresolvable, _finding("version_unresolvable", "low")),
    Provocation(_behaviorist("always_skipped"), "a component that exits early every time",
                _always_skipped, _finding("always_skipped", "medium")),
)

# ------------------------------------------------------------------------------- discovery


MIRROR_ROOTS = (".ai-badger/", ".claude/", "skills/", "tests/")


def _tracked_sources(root: Path) -> List[str]:
    """Tracked `*.py` we author: mirrors of features/ are copies, and tests are not checks."""
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=str(root), capture_output=True,
                         text=True, check=True).stdout
    return sorted(p for p in out.splitlines()
                  if p.strip() and not p.startswith(MIRROR_ROOTS))


def _declares_check_flag(text: str) -> bool:
    """True when a script exposes a `--check` verification mode on its CLI."""
    return 'add_argument("--check"' in text


def _declares_all_flag(text: str) -> bool:
    """True when a script exposes an `--all` whole-tree verification mode on its CLI.

    validate.py --all is the largest check this repo runs — five sub-checks, wired into CI —
    and it spells its flag `--all`, so a discovery predicate that only knew `--check` never saw
    it (the 2026-08-07 review's A4).
    """
    return 'add_argument("--all"' in text


def _defines_compare(text: str, path: str) -> bool:
    """True when a module defines a top-level `compare()` — a comparison is a check."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:  # pragma: no cover - a broken file is another gate's problem
        return False
    return any(isinstance(node, ast.FunctionDef) and node.name == "compare"
               for node in tree.body)


def _runs_as_a_script(text: str, path: str) -> bool:
    """True when a module has a top-level `if __name__ == ...` block — what makes it runnable.

    Not "defines a top-level `main()`": that spelling is a convention, and a gate whose entry
    point is named anything else was invisible to discovery *and* to the oracle below at once,
    because the oracle only globbed `*_guard.py`. `gates/skills_lint.py` already proves neither
    half of that convention is load-bearing.
    """
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:  # pragma: no cover - a broken file is another gate's problem
        return False
    return any(isinstance(node, ast.If)
               and any(isinstance(sub, ast.Name) and sub.id == "__name__"
                       for sub in ast.walk(node.test))
               for node in tree.body)


def _finding_kinds(text: str, path: str) -> List[str]:
    """Every finding kind `_finding(...)` can emit, read from its first argument."""
    kinds = []
    for node in ast.walk(ast.parse(text, filename=path)):
        if not isinstance(node, ast.Call) or getattr(node.func, "id", "") != "_finding":
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            kinds.append(first.value)
    return kinds


def discovered_checks(root: Path) -> Dict[str, str]:
    """Every check in this repo, keyed by id, valued by how it was found.

    Mechanical on purpose: a new gate, a new `--check` or `--all` mode, a new `compare()` or a
    new behaviorist finding kind lands in here without anyone remembering to add it.
    """
    found: Dict[str, str] = {}
    for gate in sorted((root / "gates").glob("*.py")):
        # A runnable script, not a shared helper: gate_report.py holds the finding shape three
        # gates print and has no verdict of its own, so it can have no provocation.
        if _runs_as_a_script(gate.read_text(encoding="utf-8", errors="replace"), gate.name):
            found[f"gates/{gate.name}"] = "a script in gates/"
    for rel in _tracked_sources(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if _declares_check_flag(text):
            found[f"{rel} --check"] = "declares a --check mode"
        if _declares_all_flag(text):
            found[f"{rel} --all"] = "declares an --all mode"
        if _defines_compare(text, rel):
            found[f"{rel}::compare"] = "defines a top-level compare()"
    behaviorist = (root / BEHAVIORIST).read_text(encoding="utf-8")
    for kind in _finding_kinds(behaviorist, BEHAVIORIST):
        found[f"{BEHAVIORIST}::{kind}"] = "a finding kind behaviorist analyze can emit"
    return found


# ----------------------------------------------------------------------------- the meta-test


_IDS = [f"{p.check} | {p.label}" for p in REGISTRY]


@pytest.mark.parametrize("provocation", REGISTRY, ids=_IDS)
def test_check_fails_when_provoked(provocation, tmp_path):
    """A check that passes its own known-bad state is the bug this module exists to catch."""
    outcome = provocation.run(tmp_path, True)

    unmet = provocation.signal.unmet(outcome)
    assert not unmet, (
        f"{provocation.check} did not fail on: {provocation.label}\n"
        f"  {unmet}\n"
        f"  exit {outcome.exit_code}\n"
        f"  output:\n{outcome.output}"
    )


@pytest.mark.parametrize("provocation", REGISTRY, ids=_IDS)
def test_check_holds_its_verdict_on_the_same_fixture_without_the_defect(provocation, tmp_path):
    """The other answer. A provocation whose fixture fails clean too proves nothing."""
    outcome = provocation.run(tmp_path, False)

    if provocation.signal.exit_code is not None:
        assert outcome.exit_code == 0, (
            f"{provocation.check} neither passed nor failed the clean fixture "
            f"(exit {outcome.exit_code}):\n{outcome.output}"
        )
    assert provocation.signal.unmet(outcome), (
        f"{provocation.check} reported the same failure with the defect removed, so its "
        f"provocation ({provocation.label}) proves nothing\n"
        f"  exit {outcome.exit_code}\n"
        f"  output:\n{outcome.output}"
    )


def test_every_check_has_a_provocation(root):
    """A guard with no proven failure path is a guard nobody has shown can fail."""
    registered = {p.check for p in REGISTRY}
    unproven = sorted(check for check in discovered_checks(root)
                      if check not in registered and check not in EXEMPTIONS)

    assert not unproven, (
        "these checks have no provocation and no exemption — add one to REGISTRY, "
        f"or an entry with a reason to EXEMPTIONS: {unproven}"
    )


def test_discovery_agrees_with_the_shebang_on_which_gates_are_runnable(root):
    """Two independent signals of "this file is a CLI" must name the same gates.

    The old oracle globbed `*_guard.py` while discovery asked for a top-level `main()`, so a
    runnable gate that satisfied neither convention — a real shape, `gates/skills_lint.py` is
    one — was skipped by both at once and demanded no provocation. A shebang is what an author
    writes on a script and omits on a helper module, and it is independent of the AST predicate.
    """
    discovered = discovered_checks(root)
    gates = sorted((root / "gates").glob("*.py"))

    assert gates, "no gates found — the glob is wrong, not the tree"
    disagree = [f"{gate.name}: shebang={shipped_as_a_cli}, discovered={proven}"
                for gate in gates
                for shipped_as_a_cli in [gate.read_text(encoding="utf-8").startswith("#!")]
                for proven in [f"gates/{gate.name}" in discovered]
                if shipped_as_a_cli != proven]
    assert not disagree, (
        "a gate's shebang and its discoverability disagree — one of the two is lying about "
        f"whether it runs: {disagree}")
    assert "gates/skills_lint.py" in discovered, \
        "the one gate not named *_guard.py is exactly the one a convention-shaped filter drops"


# ------------------------------------------------------------------------------- dispatch

_LANES_RE = re.compile(r'^readonly LANES="([^"]*)"', re.M)
_FUNCTION_RE = re.compile(r"^(lane_[a-z_]+)\(\) \{$(.*?)^\}$", re.M | re.S)
_ARM_RE = re.compile(r"^ {8}([a-z|-]+)\)(.*?);;\s*$", re.M)
_SCRIPT_RE = re.compile(r"(?:gates|tooling)/[A-Za-z0-9_]+\.py")


def _uncommented(text: str) -> str:
    """`text` without its comment lines — a script named only in prose is not dispatched."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def scripts_a_lane_runs(verify_sh: str) -> Dict[str, str]:
    """Every gates/ or tooling/ script a lane in `$LANES` runs, keyed by path, valued by lane.

    Reads the dispatch, not the file: `mutation` has a `lane_cmd` arm and is deliberately not in
    `$LANES`, so a gate only it ran would never run on a push.
    """
    functions = dict(_FUNCTION_RE.findall(verify_sh))
    arms = dict(_ARM_RE.findall(_uncommented(functions.get("lane_cmd", ""))))
    found: Dict[str, str] = {}
    for lane in _LANES_RE.search(verify_sh).group(1).split():
        pending, seen = [arms.get(lane, "")], set()
        while pending:
            chunk = pending.pop()
            for script in _SCRIPT_RE.findall(chunk):
                found.setdefault(script, lane)
            for name in re.findall(r"\blane_[a-z_]+\b", chunk):
                if name in functions and name not in seen:
                    seen.add(name)
                    pending.append(_uncommented(functions[name]))
    return found


def _imported_modules(text: str, path: str) -> List[str]:
    """Top-level module names `text` imports, either spelling."""
    names = []
    for node in ast.walk(ast.parse(text, filename=path)):
        if isinstance(node, ast.Import):
            names += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return names


def dispatched_gates(root: Path) -> Dict[str, str]:
    """Every gate a lane runs, directly or through a tooling script a lane runs.

    The indirect hop is load-bearing: `gates/skills_lint.py` runs on every push as an import
    inside `tooling/validate.py --all`, and its filename appears nowhere in verify.sh.
    """
    scripts = scripts_a_lane_runs((root / VERIFY).read_text(encoding="utf-8"))
    found = {path: lane for path, lane in scripts.items() if path.startswith("gates/")}
    for path, lane in sorted(scripts.items()):
        if path.startswith("gates/") or not (root / path).is_file():
            continue
        for module in _imported_modules((root / path).read_text(encoding="utf-8"), path):
            if (root / "gates" / f"{module}.py").is_file():
                found.setdefault(f"gates/{module}.py", f"{lane} (imported by {path})")
    return found


def test_every_gate_is_dispatched_by_a_lane(root):
    """A gate no lane runs is proven able to fail and unable to fail anything."""
    dispatched = dispatched_gates(root)
    gates = sorted(check for check in discovered_checks(root) if check.startswith("gates/"))

    assert gates, "no gates discovered — the discovery is wrong, not the tree"
    assert dispatched, f"read no gate at all out of {VERIFY} — the dispatch parse is broken"
    orphans = [gate for gate in gates if gate not in dispatched]
    assert not orphans, (
        f"these gates are in gates/ and in no lane of {VERIFY}, so no push runs them: {orphans}")


def test_dispatch_reading_ignores_a_lane_that_is_not_in_lanes():
    """`mutation` is the live example: dispatchable by hand, in no lane, run by no push."""
    text = ('readonly LANES="wired"\n'
            'lane_cmd() {\n    case "$1" in\n'
            '        wired)     "$PY" gates/wired.py ;;\n'
            '        by-hand)   "$PY" gates/by_hand.py ;;\n'
            '    esac\n}\n')

    assert scripts_a_lane_runs(text) == {"gates/wired.py": "wired"}


def test_dispatch_reading_follows_a_lane_helper_and_skips_a_comment():
    """docs and tdd reach their gates through a `lane_*` helper, not from the arm itself."""
    text = ('readonly LANES="docs"\n'
            'lane_docs() {\n'
            '    # gates/mentioned.py is named here and run nowhere\n'
            '    "$PY" gates/real.py\n}\n'
            'lane_cmd() {\n    case "$1" in\n'
            '        docs)  lane_docs ;;\n'
            '    esac\n}\n')

    assert scripts_a_lane_runs(text) == {"gates/real.py": "docs"}


def test_the_indirect_hop_is_what_covers_skills_lint(root):
    """The one gate no lane names: if the hop ever stops finding it, the test above went blind."""
    assert "gates/skills_lint.py" not in scripts_a_lane_runs(
        (root / VERIFY).read_text(encoding="utf-8"))
    assert "tooling/validate.py" in dispatched_gates(root)["gates/skills_lint.py"]


def test_registry_names_only_checks_that_exist(root):
    """A provocation for a check that is gone proves nothing about the tree as it is."""
    discovered = discovered_checks(root)
    phantom = sorted({p.check for p in REGISTRY} - set(discovered))

    assert not phantom, f"REGISTRY names checks discovery cannot find: {phantom}"


def test_exemptions_are_named_debts(root):
    """Each exemption must name a live check and say why it is not covered yet."""
    discovered = discovered_checks(root)
    registered = {p.check for p in REGISTRY}
    for check, reason in EXEMPTIONS.items():
        assert check in discovered, f"stale exemption, no such check any more: {check}"
        assert check not in registered, f"{check} has a provocation — drop the exemption"
        assert reason.strip(), f"exemption without a reason: {check}"


def test_both_historical_release_guard_failures_are_provoked():
    """0.21.0 and 0.35.3 were different degeneracies of the same gate; both stay proven."""
    labels = [p.label for p in REGISTRY if p.check == "gates/release_guard.py"]

    assert len(labels) >= 2, f"release_guard needs both provocations, has: {labels}"


def test_every_workflow_running_a_gate_checks_out_deep_enough(root):
    """F-11's relapse surface: `fetch-depth: 1` fetches no tags, so release_guard finds none.

    With no tag it takes its documented always-pass path and the gate becomes a silent
    no-op — the exact shape this module exists to catch, one layer out in the workflow.
    """
    offenders = []
    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if "release_guard.py" not in text:
            continue
        # A real key, not a mention: the comment above this very setting explains the hazard
        # by naming `fetch-depth: 1`, and a substring search reads that as the answer.
        settings = [line.split("#", 1)[0].strip() for line in text.splitlines()]
        if "fetch-depth: 0" not in settings:
            offenders.append(f"{workflow.name} runs release_guard.py without fetch-depth: 0")
    assert not offenders, "\n".join(offenders)