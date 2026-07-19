#!/usr/bin/env python3
"""Best-effort detection of a target repo's stacks, agents, source control, and commands.

Emits a PROPOSED config.json to stdout for the agent to refine (the agent resolves
ambiguity and fills project.summary/domain + persona routing, then validates). MECHANICAL:
no LLM. Network is used only for `git remote` (local git), which is optional.

Usage: detect.py [--target <dir>] [--root <framework>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        if (anc / "scripts" / "badger_lib.py").exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    raise RuntimeError("could not locate ai-badger scripts/badger_lib.py")


_bootstrap_lib()
import badger_lib as bl


# vendored / build / agent-tooling directories whose contents must not trigger stack detection.
# `.claude` holds agent tooling (e.g. the task skill's Python hook scripts), and `.ai-badger`
# holds the framework's own scaffolded output (e.g. .ai-badger/skills/task/scripts/) written by
# scaffold.py — both are framework machinery, not the target project's stack, so neither must
# ever propose a stack like `python`. `.ai-badger` matters especially here: without it, detect.py
# would re-propose `python` from ai-badger's own output after every scaffold, a self-inflicted
# false positive that gets worse on every re-scaffold.
_IGNORE_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".terraform", "dist",
                ".claude", ".ai-badger"}


def _has(target: Path, *globs: str) -> bool:
    """True if any glob matches a path under `target`, ignoring vendored/build dirs."""
    for g in globs:
        for p in target.rglob(g):
            if not any(part in _IGNORE_DIRS for part in p.relative_to(target).parts):
                return True
    return False


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _signal_globs(signals: List[str]) -> List[str]:
    """Keep only machine-matchable path/glob signals; prose signals (deps, usage) contain spaces."""
    return [s for s in signals if s and " " not in s]


def _dependency_stacks(target: Path) -> List[str]:
    """Stacks whose detectionSignals are dependency/content facts a file glob can't express
    (package.json deps, `.csproj` package references)."""
    found: List[str] = []
    pkg_json: Dict = {}
    pkg_text = _read(target / "package.json")
    if pkg_text:
        try:
            pkg_json = json.loads(pkg_text)
        except json.JSONDecodeError:
            pkg_json = {}
    deps: Dict = {}
    deps.update(pkg_json.get("dependencies", {}))
    deps.update(pkg_json.get("devDependencies", {}))
    if "typescript" in deps:
        found.append("ts")
    if "react" in deps:
        found.append("react")
    if any(d.startswith("@angular/") for d in deps) or (target / "angular.json").exists():
        found.append("angular")
    if "azure" in " ".join(deps).lower():
        found.append("azure")
    if "@azure/cosmos" in deps or any("cosmos" in _read(p).lower()
                                      for p in target.rglob("*.csproj")):
        found.append("cosmos")
    return found


def detect_stacks(target: Path, index: Dict) -> List[str]:
    """Detect stacks from each stack's `detectionSignals` (data-driven, read from the index),
    plus dependency/content heuristics that prose signals can't express. A new stack needs no
    change here: give its stack.json file/glob detectionSignals and it is detected automatically."""
    stacks: List[str] = []
    for stack, data in index.get("stacks", {}).items():
        if stack == "common":
            continue
        globs = _signal_globs(data.get("meta", {}).get("detectionSignals", []))
        if globs and _has(target, *globs):
            stacks.append(stack)
    stacks.extend(_dependency_stacks(target))
    # de-dupe preserving order
    seen: set = set()
    return [s for s in stacks if not (s in seen or seen.add(s))]


def expand_requires(stacks: List[str], index: Dict) -> List[str]:
    """Transitively add each detected stack's declared `requires` (from stack.json meta)."""
    out = list(stacks)
    changed = True
    while changed:
        changed = False
        for s in list(out):
            meta = index.get("stacks", {}).get(s, {}).get("meta", {})
            for req in meta.get("requires", []):
                if req not in out:
                    out.append(req)
                    changed = True
    return out


def detect_agents(target: Path) -> List[str]:
    """Detect which coding agents (claude/copilot/junie) this repo already has traces of."""
    home = Path.home()
    agents: List[str] = []
    if (target / "CLAUDE.md").exists() or (home / ".claude").exists():
        agents.append("claude")
    if ((target / ".github" / "copilot-instructions.md").exists()
            or (target / ".github" / "instructions").is_dir()
            or (target / "COPILOT_INSTRUCTIONS.md").exists()
            or (home / ".copilot").exists()):
        agents.append("copilot")
    if (target / ".junie").is_dir() or (target / "AGENTS.md").exists():
        agents.append("junie")
    return agents or ["claude"]


def detect_source_control(target: Path) -> Dict:
    """Detect the git remote's hosting platform and normalize its URL."""
    sc: Dict = {"platform": "none", "repoUrl": None, "projectUrl": None}
    if not (target / ".git").exists():
        return sc
    try:
        url = subprocess.run(["git", "-C", str(target), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10, check=False).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        url = ""
    if not url:
        return sc
    low = url.lower()
    if "github.com" in low:
        sc["platform"] = "github"
    elif "gitlab" in low:
        sc["platform"] = "gitlab"
    elif "dev.azure.com" in low or "visualstudio.com" in low:
        sc["platform"] = "azure-devops"
    # normalize git@ / .git → https URL
    web = url
    if web.startswith("git@"):
        web = "https://" + web[4:].replace(":", "/", 1)
    if web.endswith(".git"):
        web = web[:-4]
    sc["repoUrl"] = web
    return sc


def detect_commands(target: Path, stacks: List[str]) -> Dict[str, str]:
    """Detect build/test/lint/run commands from package.json scripts (or dotnet defaults)."""
    cmds: Dict[str, str] = {}
    pkg = target / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(_read(pkg)).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        has_bun_lock = (target / "bun.lock").exists() or (target / "bun.lockb").exists()
        runner = "bun run" if has_bun_lock else "npm run"
        for key, names in (("build", ["build"]), ("test", ["test"]),
                           ("lint", ["lint"]), ("run", ["dev", "start"])):
            for n in names:
                if n in scripts:
                    cmds[key] = f"{runner} {n}"
                    break
    if "dotnet" in stacks:
        cmds.setdefault("build", "dotnet build")
        cmds.setdefault("test", "dotnet test")
    return cmds


def main(argv=None) -> int:
    """CLI entry point: emit a proposed config.json for `--target` to stdout."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=".")
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    target = Path(args.target).resolve()
    root = Path(args.root).resolve() if args.root else bl.find_root()
    index = bl.read_index(root)

    stacks = expand_requires(detect_stacks(target, index), index)
    # keep only stacks the framework actually knows about
    known = set(index.get("stacks", {}).keys())
    stacks = [s for s in stacks if s in known] or stacks

    proposed = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": index["frameworkVersion"],
        "project": {"name": target.name, "summary": "", "domain": ""},
        "stacks": stacks,
        "agents": detect_agents(target),
        "sourceControl": detect_source_control(target),
        "commands": detect_commands(target, stacks),
        "personaRouting": [],
        "pluginScope": "default",
        "docs": {},
    }
    print(json.dumps(proposed, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
