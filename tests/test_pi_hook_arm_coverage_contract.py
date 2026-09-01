"""G4 — the pi hooks adapter's event set vs. ai-badger's hooks manifest, both derived.

Every value compared here is regexed or parsed out of real source at test time: the pi
extension events the adapter actually subscribes to (`features/pi/adjustments/adapter/
index.ts`), the Claude-vocabulary event name the adapter hardcodes into every gate payload
(`adapter/hook-bridge.ts`), the per-agent "arms" `features/common/hooks/hooks-manifest.json`
declares for each hook, and `tooling/validate.py`'s own `HOOK_CAPABLE_AGENTS` tuple. None of it
is copied into a literal list here and none of it is read from a docstring — a docstring and a
test that agree with each other while the code drifts underneath them is exactly the failure
this repo keeps hitting (see the hooks-manifest agent-coverage gaps issue #147, and the
`docs/dictionary.md` "Hooks" table this suite deliberately does not read as a source of truth
either, for the same reason).

**The finding, not a forced pass:** pi is not a per-hook "arm" the way hermes and copilot are.
`hooks-manifest.json` models coverage as one entry per named hook, each naming the agents that
implement it; hermes and copilot both need a new arm added by hand for every hook they cover,
and `tooling/validate.py`'s `HOOK_CAPABLE_AGENTS = ("claude", "hermes", "copilot")` is exactly
that per-agent, per-hook completeness check. pi's adapter takes a structurally different
approach (D1): it registers one `pi.on(...)` handler per arm — `tool_call` runs every
PreToolUse command, `tool_result` runs every PostToolUse command — both *dynamically* reading
the project's `.ai-badger/hooks/hooks.json` at event time — no per-hook-name registration
exists to compare against the manifest's arms, and adding "pi" as a fourth
`HOOK_CAPABLE_AGENTS` member would ask for something the adapter was deliberately built not
to need. So "pi" is absent from both sides today, on purpose, and this file asserts that
absence rather than fabricating a false equivalence between a set of pi extension-API event
names and a set of agent identifiers — two different kinds of thing that happen to both be
called "coverage" in prose.

What still gets checked, and what would actually go red:
  - the adapter keeps at least one live `pi.on(...)` subscription (a regression to zero would
    mean the extension loads and does nothing);
  - "pi" staying out of both `HOOK_CAPABLE_AGENTS` and the manifest's arms, together — if one
    side ever adds it without the other, that is exactly the kind of silent drift this file
    exists to catch, and it is reported here as a real design decision to reconcile, not
    quietly patched around.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ADAPTER_INDEX_TS = Path("features/pi/adjustments/adapter/index.ts")
ADAPTER_BRIDGE_TS = Path("features/pi/adjustments/adapter/hook-bridge.ts")
HOOKS_MANIFEST = Path("features/common/hooks/hooks-manifest.json")

PI_ON_EVENT = re.compile(r'pi\.on\(\s*[\'"]([^\'"]+)[\'"]')
HOOK_EVENT_NAME_LITERAL = re.compile(r'hook_event_name:\s*[\'"](\w+)[\'"]')
DELIVERY_MAP_ENTRY = re.compile(r'(\w+):\s*"(\w+)"\s*,?')
DELIVERY_EVENT_SET = re.compile(r'DELIVERY_EVENTS\s*=\s*frozenset\(\{([^}]*)\}')
CLOSE_EVENT_SET = re.compile(r'CLOSE_EVENTS\s*=\s*frozenset\(\{([^}]*)\}')


def _adapter_pi_on_events(root: Path) -> set[str]:
    """Every event name the adapter subscribes to, regexed from index.ts's own pi.on(...) calls."""
    source = (root / ADAPTER_INDEX_TS).read_text(encoding="utf-8")
    return set(PI_ON_EVENT.findall(source))


def _adapter_claude_event_names(root: Path) -> set[str]:
    """The Claude-vocabulary event name(s) hardcoded into the payload hook-bridge.ts builds."""
    source = (root / ADAPTER_BRIDGE_TS).read_text(encoding="utf-8")
    return set(HOOK_EVENT_NAME_LITERAL.findall(source))


def _hooks_manifest(root: Path) -> dict:
    return json.loads((root / HOOKS_MANIFEST).read_text(encoding="utf-8"))


def _manifest_non_claude_arms(manifest: dict) -> set[str]:
    """Agent identifiers appearing as a hook's arm, other than claude — hermes/copilot today."""
    arms: set[str] = set()
    for hook in manifest.get("hooks", []):
        for agent in hook.get("agents", {}):
            if agent != "claude":
                arms.add(agent)
    return arms


def _manifest_claude_event_families(manifest: dict) -> set[str]:
    """The distinct `event` values used by every hook's claude arm."""
    families: set[str] = set()
    for hook in manifest.get("hooks", []):
        claude = hook.get("agents", {}).get("claude")
        if isinstance(claude, dict) and isinstance(claude.get("event"), str):
            families.add(claude["event"])
    return families


def test_adapter_subscribes_to_at_least_one_pi_event(root):
    """A regression to zero pi.on(...) calls means the extension loads and gates nothing."""
    events = _adapter_pi_on_events(root)

    assert events, "no pi.on(...) call sites found in adapter/index.ts"


def _adapter_payload_loader_groups(root: Path) -> set[str]:
    """The hooks.json group key(s) the adapter's dynamic loader actually reads."""
    source = (root / ADAPTER_BRIDGE_TS).read_text(encoding="utf-8")
    return set(re.findall(r"hooks\?\.(\w+)", source))


def test_adapter_claude_event_names_are_real_manifest_event_families(root):
    """The Claude-vocabulary event names the adapter hardcodes must still exist in the manifest.

    hook-bridge.ts stamps `hook_event_name` onto the JSON it hands the Python hooks —
    "PreToolUse" on the pre arm, "PostToolUse" on the post arm; if hooks-manifest.json's own
    claude arms ever renamed those families (or the adapter typo'd one), the two would
    silently stop meaning the same event.
    """
    adapter_claude_events = _adapter_claude_event_names(root)
    manifest = _hooks_manifest(root)
    manifest_claude_families = _manifest_claude_event_families(manifest)

    assert adapter_claude_events, "no hook_event_name literal found in adapter/hook-bridge.ts"
    assert adapter_claude_events <= manifest_claude_families, (
        f"adapter/hook-bridge.ts hardcodes {adapter_claude_events!r}, which is not among the "
        f"manifest's own claude event families {manifest_claude_families!r}"
    )


def test_adapter_stamps_exactly_the_event_families_its_loaders_read(root):
    """Each payload stamp and the hooks.json group its loader reads must be the same family.

    A rename on the manifest side is caught by the membership test above (the stamped name
    would fall outside the manifest's families). This test closes the other direction, which
    a subset check cannot see: renaming a stamped literal to a family the manifest knows but
    the loader does not read would keep the membership check green while the two sides
    silently stop meaning the same event. Each arm's correspondence is derived:
    hook-bridge.ts must read `hooks?.PreToolUse` for the payload it stamps "PreToolUse" onto
    and `hooks?.PostToolUse` for the "PostToolUse" one — both sides regexed from source, so
    an arm added on one side without the other goes red here.
    """
    stamped = _adapter_claude_event_names(root)
    loader_groups = _adapter_payload_loader_groups(root)

    assert loader_groups == {"PreToolUse", "PostToolUse"}, loader_groups
    assert stamped == loader_groups, (
        f"hook-bridge.ts stamps {stamped!r} but its loaders read the {loader_groups!r} groups "
        f"of hooks.json — a rename on one side has broken the correspondence"
    )


def test_pi_is_not_a_hooks_manifest_arm_today(root):
    """Pins the real, current state: pi has no per-hook arm in hooks-manifest.json.

    Confirms the finding this file's docstring reports rather than asserting it only in prose:
    the manifest's per-hook 'agents' maps name hermes/copilot as arms next to claude, and pi
    names none of them, because the adapter does not register per-hook handlers to list.
    """
    manifest = _hooks_manifest(root)
    non_claude_arms = _manifest_non_claude_arms(manifest)

    assert non_claude_arms, "expected at least one non-claude arm (hermes/copilot) to exist"
    assert "pi" not in non_claude_arms, (
        f"'pi' now appears as a hooks-manifest arm ({non_claude_arms!r}) — the adapter's "
        f"dynamic per-arm pi.on('tool_call'/'tool_result', ...) handlers and the manifest's "
        f"per-hook-name arm model have diverged from the D1 design; reconcile which one is "
        f"authoritative before changing this assertion"
    )


def test_pi_is_not_a_hook_capable_agent_today(load_script):
    """Pins the same absence in tooling/validate.py's own coverage-gap check, imported live.

    HOOK_CAPABLE_AGENTS drives tests/test_hooks_manifest_agent_coverage.py's completeness gate:
    every hook must name every HOOK_CAPABLE_AGENTS member or record why not. Adding 'pi' there
    would demand a per-hook 'pi' arm for every hook — exactly what D1's dynamic single-handler
    adapter was built to avoid needing. If this ever flips, the reconciliation belongs to
    whoever adds it, not to a widened assertion here.
    """
    validate = load_script("tooling/validate.py")

    assert "pi" not in validate.HOOK_CAPABLE_AGENTS, validate.HOOK_CAPABLE_AGENTS


def test_adapter_event_set_and_manifest_arms_are_different_kinds_of_set(root):
    """The two sets G4 was asked to compare are not comparable as membership sets, and saying
    so is the actual contract: the adapter's events are pi extension-API event names (currently
    {"tool_call"}); the manifest's non-claude arms are agent identifiers ({"hermes", "copilot"}
    today). Forcing `adapter_events == non_claude_arms` would either always fail (they will
    never share a spelling) or be trivially satisfied by disjointness — neither catches real
    drift. What each side means is asserted separately by the tests above; this test only
    documents, with the real derived values, why a single equality check across them would be
    dishonest rather than useful.
    """
    adapter_events = _adapter_pi_on_events(root)
    non_claude_arms = _manifest_non_claude_arms(_hooks_manifest(root))

    assert adapter_events.isdisjoint(non_claude_arms), (
        f"adapter events {adapter_events!r} and manifest non-claude arms {non_claude_arms!r} "
        f"now share a spelling — re-examine whether they still mean different things before "
        f"trusting this test's framing"
    )


def test_adapter_subscribes_to_the_event_per_arm_it_loads(root):
    """The pre arm needs a tool_call subscription and the post arm a tool_result one.

    A missing subscription means that arm silently does nothing: after 0.144.0's post arm
    (the pi twin of Claude's PostToolUse marker recording), a tool_result handler that
    vanished would put pi back to a gate that denies text search forever — the marker the
    post arm records is the only thing that unlocks it.
    """
    events = _adapter_pi_on_events(root)

    assert {"tool_call", "tool_result"} <= events, events


# ---------------------------------------------------------------------------
# P6 (aib-user-db-message-bus) — the delivery arm: pi's message-bus events translate
# into Claude-shaped payloads for the shared delivery script. The gates arm's stamp
# literal stays what its hooks.json loaders read (tests above); the delivery arm's
# stamps flow through PI_DELIVERY_EVENT_MAP, so the contract here is map ↔ subscription
# ↔ script routing, each side derived from its own source.
# ---------------------------------------------------------------------------

DELIVERY_MAP_HEADER = "PI_DELIVERY_EVENT_MAP"


def _adapter_delivery_map(root: Path) -> dict[str, str]:
    """The pi→Claude event translation table, parsed from hook-bridge.ts's own map."""
    source = (root / ADAPTER_BRIDGE_TS).read_text(encoding="utf-8")
    start = source.index(DELIVERY_MAP_HEADER)
    body = source[start:source.index("};", start)]
    return dict(DELIVERY_MAP_ENTRY.findall(body))


def _delivery_hook_event_sets(root: Path) -> tuple[set[str], set[str]]:
    """message_delivery_hook.py's DELIVERY_EVENTS / CLOSE_EVENTS, lowercased there."""
    source = (root / "features/common/hooks/message_delivery_hook.py").read_text(encoding="utf-8")
    delivery = {name.strip().strip('"\'') for name in DELIVERY_EVENT_SET.search(source).groups()[0].split(",")}
    close = {name.strip().strip('"\'') for name in CLOSE_EVENT_SET.search(source).groups()[0].split(",")}
    return delivery, close


def test_adapter_delivery_map_routes_pi_events_to_claude_families(root):
    """The translation table maps exactly the three bus events, and its Claude spellings
    are real: families the manifest's claude arms use, and spellings the shared delivery
    script actually routes (its DELIVERY_EVENTS deliver mail, its CLOSE_EVENTS clean up —
    a spelling drift here would silently no-op every pi close event)."""
    delivery_map = _adapter_delivery_map(root)

    assert delivery_map == {
        "session_start": "SessionStart",
        "before_agent_start": "UserPromptSubmit",
        "session_shutdown": "SessionEnd",
    }, delivery_map

    manifest = _hooks_manifest(root)
    manifest_claude_families = _manifest_claude_event_families(manifest)
    assert set(delivery_map.values()) <= manifest_claude_families

    delivery, close = _delivery_hook_event_sets(root)
    for claude_name in delivery_map.values():
        assert claude_name.lower() in delivery | close, (
            f"{claude_name.lower()} is routed by neither DELIVERY_EVENTS nor CLOSE_EVENTS "
            f"in features/common/hooks/message_delivery_hook.py"
        )


def test_adapter_subscribes_to_the_three_delivery_events_via_the_router(root):
    """The delivery arm's subscriptions exist and delegate to the bridge's router.

    A missing subscription means pi sessions never get bus mail on that event: the
    session-start stash, the per-turn live delivery and the close cleanup each need
    their own pi.on(...) wired through createDeliveryRouter/toClaudeDeliveryPayload.
    """
    source = (root / ADAPTER_INDEX_TS).read_text(encoding="utf-8")
    events = set(PI_ON_EVENT.findall(source))

    assert {"session_start", "before_agent_start", "session_shutdown"} <= events, events

    for seam in ("createDeliveryRouter", "toClaudeDeliveryPayload", "parseDeliveryStdout"):
        assert re.search(rf"\b{seam}\b", source), (
            f"index.ts never references {seam} — the delivery arm bypasses the bridge's "
            f"tested translation layer"
        )
