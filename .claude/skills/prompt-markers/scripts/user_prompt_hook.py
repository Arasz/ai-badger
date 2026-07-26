#!/usr/bin/env python3
"""UserPromptSubmit hook: detect a leading prompt marker and inject behavior context.

Standalone, stdlib-only, project-agnostic. Detects a marker prefix (e.g. `h:`, `hint:`) at the
very start of the submitted prompt (case-insensitive), looks up its injected instruction text in
`markers-context.json` (resolved relative to this script, i.e. the skill directory next to
`scripts/`), and emits it via the hook's `additionalContext` field.

`additionalContext` is *appended*, never used to rewrite or prepend to the prompt: appending
preserves the prefix of the conversation so far, which keeps prompt caching effective (see
ADR-0017 "Prompt markers for agent context injection" in the originating project, or the
equivalent rationale wherever this hook is deployed). Prepending or replacing the prompt would
invalidate the cached prefix for this and every subsequent turn.

Silent (exit 0, no output) when: no marker matches, `markers-context.json` is missing/invalid, or
any internal error occurs — a broken hook must never block a prompt from going through.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
MARKERS_CONTEXT_FILE = SKILL_DIR / "markers-context.json"

# Convention shared with the rest of an ai-badger-scaffolded project: a project-tracking
# directory at the repo root named ".ai-badger". Transformations are recorded there only if the
# project has actually adopted that convention (directory already exists) — this hook never
# creates project-tracking structure on its own.
TRACKING_DIR_NAME = ".ai-badger"
STATE_SUBPATH = ("prompt-markers", "marker-state.json")
MAX_HISTORY = 100


def now_iso() -> str:
    """Return the current UTC time as a second-precision ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_markers_context() -> dict:
    """Load markers-context.json (marker definitions + their injected instruction text)."""
    with MARKERS_CONTEXT_FILE.open() as fh:
        return json.load(fh)


def match_marker(prompt: str, markers: list[dict]) -> tuple[dict, str] | None:
    """Return the (marker, matched prefix) whose prefix leads `prompt`, or None."""
    prompt_trimmed = prompt.strip().lower()
    for marker in markers:
        for prefix in marker.get("prefixes", []):
            if prompt_trimmed.startswith(prefix.lower()):
                return marker, prefix
    return None


def find_tracking_dir(start: Path) -> Path | None:
    """Walk up from `start` looking for an existing `.ai-badger` directory."""
    for candidate in (start, *start.parents):
        maybe = candidate / TRACKING_DIR_NAME
        if maybe.is_dir():
            return maybe
    return None


def record_transformation(
    cwd: str, prompt: str, marker_id: str, prefix: str, injected: str
) -> None:
    """Best-effort audit trail. Skips silently if the project has no tracking dir."""
    tracking_dir = find_tracking_dir(Path(cwd) if cwd else Path.cwd())
    if tracking_dir is None:
        return

    state_dir = tracking_dir.joinpath(*STATE_SUBPATH[:-1])
    state_file = state_dir / STATE_SUBPATH[-1]
    state_dir.mkdir(parents=True, exist_ok=True)

    try:
        state = json.loads(state_file.read_text()) if state_file.exists() else {"history": []}
    except (OSError, ValueError):
        state = {"history": []}

    state.setdefault("history", []).append({
        "timestamp": now_iso(),
        "originalPrompt": prompt,
        "matchedPrefix": prefix,
        "markerId": marker_id,
        "injectedContext": injected,
    })
    state["history"] = state["history"][-MAX_HISTORY:]
    state_file.write_text(json.dumps(state, indent=2) + "\n")


def main() -> int:
    """Read the hook payload from stdin and emit additionalContext if a marker matched."""
    payload = json.load(sys.stdin)
    prompt = payload.get("prompt", "")
    if not prompt:
        return 0

    config = load_markers_context()
    matched = match_marker(prompt, config.get("markers", []))
    if matched is None:
        return 0

    marker, prefix = matched
    injected = marker["inject"]

    record_transformation(payload.get("cwd", ""), prompt, marker["id"], prefix, injected)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": injected,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # pylint: disable=broad-exception-caught
        # A broken hook must never block the prompt: swallow everything, not just the
        # exceptions we anticipated.
        sys.exit(0)
