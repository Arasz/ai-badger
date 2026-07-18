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
from typing import Dict, List, Optional

def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        if (anc / "scripts" / "badger_lib.py").exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    raise RuntimeError("could not locate ai-badger scripts/badger_lib.py")


_bootstrap_lib()
import badger_lib as bl


def _has(target: Path, *globs: str) -> bool:
    return any(next(target.rglob(g), None) is not None for g in globs)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def detect_stacks(target: Path) -> List[str]:
    stacks: List[str] = []
    pkg = target / "package.json"
    pkg_text = _read(pkg)
    pkg_json: Dict = {}
    if pkg_text:
        try:
            pkg_json = json.loads(pkg_text)
        except json.JSONDecodeError:
            pkg_json = {}
    deps = {}
    deps.update(pkg_json.get("dependencies", {}))
    deps.update(pkg_json.get("devDependencies", {}))

    if pkg.exists():
        stacks.append("node")
    if "typescript" in deps or _has(target, "*.ts", "*.tsx") or (target / "tsconfig.json").exists():
        stacks.append("ts")
    if not any(s in stacks for s in ("ts",)) and _has(target, "*.js", "*.mjs"):
        stacks.append("js")
    if "react" in deps or _has(target, "*.tsx", "*.jsx"):
        stacks.append("react")
    if any(d.startswith("@angular/") for d in deps) or (target / "angular.json").exists():
        stacks.append("angular")
    if _has(target, "*.css", "*.scss"):
        stacks.append("css")
    if _has(target, "*.csproj", "*.sln"):
        stacks.append("dotnet")
    if _has(target, "*.tf"):
        stacks.append("terraform")
    if _has(target, "host.json", "*.bicep") or "azure" in " ".join(deps).lower():
        stacks.append("azure")
    # cosmos: only if referenced in a csproj
    if any("cosmos" in _read(p).lower() for p in target.rglob("*.csproj")):
        stacks.append("cosmos")

    # de-dupe preserving order
    seen = set()
    return [s for s in stacks if not (s in seen or seen.add(s))]


def expand_requires(stacks: List[str], index: Dict) -> List[str]:
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
    sc: Dict = {"platform": "none", "repoUrl": None, "projectUrl": None}
    if not (target / ".git").exists():
        return sc
    try:
        url = subprocess.run(["git", "-C", str(target), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
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
    cmds: Dict[str, str] = {}
    pkg = target / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(_read(pkg)).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        runner = "bun run" if (target / "bun.lock").exists() or (target / "bun.lockb").exists() else "npm run"
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=".")
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    target = Path(args.target).resolve()
    root = Path(args.root).resolve() if args.root else bl.find_root()
    index = bl.read_index(root)

    stacks = expand_requires(detect_stacks(target), index)
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
