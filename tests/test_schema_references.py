"""Every relative `$schema` a JSON file carries resolves to a schema that exists — in the
framework tree, and in a project the scaffold just wrote."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List

from scaffold_helpers import _config


def _broken_refs(base: Path, files: List[Path]) -> List[str]:
    """`file -> $schema` for each relative reference that does not resolve from its file."""
    broken = []
    for path in files:
        try:
            ref = json.loads(path.read_text(encoding="utf-8")).get("$schema")
        except (ValueError, UnicodeDecodeError, AttributeError):
            continue
        if not isinstance(ref, str) or "://" in ref:
            continue
        if not (path.parent / ref.split("#")[0]).is_file():
            broken.append(f"{path.relative_to(base).as_posix()} -> {ref}")
    return broken


def test_framework_json_schema_references_resolve(root):
    tracked = subprocess.run(["git", "ls-files", "-z", "*.json"], cwd=str(root),
                             capture_output=True, text=True, check=True).stdout.split("\0")
    assert _broken_refs(root, [root / rel for rel in tracked if rel]) == []


def test_scaffolded_json_schema_references_resolve(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder(config=_config(stacks=["dotnet", "python"]), skills=["task"]).run(
        generated_at="2026-07-19T00:00:00Z")

    files = [p for p in target.rglob("*.json") if ".git" not in p.parts]
    assert any(p.name == "manifest.json" for p in files)
    assert any(p.name == "model-groups.json" for p in files)
    assert _broken_refs(target, files) == []
