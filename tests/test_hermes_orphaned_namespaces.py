"""Namespaces in ~/.hermes/skills/ whose project is gone: reported by default, pruned on request.

Found by dogfooding, not by a test: every test here patches `$HOME`, so the suite could not see
the 31 dangling links a real `~/.hermes` had accumulated — two namespaces orphaned by a project
rename and a deleted mktemp scaffold, plus one stale link the per-namespace relink already owns.

The dangerous half is the other direction. `~/.hermes/skills/` also holds Hermes's own category
directories (`react`, `devops`, `uncategorized`), which ai-badger did not create and must never
remove. Every test below runs against a fixture Hermes home; none touches the real one.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"
REFRESH = "features/common/skills/den-refresh/scripts/refresh.py"


@pytest.fixture(name="delivery")
def _delivery(load_script, root):
    """welcome-ai-badger's skill_delivery module, with its sibling modules importable."""
    for entry in (str(root / SCRIPTS), str(root / "engine"), str(root / "tooling")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/skill_delivery.py")


@pytest.fixture(name="hermes")
def _hermes(tmp_path, monkeypatch):
    """A Hermes skills root of our own. HERMES_HOME keeps the real ~/.hermes out of reach."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    skills = tmp_path / "hermes-home" / "skills"
    skills.mkdir(parents=True)
    return skills


def _project(tmp_path, name, skills=("task", "prompt-markers")):
    """A project whose `.ai-badger/skills/` holds real skill directories."""
    root = tmp_path / name / ".ai-badger" / "skills"
    for skill in skills:
        (root / skill).mkdir(parents=True)
        (root / skill / "SKILL.md").write_text(f"# {skill}\n", encoding="utf-8")
    return root


def _namespace(hermes, name, skills_root, links=("task", "prompt-markers")):
    """A namespace of relative symlinks into `skills_root`, the shape scaffold.py writes."""
    namespace = hermes / name
    namespace.mkdir(parents=True, exist_ok=True)
    for skill in links:
        (namespace / skill).symlink_to(
            os.path.relpath(skills_root / skill, namespace))
    return namespace


def _hermes_category(hermes, name="react"):
    """A directory of Hermes's own: real skill folders, no symlink anywhere in it."""
    category = hermes / name
    (category / "hooks-discipline").mkdir(parents=True)
    (category / "hooks-discipline" / "SKILL.md").write_text("# hand-written\n", encoding="utf-8")
    return category


def _orphan(tmp_path, hermes, name="AiRaccon"):
    """A namespace whose whole target tree has been deleted — the defect, reproduced."""
    skills_root = _project(tmp_path, name)
    namespace = _namespace(hermes, name, skills_root)
    shutil.rmtree(tmp_path / name)
    return namespace


# ------------------------------------------------------------------ what counts as orphaned
def test_a_namespace_whose_target_tree_is_gone_is_reported(tmp_path, hermes, delivery):
    """The default names the orphan and its dead target; nothing on disk moves."""
    namespace = _orphan(tmp_path, hermes)

    found = delivery.prune_namespaces()

    assert [n.path for n in found] == [namespace]
    assert found[0].status == "reported"
    assert found[0].links == 2
    assert found[0].target.endswith("/.ai-badger/skills")
    assert namespace.is_dir()
    assert sorted(p.name for p in namespace.iterdir()) == ["prompt-markers", "task"]


def test_a_live_namespace_is_not_an_orphan(tmp_path, hermes, delivery):
    """Its project is still on disk, so nothing about it is stale."""
    _namespace(hermes, "live", _project(tmp_path, "live"))

    assert delivery.prune_namespaces() == []


def test_a_partly_dangling_namespace_is_not_an_orphan(tmp_path, hermes, delivery):
    """One dead link means one removed skill; the per-namespace relink owns that case."""
    skills_root = _project(tmp_path, "half")
    namespace = _namespace(hermes, "half", skills_root)
    shutil.rmtree(skills_root / "task")

    assert delivery.prune_namespaces() == []
    assert (namespace / "task").is_symlink()


# --------------------------------------------------- anything ai-badger did not create is safe
def test_a_hermes_category_is_never_reported(hermes, delivery):
    """`react`, `devops`, `uncategorized` — real directories of Hermes's own, not our links."""
    _hermes_category(hermes)

    assert delivery.prune_namespaces() == []


def test_a_hermes_category_survives_an_explicit_prune(tmp_path, hermes, delivery):
    """The flag deletes orphans and nothing else — this is the one that must never regress."""
    category = _hermes_category(hermes)
    empty = hermes / "uncategorized"
    empty.mkdir()
    outside = hermes / "personal"
    outside.mkdir()
    (outside / "notes").symlink_to("../../elsewhere/notes")
    orphan = _orphan(tmp_path, hermes)

    found = delivery.prune_namespaces(execute=True)

    assert [n.path for n in found] == [orphan]
    assert not orphan.exists()
    assert (category / "hooks-discipline" / "SKILL.md").read_text(
        encoding="utf-8") == "# hand-written\n"
    assert empty.is_dir()
    assert outside.is_dir() and (outside / "notes").is_symlink()


def test_a_namespace_holding_one_foreign_entry_is_left_whole(tmp_path, hermes, delivery):
    """A Hermes-authored skill sitting beside our dead links makes the directory not ours."""
    namespace = _orphan(tmp_path, hermes)
    (namespace / "agent-skill-discovery").mkdir()

    assert delivery.prune_namespaces(execute=True) == []
    assert namespace.is_dir()


def test_a_symlinked_namespace_is_left_whole(tmp_path, hermes, delivery):
    """We create namespaces as directories; a link in that slot is somebody else's arrangement."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (hermes / "linked").symlink_to(elsewhere)

    assert delivery.prune_namespaces(execute=True) == []
    assert (hermes / "linked").is_symlink()


# ------------------------------------------------------------------------------- the prune
def test_prune_removes_the_orphan_only_when_asked(tmp_path, hermes, delivery):
    orphan = _orphan(tmp_path, hermes)

    assert delivery.prune_namespaces()[0].status == "reported" and orphan.is_dir()

    removed = delivery.prune_namespaces(execute=True)

    assert removed[0].status == "removed" and not orphan.exists()


def test_re_running_after_a_prune_finds_nothing(tmp_path, hermes, delivery):
    _orphan(tmp_path, hermes)
    delivery.prune_namespaces(execute=True)

    assert delivery.prune_namespaces(execute=True) == []


def test_the_report_names_the_flag_that_acts_on_it(tmp_path, hermes, delivery):
    """A finding with no next step is a finding nobody acts on."""
    _orphan(tmp_path, hermes)

    assert "--prune-namespaces" in delivery.prune_namespaces()[0].detail


# --------------------------------------------------------------- den-refresh reports it
def _scaffolded(tmp_path, root, make_scaffolder):
    """A mock framework and a project scaffolded from it, ready for refresh.main."""
    from test_den_refresh import _mock_fw_with_skills, _write_config  # noqa: E402

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    return fw, proj


def test_den_refresh_reports_the_orphan_and_leaves_it(
        tmp_path, hermes, load_script, root, capsys, make_scaffolder):
    refresh = load_script(REFRESH)
    fw, proj = _scaffolded(tmp_path, root, make_scaffolder)
    orphan = _orphan(tmp_path, hermes)

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert [n["path"] for n in report["hermesNamespaces"]] == [str(orphan)]
    assert report["hermesNamespaces"][0]["status"] == "reported"
    assert orphan.is_dir()


def test_den_refresh_prunes_the_orphan_under_the_flag(
        tmp_path, hermes, load_script, root, capsys, make_scaffolder):
    refresh = load_script(REFRESH)
    fw, proj = _scaffolded(tmp_path, root, make_scaffolder)
    orphan = _orphan(tmp_path, hermes)
    category = _hermes_category(hermes)

    rc = refresh.main(["--target", str(proj), "--root", str(fw), "--prune-namespaces"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["hermesNamespaces"][0]["status"] == "removed"
    assert not orphan.exists()
    assert (category / "hooks-discipline" / "SKILL.md").is_file()


def test_den_refresh_says_nothing_when_no_namespace_is_orphaned(
        tmp_path, hermes, load_script, root, capsys, make_scaffolder):
    """A section that appears every run is a section nobody reads."""
    refresh = load_script(REFRESH)
    fw, proj = _scaffolded(tmp_path, root, make_scaffolder)
    _hermes_category(hermes)

    refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert "hermesNamespaces" not in report


# ------------------------------------------------------------------------ the skill's own words
def test_the_skill_tells_the_agent_to_ask_before_pruning():
    """The flag is the user's to grant: the procedure has to present the report and ask."""
    skill = (Path(__file__).resolve().parents[1]
             / "features/common/skills/den-refresh/SKILL.md").read_text(encoding="utf-8")

    assert "--prune-namespaces" in skill
    assert "hermesNamespaces" in skill
    step = skill[skill.index("hermesNamespaces"):]
    assert "ask" in step.lower()
