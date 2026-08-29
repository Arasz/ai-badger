"""Derive-or-delete guard: support.json's capability matrix must not drift from reality.

Every `aiBadgerSupport: true` capability whose `scaffoldedBy`/`wiredBy` text names an
`adjust_*.py` script is claiming that script runs as a registered arm of that agent's
adjustment.json. Nothing here hardcodes an agent list or a capability list — both are derived
from features/common/support.json and each agent's own adjustment.json, so a future agent or
capability is covered automatically.
"""
from __future__ import annotations

import json
import re

SCRIPT_PATTERN = re.compile(r"adjust_\w+\.py")


def test_every_scaffolded_capability_has_a_matching_adjustment_arm(root):
    """A phantom scaffoldedBy/wiredBy script must not survive as an unregistered claim.

    Regression for F4: pi's `skills` capability claims `aiBadgerSupport: true` via
    "scaffold.py + pi/adjustments/adjust_skills.py", but pi/adjustments/adjustment.json
    registers no "skills" arm (only hooks, mcp, task, cron) and the script itself does not
    exist — a capability matrix claim with nothing behind it.
    """
    support = json.loads(
        (root / "features" / "common" / "support.json").read_text(encoding="utf-8"))

    missing = []
    for agent, agent_info in support["agents"].items():
        adjustment_path = root / "features" / agent / "adjustments" / "adjustment.json"
        if not adjustment_path.is_file():
            # No per-agent adjustment mechanism at all — nothing to compare an arm against.
            continue
        adjustment = json.loads(adjustment_path.read_text(encoding="utf-8"))
        registered_scripts = {arm["script"] for arm in adjustment["adjustments"]}

        for capability, info in agent_info.get("capabilities", {}).items():
            if not info.get("aiBadgerSupport"):
                continue
            mechanism_text = " ".join(
                str(info.get(key, "")) for key in ("scaffoldedBy", "wiredBy"))
            for script in SCRIPT_PATTERN.findall(mechanism_text):
                if script not in registered_scripts:
                    missing.append(
                        f"{agent}.{capability} names {script}, which is not a registered arm "
                        f"in {adjustment_path.relative_to(root)} (arms: "
                        f"{sorted(registered_scripts)})"
                    )

    assert not missing, "\n".join(missing)
