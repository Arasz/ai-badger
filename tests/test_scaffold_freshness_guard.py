"""Tests for gates/scaffold_freshness_guard.py: the self-scaffold must be reproducible.

The defect (issue #206): a PR edits `features/**`, never re-scaffolds, and ships a
`.ai-badger/` that describes a tree that no longer exists. The gate re-runs the scaffolder in
a throwaway copy and fails on any non-stamp difference. Fixtures here are copies of this repo,
made fresh by construction (scaffolded once before the test mutates them), so a stale real
tree fails the gate's own lane rather than these tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _test_write

import badger_lib as bl

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "gates" / "scaffold_freshness_guard.py"
SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
SKILL_SOURCE = "features/common/skills/welcome-ai-badger"
SKILL_MIRROR = ".ai-badger/skills/welcome-ai-badger"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True).stdout


def _copy_working_tree(dest: Path) -> Path:
    """Copy this repo's tracked + untracked-unignored files into `dest`, symlinks preserved."""
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"],
                         cwd=str(ROOT), check=True, capture_output=True).stdout
    for rel in (p.decode("utf-8") for p in out.split(b"\0") if p):
        src, dst = ROOT / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(str(src)), str(dst))
        elif src.is_file():
            shutil.copy2(src, dst)
    return dest


def _freshen(repo: Path) -> None:
    """Scaffold `repo` against itself and commit, making it fresh by construction.

    Runs with AI_BADGER_MCP_AVAILABILITY=all to mirror the gate's own re-scaffold env: the
    scaffold's MCP availability gate probes the host PATH, and the fixture must commit the
    same tree the gate would regenerate or every test fails on a machine with hermes.

    D5's canary (API-F12/QA-F10): the recovery note's count must equal the manifest's skill
    rows — the one structural check that the fixture is fresh by construction. If it fires,
    the fixture's committed manifest narrowed; fix the fixture, not the guard.
    """
    env = dict(os.environ)
    env["AI_BADGER_MCP_AVAILABILITY"] = "all"
    manifest_rows = len(bl.scaffolded_skill_names(
        json.loads((repo / ".ai-badger/manifest.json").read_text(encoding="utf-8"))))
    proc = subprocess.run(
        [sys.executable, str(repo / SCAFFOLD), "--config", str(repo / ".ai-badger/config.json"),
         "--target", str(repo), "--root", str(repo), "--no-install", "--skills", ""],
        cwd=str(repo), capture_output=True, text=True, check=False, env=env)
    assert proc.returncode == 0, f"fixture self-scaffold failed:\n{proc.stdout}{proc.stderr}"
    reused = re.search(r"reused (\d+) skill\(s\)", proc.stdout)
    assert reused, f"fixture self-scaffold did not recover from the manifest:\n{proc.stdout}"
    assert int(reused.group(1)) == manifest_rows, (
        f"the fixture's manifest narrowed: recovery re-delivered {reused.group(1)} skill(s) "
        f"but the manifest records {manifest_rows} — the fixture is not fresh by "
        f"construction (D5 canary):\n{proc.stdout}")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "self-scaffold")


@pytest.fixture(scope="module", name="fresh_repo")
def fresh_repo_fixture(tmp_path_factory) -> Path:
    """A git copy of this repo, freshly self-scaffolded. Never mutated — clone it instead."""
    repo = _copy_working_tree(tmp_path_factory.mktemp("fresh") / "repo")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _freshen(repo)
    return repo


@pytest.fixture(name="mutable_repo")
def mutable_repo_fixture(fresh_repo: Path, tmp_path: Path) -> Path:
    """A throwaway clone of the fresh fixture for tests that provoke staleness."""
    clone = tmp_path / "repo"
    shutil.copytree(fresh_repo, clone, symlinks=True)
    return clone


def _run_gate(repo: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([sys.executable, str(GATE), "--root", str(repo)],
                          capture_output=True, text=True, check=False)


# AC4's predicate (test-engineer §3), carried by the test file on purpose: it audits the
# argv *contract*, not the guard's self-assessment. EMPTY catches every empty-value shape
# the remediation could render — including the trailing-space + EOS shape the pre-fix argv
# actually had (`--skills ` at the end of the joined line). NONEMPTY is its mirror: the
# union form `--skills a,b,c` must always satisfy it, so the audit cannot be passed by
# dropping --skills' value silently.
EMPTY_SKILLS_RE = re.compile(r"--skills(?:=|\s+)(?:\"\"|''|$)")
NONEMPTY_SKILLS_RE = re.compile(r"--skills(?:=|\s+)(?!\"\"|''|$)[^\s\"']+")


def _narrow_victim(repo: Path) -> str:
    """The first scope-default skill config.include does not ask for and no stack ships.

    The AC2/AC3 recipe's victim (plan rev 2, QA-F3): a skill whose delivery no config or
    stack owns, so stripping its manifest rows is the self-consistent narrowing the
    rebuilt recipe needs. No hardcoded name — the catalog churns.
    """
    config = bl.load_json(repo / ".ai-badger/config.json")
    included = set(bl.include_derived_skill_names(
        config, bl.gateway_aliases(repo),
        set(bl.opt_in_skills_in(repo / "features/common/skills"))))
    stack_local = {name for stack in bl.resolve_stacks(config)
                   if stack not in bl.DEFAULT_COMMON_STACKS
                   for name in bl.stack_local_skills(repo / f"features/{stack}/skills")}
    victim = next((n for n in bl.default_skills_in(repo / "features/common/skills")
                   if n not in included and n not in stack_local), None)
    assert victim, "no scope-default, non-included, non-stack-local skill to narrow with"
    return victim


def _strip_victim_rows(repo: Path, victim: str) -> int:
    """Strip EVERY manifest row whose target names *victim*, and say how many went.

    Mirror rows (.ai-badger/skills/<v>/…) and out-of-mirror adjustment rows
    (.claude/skills/<v>, .github/skills/<v>) alike: the manifest must end up
    self-consistent — a narrowed manifest still naming the victim's host links would fail
    the guard for the wrong reason (QA-F3).
    """
    manifest_path = repo / ".ai-badger/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names_victim = re.compile(r"(?:^|/)skills/" + re.escape(victim) + r"(?:/|$)")
    kept = [e for e in manifest["entries"] if not names_victim.search(e.get("target", ""))]
    removed = len(manifest["entries"]) - len(kept)
    manifest["entries"] = kept
    _test_write(manifest_path, json.dumps(manifest) + "\n", encoding="utf-8")
    return removed


def test_a_fresh_tree_passes(fresh_repo):
    """The healthy tree passes. A D2 narrowing failure here means the FIXTURE's manifest
    narrowed — the `_freshen` canary should catch that first; diagnose the fixture, not
    the guard."""
    done = _run_gate(fresh_repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS" in done.stdout


def test_a_skill_source_gaining_a_file_fails_naming_the_missing_mirror_path(mutable_repo):
    """The #204 incident: a file lands in a skill's source and nothing re-scaffolds."""
    added = mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py"
    _test_write(added, '"""Added after the last self-scaffold."""\n', encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "SCAFFOLD FRESHNESS GUARD FAILED" in done.stdout
    assert f"{SKILL_MIRROR}/scripts/added_after_scaffold.py" in done.stdout
    assert "welcome-ai-badger" in done.stdout  # the remediation names the scaffolder


def test_a_source_edit_without_rescaffold_is_reported_as_stale(mutable_repo):
    """The mirror still matches what the last scaffold wrote, so the change is upstream."""
    skill_md = mutable_repo / SKILL_SOURCE / "SKILL.md"
    _test_write(skill_md, skill_md.read_text(encoding="utf-8") + "\nMoved ahead.\n", encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert f"{SKILL_MIRROR}/SKILL.md" in done.stdout
    assert "stale" in done.stdout
    assert "hand-edited" not in done.stdout


def test_a_hand_edited_mirror_is_reported_as_such(mutable_repo):
    """The source never moved, so a mirror that re-scaffolds differently was edited here."""
    mirror_md = mutable_repo / SKILL_MIRROR / "SKILL.md"
    _test_write(mirror_md, mirror_md.read_text(encoding="utf-8") + "\nEdited in place.\n", encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert f"{SKILL_MIRROR}/SKILL.md" in done.stdout
    assert "hand-edited" in done.stdout


def test_version_stamp_churn_alone_is_exempt(mutable_repo):
    """A version bump re-stamps manifest, config and agent docs; none of that is staleness."""
    index = mutable_repo / "index.json"
    _test_write(index, index.read_text(encoding="utf-8").replace(
        '"frameworkVersion": "', '"frameworkVersion": "9', 1), encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS" in done.stdout


def test_an_unscaffolded_root_refuses_loudly(tmp_path):
    """No config, nothing to compare — that is a refusal, never a pass."""
    repo = tmp_path / "bare"
    repo.mkdir()
    _git(repo, "init", "-q")

    done = _run_gate(repo)

    assert done.returncode != 0
    assert "PASS" not in done.stdout
    assert ".ai-badger/config.json" in done.stdout + done.stderr


def test_a_root_git_cannot_enumerate_refuses_loudly(tmp_path):
    """An empty file list proves nothing about freshness, so the gate must not read it as clean."""
    done = _run_gate(tmp_path / "not-a-repo")

    assert done.returncode != 0
    assert "PASS" not in done.stdout
    assert "GIT COMMAND FAILED" in done.stdout + done.stderr


def test_the_gate_never_mutates_the_tree_it_checks(mutable_repo):
    """The comparison must happen in a throwaway copy, even when it finds staleness."""
    _test_write(mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py", '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    before = _git(mutable_repo, "status", "--porcelain")

    _run_gate(mutable_repo)

    assert _git(mutable_repo, "status", "--porcelain") == before


def _tree_digest(path: Path) -> dict:
    """Every entry under `path` by relative path and content — a byte-level snapshot."""
    if not path.exists():
        return {}
    out = {}
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            entry = Path(base) / name
            rel = entry.relative_to(path).as_posix()
            if entry.is_symlink():
                out[rel] = "-> " + os.readlink(str(entry))
            elif entry.is_file():
                out[rel] = hashlib.sha256(entry.read_bytes()).hexdigest()
            else:
                out[rel] = "dir"
    return out


def _seed_hermes_home(home: Path) -> None:
    """An operator's installed Hermes plugin, as the gate would find it on a real machine."""
    plugin = home / ".hermes" / "plugins" / "ai-badger"
    (plugin / ".ai-badger").mkdir(parents=True)
    _test_write(plugin / "ai_badger_hooks.py", "# the operator's install\n", encoding="utf-8")
    _test_write(plugin / ".ai-badger" / "manifest.json", '{"frameworkRoot": "/the/operators/checkout"}\n', encoding="utf-8")
    (home / ".hermes" / "skills" / "ai-badger").mkdir(parents=True)


def test_the_gate_never_writes_into_the_operators_hermes_home(fresh_repo, tmp_path):
    """A read-only gate must leave the user scope alone (theme B, B1).

    The gate re-scaffolds a throwaway copy, and that run installed the Hermes plugin and
    relinked the skill namespace into the real `$HOME`, recording the temp directory as
    `frameworkRoot` — so the operator's plugin pointed at a path the gate then deleted.
    """
    home = tmp_path / "home"
    _seed_hermes_home(home)
    before = _tree_digest(home / ".hermes")

    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    done = subprocess.run([sys.executable, str(GATE), "--root", str(fresh_repo)],
                          capture_output=True, text=True, check=False, env=env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert _tree_digest(home / ".hermes") == before


def _printed_remediation(stdout: str) -> str:
    """The command the gate told the operator to run, joined back into one line."""
    lines = stdout.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Re-scaffold this repo"))
    return " ".join(ln.strip().rstrip("\\").strip()
                    for ln in lines[start + 1:] if ln.strip())


def test_the_printed_remediation_produces_a_tree_the_gate_then_passes(mutable_repo):
    """The advice must be the gate's own command (theme B, B3).

    It printed the scaffolder invocation without `AI_BADGER_MCP_AVAILABILITY=all`, which the
    gate sets internally, so following it verbatim dropped every server the host cannot probe
    from `.github/mcp.json` and the gate rejected the tree its own message produced.

    The remediation runs on a minimal `PATH` — the machine the forced availability exists for.
    A developer with `hermes` and `ai-raccoon` installed probes the same answer either way, so
    on their PATH this test cannot fail for the reason it was written. Only the interpreter is
    substituted: `python3` on an operator's PATH has the dependencies.

    AC3 carries the dimension this test cannot see: the advice must also not RE-BLIND the
    tree it repairs (no `--skills ''`; the manifest regenerated complete). This pin keeps its
    own failure mode — the advice executing to green on a minimal PATH at all.
    """
    _test_write(mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py", '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    failed = _run_gate(mutable_repo)
    assert failed.returncode == 1, failed.stdout + failed.stderr

    command = _printed_remediation(failed.stdout).replace("python3", sys.executable, 1)
    bare = dict(os.environ, PATH="/usr/bin:/bin")
    bare.pop("AI_BADGER_MCP_AVAILABILITY", None)
    done = subprocess.run(command, shell=True, cwd=str(mutable_repo), env=bare,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, command + "\n" + done.stdout + done.stderr

    again = _run_gate(mutable_repo)
    assert again.returncode == 0, command + "\n" + again.stdout + again.stderr


def test_the_rescaffold_points_hermes_home_away_from_the_operators(tmp_path, load_script,
                                                                   monkeypatch):
    """The belt to `--no-install`'s braces, asserted on the mechanism because no outcome can.

    `test_the_gate_never_writes_into_the_operators_hermes_home` watches a seeded `~/.hermes`
    and passes with this line deleted: `--no-install` already skips every Hermes write, so the
    outcome is identical either way and only `--no-install` is really under test. `$HERMES_HOME`
    outranks `$HOME` wherever the user scope is resolved, so a future scaffolder that installs
    despite the flag would land here — but only if this env entry survives.

    The work copy carries a minimal config + catalog so `rescaffold`'s expected-set
    derivation (API-F8: it computes the list from the copy's own config.json) is answerable
    without a full scaffolded tree; the hermes assertions below are unchanged.
    """
    guard = load_script("gates/scaffold_freshness_guard.py")
    work = tmp_path / "copy" / "repo"
    (work / "features" / "common" / "skills" / "welcome-ai-badger").mkdir(parents=True)
    (work / ".ai-badger").mkdir(parents=True)
    _test_write(work / "features/common/skills/welcome-ai-badger/SKILL.md",
                "---\nname: welcome-ai-badger\nscope: default\n---\n\n# welcome\n",
                encoding="utf-8")
    _test_write(work / ".ai-badger" / "config.json", "{}\n", encoding="utf-8")
    seen = {}

    def _record(argv, **kwargs):  # pylint: disable=unused-argument
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(guard.subprocess, "run", _record)
    guard.rescaffold(work)

    hermes_home = Path(seen[guard.HERMES_HOME_ENV])
    assert hermes_home == work.parent / "hermes-home"
    assert Path.home() not in hermes_home.parents, \
        "the re-scaffold would resolve the operator's own Hermes user scope"


def test_a_deleted_but_unstaged_file_is_not_reported_as_present(tmp_path, load_script):
    """`git ls-files -c` lists the index, so an unstaged deletion reads as a file that still
    exists — and the gate then reports a phantom difference no re-scaffold can clear."""
    guard = load_script(GATE)
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    _test_write(repo / "sub" / "gone.py", '"""deleted below."""\n', encoding="utf-8")
    _test_write(repo / "sub" / "kept.py", '"""stays."""\n', encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "both files")
    (repo / "sub" / "gone.py").unlink()          # deleted, deliberately NOT staged

    listed = guard.tracked_and_untracked(repo)

    assert "sub/kept.py" in listed
    assert "sub/gone.py" not in listed, (
        "a file deleted from the working tree but still in the index was reported as present")


def test_a_symlink_is_still_reported(tmp_path, load_script):
    """The filter must key on lexistence: this repo ships symlinks, and a dangling one is still
    a path the scaffold placed."""
    guard = load_script(GATE)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _test_write(repo / "real.py", '"""target."""\n', encoding="utf-8")
    (repo / "good-link").symlink_to("real.py")
    (repo / "dangling-link").symlink_to("nowhere.py")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "links")

    listed = guard.tracked_and_untracked(repo)

    assert "good-link" in listed
    assert "dangling-link" in listed, "a dangling symlink is still a path the scaffold placed"


# ------------------------------------------------- AC2: the manifest-narrowing blind spot


def test_a_narrowed_manifest_fails_fast_naming_the_lost_mirror(mutable_repo):
    """AC2, rebuilt recipe (QA-F3, plan rev 2): a hand-edit to a mirror whose manifest
    coverage is gone must fail the guard naming the mirror and the narrowing.

    Pre-fix this exact recipe yielded exit 1 — but via out-of-mirror host-link findings
    only (the tree keeps .claude/.github links the manifest no longer explains), WITHOUT
    the mirror path and WITHOUT any narrowing cause; on a narrowed-RUN tree (the d-16
    shape, D6b E1) it yielded a full PASS. Both artifacts are witnessed in
    docs/work/2026-08-31-scaffold-freshness-guard-red-witnesses.md. The two discriminating
    assertions below bind to the D2 fail-fast, which fires before any re-scaffold.

    Victim = a scope-default skill config.include does not ask for and no stack ships;
    EVERY manifest row naming it is stripped (mirror rows and out-of-mirror adjustment
    rows), and the mirror itself is hand-edited — the tree's only drift is an edited
    mirror whose manifest coverage is gone.
    """
    victim = _narrow_victim(mutable_repo)
    mirror = f".ai-badger/skills/{victim}"
    mirror_md = mutable_repo / mirror / "SKILL.md"
    assert mirror_md.is_file(), f"victim mirror precondition: {mirror}/SKILL.md must exist"
    _test_write(mirror_md, mirror_md.read_text(encoding="utf-8") + "\nEdited in place.\n",
                encoding="utf-8")
    assert _strip_victim_rows(mutable_repo, victim) >= 1, "narrowing precondition"

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.returncode != 2, "a refusal would be a false green for this AC"
    assert "PASS" not in done.stdout, done.stdout
    assert "SCAFFOLD FRESHNESS GUARD FAILED" in done.stdout, \
        "a narrowing is a verdict, rendered like every other failed run"
    assert f"{mirror}/SKILL.md" in done.stdout, \
        f"the lost mirror must be named by full path:\n{done.stdout}"
    assert "expected from .ai-badger/config.json" in done.stdout, \
        f"the narrowing must be named as a recorded-vs-expected mismatch:\n{done.stdout}"


# ----------------------------------------------------- AC3: the remediation re-blinding trap


def test_the_remediation_restores_what_the_manifest_lost_and_the_next_guard_catches_a_later_edit(mutable_repo):
    """AC3, the eight-step trap (test-engineer §2): the printed advice must not re-blind.

    1. clone → 2. narrow the manifest (strip every victim row) → 3. add a stale source
    file so a remediation exists to capture → 4. guard#1 fails → 5. execute the printed
    remediation verbatim on a minimal PATH → 6. pin the manifest regenerated COMPLETE →
    7. hand-edit the regenerated mirror → 8. guard#2 fails with the ordinary hand-edited
    verdict.

    The order is load-bearing (test-engineer §2): the narrowing precedes the remediation so
    the advice inherits the narrowed tree; the edit follows the remediation so guard#2's
    verdict depends on the regenerated manifest. Pre-fix (witnessed, Package 1) steps 6 and
    8 went RED: the `--skills ''` remediation recovered the narrowed set and a later
    hand-edit to the lost mirror passed guard#2. Assertion 6 is the normative proof that
    the advice regenerates skills, not merely stops naming the trap (AC4's behavioural
    layer references this pin rather than duplicating it).
    """
    victim = _narrow_victim(mutable_repo)
    mirror = f".ai-badger/skills/{victim}"
    _test_write(mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py",
                '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    assert _strip_victim_rows(mutable_repo, victim) >= 1, "narrowing precondition"

    # 4. guard#1 must fail — post-fix via the D2 fail-fast; a remediation must still print
    failed = _run_gate(mutable_repo)
    assert failed.returncode == 1, failed.stdout + failed.stderr

    # 5. execute the printed remediation verbatim, bare PATH (harness L241 pattern)
    command = _printed_remediation(failed.stdout).replace("python3", sys.executable, 1)
    bare = dict(os.environ, PATH="/usr/bin:/bin")
    bare.pop("AI_BADGER_MCP_AVAILABILITY", None)
    done = subprocess.run(command, shell=True, cwd=str(mutable_repo), env=bare,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, command + "\n" + done.stdout + done.stderr

    # 6. manifest-regeneration pin: the victim's mirror row is back — restored, not silenced
    manifest = json.loads(
        (mutable_repo / ".ai-badger/manifest.json").read_text(encoding="utf-8"))
    assert any(e.get("target") == mirror for e in manifest["entries"]), (
        f"the remediation re-blinded the tree: {mirror} still recorded in no manifest row\n"
        f"executed: {command}\n{done.stdout}")

    # 7. hand-edit the regenerated mirror (precondition: the remediation rebuilt it)
    mirror_md = mutable_repo / mirror / "SKILL.md"
    assert mirror_md.is_file(), "the remediation must regenerate the mirror itself"
    _test_write(mirror_md, mirror_md.read_text(encoding="utf-8") + "\nEdited in place.\n",
                encoding="utf-8")

    # 8. guard#2 catches the edit through the ordinary hand-edited verdict
    again = _run_gate(mutable_repo)
    assert again.returncode == 1, again.stdout + again.stderr
    assert "PASS" not in again.stdout, again.stdout
    assert f"{mirror}/SKILL.md" in again.stdout, again.stdout
    assert "hand-edited" in again.stdout, \
        f"the verdict must be hand-edited, not an unclassified orphan:\n{again.stdout}"


# --------------------------------------------------- AC4: the remediation message audit


@pytest.mark.parametrize("line", [
    "--skills '' --no-install",              # quoted-empty, space form, followed by argv
    "cmd --no-install --skills ''",          # quoted-empty at end of line
    '--skills ""',                           # double-quoted empty
    "--skills=",                             # bare = with nothing after
    "--skills='' --no-install",              # =-joined single-quoted empty
    '--skills=""',                           # =-joined double-quoted empty
    "scaffold.py --root . --no-install --skills ",  # trailing space + EOS (the pre-fix argv)
])
def test_the_empty_skills_predicate_catches_every_transport_shape(line):
    """The negative predicate must match every empty-value shape the remediation could
    render — including the trailing-space + EOS shape the pre-fix argv actually carried
    (QA-F9, witnessed at span (171, 180) of the joined argv)."""
    assert EMPTY_SKILLS_RE.search(line), line


@pytest.mark.parametrize("line", [
    "--skills welcome-ai-badger,task --no-install",   # non-empty space-form value
    "--skills=welcome-ai-badger,task",                # non-empty =-form value
    "--no-install --root .",                          # no --skills at all
    "--skills, --skills-file x",                      # not a --skills flag boundary
])
def test_the_empty_skills_predicate_rejects_the_union_form_and_unrelated_flags(line):
    """§3's non-match rows: the negative predicate must be incapable of rejecting the union
    form the fix ships (or the audit would fail every honest remediation) and must not fire
    on unrelated flags elsewhere in the output."""
    assert not EMPTY_SKILLS_RE.search(line), line


@pytest.mark.parametrize("line", [
    "--skills '' --no-install",
    "cmd --no-install --skills ''",
    '--skills ""',
    "--skills=",
    "--skills='' --no-install",
    '--skills=""',
    "scaffold.py --root . --no-install --skills ",    # trailing space + EOS is empty, not a value
])
def test_the_nonempty_predicate_rejects_empty_values(line):
    """The positive predicate's mirror rows: it must reject every empty shape (so the audit
    cannot be satisfied by the very line that re-blinds)."""
    assert not NONEMPTY_SKILLS_RE.search(line), line


def test_the_remediation_argv_carries_the_expected_set_explicitly(load_script):
    """AC4, mechanism tier (API-F8 signatures): the argv builder and the renderer take the
    config-derived expected set explicitly and cannot carry an empty --skills.

    Pre-fix `rescaffold_argv` took five arguments and ended `--skills ""`, and the 0-arg
    `remediation()` rendered `--skills ''` — both matched EMPTY_SKILLS_RE (witnessed,
    Package 1). The predicate is this file's own compiled copy: it audits the contract,
    not the implementation's self-assessment.
    """
    guard = load_script(GATE)
    expected = ["task", "prompt-markers", "welcome-ai-badger"]

    argv = guard.rescaffold_argv(sys.executable, guard.SCAFFOLD, guard.CONFIG, ".", ".",
                                 expected)
    joined = " ".join(argv)
    assert EMPTY_SKILLS_RE.search(joined) is None, joined
    assert NONEMPTY_SKILLS_RE.search(joined), joined
    assert "task,prompt-markers,welcome-ai-badger" in joined, \
        f"the argv must carry the set itself: {joined}"

    rendered = guard.remediation(expected)
    assert EMPTY_SKILLS_RE.search(rendered) is None, rendered
    assert NONEMPTY_SKILLS_RE.search(rendered), rendered
    assert "task,prompt-markers,welcome-ai-badger" in rendered, \
        f"the rendered advice must carry the set itself: {rendered}"


def test_the_printed_remediation_never_carries_an_empty_skills_value(mutable_repo):
    """AC4, outcome tier: on a real failing run, the rendered advice carries no empty
    --skills anywhere in the output (pre-fix: `--skills ''` at span (663, 674) of guard
    stdout — witnessed, Package 1), and the rationale clause prints BEFORE the
    `Re-scaffold this repo` header (QA-F8): everything after that header is executed as one
    shell command, so a trailing clause would be run, not read.

    The behavioural layer — the advice actually regenerates skills — is AC3's step-6 pin,
    not duplicated here.
    """
    _test_write(mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py",
                '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    failed = _run_gate(mutable_repo)
    assert failed.returncode == 1, failed.stdout + failed.stderr

    command = _printed_remediation(failed.stdout)
    assert EMPTY_SKILLS_RE.search(command) is None, command
    assert NONEMPTY_SKILLS_RE.search(command), command
    assert EMPTY_SKILLS_RE.search(failed.stdout) is None, \
        f"no empty --skills anywhere in the output:\n{failed.stdout}"
    assert failed.stdout.index("narrow the repair") < failed.stdout.index(
        "Re-scaffold this repo"), \
        f"the rationale clause must precede the remediation block:\n{failed.stdout}"


# --------------------------------------------- D2/D4: the derivation site's refusals


def test_an_empty_derived_expected_set_refuses_instead_of_recovering(tmp_path):
    """D4: a config.json from which no skill can be derived must refuse (exit 2), never
    fall back to `--skills ''` recovery — a broken derivation is not a licence to re-deliver
    whatever the manifest records. Pre-fix the site read no config at all and the failure
    came late, from inside the scaffolder run, naming nothing about the derivation."""
    repo = tmp_path / "bare"
    (repo / ".ai-badger").mkdir(parents=True)
    _test_write(repo / ".ai-badger" / "config.json", "{}\n", encoding="utf-8")
    _test_write(repo / "README.md", "# bare\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "config only")

    done = _run_gate(repo)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "COULD NOT RUN" in done.stdout, done.stdout
    assert "expected skill set" in done.stdout, \
        f"the refusal must name the empty derivation, not a scaffolder failure:\n{done.stdout}"


def test_an_unparseable_config_refuses_at_the_derivation_site_not_a_traceback(tmp_path):
    """A config.json the oracle cannot parse is a refusal (exit 2) with a named message at
    the derivation site — never a traceback, and never a late SCAFFOLDER FAILED after the
    re-scaffold spend (API-F4)."""
    repo = tmp_path / "broken"
    (repo / ".ai-badger").mkdir(parents=True)
    _test_write(repo / ".ai-badger" / "config.json", "{not json\n", encoding="utf-8")
    _test_write(repo / "README.md", "# broken\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "broken config")

    done = _run_gate(repo)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "COULD NOT RUN" in done.stdout, done.stdout
    assert "could not be parsed" in done.stdout, \
        f"the refusal must name the parse failure at the derivation site:\n{done.stdout}"
    assert "Traceback" not in done.stderr, done.stderr


# ------------------------------------- F4: the printed advice is what the guard ran


def test_rescaffold_derives_the_skill_list_from_the_work_copys_own_config(tmp_path,
                                                                          load_script,
                                                                          monkeypatch):
    """`rescaffold(work)` computes the expected set from the copy's own config.json — a
    faithful copy of the audited tree's — so the printed advice (derived from `--root`) and
    the executed command (derived from the copy) are the same `expected_skill_names`
    derivation: the one-oracle property (API-F4/F8). The hermes-home test pins the call
    shape (`subprocess.run(argv, **kwargs)`, env in kwargs); this pins the argv content."""
    guard = load_script(GATE)
    work = tmp_path / "copy" / "repo"
    (work / "features" / "common" / "skills" / "alpha").mkdir(parents=True)
    (work / ".ai-badger").mkdir(parents=True)
    _test_write(work / "features/common/skills/alpha/SKILL.md",
                "---\nname: alpha\nscope: default\n---\n\n# alpha\n", encoding="utf-8")
    _test_write(work / ".ai-badger" / "config.json", "{}\n", encoding="utf-8")
    seen = {}

    def _record(argv, **kwargs):  # pylint: disable=unused-argument
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(guard.subprocess, "run", _record)
    guard.rescaffold(work)

    assert seen["argv"][-2:] == ["--skills", "alpha"], seen["argv"]


# -------------------------------------------------- AC1a: consecutive-run idempotence


def _managed_digest(path: Path, guard) -> dict:
    """A byte digest over the managed tree only: `.git` excluded explicitly (a copytree
    clone's index differs environmentally — QA-F5) and the guard's `is_noise` semantics
    applied (bytecode the re-scaffold's own imports leave behind)."""
    return {rel: content for rel, content in _tree_digest(path).items()
            if rel != ".git" and not rel.startswith(".git/") and not guard.is_noise(rel)}


def test_a_second_scaffold_regenerates_the_same_tree_modulo_stamps(fresh_repo, tmp_path,
                                                                   load_script):
    """AC1a — consecutive-run idempotence, the foundation of the tree-vs-tree comparison
    (test-engineer §1-AC1). Clone A stays as the fixture committed it; clone B gets a
    second scaffold driven directly against scaffold.py with an explicitly named env (the
    F1 countermeasure: inherit no machine state the test does not name) and a pinned
    clock. The digests are compared over the managed tree only, then the guard's own
    `normalized()` (stamp keys + stamp line) must reduce every differing path to equality.

    Post-fix the second run uses the explicit config-derived argv — the same form the
    guard's re-scaffold and its printed remediation now use — so this pin also proves the
    remediation cannot green a tree by luck (AC3's execution would not converge otherwise).
    Control, not provocation: GREEN pre- and post-fix by design (witnessed, Package 1).
    """
    guard = load_script(GATE)
    clone_a, clone_b = tmp_path / "a", tmp_path / "b"
    shutil.copytree(fresh_repo, clone_a, symlinks=True)
    shutil.copytree(fresh_repo, clone_b, symlinks=True)

    config = bl.load_json(clone_b / ".ai-badger/config.json")
    env = dict(os.environ, PATH="/usr/bin:/bin", HOME=str(tmp_path / "home"),
               HERMES_HOME=str(tmp_path / "hermes-home"),
               USERPROFILE=str(tmp_path / "home"))
    env["AI_BADGER_MCP_AVAILABILITY"] = "all"
    proc = subprocess.run(
        [sys.executable, str(clone_b / SCAFFOLD),
         "--config", str(clone_b / ".ai-badger/config.json"),
         "--target", str(clone_b), "--root", str(clone_b), "--no-install",
         "--skills", ",".join(bl.expected_skill_names(clone_b, config)),
         "--generated-at", "2026-01-01T00:00:00Z"],
        cwd=str(clone_b), capture_output=True, text=True, check=False, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "reused" not in proc.stdout, \
        f"the run is explicit-argv; manifest recovery must not happen:\n{proc.stdout}"

    digest_a, digest_b = _managed_digest(clone_a, guard), _managed_digest(clone_b, guard)
    differing = sorted(rel for rel in set(digest_a) | set(digest_b)
                       if digest_a.get(rel) != digest_b.get(rel))
    residual = []
    for rel in differing:
        left, right = clone_a / rel, clone_b / rel
        if not (left.is_file() or left.is_symlink()) or not (right.is_file() or right.is_symlink()):
            residual.append(rel)
        elif guard.normalized(left) != guard.normalized(right):
            residual.append(rel)
    assert residual == [], (
        "the second scaffold regenerates a different tree (stamp-tolerated paths only): "
        f"{residual}\nrun-2 stdout:\n{proc.stdout}")
