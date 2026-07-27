#!/usr/bin/env python3
"""Open a draft PR to the ai-badger framework repo with generalized contributions.

The agent first writes the generalized feature files into the ai-badger CHECKOUT (under the
right {stack}/{feature}/ paths) and regenerates index.json. This script does the mechanical
git+PR work: branch, commit, push, `gh pr create --draft`. No LLM.

Every declared path is scanned for credential-shaped literals first; a finding refuses the
PR. Only declared paths are staged — an unrelated dirty file in the checkout never rides along
(security I4).

Usage:
  open_pr.py --checkout <ai-badger checkout> --branch feed/<slug> \
             --title "..." --body-file <path> --path <rel> [--path <rel> ...] \
             [--repo Arasz/ai-badger] [--dry-run]

--dry-run prints the git/gh commands without executing (used for logic-tests).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

def _bootstrap_lib() -> Path:
    """Put the framework's scripts/ on sys.path and return its root.

    One predicate, shared with badger_lib.is_framework_root: schemas/ + features/ +
    scripts/badger_lib.py. Ordered inputs: --root, $AI_BADGER, an ancestor walk, the root
    recorded in a nearby .ai-badger/manifest.json, then ~/.ai-badger/framework (ADR-0007).
    Duplicated verbatim in every entry point because locating badger_lib is what it is for.
    """
    def is_root(path):
        return ((path / "schemas").is_dir() and (path / "features").is_dir()
                and (path / "scripts" / "badger_lib.py").is_file())

    def declared():
        argv = sys.argv[1:]
        for i, arg in enumerate(argv):
            if arg == "--root" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--root="):
                return arg.split("=", 1)[1]
        return os.environ.get("AI_BADGER")

    def recorded(start):
        for anc in [start, *start.parents]:
            manifest = (anc / "manifest.json" if anc.name == ".ai-badger"
                        else anc / ".ai-badger" / "manifest.json")
            if not manifest.is_file():
                continue
            try:
                value = json.loads(manifest.read_text(encoding="utf-8")).get("frameworkRoot")
            except (OSError, ValueError):
                continue
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = manifest.parent.parent / candidate
            if is_root(candidate):
                return candidate.resolve()
        return None

    def working_dir():
        try:
            return Path.cwd().resolve()
        except OSError:
            return here

    here = Path(__file__).resolve()
    cache = Path.home() / ".ai-badger" / "framework"
    value = declared()
    if value:
        root = Path(value).expanduser()
        if not is_root(root):
            raise RuntimeError(
                f"--root/$AI_BADGER is {root}, which is not an ai-badger framework root "
                f"(no schemas/ + features/ + scripts/badger_lib.py)"
            )
    else:
        root = next((anc for anc in [here, *here.parents] if is_root(anc)), None)
        root = root or recorded(here) or recorded(working_dir())
        root = root or (cache if is_root(cache) else None)
    if root is None:
        raise RuntimeError(
            f"could not locate the ai-badger framework: none above {here.parent}, no "
            f"$AI_BADGER, no frameworkRoot in a nearby .ai-badger/manifest.json, and no "
            f"cache at {cache} — pass --root <framework> or clone "
            f"https://github.com/Arasz/ai-badger"
        )
    sys.path.insert(0, str(root / "scripts"))
    return root.resolve()


FRAMEWORK_ROOT = _bootstrap_lib()
import unsafe_literals as ul  # pylint: disable=wrong-import-position


def run(cmd: List[str], cwd: Path, dry: bool) -> int:
    """Print `cmd`, then execute it in `cwd` unless `dry` is set; return its exit code."""
    printable = " ".join(cmd)
    if dry:
        print(f"    $ {printable}")
        return 0
    print(f"    $ {printable}")
    proc = subprocess.run(cmd, cwd=str(cwd), check=False)
    return proc.returncode


def main(argv=None) -> int:
    """CLI entry point: branch, commit, push, and open a draft PR for --checkout."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkout", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--repo", default="Arasz/ai-badger")
    ap.add_argument("--path", action="append", dest="paths", required=True, metavar="REL",
                    help="Checkout-relative path to contribute. Repeatable. Required: only "
                         "declared paths are staged, so nothing else in the tree can ride "
                         "along.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    checkout = Path(args.checkout).resolve()
    dry = args.dry_run

    findings = ul.scan_paths(checkout, args.paths)
    if findings:
        print("refusing to open a PR — content that looks like a credential was found:")
        for finding in findings:
            print(f"    - {finding['file']}: {finding['pattern']}")
        print("Remove it (or replace it with an obviously fake value) and re-run. This is a "
              "guard, not proof: it checks known literal shapes, nothing more.")
        return 1

    steps = [
        ["git", "checkout", "-b", args.branch],
        ["git", "add", "--", *args.paths],
        ["git", "commit", "-m", args.title],
        ["git", "push", "-u", "origin", args.branch],
        ["gh", "pr", "create", "--draft", "--repo", args.repo,
         "--title", args.title, "--body-file", args.body_file],
    ]
    print(f"opening draft PR to {args.repo} from {checkout} (dry-run={dry}):")
    for step in steps:
        rc = run(step, checkout, dry)
        if rc != 0 and not dry:
            print(f"step failed ({rc}); aborting.")
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
