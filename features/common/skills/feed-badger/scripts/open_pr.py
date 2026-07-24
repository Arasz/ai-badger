#!/usr/bin/env python3
"""Open a draft PR to the ai-badger framework repo with generalized contributions.

The agent first writes the generalized feature files into the ai-badger CHECKOUT (under the
right {stack}/{feature}/ paths) and regenerates index.json. This script does the mechanical
git+PR work: branch, commit, push, `gh pr create --draft`. No LLM.

Usage:
  open_pr.py --checkout <ai-badger checkout> --branch feed/<slug> \
             --title "..." --body-file <path> [--repo Arasz/ai-badger] [--dry-run]

--dry-run prints the git/gh commands without executing (used for logic-tests).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "scripts" / "badger_lib.py"
        if cand.exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    # Fallback: check cached framework repo at ~/.ai-badger/framework/
    cache = Path.home() / ".ai-badger" / "framework"
    cache_scripts = cache / "scripts" / "badger_lib.py"
    if cache_scripts.exists() and (cache / "schemas").is_dir():
        sys.path.insert(0, str(cache / "scripts"))
        return
    raise RuntimeError(
        "could not locate ai-badger scripts/badger_lib.py locally or at "
        f"{cache} — run with --root <framework> or clone https://github.com/Arasz/ai-badger"
    )


_bootstrap_lib()


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
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    checkout = Path(args.checkout).resolve()
    dry = args.dry_run

    steps = [
        ["git", "checkout", "-b", args.branch],
        ["git", "add", "-A"],
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
