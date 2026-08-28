#!/usr/bin/env python3
"""Phase 0 trust sentinel test: prove pi extensions fire at user scope, not project scope.

Implements the F20 run A/B pair as an automated assertion:
- Run A: extension at project-local .pi/extensions/ without --approve → NOT-LOADED
- Run B: extension at user scope ~/.pi/agent/extensions/ → LOADED

Exit 0 if both outcomes are correct, 1 otherwise.
"""

import os
import sys
import tempfile
import subprocess
import shutil
from pathlib import Path

SENTINEL_FILE = "/tmp/pi-badger-probe-sentinel"
PROBE_EXTENSION = """import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { writeFileSync } from "fs"
export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    writeFileSync("/tmp/pi-badger-probe-sentinel", "LOADED\\n", "utf-8")
    ctx.ui.notify("Badger probe: LOADED", "info")
  })
}
"""


def clean_sentinel():
    if os.path.exists(SENTINEL_FILE):
        os.remove(SENTINEL_FILE)


def run_pi(workdir: str, extension_path: str, use_approve: bool = False) -> int:
    """Run pi headless in a workdir, return exit code."""
    cmd = ["pi", "-p", "--no-tools", "-e", extension_path, "hi"]
    if use_approve:
        cmd.insert(cmd.index("-p") + 1, "--approve")
    result = subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode


def test_project_local_without_approve(tmpdir: str) -> bool:
    """Run A: project-local .pi/extensions/ without --approve → sentinel NOT written."""
    pi_dir = Path(tmpdir) / ".pi" / "extensions"
    pi_dir.mkdir(parents=True, exist_ok=True)
    ext_file = pi_dir / "badger-probe.ts"
    ext_file.write_text(PROBE_EXTENSION)

    clean_sentinel()
    rc = run_pi(tmpdir, str(ext_file), use_approve=False)

    if os.path.exists(SENTINEL_FILE):
        print(f"FAIL (Run A): sentinel WAS written — extension fired without --approve (rc={rc})")
        return False
    print(f"OK (Run A): sentinel NOT written — project-local extension correctly blocked (rc={rc})")
    return True


def test_user_scope_without_approve() -> bool:
    """Run B: user scope ~/.pi/agent/extensions/ without --approve → sentinel IS written."""
    user_ext_dir = Path.home() / ".pi" / "agent" / "extensions"
    user_ext_dir.mkdir(parents=True, exist_ok=True)
    ext_file = user_ext_dir / "badger-probe.ts"
    backup = None
    if ext_file.exists():
        backup = ext_file.read_text()
    ext_file.write_text(PROBE_EXTENSION)

    try:
        clean_sentinel()
        with tempfile.TemporaryDirectory() as tmpdir:
            rc = run_pi(tmpdir, str(ext_file), use_approve=False)

        if not os.path.exists(SENTINEL_FILE):
            print(f"FAIL (Run B): sentinel NOT written — user-scope extension did NOT fire (rc={rc})")
            return False
        sentinel_content = Path(SENTINEL_FILE).read_text().strip()
        print(f"OK (Run B): sentinel written with '{sentinel_content}' — user-scope extension fires (rc={rc})")
        return True
    finally:
        clean_sentinel()
        if backup is not None:
            ext_file.write_text(backup)
        elif ext_file.exists():
            ext_file.unlink()


def main():
    print("=== Phase 0: pi trust sentinel test ===")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        a_ok = test_project_local_without_approve(tmpdir)

    b_ok = test_user_scope_without_approve()

    print()
    if a_ok and b_ok:
        print("PASS: Trust sentinel test — user-scope extensions fire, project-local blocked.")
        return 0
    else:
        print("FAIL: Trust sentinel test did not pass. See findings above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
