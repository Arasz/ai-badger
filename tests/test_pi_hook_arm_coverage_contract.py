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
approach (D1): it registers exactly one `pi.on("tool_call", ...)` handler that *dynamically*
reads the project's `.ai-badger/hooks/hooks.json` at call time and runs every PreToolUse
command it finds — no per-hook-name registration exists to compare against the manifest's
arms, and adding "pi" as a fourth `HOOK_CAPABLE_AGENTS` member would ask for something the
adapter was deliberately built not to need. So "pi" is absent from both sides today, on
purpose, and this file asserts that absence rather than fabricating a false equivalence between
a set of pi extension-API event names and a set of agent identifiers — two different kinds of
thing that happen to both be called "coverage" in prose.

What still gets checked, and what would actually go red:
  - the adapter keeps at least one live `pi.on(...)` subscription (a regression to zero would
    mean the extension loads and does nothing);
  - the Claude-vocabulary event name the adapter hardcodes into every gate payload
    (`hook_event_name: "PreToolUse"`) is still one of the event families the manifest's own
    claude arms actually use — catching a rename on either side;
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


def test_adapter_claude_event_name_is_a_real_manifest_event_family(root):
    """The Claude-vocabulary event name the adapter hardcodes must still exist in the manifest.

    hook-bridge.ts's toClaudePayload always stamps `hook_event_name: "PreToolUse"` onto the
    JSON it hands the Python hooks; if hooks-manifest.json's own claude arms ever renamed that
    family (or the adapter typo'd it), the two would silently stop meaning the same event.
    """
    adapter_claude_events = _adapter_claude_event_names(root)
    manifest = _hooks_manifest(root)
    manifest_claude_families = _manifest_claude_event_families(manifest)

    assert adapter_claude_events, "no hook_event_name literal found in adapter/hook-bridge.ts"
    assert adapter_claude_events <= manifest_claude_families, (
        f"adapter/hook-bridge.ts hardcodes {adapter_claude_events!r}, which is not among the "
        f"manifest's own claude event families {manifest_claude_families!r}"
    )


def test_adapter_stamps_exactly_the_event_family_its_loader_reads(root):
    """The payload stamp and the hooks.json group the loader reads must be the same family.

    A rename on the manifest side is caught by the membership test above (the stamped name
    would fall outside the manifest's families). This test closes the other direction, which
    a subset check cannot see: renaming the stamped literal to PostToolUse stays inside the
    manifest's families (they include PostToolUse) while the loader still reads the PreToolUse
    group — the two sides would silently stop meaning the same event. The loader's group key
    is regexed from hook-bridge.ts's own `hooks?.<Group>` read, so both sides of the equality
    are derived, not copied.
    """
    stamped = _adapter_claude_event_names(root)
    loader_groups = _adapter_payload_loader_groups(root)

    assert loader_groups == {"PreToolUse"}, loader_groups
    assert stamped == loader_groups, (
        f"hook-bridge.ts stamps {stamped!r} but its loader reads the {loader_groups!r} group "
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
        f"single dynamic pi.on('tool_call', ...) handler and the manifest's per-hook-name arm "
        f"model have diverged from the D1 design; reconcile which one is authoritative before "
        f"changing this assertion"
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
