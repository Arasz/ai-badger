#!/usr/bin/env python3
"""Pull framework updates into an already-scaffolded project.

Orchestrates drift detection + re-scaffold: checks what changed upstream,
re-scaffolds using the project's existing config.json, and reports the result.

MECHANICAL ONLY — no LLM. The agent's role is to present the report and help
the user review the diff.

Usage: refresh.py --target <dir> --root <framework>
Exit codes: 0 = up to date or changes applied, 1 = drift found but re-scaffold
            could not run (reserved), 2 = usage error (missing config/manifest).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "scripts" / "badger_lib.py"
        if cand.exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    raise RuntimeError("could not locate ai-badger scripts/badger_lib.py")


def _load_script(relpath: str, base: Path):
    """Import an ai-badger script by repo-relative path (same pattern as test conftest).

    Tries `base` first (the framework root), then falls back to the real repo root
    this script lives in — so mock/minimal frameworks used in tests still work.
    """
    # Try the given base first, then the script's own repo root
    candidates = [base]
    script_repo = Path(__file__).resolve()
    for anc in script_repo.parents:
        if (anc / "scripts" / "badger_lib.py").exists() and (anc / "schemas").is_dir():
            candidates.append(anc)
            break
    for cand in candidates:
        path = cand / relpath
        if path.exists():
            name = "aib_" + path.stem
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError(f"could not find {relpath} in {candidates}")


_bootstrap_lib()
import badger_lib as bl


def check_breaking_and_backup(root: Path, target: Path) -> Dict[str, Any]:
    """Check if the version transition is breaking; if so, back up .ai-badger/.

    Returns {"isBreaking": bool, "backupPath": str|None}.
    """
    aib = target / ".ai-badger"
    config = bl.load_json(aib / "config.json")
    from_version = config.get("frameworkVersion", "0.0.0")
    to_version = (root / "VERSION").read_text(encoding="utf-8").strip()

    is_breaking = bl.is_breaking_transition(from_version, to_version, root)
    if not is_breaking:
        return {"isBreaking": False, "backupPath": None}

    # Back up .ai-badger/ to .ai-badger.bckp/
    import shutil
    bckp = target / ".ai-badger.bckp"
    if bckp.exists():
        shutil.rmtree(bckp)
    shutil.copytree(aib, bckp)
    return {"isBreaking": True, "backupPath": str(bckp)}


def check_prerequisites(target: Path) -> Optional[str]:
    """Verify target has config.json and manifest.json; return error message or None."""
    aib = target / ".ai-badger"
    if not (aib / "config.json").exists():
        return f"no .ai-badger/config.json at {aib} — project not scaffolded by ai-badger"
    if not (aib / "manifest.json").exists():
        return f"no .ai-badger/manifest.json at {aib} — project was never fully scaffolded"
    return None


def run_drift(root: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Run drift comparison against the framework's current content."""
    drift_mod = _load_script("features/common/skills/welcome-ai-badger/scripts/drift.py", root)
    return drift_mod.compare(root, manifest)


def re_scaffold(root: Path, target: Path, config: Dict[str, Any],
                manifest: Dict[str, Any],
                generated_at: Optional[str] = None) -> Dict[str, Any]:
    """Re-run scaffold.py with the existing config.json.

    Extracts skill names from the manifest so skills with extensions
    (e.g., task with github/hermes extensions) are re-scaffolded and
    their extensions re-embedded.
    """
    scaffold_mod = _load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py", root)

    # Extract skill names from manifest entries
    skill_names = list(dict.fromkeys(
        e["name"] for e in manifest.get("entries", [])
        if e.get("feature") == "skills"
    ))

    scaf = scaffold_mod.Scaffolder(
        root=root, target=target, config=config,
        skills=skill_names, install=False,
    )
    result = scaf.run(generated_at=generated_at)
    return {
        "entries": len(result["manifest"]["entries"]),
        "notes": result["notes"],
        "pluginCommands": result["pluginCommands"],
        "refreshedSkills": skill_names,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: check drift, re-scaffold if needed, print JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="framework repo root (default: autodetect)")
    parser.add_argument("--target", required=True, help="scaffolded project root")
    parser.add_argument("--generated-at", default=None,
                        help="ISO timestamp for manifest (default: none)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()
    target = Path(args.target).resolve()

    # 1. Check prerequisites
    err = check_prerequisites(target)
    if err:
        print(json.dumps({"error": err}))
        return 2

    # 2. Read existing config
    config_path = target / ".ai-badger" / "config.json"
    try:
        config = bl.load_json(config_path)
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": f"could not read config at {config_path}: {exc}"}))
        return 2

    # 3. Validate config against schema
    errors = bl.validate_file(config_path, root / "schemas" / "config.schema.json")
    if errors:
        print(json.dumps({
            "error": "config.json is INVALID — fix before refreshing",
            "validationErrors": errors,
        }))
        return 2

    # 4. Read manifest (needed by both drift and re-scaffold)
    manifest_path = target / ".ai-badger" / "manifest.json"
    try:
        manifest = bl.load_json(manifest_path)
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": f"could not read manifest at {manifest_path}: {exc}"}))
        return 2

    # 5. Check for breaking version transition
    breaking_result = check_breaking_and_backup(root, target)

    # 6. Check drift
    scaffold_version = config.get("frameworkVersion", "?")
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    drift_result = run_drift(root, manifest)

    has_drift = bool(drift_result.get("changed") or drift_result.get("removed"))

    # 7. Re-scaffold if drift detected (or breaking change forces full re-scaffold)
    scaffold_result = None
    if has_drift or breaking_result["isBreaking"]:
        scaffold_result = re_scaffold(root, target, config, manifest,
                                       generated_at=args.generated_at)

    # 8. Report
    report = {
        "frameworkVersion": {
            "scaffolded": scaffold_version,
            "current": current_version,
        },
        "breakingChange": breaking_result,
        "drift": {
            "changed": drift_result.get("changed", []),
            "removed": drift_result.get("removed", []),
            "skipped": drift_result.get("skipped", []),
            "invalid": drift_result.get("invalid", 0),
        },
        "reScaffolded": has_drift or breaking_result["isBreaking"],
    }
    if scaffold_result:
        report["scaffold"] = scaffold_result

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
