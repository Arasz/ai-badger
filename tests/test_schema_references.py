"""Every relative `$schema` a JSON file carries resolves to a schema that exists — in the
framework tree, and in a project the scaffold just wrote."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
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


def test_checked_in_schemas_match_generator(root, tmp_path):
    """The review-flow schemas pass --check, and a one-byte edit to a copy makes it fail."""
    scripts = "features/common/skills/review-flow/scripts"
    tree = tmp_path / "tree"
    for rel in (f"{scripts}/review_flow_model.py", f"{scripts}/review_render.py",
                "schemas/review-flow.schema.json", "schemas/review-rules.schema.json"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, tree / rel)

    def check():
        return subprocess.run([sys.executable, str(root / "tooling/review_flow_schema.py"),
                               "--check", "--root", str(tree)],
                              capture_output=True, text=True, check=False)

    clean = check()
    assert clean.returncode == 0, clean.stdout + clean.stderr
    for name in ("review-flow.schema.json", "review-rules.schema.json"):
        path = tree / "schemas" / name
        original = path.read_bytes()
        at = original.index(b'"blocker"') + 1
        path.write_bytes(original[:at] + b"c" + original[at + 1:])
        stale = check()
        assert stale.returncode != 0, f"{name}: one-byte edit passed --check"
        assert f"STALE schemas/{name}" in stale.stdout
        path.write_bytes(original)
    assert check().returncode == 0
