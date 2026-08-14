"""Every agent instruction file must list every marker the hook knows.

The standing list is not decoration. `UserPromptSubmit` fires only when a prompt is
submitted at the start of a turn; a message queued mid-turn reaches the model as a
`queue-operation`/`attachment` record and never passes through the hook, so the marker in it
is never expanded. In that case the standing list in the agent file is the only thing that
tells the agent what the marker means.

Measured 2026-08-14 in a real session transcript: two mid-turn `f:` messages appear only as
`type: "queue-operation"` and `type: "attachment"`, while every turn-start message is a
`type: "user"` record carrying `promptSource`/`origin`. The hook never saw the mid-turn pair.

This test exists because the list drifted exactly that way: `q:` and `i!:` were added to
markers-context.json and to the Hermes files, and the Claude and Copilot files kept listing
three markers.
"""
from __future__ import annotations

import json

import pytest
from conftest import ROOT

MARKERS_FILE = ROOT / "features/common/skills/prompt-markers/markers-context.json"

# The generated agent files come from these; fixing an agent file without fixing its template
# is undone by the next scaffold, which is how the Claude side kept reverting to three markers.
TEMPLATES = (
    ROOT / "features/common/templates/CLAUDE.md.tmpl",
    ROOT / "features/common/templates/HERMES.md.tmpl",
)

SENTINEL = "understands prompt markers"


def _markers():
    return json.loads(MARKERS_FILE.read_text(encoding="utf-8"))["markers"]


def _agent_files():
    found = [p for p in ROOT.rglob("*.md")
             if ".ai-badger/worktrees" not in p.as_posix()
             and "/node_modules/" not in p.as_posix()
             and SENTINEL in p.read_text(encoding="utf-8", errors="ignore")]
    assert found, f"no agent instruction file mentions {SENTINEL!r}"
    return found


def test_the_marker_catalog_is_the_thing_being_compared_against():
    """Guard the guard: a catalog that lost its markers would make every case below vacuous."""
    ids = {m["id"] for m in _markers()}
    assert {"hint", "feedback", "extension"} <= ids
    assert len(ids) >= 5


@pytest.mark.parametrize("marker", _markers(), ids=lambda m: m["id"])
def test_every_template_lists_every_marker(marker):
    """The templates are the source: an agent file fixed without them reverts on re-scaffold."""
    missing = [t.relative_to(ROOT).as_posix() for t in TEMPLATES
               if not all(prefix in t.read_text(encoding="utf-8") for prefix in marker["prefixes"])]
    assert not missing, (
        f"marker {marker['id']!r} ({'/'.join(marker['prefixes'])}) is missing from: "
        f"{', '.join(sorted(missing))}"
    )


def test_templates_say_a_mid_turn_marker_bypasses_the_hook():
    silent = [t.relative_to(ROOT).as_posix() for t in TEMPLATES
              if "mid-turn" not in t.read_text(encoding="utf-8").lower()]
    assert not silent, f"templates never mention the bypass: {', '.join(sorted(silent))}"


@pytest.mark.parametrize("marker", _markers(), ids=lambda m: m["id"])
def test_every_agent_file_lists_every_marker(marker):
    missing = []
    for path in _agent_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not all(prefix in text for prefix in marker["prefixes"]):
            missing.append(path.relative_to(ROOT).as_posix())
    assert not missing, (
        f"marker {marker['id']!r} ({'/'.join(marker['prefixes'])}) is missing from: "
        f"{', '.join(sorted(missing))}. A marker the hook expands but the agent file omits "
        f"is invisible whenever the hook does not fire — which is every mid-turn message."
    )


def test_agent_files_say_a_mid_turn_marker_bypasses_the_hook():
    """The standing list only helps if the agent knows when it has to fall back on it."""
    silent = [p.relative_to(ROOT).as_posix() for p in _agent_files()
              if "mid-turn" not in p.read_text(encoding="utf-8", errors="ignore").lower()]
    assert not silent, (
        f"these agent files list the markers but never say the hook can miss one: "
        f"{', '.join(sorted(silent))}"
    )
