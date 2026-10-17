#!/usr/bin/env python3
"""Install rtk (rtk-ai/rtk) through Homebrew, or print the recipes to install it by hand.

Without --run it only prints what it would do. With --run it prints the licence choice,
then runs `brew install` when brew is on PATH; otherwise it prints the recipes and fails.
winget is only ever printed. No recipe pipes a download into a shell.

Usage: python3 install.py [--run]
Exit code: 0 = installed (or dry run), non-zero = not installed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

REPO = "https://github.com/rtk-ai/rtk"
INSTALL_SCRIPT = "https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh"

LICENCE = (
    "Licence: the default rtk build links rtk-engine, which is BUSL-1.1. The Apache-2.0-only "
    "rtk-oss edition has no `rtk pipeline` and no PostToolUse compression. To choose it, set "
    "RTK_EDITION=oss (brew installs rtk-ai/tap/rtk-oss), or build with "
    f"`cargo install --git {REPO} rtk --no-default-features`."
)

RECIPES = (
    "Install rtk by hand with one of:",
    "  macOS/Linux:  brew install rtk        (rtk-oss: brew install rtk-ai/tap/rtk-oss)",
    f"  From source:  cargo install --git {REPO} rtk   (not `cargo install rtk`: that crate"
    " is Rust Type Kit)",
    f"  Script:       curl -fsSL -o rtk-install.sh {INSTALL_SCRIPT}",
    "                read rtk-install.sh, then: sh rtk-install.sh   (RTK_EDITION=oss for rtk-oss)",
    "  Windows:      winget install rtk-ai.rtk   (ai-badger's rtk hooks are POSIX-only)",
    f"  Releases:     {REPO}/releases",
)


def formula() -> str:
    """Return the Homebrew formula for the edition RTK_EDITION selects."""
    return "rtk-ai/tap/rtk-oss" if os.environ.get("RTK_EDITION") == "oss" else "rtk"


def main(argv: list[str] | None = None) -> int:
    """Print or run the rtk install."""
    parser = argparse.ArgumentParser(description="Install rtk (rtk-ai/rtk).")
    parser.add_argument("--run", action="store_true", help="Run the install instead of printing it")
    args = parser.parse_args(argv)

    command = ["brew", "install", formula()]
    if not args.run:
        print(f"Would run: {' '.join(command)}  (pass --run to install)")
        print(LICENCE)
        print("\n".join(RECIPES))
        return 0

    print(LICENCE)
    brew = shutil.which("brew") if os.name != "nt" else None
    if not brew:
        print("\n".join(RECIPES))
        print("rtk was not installed: no Homebrew on PATH.", file=sys.stderr)
        return 1

    print(f"Running: {' '.join(command)}")
    result = subprocess.run([brew, *command[1:]], stdin=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        print(f"brew install failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
