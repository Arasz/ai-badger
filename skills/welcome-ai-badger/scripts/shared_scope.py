#!/usr/bin/env python3
"""Collect explicitly selected repositories into a shared ai-badger scope."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from scaffold import DEFAULT_SKILLS, FRAMEWORK_ROOT, Scaffolder
import badger_lib as bl


def read_object(path: Path) -> dict[str, Any]:
    """Read one JSON object, refusing malformed profiles."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def members(target: Path, names: list[str]) -> list[Path]:
    """Validate explicit, distinct repository roots inside the collection."""
    result: list[Path] = []
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"repository must be relative to collection: {name}")
        child = (target / relative).resolve()
        if child == target or not child.is_relative_to(target):
            raise ValueError(f"repository escapes collection or selects itself: {name}")
        if any(child == prior or child.is_relative_to(prior) or prior.is_relative_to(child)
               for prior in result):
            raise ValueError(f"duplicate or overlapping repository: {name}")
        if not (child / ".git").exists():
            raise ValueError(f"not a repository root: {child}")
        if (child / ".ai-badger").is_symlink():
            raise ValueError(f"shared child scaffold must be a real directory: {child}")
        result.append(child)
    return result


def collect(target: Path, names: list[str], root: Path, config_path: Path | None) -> None:
    """Recompute the parent stack union from its explicit membership."""
    selected = members(target, names)
    configs = [read_object(child / ".ai-badger" / "config.json") for child in selected]
    parent_path = config_path or target / ".ai-badger" / "config.json"
    if parent_path.exists():
        config = copy.deepcopy(read_object(parent_path))
    else:
        config = {"frameworkVersion": bl.read_index(root)["frameworkVersion"],
                  "project": {"name": target.name}, "agents": ["claude"],
                  "commands": {}, "personaRouting": [], "docs": {}}
    config["stacks"] = list(dict.fromkeys(stack for child in configs
                                         for stack in child["stacks"]))
    errors = bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))
    if errors:
        raise ValueError("invalid collection config: " + "; ".join(errors))
    Scaffolder(root, target, config, DEFAULT_SKILLS, install=False).run()


def main(argv: list[str] | None = None) -> int:
    """Run the explicit shared-scope command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--target", required=True)
    collect_parser.add_argument("--repo", action="append", required=True)
    collect_parser.add_argument("--config")
    collect_parser.add_argument("--root")
    args = parser.parse_args(argv)
    try:
        collect(Path(args.target).resolve(), args.repo,
                Path(args.root).resolve() if args.root else FRAMEWORK_ROOT,
                Path(args.config).resolve() if args.config else None)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"shared scope refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
