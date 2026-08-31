"""The config-rendered prose slots surface for staleness review, never as drift.

`project.summary` and `project.domain` are the only free-form prose the scaffolder renders
into managed agent files — `{{PROJECT_SUMMARY}}` / `{{PROJECT_DOMAIN}}` via
template_rendering.compute_doc_slots, re-rendered on every scaffold. Fingerprints, version
and config-hash comparisons all stay green while the sentences go stale as the project
evolves: a scaffold faithfully re-renders the same stale words. drift.py and den-refresh now
list the slots — human-written, review for staleness — without ever counting them as drift
or rewriting them: config.json is project-owned (#172).
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from conftest import _test_write

DRIFT = "features/common/skills/welcome-ai-badger/scripts/drift.py"
SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"


def _load_rendering(load_script, root):
    """template_rendering imports its siblings by bare name, as the scaffold runs it."""
    for entry in (str(root / SCRIPTS), str(root / "engine"), str(root / "tooling")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/template_rendering.py")


def _write_config(target, summary="One sentence of prose.", domain="a domain"):
    """Write a config.json whose project carries prose; None omits the key entirely."""
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    project = {"name": "proj"}
    if summary is not None:
        project["summary"] = summary
    if domain is not None:
        project["domain"] = domain
    config = {"project": project}
    _test_write(aib / "config.json", json.dumps(config), encoding="utf-8")
    return config


def _write_manifest(target, config):
    """A minimal manifest drift.main accepts as current: entries empty, configHash matching."""
    bl = load_badger_lib()
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    _test_write(aib / "manifest.json", json.dumps({
        "frameworkVersion": "0.3.0", "agents": [], "entries": [],
        "configHash": bl.config_hash(config),
    }), encoding="utf-8")


def load_badger_lib():
    """engine/badger_lib.py by path — conftest has already put engine/ on sys.path."""
    import badger_lib  # pylint: disable=import-outside-toplevel  # conftest sets sys.path
    return badger_lib


def _mock_framework(tmp_path):
    """A framework root drift.main can read a version from; no catalog, no scripts."""
    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    return fw


# --------------------------------------------------------------------------- drift.prose_review

def test_prose_review_lists_both_prose_slots_with_their_values(tmp_path, load_script):
    """A config with prose in both slots lists each with its config key, slot and value."""
    drift = load_script(DRIFT)
    target = tmp_path / "proj"
    _write_config(target)

    review = drift.prose_review(target)

    assert [(item["configKey"], item["slot"], item["value"]) for item in review] == [
        ("project.summary", "PROJECT_SUMMARY", "One sentence of prose."),
        ("project.domain", "PROJECT_DOMAIN", "a domain"),
    ]
    assert all(item["note"] == "human-written — review for staleness" for item in review)


def test_prose_review_skips_empty_and_missing_prose(tmp_path, load_script):
    """An empty, whitespace-only or absent slot is not listed — there is nothing to review."""
    drift = load_script(DRIFT)
    target = tmp_path / "proj"
    _write_config(target, summary="   \n  ", domain=None)

    assert drift.prose_review(target) == []


def test_prose_review_is_empty_without_a_target_or_a_config(tmp_path, load_script):
    """No target, or no config.json behind it, means nothing to list — and no crash."""
    drift = load_script(DRIFT)

    assert drift.prose_review(None) == []
    assert drift.prose_review(tmp_path / "nowhere") == []


# ------------------------------------------------------------------------------- drift.compare

def test_compare_carries_prose_review_alongside_the_drift_keys(tmp_path, load_script):
    """compare() reports the prose slots in the same dict every caller already reads."""
    drift = load_script(DRIFT)
    target = tmp_path / "proj"
    _write_config(target)
    manifest = {"frameworkVersion": "0.3.0", "agents": [], "entries": []}

    result = drift.compare(tmp_path / "fw", manifest, target=target)

    assert [item["slot"] for item in result["proseReview"]] == [
        "PROJECT_SUMMARY", "PROJECT_DOMAIN"]


# ---------------------------------------------------------------------------------- drift.main

def test_main_lists_the_prose_for_review_without_counting_it_as_drift(
        tmp_path, load_script, capsys):
    """Prose rides the CLI report with the human-written note; the verdict stays 'no drift'."""
    drift = load_script(DRIFT)
    target = tmp_path / "proj"
    config = _write_config(target)
    _write_manifest(target, config)
    fw = _mock_framework(tmp_path)

    rc = drift.main(["--target", str(target), "--root", str(fw)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "human-written" in out
    assert "project.summary" in out
    assert "One sentence of prose." in out
    assert "no drift" in out


def test_main_stays_silent_about_prose_when_the_config_has_none(
        tmp_path, load_script, capsys):
    """No prose, no section — the report does not nag about slots that hold nothing."""
    drift = load_script(DRIFT)
    target = tmp_path / "proj"
    config = _write_config(target, summary=None, domain=None)
    _write_manifest(target, config)
    fw = _mock_framework(tmp_path)

    rc = drift.main(["--target", str(target), "--root", str(fw)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "prose" not in out


# --------------------------------------------------------------- the constant tracks the writer

def test_drifts_slot_list_is_what_the_scaffolder_actually_renders(load_script, root):
    """drift.py duplicates PROSE_SLOTS because it runs standalone; this pin keeps them equal.

    The scaffolder's compute_doc_slots is the only writer of the prose slots. If it ever
    renders another free-form config key (or renames one), this test fails until drift.py's
    copy moves with it — the duplication is the price of a standalone drift.py, the pin is
    what makes it safe.
    """
    drift = load_script(DRIFT)
    rendering = _load_rendering(load_script, root)

    assert drift.PROSE_SLOTS == rendering.PROSE_SLOTS

    ctx = SimpleNamespace(
        config={"project": {"summary": "s prose", "domain": "d prose"},
                "commands": {}, "personaRouting": [], "stacks": []},
        index={"frameworkVersion": "0.0.0"},
        mcp_described=[])
    slots = rendering.TemplateRendering(ctx).compute_doc_slots([], [])
    for key, slot in rendering.PROSE_SLOTS.items():
        assert slots[slot] == {"summary": "s prose", "domain": "d prose"}[key]
