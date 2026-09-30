"""R7/0.183.0 honesty pins for the pi row of features/common/support.json.

The capability matrix is documentation users act on, so it is pinned the way code is: the
row is selected by JSON path (``agents.pi`` — never by line number), the load-bearing claims
are pinned as positive substrings (each one carries the gate — remove the claim, fail the
test), and the phrases the plan review caught lying are pinned as full-phrase
must-not-contain, scoped to where they would actually lie.

0.183.0 retires the pi-mcp-tools fork claims. The truth the pins carry (research record F1,
F4, F10/F11): pi 0.99.1 reads MCP config natively from ``~/.pi/agent/mcp.json`` (global) and
``.pi/mcp.json`` (project, read only in a trusted project), this scaffold writes the project
file with union-merge semantics (existing entries survive byte-identical with their
exposure/toolExposure tuning, new entries are templated with ``"exposure": "direct"``,
user-added servers are never dropped), ``.mcp.json`` belongs to Claude Code and the Copilot
CLI, and tools are named ``mcp__<server>__<tool>`` under the
codemode/deferred/direct/hidden exposure model.

The fork claim is pinned as an any-wording must-not: a sentence that names ``pi-mcp-tools``
together with a capability verb is a claim, while a retirement mention — the fork named in a
removal/proposal context with no capability verb — is honest and passes.
"""
from __future__ import annotations

import json
import re

MCP_REQUIRED_SUBSTRINGS = [
    "~/.pi/agent/mcp.json",
    ".pi/mcp.json",
    "trusted project",
    "defaultProjectTrust",
    "ask|never",
    "mcp__<server>__<tool>",
    "codemode",
    "codemode-deferred",
    "deferred",
    "direct",
    "hidden",
    "toolExposure",
    "union",
    "byte-identical",
    "user-added",
    "never dropped",
    "not read",
]

# A sentence that names pi-mcp-tools may retire it; it may not claim what it does. These are
# the capability verbs the retired claim used ("the fork reads .mcp.json at session_start",
# "claude→fork conversion", "${HOME} expanded", "armed servers") plus their inflections, so
# a reworded reintroduction fails while the retirement mention the row is allowed to carry
# ("... the retired pi-mcp-tools fork's user-global state: removes ...") does not.
FORK_CLAIM_VERBS = (
    "read", "reads", "reading",
    "expand", "expands", "expanded", "expanding",
    "convert", "converts", "converted", "converting", "conversion",
    "map", "maps", "mapped", "mapping",
    "arm", "arms", "armed", "arming",
    "serve", "serves", "served", "serving",
    "support", "supports", "supported",
    "provide", "provides", "provided",
    "inject", "injects", "injected",
    "translate", "translates", "translated",
)

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

# The MCP bullet's own claims — pi.instructions.md is what a pi session reads.
INSTRUCTIONS_MCP_REQUIRED_SUBSTRINGS = [
    ".pi/mcp.json",
    "ai-badger",
    "exposure",
    "toolExposure",
    "re-scaffold",
]


def _load_support(root) -> dict:
    return json.loads(
        (root / "features" / "common" / "support.json").read_text(encoding="utf-8"))


def _pi_row(root) -> dict:
    """The pi row, selected by JSON path — the pin's scope, not a line number."""
    return _load_support(root)["agents"]["pi"]


def _row_text(value) -> str:
    """Every string in the subtree, serialized — a lie in any field is still a lie."""
    return json.dumps(value, ensure_ascii=False)


def _strings(value):
    """Every string in the subtree, one at a time — for sentence-scoped checks."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _sentences(text: str):
    """Split *text* on sentence-ish boundaries; a claim sentence is judged whole."""
    return [part for part in re.split(r"(?<=[.;])\s+", text) if part.strip()]


def _mcp_bullet(root) -> str:
    """The MCP bullet of pi.instructions.md, the next top-level bullet apart."""
    lines = (root / "features" / "pi" / "instructions" / "pi.instructions.md").read_text(
        encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("- MCP:"))
    out = [lines[start]]
    for line in lines[start + 1:]:
        if line.startswith("- "):
            break
        out.append(line)
    return "\n".join(out)


def test_pi_mcp_row_carries_the_project_scope_claims(root):
    """mcpServers' mechanism must state pi's native contract as measured (F1/F4/F10)."""
    row = _pi_row(root)["capabilities"]["mcpServers"]
    mechanism = row["mechanism"]

    missing = [s for s in MCP_REQUIRED_SUBSTRINGS if s not in mechanism]
    assert not missing, (
        f"mcpServers mechanism is missing load-bearing claims {missing}; "
        f"got: {mechanism!r}"
    )


def test_pi_mcp_row_makes_no_fork_capability_claim(root):
    """A fork-era capability claim must not survive in any wording (F2, 0.183.0).

    The retired row said "the pi-mcp-tools fork reads the project's .mcp.json at
    session_start (claude→fork conversion; ${HOME} expanded ...); armed servers are gated".
    The gate is the name plus a capability verb, not the literal "fork reads", so a reworded
    reclaim fails. A retirement mention with no capability verb is honest and passes.
    """
    offenders = []
    for text in _strings(_pi_row(root)):
        for sentence in _sentences(text):
            if "pi-mcp-tools" not in sentence.lower():
                continue
            hits = [verb for verb in FORK_CLAIM_VERBS
                    if re.search(rf"\b{re.escape(verb)}\b", sentence, re.IGNORECASE)]
            if hits:
                offenders.append((sentence.strip(), hits))
    assert not offenders, (
        "the agents.pi row still claims what the retired pi-mcp-tools fork does "
        f"(name plus capability verb): {offenders!r}"
    )


def test_pi_mcp_row_is_full_support_after_remote_mapping(root):
    """Native pi speaks stdio and remote transports both — no 'partial' asterisk remains."""
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


def test_pi_instructions_mcp_bullet_names_the_scaffold_write(root):
    """The MCP bullet must name ai-badger's .pi/mcp.json write and its preservation semantics.

    support.json is not the only pi MCP documentation the framework ships: the instructions
    bullet is what a pi session reads. It described pi's native contract but never named
    ai-badger's own write, so nothing in the loaded instructions explained the scaffolded
    file or why hand-tuned exposure survives a refresh.
    """
    bullet = _mcp_bullet(root)
    missing = [s for s in INSTRUCTIONS_MCP_REQUIRED_SUBSTRINGS if s not in bullet]
    assert not missing, (
        f"pi instructions' MCP bullet is missing the scaffold-write claims {missing}; "
        f"got: {bullet!r}"
    )
