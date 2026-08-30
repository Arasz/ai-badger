"""R7 honesty pins for the pi row of features/common/support.json.

The capability matrix is documentation users act on, so it is pinned the way code is: the
row is selected by JSON path (``agents.pi`` — never by line number), the load-bearing claims
are pinned as positive substrings (each one carries the gate — remove the claim, fail the
test), and the phrases the plan review caught lying are pinned as full-phrase
must-not-contain, scoped to where they would actually lie.

The claims pinned here are the plan's §3 row content (rev 3): the fork reads the project
.mcp.json at session_start with ${HOME} expansion, the trust gate with its measured
short-circuit (scaffolded projects arm in all modes), local stdio + remote http/sse mapping,
the global 'mcp' key demoted to user-owned fallback no longer scaffold-written, and the
adapter's ungated resources_discover skills contribution.
"""
from __future__ import annotations

import json

MCP_REQUIRED_SUBSTRINGS = [
    ".mcp.json",
    "session_start",
    "${HOME} expanded",
    "gated by pi project trust",
    "pi-trust-requiring resources",
    "arm in all modes",
    "local stdio",
    "http",
    "sse",
    "user-owned fallback",
    "no longer scaffold-written",
]

# Full-phrase lies (plan-review R7): a literal substring anywhere in the pi row is a
# documentation lie — there is no true sentence containing them.
ROW_WIDE_LYING_PHRASES = [
    # The scaffold no longer merges anything into settings.json — it removes, marker-gated.
    "the scaffold merges into settings.json",
    # D5 mapped remote http/sse; the equality claim is no longer qualified away.
    "same servers as Claude Code",
    # "headless-safe" without the trust sentence was the rev-2 overclaim direction.
    "headless-safe",
]


def _load_support(root) -> dict:
    return json.loads(
        (root / "features" / "common" / "support.json").read_text(encoding="utf-8"))


def _pi_row(root) -> dict:
    """The pi row, selected by JSON path — the pin's scope, not a line number."""
    support = _load_support(root)
    return support["agents"]["pi"]


def _row_text(value) -> str:
    """Every string in the subtree, serialized — a lie in any field is still a lie."""
    return json.dumps(value, ensure_ascii=False)


def test_pi_mcp_row_carries_the_project_scope_claims(root):
    """mcpServers' mechanism must state the project-scope contract as measured (plan §3)."""
    row = _pi_row(root)["capabilities"]["mcpServers"]
    mechanism = row["mechanism"]

    missing = [s for s in MCP_REQUIRED_SUBSTRINGS if s not in mechanism]
    assert not missing, (
        f"mcpServers mechanism is missing load-bearing claims {missing}; "
        f"got: {mechanism!r}"
    )


def test_pi_mcp_row_is_full_support_after_remote_mapping(root):
    """D5 mapped claude http/sse to the fork's remote transport — the stdio-only 'partial'
    asterisk is gone, so the row no longer understates the capability either."""
    row = _pi_row(root)["capabilities"]["mcpServers"]
    assert row["supported"] is True, row["supported"]


def test_pi_skills_row_names_the_resources_discover_contribution(root):
    """skills' mechanism must name resources_discover and its ungated contribution (D2)."""
    row = _pi_row(root)["capabilities"]["skills"]
    mechanism = row["mechanism"]

    assert "resources_discover" in mechanism, mechanism
    assert "ungated" in mechanism, mechanism


def test_pi_skills_row_does_not_claim_trust_gating(root):
    """The skills contribution is ungated by design (ADR-0023's recorded asymmetry); a
    trust-gating claim on this row is the opposite lie to the M2 short-circuit sentence."""
    row = _pi_row(root)["capabilities"]["skills"]
    assert "trust-gated" not in _row_text(row), (
        "the skills row must not claim trust gating — the adapter's resources_discover "
        "contribution is deliberately ungated (plan D2/M4)"
    )


def test_pi_row_contains_no_lying_phrases(root):
    """Full-phrase must-not-contain, scoped to the whole agents.pi row (R7)."""
    text = _row_text(_pi_row(root))
    for phrase in ROW_WIDE_LYING_PHRASES:
        assert phrase not in text, (
            f"lying phrase {phrase!r} found in the agents.pi row of support.json"
        )
