"""The shipped-surface root list: what actually ships to a plugin consumer (R42).

`gates/release_guard.py` diffs the working tree against this list to decide whether a
change needs a version bump; `tooling/version_sync.py` derives its stamp targets from the
same list, so the two readers cannot disagree about what "shipped" means. The list lives
here, in `tooling/`, rather than in `gates/`, because `version_sync` must not import from
`gates/` — `gates/` depends on `tooling/`, never the other way around.

`gates/` itself is deliberately absent: repo gates are internal tooling no consumer runs,
so a gate-only change needs no bump (see release_guard.py's own docstring).
"""
from __future__ import annotations

SHIPPED_PATHS = [
    "skills",
    "features",
    "engine",
    "tooling",
    "schemas",
    "index.json",
    "hooks",
    ".claude-plugin",
    "BREAKING_VERSIONS",
]
