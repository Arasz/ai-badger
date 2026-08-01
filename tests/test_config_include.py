"""`config.include`: the project names an `optIn` catalog skill and both entry points obey.

The enforcement point is `Scaffolder.__init__`, the same one `config.exclude` uses, so
`welcome-ai-badger` and `den-refresh` cannot disagree about what a project asked for.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
REFRESH = "features/common/skills/den-refresh/scripts/refresh.py"
OPT_IN_SKILL = "update-documentation"


def _including(*names, exclude=None) -> dict:
    config = _config(agents=["claude"])
    config["include"] = {"skills": list(names)}
    if exclude is not None:
        config["exclude"] = {"skills": list(exclude)}
    return config


def _scaffold(make_scaffolder, config, skills=("task",)):
    target = make_scaffolder.target
    scaf = make_scaffolder(config=config, skills=list(skills))
    result = scaf.run(generated_at="2026-08-01T00:00:00Z")
    return target, result


# ------------------------------------------------------------------------------- schema
def test_config_schema_accepts_an_include_block(load_script, root):
    bl = load_script("engine/badger_lib.py")

    assert bl.validate(_including(OPT_IN_SKILL),
                       bl.load_json(root / "schemas" / "config.schema.json")) == []


def test_config_schema_rejects_an_unknown_include_key(load_script, root):
    """A typo must fail validation rather than silently include nothing."""
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"])
    config["include"] = {"skils": [OPT_IN_SKILL]}

    assert bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))


def test_config_schema_rejects_an_empty_skill_name(load_script, root):
    bl = load_script("engine/badger_lib.py")

    assert bl.validate(_including(""), bl.load_json(root / "schemas" / "config.schema.json"))


def test_config_schema_include_is_an_object_not_a_bare_array(load_script, root):
    """The object shape is what leaves room for include.personas later."""
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"])
    config["include"] = [OPT_IN_SKILL]

    assert bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))


# -------------------------------------------------------------------------- inclusions()
def test_inclusions_mirrors_exclusions(load_script):
    bl = load_script("engine/badger_lib.py")

    assert bl.inclusions(_including(OPT_IN_SKILL))["skills"] == {OPT_IN_SKILL}


def test_inclusions_tolerates_a_malformed_block(load_script):
    """Drift reads configs this library never validated; a refusal breaks the refresh."""
    bl = load_script("engine/badger_lib.py")

    assert bl.inclusions({"include": "nope"})["skills"] == set()
    assert bl.inclusions({"include": {"skills": [1, OPT_IN_SKILL]}})["skills"] == {OPT_IN_SKILL}
    assert bl.inclusions({})["skills"] == set()


# ------------------------------------------------------------------------------ delivery
def test_an_included_opt_in_skill_is_delivered(make_scaffolder):
    target, result = _scaffold(make_scaffolder, _including(OPT_IN_SKILL))

    assert (target / ".ai-badger" / "skills" / OPT_IN_SKILL / "SKILL.md").is_file()
    names = [e["name"] for e in result["manifest"]["entries"] if e["feature"] == "skills"]
    assert OPT_IN_SKILL in names


def test_an_opt_in_skill_nobody_asked_for_is_not_delivered(make_scaffolder):
    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]))

    assert not (target / ".ai-badger" / "skills" / OPT_IN_SKILL).exists()


def test_exclude_wins_over_include(make_scaffolder):
    """A name in both is declined: the project's refusal outranks its request."""
    target, result = _scaffold(
        make_scaffolder, _including(OPT_IN_SKILL, exclude=[OPT_IN_SKILL]))

    assert not (target / ".ai-badger" / "skills" / OPT_IN_SKILL).exists()
    assert any(OPT_IN_SKILL in n and "exclude" in n for n in result["notes"])


# --------------------------------------------------------------------- notes, never fatal
def test_an_inclusion_matching_no_catalog_skill_is_reported_and_not_fatal(make_scaffolder):
    """An upstream deletion must not break the next refresh — the `_note_exclusions` precedent."""
    target, result = _scaffold(make_scaffolder, _including("no-such-skill"))

    assert (target / ".ai-badger" / "manifest.json").exists()
    assert any("no-such-skill" in n and "matches no" in n for n in result["notes"])


def test_including_a_default_skill_is_reported_and_not_fatal(make_scaffolder):
    """A default-scope skill is already installed; naming it is a no-op worth saying out loud."""
    target, result = _scaffold(make_scaffolder, _including("call-behaviorist"))

    assert (target / ".ai-badger" / "manifest.json").exists()
    assert any("call-behaviorist" in n and "already" in n for n in result["notes"])


# ------------------------------------------------------------------------- availableOptIn
def test_the_scaffold_report_lists_the_opt_in_skills_the_project_has_not_installed(
        make_scaffolder):
    _, result = _scaffold(make_scaffolder, _config(agents=["claude"]))

    offered = {s["name"]: s for s in result["availableOptIn"]}
    assert OPT_IN_SKILL in offered
    entry = offered[OPT_IN_SKILL]
    assert entry["description"] and entry["description"] != "(no description)"
    assert OPT_IN_SKILL in entry["configEdit"] and "include" in entry["configEdit"]


def test_an_installed_opt_in_skill_is_no_longer_offered(make_scaffolder):
    _, result = _scaffold(make_scaffolder, _including(OPT_IN_SKILL))

    assert OPT_IN_SKILL not in [s["name"] for s in result["availableOptIn"]]


def test_a_default_skill_is_never_offered_as_opt_in(make_scaffolder):
    _, result = _scaffold(make_scaffolder, _config(agents=["claude"]))

    assert "call-behaviorist" not in [s["name"] for s in result["availableOptIn"]]


def test_the_offered_description_is_the_skills_own_frontmatter(load_script, root,
                                                               make_scaffolder):
    bl = load_script("engine/badger_lib.py")
    _, result = _scaffold(make_scaffolder, _config(agents=["claude"]))

    offered = {s["name"]: s["description"] for s in result["availableOptIn"]}
    on_disk = bl.skill_description(
        root / "features" / "common" / "skills" / OPT_IN_SKILL / "SKILL.md")
    assert offered[OPT_IN_SKILL] == on_disk


# --------------------------------------------------------------- the description extractor
def test_skill_description_reads_a_folded_block(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: probe\ndescription: >-\n  first line\n  second line\nversion: 1.0.0\n---\n"
        "# body\n", encoding="utf-8")

    assert bl.skill_description(skill_md) == "first line second line"


def test_skill_description_reads_a_plain_scalar(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: probe\ndescription: one liner\n---\n", encoding="utf-8")

    assert bl.skill_description(skill_md) == "one liner"


def test_skill_description_degrades_to_none_rather_than_raising(tmp_path, load_script):
    """Reporting only (ADR-0005): no YAML dependency, and any parse miss is None."""
    bl = load_script("engine/badger_lib.py")
    cases = {
        "missing.md": None,
        "no-frontmatter.md": "# just a heading\n",
        "unterminated.md": "---\nname: probe\ndescription: x\n",
        "no-description.md": "---\nname: probe\n---\n",
        "empty-block.md": "---\ndescription: >-\n---\n",
        "binary.md": "\x00\x01---\n",
    }
    for name, body in cases.items():
        path = tmp_path / name
        if body is not None:
            path.write_text(body, encoding="utf-8")

        assert bl.skill_description(path) is None, name


def test_an_unreadable_description_degrades_to_a_placeholder_not_an_omission(load_script):
    """A skill with no parseable description is still offered, with a stand-in string."""
    bl = load_script("engine/badger_lib.py")

    assert bl.NO_DESCRIPTION == "(no description)"


# ----------------------------------------------------------------------- den-refresh path
def _edit_config(target, **updates):
    """Patch target/.ai-badger/config.json in place — a hand edit, not a re-scaffold."""
    config_path = target / ".ai-badger" / "config.json"
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    on_disk.update(updates)
    config_path.write_text(json.dumps(on_disk), encoding="utf-8")
    return on_disk


def test_refresh_delivers_a_skill_included_after_the_last_scaffold(
        load_script, root, make_scaffolder, capsys):
    """The path that matters: refresh re-derives skills from the manifest, so it can no-op."""
    refresh = load_script(REFRESH)
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-08-01T00:00:00Z")
    assert not (target / ".ai-badger" / "skills" / OPT_IN_SKILL).exists()

    _edit_config(target, include={"skills": [OPT_IN_SKILL]})

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["drift"]["configChanged"] is not None
    assert report["reScaffolded"] is True
    assert OPT_IN_SKILL in report["scaffold"]["refreshedSkills"]
    assert (target / ".ai-badger" / "skills" / OPT_IN_SKILL / "SKILL.md").is_file()


def test_refresh_reports_the_opt_in_skills_still_available(
        load_script, root, make_scaffolder, capsys):
    refresh = load_script(REFRESH)
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-08-01T00:00:00Z")

    refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    offered = {s["name"]: s for s in report["availableOptIn"]}
    assert OPT_IN_SKILL in offered
    assert offered[OPT_IN_SKILL]["configEdit"]


def test_an_opt_in_skill_is_never_reported_as_drift(load_script, root, make_scaffolder):
    """Otherwise every refresh nags to install a skill nobody asked for, and never quiets."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    manifest = make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-08-01T00:00:00Z")["manifest"]

    result = drift.compare(root, manifest, stacks=["common"], target=target)

    assert OPT_IN_SKILL not in [i["name"] for i in result["newItems"]]
