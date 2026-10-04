"""tests/test_project_id_registration.py — the shared project-id flow.

ensure_project_id is the one mint site: a missing or blank .ai-badger/project-id reuses
the id ai-raccoon already knows by name, or mints a uuid4 and registers it; a present id
is never rewritten and costs exactly one register when it is a uuid. Every branch here
drives tests/raccoon_cli_fake.py and names its proving mutation.

The session conftest sets AI_BADGER_RACCOON_REGISTER=0, so no other test can reach a real
ai-raccoon; a test that wants the fake must delenv the switch.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from raccoon_cli_fake import raccoon_cli_fake  # noqa: F401  (fixture)
from scaffold_helpers import _config

_GIT_ENV = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _git(*args, cwd):
    subprocess.run(["git", *_GIT_ENV, *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def project_id_script(load_script):
    return load_script("features/common/skills/welcome-ai-badger/scripts/project_id.py")


@pytest.fixture
def scaffold_module(load_script, monkeypatch, tmp_path):
    """The real scaffolder with HOME redirected so no live cache is consulted."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")


def _scaffold_into(scaffold_module, root, tmp_path, target, install: bool) -> None:
    """Scaffold into `target` from the real framework root (no live cache consult)."""
    cache = tmp_path / "home" / ".ai-badger" / "framework"
    for name in ("schemas", "features", "engine"):
        (cache / name).mkdir(parents=True, exist_ok=True)
    (cache / "VERSION").write_text("0.13.0\n", encoding="utf-8")
    (cache / "engine" / "badger_lib.py").write_bytes(b"")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config(stacks=["python"])), encoding="utf-8")
    argv = ["--config", str(config_path), "--target", str(target),
            "--root", str(root), "--skills", ""]
    if not install:
        argv.append("--no-install")
    assert scaffold_module.main(argv) == 0


def _drive_fake(monkeypatch, project_id_script) -> None:
    """Let a test reach the fake: the session conftest switch is off by design."""
    monkeypatch.delenv(project_id_script.REGISTER_SWITCH, raising=False)


def _fresh_aib(tmp_path, name="proj"):
    target = tmp_path / name
    aib = target / ".ai-badger"
    aib.mkdir(parents=True)
    return target, aib


# ------------------------------------------------------------- missing / blank file
def test_missing_file_reuses_a_legacy_hit(project_id_script, raccoon_cli_fake,
                                          tmp_path, monkeypatch):
    """A hit is written verbatim; register is not called (the bank already knows it).

    Mutation: always mint (the legacy hit is ignored).
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK,
                                 "stdout": "legacy-name\n"})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    assert (project_id, notes) == ("legacy-name", [])
    assert (aib / "project-id").read_text(encoding="utf-8") == "legacy-name\n"
    assert len(raccoon_cli_fake.calls()) == 1


def test_missing_file_not_found_mints_and_registers_once(project_id_script, raccoon_cli_fake,
                                                         tmp_path, monkeypatch):
    """Not-found: mint a uuid4, then register it once with the project name.

    Mutation: register before checking (a not-found would register the wrong id), or skip
    the register.
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_PROJECT_UNKNOWN},
                            register={"exit": project_id_script.EXIT_OK})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    uuid.UUID(project_id)
    assert notes == []
    assert (aib / "project-id").read_text(encoding="utf-8") == project_id + "\n"
    calls = raccoon_cli_fake.calls()
    assert len(calls) == 2
    register_argv = calls[1]["argv"]
    assert "register" in register_argv and project_id in register_argv
    assert register_argv[register_argv.index("--name") + 1] == "proj"


def test_missing_file_ambiguous_mints_with_the_note(project_id_script, raccoon_cli_fake,
                                                    tmp_path, monkeypatch):
    """Ambiguous: mint, do NOT register, and keep the warning for the report.

    Mutation: register after ambiguous (a second project under an ambiguous name).
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_PROJECT_AMBIGUOUS,
                                 "stderr": "Candidates:\nlegacy-a\nlegacy-b\n"})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    uuid.UUID(project_id)
    assert len(notes) == 1
    assert "several projects" in notes[0] and "legacy-a" in notes[0]
    assert len(raccoon_cli_fake.calls()) == 1


def test_missing_file_malformed_mints_with_the_note(project_id_script, raccoon_cli_fake,
                                                    tmp_path, monkeypatch):
    """Mutation: register after a malformed reply (it may not even be a real id)."""
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK, "stdout": "two\nlines\n"})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    uuid.UUID(project_id)
    assert len(notes) == 1 and "not one valid project id" in notes[0]
    assert len(raccoon_cli_fake.calls()) == 1


@pytest.mark.parametrize("case", ["unparseable", "key-band", "server-band", "timeout"])
def test_missing_file_unavailable_bands_mint_with_the_note(project_id_script,
                                                           raccoon_cli_fake, tmp_path,
                                                           monkeypatch, case):
    """Every unavailable band mints silently-or-with-a-warning and never registers.

    Mutation: treat any unavailable band as not-found (mint AND register).
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    codes = {"unparseable": project_id_script.EXIT_UNPARSEABLE,
             "key-band": project_id_script.KEY_BAND[0],
             "server-band": project_id_script.SERVER_BAND[0],
             "timeout": project_id_script.TIMEOUT_CODE}
    raccoon_cli_fake.script(get={"exit": codes[case]})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    uuid.UUID(project_id)
    assert len(notes) == 1 and notes[0]
    assert len(raccoon_cli_fake.calls()) == 1


def test_missing_file_missing_executable_mints_silently(project_id_script, raccoon_cli_fake,
                                                        tmp_path, monkeypatch):
    """No ai-raccoon at all: mint silently, no note and no call.

    Mutation: attach a warning to the missing-executable branch.
    """
    _drive_fake(monkeypatch, project_id_script)
    monkeypatch.setenv("PATH", "")
    _target, aib = _fresh_aib(tmp_path)

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    uuid.UUID(project_id)
    assert notes == []
    assert raccoon_cli_fake.arcs() == []


def test_blank_file_is_treated_as_missing(project_id_script, raccoon_cli_fake, tmp_path,
                                          monkeypatch):
    """A whitespace-only id is not an identity; the flow mints and registers over it.

    Mutation: an exists()-only check (the blank is returned and kept on disk).
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    (aib / "project-id").write_text("  \n", encoding="utf-8")
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_PROJECT_UNKNOWN},
                            register={"exit": project_id_script.EXIT_OK})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    uuid.UUID(project_id)
    assert notes == []
    assert len(raccoon_cli_fake.calls()) == 2


# ------------------------------------------------------------- present file
def test_present_uuid_costs_exactly_one_register(project_id_script, raccoon_cli_fake,
                                                 tmp_path, monkeypatch):
    """The file is the identity: never rewritten, never looked up, registered once.

    Mutation: skip registration for a present file, or call get.
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    guid = str(uuid.uuid4())
    (aib / "project-id").write_text(guid + "\n", encoding="utf-8")
    raccoon_cli_fake.script(register={"exit": project_id_script.EXIT_OK})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    assert (project_id, notes) == (guid, [])
    assert (aib / "project-id").read_text(encoding="utf-8") == guid + "\n"
    calls = raccoon_cli_fake.calls()
    assert len(calls) == 1
    assert "register" in calls[0]["argv"] and "get" not in calls[0]["argv"]


def test_present_uuid_retired_reports_and_does_not_retry(project_id_script,
                                                         raccoon_cli_fake, tmp_path,
                                                         monkeypatch):
    """A retired id is a human's problem; nothing retries and the file is unchanged.

    Mutation: drop the note, or call register twice.
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    guid = str(uuid.uuid4())
    (aib / "project-id").write_text(guid + "\n", encoding="utf-8")
    raccoon_cli_fake.script(register={"exit": project_id_script.EXIT_PROJECT_UNKNOWN})

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    assert project_id == guid
    assert len(notes) == 1 and "retired" in notes[0]
    assert len(raccoon_cli_fake.calls()) == 1
    assert (aib / "project-id").read_text(encoding="utf-8") == guid + "\n"


def test_present_non_guid_is_skipped_silently(project_id_script, raccoon_cli_fake,
                                              tmp_path, monkeypatch):
    """Register only accepts guids: a legacy file id is left exactly as it is.

    Mutation: register any id (a legacy id reaches a verb that cannot take it).
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)
    (aib / "project-id").write_text("ai-badger\n", encoding="utf-8")

    project_id, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)

    assert (project_id, notes) == ("ai-badger", [])
    assert raccoon_cli_fake.arcs() == []
    assert (aib / "project-id").read_text(encoding="utf-8") == "ai-badger\n"


def test_raccoon_false_never_calls_and_never_rewrites(project_id_script, raccoon_cli_fake,
                                                      tmp_path, monkeypatch):
    """A --no-install scaffold mints without the binary; a present file stays untouched.

    Mutation: ignore the raccoon flag (a --no-install scaffold reaches the bank).
    """
    _drive_fake(monkeypatch, project_id_script)
    _target, aib = _fresh_aib(tmp_path)

    minted, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=False)
    uuid.UUID(minted)
    assert notes == []
    assert raccoon_cli_fake.arcs() == []

    guid = str(uuid.uuid4())
    (aib / "project-id").write_text(guid + "\n", encoding="utf-8")
    kept, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=False)
    assert (kept, notes) == (guid, [])
    assert raccoon_cli_fake.arcs() == []


# ------------------------------------------------------------- den-refresh wiring
def test_den_refresh_reports_one_register_and_no_second_call(scaffold_module, root,
                                                             tmp_path, raccoon_cli_fake,
                                                             project_id_script, load_script,
                                                             monkeypatch, capsys):
    """Step 1c registers the present uuid once; its note rides report.projectIdWarning and
    the re-scaffold (install=False) adds no second call.

    Mutation: attach the note to the wrong report key, or register again inside the
    re-scaffold; or run without --force so the re-scaffold never happens (then assert the
    report's scaffold key is missing, failing the vacuity guard).
    """
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    _drive_fake(monkeypatch, project_id_script)
    target = tmp_path / "refresh-proj"
    target.mkdir()
    _scaffold_into(scaffold_module, root, tmp_path, target, install=False)
    id_file = target / ".ai-badger" / "project-id"
    before = id_file.read_bytes()
    raccoon_cli_fake.script(register={"exit": project_id_script.EXIT_UNPARSEABLE})

    rc = refresh.main(["--target", str(target), "--root", str(root), "--force"])

    assert rc == 0
    out = capsys.readouterr().out
    # refresh.main prints advisory lines before the report; the report is the last object.
    report = json.loads(out[out.rindex("\n{") + 1:])
    assert "scaffold" in report, "--force must exercise the re-scaffold, not a vacuous run"
    assert "1.57.0" in report["projectIdWarning"]
    calls = raccoon_cli_fake.calls()
    assert len(calls) == 1
    assert "register" in calls[0]["argv"] and "get" not in calls[0]["argv"]
    assert id_file.read_bytes() == before


# ------------------------------------------------------------- project_name
def test_project_name_collapses_a_linked_worktree_to_the_main_checkout(project_id_script,
                                                                       tmp_path):
    """A worktree must ask the bank for the repo's name, never the worktree's own.

    Mutation: take the on-disk basename directly (an unregistered worktree project).
    """
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _git("init", "-q", cwd=main_repo)
    (main_repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "README.md", cwd=main_repo)
    _git("commit", "-q", "-m", "initial", cwd=main_repo)
    worktree = tmp_path / "worktrees" / "task-branch"
    worktree.parent.mkdir(parents=True)
    _git("worktree", "add", "-q", "-b", "task-branch", str(worktree), cwd=main_repo)

    assert project_id_script.project_name(worktree) == "main-repo"
    assert project_id_script.project_name(main_repo) == "main-repo"


def test_project_name_recovers_the_on_disk_case(project_id_script, tmp_path):
    """A checkout whose spelling differs in case still asks for the on-disk name.

    Mutation: return Path(target).name when the on-disk entry differs only in case.
    """
    actual = tmp_path / "MyProject"
    actual.mkdir()

    assert project_id_script.project_name(tmp_path / "myproject") == "MyProject"


def test_project_name_falls_back_to_the_resolved_basename(project_id_script, tmp_path):
    """No git, no on-disk entry: the resolved path's basename answers.

    Mutation: crash on a missing directory.
    """
    missing = tmp_path / "not-there" / "proj"
    assert project_id_script.project_name(missing) == "proj"


# ------------------------------------------------------------- scaffold wiring
def test_scaffold_stdout_never_carries_cli_output(scaffold_module, root,
                                                 tmp_path, raccoon_cli_fake,
                                                 monkeypatch, capfd):
    """An installing scaffold registers under the project name; CLI output stays captured.

    Mutation: skip the flow for install=True, or pass the wrong name, or let _run inherit
    stdout/stderr (the fake's 'registered ...' line lands on the scaffold's fd 1 — capfd,
    not capsys, is what can see an inherited descriptor).
    """
    monkeypatch.delenv("AI_BADGER_RACCOON_REGISTER", raising=False)
    target = tmp_path / "wire-proj"
    target.mkdir()
    raccoon_cli_fake.script(
        get={"exit": 18},
        register={"exit": 0, "stdout": "registered 11111111-1111-1111-1111-111111111111\n",
                  "stderr": "fake-raccoon: warning\n"})

    _scaffold_into(scaffold_module, root, tmp_path, target, install=True)

    calls = raccoon_cli_fake.calls()
    assert len(calls) == 2
    register_argv = calls[1]["argv"]
    assert "register" in register_argv
    assert register_argv[register_argv.index("--name") + 1] == "wire-proj"
    out = capfd.readouterr().out
    assert "registered" not in out
    assert "fake-raccoon" not in out


def test_no_install_scaffold_makes_zero_calls(scaffold_module, root, tmp_path,
                                              raccoon_cli_fake, monkeypatch):
    """--no-install is the gate for registration, not just for plugin commands.

    Mutation: ignore self.install (a --no-install scaffold reaches the bank).
    """
    monkeypatch.delenv("AI_BADGER_RACCOON_REGISTER", raising=False)
    target = tmp_path / "noinstall-proj"
    target.mkdir()

    _scaffold_into(scaffold_module, root, tmp_path, target, install=False)

    minted = (target / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip()
    uuid.UUID(minted)
    assert raccoon_cli_fake.arcs() == []


def test_switch_off_covers_missing_and_present_files(project_id_script, raccoon_cli_fake,
                                                     tmp_path, monkeypatch):
    """The kill switch is checked once, before any verb; both file states make no call.

    Mutation: check the switch in lookup only (a present uuid still registers).
    """
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "0")
    _target, aib = _fresh_aib(tmp_path)

    minted, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)
    uuid.UUID(minted)
    assert notes == []

    guid = str(uuid.uuid4())
    (aib / "project-id").write_text(guid + "\n", encoding="utf-8")
    kept, notes = project_id_script.ensure_project_id(aib, "proj", raccoon=True)
    assert (kept, notes) == (guid, [])
    assert raccoon_cli_fake.arcs() == []


def test_subprocess_with_inherited_env_makes_zero_calls(project_id_script,
                                                        raccoon_cli_fake, tmp_path,
                                                        monkeypatch):
    """A child spawned with env=dict(os.environ) must inherit the switch too.

    Mutation: remove the conftest setenv (the child then reaches the fake on PATH).
    """
    _target, aib = _fresh_aib(tmp_path)
    code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(Path(project_id_script.__file__).parent)!r}); "
        "import project_id as p; "
        f"r = p.ensure_project_id(Path({str(aib)!r}), 'proj', raccoon=True); "
        "assert r[1] == [], r"
    )

    done = subprocess.run([sys.executable, "-c", code], env=dict(os.environ),
                          capture_output=True, text=True, timeout=60, check=False)

    assert done.returncode == 0, done.stderr
    assert raccoon_cli_fake.arcs() == []