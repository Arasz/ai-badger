#!/usr/bin/env python3
"""Collect explicitly selected repositories into a shared ai-badger scope."""
from __future__ import annotations

import argparse
import copy
import json
import os
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


def merge(parent: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge objects recursively; an authored list replaces the inherited list."""
    result = copy.deepcopy(parent)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def descriptor(child: Path) -> dict[str, Any]:
    """Load authored child inputs, separate from the generated effective profile."""
    path = child / ".ai-badger" / "shared-scope.json"
    if path.exists():
        return read_object(path)
    config = read_object(child / ".ai-badger" / "config.json")
    return {"mode": "inherit", "localStacks": config["stacks"],
            "overrides": {key: value for key, value in config.items()
                          if key not in {"stacks", "frameworkVersion", "$schema"}}}


def validate_config(config: dict[str, Any], root: Path) -> None:
    """Validate an effective profile before scaffold writes."""
    errors = bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))
    if errors:
        raise ValueError("invalid shared config: " + "; ".join(errors))


def detach_links(child: Path, source: Path) -> None:
    """Turn only previously recorded parent links back into private files."""
    manifest_path = child / ".ai-badger" / "manifest.json"
    if not manifest_path.is_file():
        return
    links = read_object(manifest_path).get("sharedScope", {}).get("links", [])
    if not isinstance(links, list):
        raise ValueError("shared-scope link ledger must be a list")
    checked: list[tuple[Path, str]] = []
    root = child.resolve()
    parent = source.resolve()
    for entry in links:
        if not isinstance(entry, dict):
            raise ValueError("shared-scope link record must be an object")
        relative = Path(entry.get("path", ""))
        raw_target = entry.get("target")
        if (not relative.parts or relative.is_absolute() or ".." in relative.parts
                or not isinstance(raw_target, str) or not raw_target):
            raise ValueError("invalid shared-scope link record")
        destination = child / relative
        if not destination.absolute().is_relative_to(root):
            raise ValueError(f"shared-scope link escapes child: {relative}")
        cursor = destination.parent
        while cursor not in (child, cursor.parent):
            if cursor.is_symlink():
                raise ValueError(f"shared-scope link has a symlink ancestor: {relative}")
            cursor = cursor.parent
        canonical = (destination.parent / raw_target).resolve(strict=False)
        if not canonical.is_relative_to(parent) or str(canonical) != entry.get("source"):
            raise ValueError(f"shared-scope link target escapes its parent: {relative}")
        if destination.is_symlink():
            if os.readlink(destination) != raw_target:
                raise ValueError(f"shared-scope link was replaced: {relative}")
        elif destination.exists():
            raise ValueError(f"shared-scope link was replaced with a file: {relative}")
        checked.append((destination, raw_target))

    for destination, _raw_target in checked:
        if destination.is_symlink():
            content = destination.read_bytes()
            destination.unlink()
            destination.write_bytes(content)


def link_instructions(child: Path, source: Path, mode: str) -> None:
    """Link matching instruction files and record exact ownership in the manifest."""
    aib = child / ".ai-badger"
    links: list[dict[str, str]] = []
    source_instructions = source / "instructions"
    if source_instructions.is_dir():
        for parent_file in sorted(source_instructions.rglob("*.instructions.md")):
            relative = parent_file.relative_to(source)
            child_file = aib / relative
            if parent_file.is_symlink() or any(
                    ancestor.is_symlink() for ancestor in child_file.parents
                    if ancestor != child):
                continue
            if not child_file.is_file() or child_file.is_symlink():
                continue
            if child_file.read_bytes() != parent_file.read_bytes():
                continue
            raw_target = os.path.relpath(parent_file, child_file.parent)
            child_file.unlink()
            child_file.symlink_to(raw_target)
            links.append({
                "path": (Path(".ai-badger") / relative).as_posix(),
                "target": raw_target,
                "source": str(parent_file.resolve()),
            })
    manifest_path = aib / "manifest.json"
    manifest = read_object(manifest_path)
    manifest["sharedScope"] = {
        "mode": mode,
        "source": str(source.resolve()),
        "links": links,
    }
    bl.dump_json(manifest_path, manifest)


def materialize(child: Path, source: Path, authored: dict[str, Any],
                parent: dict[str, Any], root: Path, mode: str) -> None:
    """Render a private child scaffold through the existing scaffolder."""
    config = merge(parent, authored["overrides"])
    config["stacks"] = parent["stacks"] if mode == "inherit" else authored["localStacks"]
    validate_config(config, root)
    detach_links(child, source)
    Scaffolder(root, child, config, DEFAULT_SKILLS, install=False).run(
        allow_shared_scope=True)
    authored = dict(authored, mode=mode, source=os.path.relpath(source, child))
    bl.dump_json(child / ".ai-badger" / "shared-scope.json", authored)
    link_instructions(child, source, mode)


def collect(target: Path, names: list[str], root: Path, config_path: Path | None) -> None:
    """Recompute the parent stack union and enroll its explicit members."""
    selected = members(target, names)
    authored = [descriptor(child) for child in selected]
    parent_path = config_path or target / ".ai-badger" / "config.json"
    if parent_path.exists():
        config = copy.deepcopy(read_object(parent_path))
    else:
        config = {"frameworkVersion": bl.read_index(root)["frameworkVersion"],
                  "project": {"name": target.name}, "agents": ["claude"],
                  "commands": {}, "personaRouting": [], "docs": {}}
    config["stacks"] = list(dict.fromkeys(stack for child in authored
                                         for stack in child["localStacks"]))
    validate_config(config, root)
    for child in authored:
        effective = merge(config, child["overrides"])
        effective["stacks"] = config["stacks"]
        validate_config(effective, root)
    Scaffolder(root, target, config, DEFAULT_SKILLS, install=False).run()
    source = target / ".ai-badger"
    bl.dump_json(source / "shared-scope.json", {
        "mode": "collection", "members": [str(child.relative_to(target)) for child in selected]})
    for child, inputs in zip(selected, authored):
        materialize(child, source, inputs, config, root, "inherit")


def sync(child: Path, source: Path, root: Path) -> None:
    """Render one enrolled child using its local stacks and current parent defaults."""
    inputs = descriptor(child)
    parent = read_object(source / "config.json")
    materialize(child, source, inputs, parent, root, "sync")


def main(argv: list[str] | None = None) -> int:
    """Run the explicit shared-scope command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--target", required=True)
    collect_parser.add_argument("--repo", action="append", required=True)
    collect_parser.add_argument("--config")
    collect_parser.add_argument("--root")
    sync_parser = commands.add_parser("sync")
    sync_parser.add_argument("--target", required=True)
    sync_parser.add_argument("--source", required=True)
    sync_parser.add_argument("--root")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else FRAMEWORK_ROOT
        target = Path(args.target).resolve()
        if args.command == "collect":
            collect(target, args.repo, root,
                    Path(args.config).resolve() if args.config else None)
        else:
            sync(target, Path(args.source).resolve(), root)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"shared scope refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
