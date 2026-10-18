#!/usr/bin/env python3
"""Fail open on Codex when the shared memory lookup cannot reach its backend."""
from __future__ import annotations

import contextlib
import io
import runpy
import sys
from pathlib import Path
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    """Run the shared gate and suppress its denial only when memory lookup is unavailable."""
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return 0
    hook = Path(args[-1]).resolve()
    if not hook.is_file():
        return 0
    sys.path.insert(0, str(hook.parent))
    try:
        import memory_first_gate as gate  # pylint: disable=import-outside-toplevel
    except ImportError:
        return 0

    unavailable = False
    original_memory_hits = gate.memory_hits

    def memory_hits(*call_args, **call_kwargs):
        nonlocal unavailable
        try:
            result = original_memory_hits(*call_args, **call_kwargs)
        except Exception:  # pylint: disable=broad-exception-caught  # Codex adapter fails open
            unavailable = True
            raise
        if result is None:
            unavailable = True
        return result

    gate.memory_hits = memory_hits
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            namespace = runpy.run_path(str(hook), run_name='codex_memory_first_gate_hook')
            namespace['main']()
    except Exception:  # pylint: disable=broad-exception-caught  # hooks must not block tools
        return 0
    finally:
        gate.memory_hits = original_memory_hits
    if not unavailable:
        sys.stdout.write(output.getvalue())
    return 0


if __name__ == '__main__':
    sys.exit(main())
