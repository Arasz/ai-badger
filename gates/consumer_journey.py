#!/usr/bin/env python3
"""Rehearse a real installation of ai-badger, end to end, in a throwaway home.

Every defect the 2026-08 review found escaped this repo's in-process suite by living in the gap
between a fixture and a real installation: 38 `monkeypatch` calls under `tests/` redirect `HOME`
or `Path.home`, and 71 call sites scaffold with `--root <source checkout>`. A consumer's path
differs in ways that each produced a shipped bug — `--no-install` writing 14 symlinks into
`~/.hermes`, 31 dangling `~/.hermes/skills/<project>/` links, a guard denying the one file a
project is told to own.

So this runs the consumer's path instead of a fixture's: a real `git init`, an install from a
plugin-cache-shaped copy with no `.git` (which is how `frameworkRoot` resolves for everyone who
did not clone the repo), a scaffold, an edit the guard must refuse and one it must allow, a
re-scaffold, and a teardown. `$HOME` is a scratch directory for the whole run and is snapshotted
before and after — directories and symlinks included, because an acceptance check that hashed
only regular files is precisely how the `~/.hermes` leak was declared fixed while it was still
happening.

Usage: consumer_journey.py [--root <framework>] [--scratch <dir>] [--keep]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Both siblings live beside this file; the engine lives in engine/ (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl
import scaffold_freshness_guard as sfg

WELCOME = "features/common/skills/welcome-ai-badger/scripts"
DETECT = f"{WELCOME}/detect.py"
DRIFT = f"{WELCOME}/drift.py"
SCAFFOLD = f"{WELCOME}/scaffold.py"
VALIDATE = "tooling/validate.py"

# Where Claude Code keeps an installed plugin. The journey stages the framework here so the
# scaffold resolves `frameworkRoot` the way it does for a consumer: a plain copy, no `.git`.
CACHE = ".claude/plugins/cache/ai-badger"
PROJECT = "widget-shop"

# The scaffold's MCP availability gate probes the host PATH, so an unforced run declares
# different servers on a laptop with `hermes` installed than in CI. Forced, for the same reason
# scaffold_freshness_guard forces it: the verdict must describe the tree, not the host.
SCAFFOLD_ENV = {"AI_BADGER_MCP_AVAILABILITY": "all"}

# Directories an installing scaffold may create but never fill directly: they hold the trees
# below and nothing else. Exact matches — `~/.hermes/skills/<other-project>` is another repo's.
ALLOWED_HOME_CONTAINERS = (".hermes", ".hermes/plugins", ".hermes/skills", ".claude")

# Trees the install owns outright, with everything under them. Each is either the framework's
# own copy (project-independent, one per machine) or named for this project, so a consumer
# looking at `$HOME` can say which repo asked for it. Anything else is an untraceable write.
ALLOWED_HOME_TREES = (".hermes/plugins/ai-badger", f".hermes/skills/{PROJECT}",
                      ".claude/settings.json")

# One refusal type across both gates: a rehearsal that could not run is not a rehearsal that
# failed, and the distinction is the same one scaffold_freshness_guard already draws.
Refusal = sfg.Refusal


# ------------------------------------------------------------------------ observing $HOME


def _kind(path: Path) -> str:
    """What *path* is, in one comparable string. Symlinks are never followed.

    A file is its digest, not its size: `~/.claude/settings.json` is edited in place, and two
    hook wirings of the same length would otherwise read as no change at all.
    """
    if path.is_symlink():
        return f"link -> {os.readlink(str(path))}"
    if path.is_dir():
        return "dir"
    try:
        return f"file {bl.sha256_file(path)[:16]}"
    except OSError as exc:
        return f"unreadable {exc.errno}"


def snapshot(home: Path) -> Dict[str, str]:
    """Every entry under *home*, keyed by relative posix path, valued by its kind.

    Directories and symlinks are entries in their own right: the `~/.hermes` leak was 14
    symlinks and a namespace directory, and an acceptance check that hashed regular files
    reported it clean. Symlinks are recorded by their target and never followed, so a link
    retargeted in place is a change and a link into the project does not drag the project's
    tree into the diff.
    """
    found: Dict[str, str] = {}
    if not home.is_dir() or home.is_symlink():
        return found
    for parent, dirnames, filenames in os.walk(str(home), followlinks=False):
        base = Path(parent)
        for name in list(dirnames):
            entry = base / name
            rel = entry.relative_to(home).as_posix()
            if sfg.is_noise(rel):
                dirnames.remove(name)
                continue
            found[rel] = _kind(entry)
            if entry.is_symlink():
                dirnames.remove(name)   # a link to a directory is a leaf, not a way in
        for name in filenames:
            entry = base / name
            rel = entry.relative_to(home).as_posix()
            if not sfg.is_noise(rel):
                found[rel] = _kind(entry)
    return found


def gained(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    """`<path>: <kind>` for every entry *after* has that *before* did not, or has differently.

    Ordered by path, not by the rendered line: a colon sorts after a slash, so sorting the
    rendered strings would file a directory after the files inside it.

    What `$HOME` lost is the teardown's business. This answers only what it gained, because
    that is the half that outlives the project.
    """
    return [f"{rel}: {after[rel]}" for rel in sorted(after) if before.get(rel) != after[rel]]


def strays(additions: Sequence[str]) -> List[str]:
    """The `gained` lines naming something outside every namespace a consumer can point at.

    The two lists cannot be derived from the scaffolder — the scaffolder is what they check —
    so this is the comparison that keeps them honest, and it is proven to reject.
    """
    out = []
    for line in additions:
        rel = line.split(": ", 1)[0]
        allowed = rel in ALLOWED_HOME_CONTAINERS or any(
            rel == tree or rel.startswith(tree + "/") for tree in ALLOWED_HOME_TREES)
        if not allowed:
            out.append(line)
    return out


def dangling_links(home: Path) -> List[str]:
    """Every symlink under *home* whose target does not resolve, relative to *home*.

    Walks the same way `snapshot` does — a live namespace link points into the project, and
    the project's own broken links are the project's problem, not the home directory's.
    """
    broken = []
    for rel, kind in snapshot(home).items():
        if kind.startswith("link -> ") and not (home / rel).exists():
            broken.append(rel)
    return sorted(broken)


# ---------------------------------------------------------------- never the real home


def check_scratch_home(scratch: Path) -> None:
    """Raise unless *scratch* is outside the operator's real home directory.

    A script that wrote to a real `~/.hermes` destroyed a Hermes install once. This is the
    first check the journey makes and nothing runs before it.
    """
    real = Path(os.path.expanduser("~")).resolve()
    candidate = Path(scratch).expanduser().resolve()
    if candidate == real or real in candidate.parents:
        raise Refusal(
            f"REFUSING TO RUN: the scratch home {candidate} is the real home {real} "
            "(or inside it). Point --scratch somewhere else.")


def child_env(scratch: Path, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment every subprocess in the journey runs under.

    `HOME` alone is not enough: `$HERMES_HOME` and the XDG variables each reroute a write past
    it, and `GIT_DIR` — exported by any git hook that invokes this — pointed three call sites
    at the operator's repository.
    """
    env = bl.git_env(dict(os.environ if base is None else base))
    env.update(SCAFFOLD_ENV)
    env["HOME"] = str(scratch)
    env["HERMES_HOME"] = str(scratch / ".hermes")
    env["XDG_CONFIG_HOME"] = str(scratch / ".config")
    env["XDG_DATA_HOME"] = str(scratch / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(scratch / ".cache")
    return env


# ------------------------------------------------------------------------- the journey


class Journey:
    """One consumer's installation, from `git init` to teardown. Collects findings, never raises.

    Every step returns nothing and appends to `findings`; a step that cannot run at all raises
    `Refusal`, which is a broken rehearsal rather than a failed one.
    """

    def __init__(self, root: Path, scratch: Path):
        self.root = root
        self.scratch = scratch
        self.home = scratch / "home"
        self.cache = self.home / CACHE
        self.project = scratch / PROJECT
        self.config = scratch / "config.json"
        self.findings: List[str] = []
        self.env = child_env(self.home)
        self._before_install: Dict[str, str] = {}

    # -- plumbing ------------------------------------------------------------------

    def _run(self, argv: Sequence[str], cwd: Optional[Path] = None,
             stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run([str(a) for a in argv], cwd=str(cwd or self.project),
                              input=stdin, capture_output=True, text=True, check=False,
                              env=self.env)

    def _script(self, rel: str, *args: str) -> subprocess.CompletedProcess:
        """Run a framework script out of the staged cache — the copy a consumer actually has."""
        return self._run([sys.executable, self.cache / rel, *args])

    def _must(self, proc: subprocess.CompletedProcess, what: str) -> None:
        if proc.returncode != 0:
            raise Refusal(f"{what} FAILED (exit {proc.returncode}):\n"
                          f"{proc.stdout}{proc.stderr}")

    def _fail(self, step: str, detail: str) -> None:
        self.findings.append(f"{step}: {detail}")

    # -- 1. the framework a consumer has -------------------------------------------

    def stage_the_plugin_cache(self) -> None:
        """Copy the framework into `~/.claude/plugins/cache/`, the way a plugin install lands.

        A cache is a plain copy with no `.git`, so `git_provenance` records no commit and
        `frameworkRoot` resolves through a path no test in the suite exercises.
        """
        relatives = sfg.tracked_and_untracked(self.root)
        ignored = sfg.ignored_in(self.root, relatives)
        sfg.copy_into(self.root, [r for r in relatives if r not in ignored], self.cache)
        if (self.cache / ".git").exists():
            self._fail("cache", ".git reached the plugin cache; this is not a cache install")
        if not (self.cache / "index.json").is_file():
            raise Refusal(f"STAGING FAILED: no index.json under {self.cache}")

    # -- 2. a project that is really a git repository -------------------------------

    def create_the_project(self) -> None:
        """A real `git init`, because the provenance code branches on `.git` existing."""
        self.project.mkdir(parents=True)
        for argv in (["git", "init", "-q", "."],
                     ["git", "config", "user.email", "journey@example.invalid"],
                     ["git", "config", "user.name", "Consumer Journey"]):
            self._must(self._run(argv), " ".join(argv))
        (self.project / "app.py").write_text('def price(x):\n    return x * 2\n',
                                             encoding="utf-8")
        (self.project / "README.md").write_text("# widget-shop\n", encoding="utf-8")
        self._must(self._run(["git", "add", "-A"]), "git add")
        self._must(self._run(["git", "commit", "-qm", "first commit"]), "git commit")

    # -- 3. detect, author, validate -------------------------------------------------

    def author_the_config(self) -> None:
        """Run `detect.py`, fill in the fields a human owns, and validate the result."""
        proposed = self._script(DETECT, "--target", ".", "--root", str(self.cache))
        self._must(proposed, "detect.py")
        config = json.loads(proposed.stdout)
        config["project"]["summary"] = "A throwaway shop the consumer journey scaffolds."
        config["project"]["domain"] = "Rehearsal of a real ai-badger installation."
        config["personaRouting"] = [
            {"work": "Design and decomposition", "agent": "architect"},
            {"work": "Test strategy and the failing test", "agent": "test-engineer"},
            {"work": "Quality gate before merge", "agent": "code-reviewer"},
        ]
        self.config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        self._must(self._script(VALIDATE, "--kind", "config", str(self.config)), "validate.py")
        if "hermes" not in config.get("agents", []):
            self._fail("detect", "hermes was not detected although ~/.hermes exists, so the "
                                 "user-global writes this journey watches never happen")

    # -- 4. the scaffold that must touch nothing outside the project ------------------

    def scaffold_without_installing(self) -> None:
        """`--no-install` must add nothing at all to `$HOME`. Not less; nothing.

        The 0.10x defect wrote 14 symlinks into `~/.hermes` under this exact flag, and the
        test that was supposed to catch it asserted the `plugins/` path a prior fix had
        patched rather than the invariant.
        """
        before = snapshot(self.home)
        self._must(self._scaffold("--no-install"), "scaffold.py --no-install")
        leaked = gained(before, snapshot(self.home))
        if leaked:
            self._fail("--no-install", f"$HOME gained {len(leaked)} entries: {leaked}")

    def _scaffold(self, *extra: str) -> subprocess.CompletedProcess:
        return self._script(SCAFFOLD, "--config", str(self.config), "--target",
                            str(self.project), "--root", str(self.cache),
                            "--generated-at", "2026-01-01T00:00:00Z", *extra)

    # -- 5. is the scaffold actually complete? ----------------------------------------

    def check_the_scaffold_is_complete(self) -> None:
        """Config, manifest, skills, agent-discovery files and the hook wiring, all present."""
        for rel in (".ai-badger/config.json", ".ai-badger/manifest.json", ".ai-badger/CLAUDE.md",
                    ".ai-badger/state.json", "CLAUDE.md", ".claude/settings.json"):
            if not (self.project / rel).is_file():
                self._fail("scaffold", f"{rel} was not written")
        skills = self.project / ".ai-badger" / "skills"
        delivered = sorted(p.name for p in skills.iterdir()) if skills.is_dir() else []
        if "welcome-ai-badger" not in delivered or "task" not in delivered:
            self._fail("scaffold", f"skills tree is not populated: {delivered}")
        for name in delivered:
            if not (skills / name / "SKILL.md").is_file():
                self._fail("scaffold", f"delivered skill {name} has no SKILL.md")
        if not (self.project / ".claude" / "agents").is_dir():
            self._fail("scaffold", "no .claude/agents/ — no persona is discoverable")
        manifest = self._manifest()
        if not manifest.get("entries"):
            self._fail("scaffold", "manifest records no entries")
        if not self._guard_command():
            self._fail("scaffold", "no PreToolUse hook on Edit is wired in .claude/settings.json")

    def _manifest(self) -> Dict[str, Any]:
        try:
            return json.loads((self.project / ".ai-badger" / "manifest.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # -- 6. working in the project ------------------------------------------------------

    def _guard_command(self) -> str:
        """The shell command the project's own settings.json registers for an edit.

        Read, never reconstructed: a hook registered against a path that does not exist is
        this project's signature defect, and only running what is registered can see it.
        """
        try:
            settings = json.loads((self.project / ".claude" / "settings.json")
                                  .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        for entry in settings.get("hooks", {}).get("PreToolUse", []):
            if "Edit" not in str(entry.get("matcher", "")):
                continue
            for hook in entry.get("hooks", []):
                command = hook.get("command")
                if isinstance(command, str) and "generated_file_guard" in command:
                    return command
        return ""

    def _guard_says(self, target: Path) -> str:
        """The guard's decision on an edit to *target*, via the command settings.json registers."""
        command = self._guard_command()
        if not command:
            return "unwired"
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
        env = dict(self.env, CLAUDE_PROJECT_DIR=str(self.project))
        proc = subprocess.run(["sh", "-c", command], cwd=str(self.project), input=payload,
                              capture_output=True, text=True, check=False, env=env)
        if proc.returncode != 0:
            return f"crashed (exit {proc.returncode}): {proc.stderr.strip()}"
        if not proc.stdout.strip():
            return "allow"
        try:
            decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
        except (ValueError, KeyError, TypeError):
            return f"unreadable: {proc.stdout.strip()[:120]}"
        return str(decision)

    def work_in_the_project(self) -> None:
        """Attempt the edits a user attempts, and hold the guard to both answers.

        Nothing in the suite scaffolds and then edits as a user would, which is how the guard
        shipped denying `project-local.md` — the one file a project is explicitly told it owns.
        """
        generated = self.project / ".ai-badger" / "skills" / "task" / "SKILL.md"
        verdict = self._guard_says(generated)
        if verdict != "deny":
            self._fail("guard", f"editing the generated {generated.name} was not denied "
                                f"({verdict}); the next scaffold silently reverts it")

        owned = self.project / ".ai-badger" / "skills" / "task" / "project-local.md"
        verdict = self._guard_says(owned)
        if verdict != "allow":
            self._fail("guard", f"editing project-local.md was {verdict}, but the manifest "
                                "names it projectOwned and the scaffold preserves it")

        source = self.project / "app.py"
        verdict = self._guard_says(source)
        if verdict != "allow":
            self._fail("guard", f"editing the project's own app.py was {verdict}")

        # Make the two edits, and after each one ask the reporter a consumer actually runs.
        # A project has no `scaffold_freshness_guard` — that gate re-scaffolds a repo against
        # itself and needs --root to be both project and framework. `drift.py` is the
        # consumer's equivalent, and it must agree with the guard on both files or one of the
        # two is telling a project the wrong thing about its own tree.
        owned.write_text("# widget-shop local notes\n\nDo not lose this line.\n",
                         encoding="utf-8")
        if self._drift_calls_the_task_skill_edited():
            self._fail("drift", "the drift report calls the task skill locally modified when "
                                "only project-local.md was written, contradicting the guard "
                                "that allowed it")

        generated.write_text(generated.read_text(encoding="utf-8") + "\nHand-edited.\n",
                             encoding="utf-8")
        if not self._drift_calls_the_task_skill_edited():
            self._fail("drift", "the drift report is silent about a hand-edited generated "
                                "file, so nothing warns a consumer the next refresh discards it")

    def _drift_calls_the_task_skill_edited(self) -> bool:
        """Whether `drift.py` reports the task skill as this project's own edit."""
        proc = self._script(DRIFT, "--target", str(self.project), "--root", str(self.cache))
        self._must(proc, "drift.py")
        return ("locally modified" in proc.stdout
                and "features/common/skills/task" in proc.stdout)

    # -- 7. installing the way a consumer does -------------------------------------------

    def install_the_way_a_consumer_does(self) -> None:
        """The default run: user-global state is written, and only where it can be named."""
        self._before_install = snapshot(self.home)
        self._must(self._scaffold(), "scaffold.py (installing)")
        additions = gained(self._before_install, snapshot(self.home))
        untraceable = strays(additions)
        if untraceable:
            self._fail("install", f"$HOME gained entries outside every namespace a consumer "
                                  f"can name: {untraceable}")
        if not additions:
            self._fail("install", "an installing scaffold wrote nothing to $HOME at all, so "
                                  "this step is not observing the install it claims to")
        else:
            print(f"    note: $HOME gained {len(additions)} entries, every one inside "
                  f"{', '.join(ALLOWED_HOME_TREES)}")

    # -- 8. idempotence -------------------------------------------------------------------

    def _project_content(self) -> Dict[str, Any]:
        """Every file in the project except git's own, with stamp churn normalized away.

        A symlink is its target: the discovery trees are links into `.ai-badger/`, and reading
        through one would compare the same file with itself under two names.
        """
        content: Dict[str, Any] = {}
        for rel in sfg.files_under(self.project):
            if rel == ".git" or rel.startswith(".git/"):
                continue
            path = self.project / rel
            content[rel] = (f"-> {os.readlink(str(path))}" if path.is_symlink()
                            else sfg.normalized(path))
        return content

    def check_the_scaffolder_backs_the_guard(self) -> None:
        """Re-scaffold over both edits and hold the scaffolder to the answers the guard gave.

        The pairing is the point, and it is the only thing that makes either verdict checkable.
        `project-local.md` survives byte for byte, which is why the guard allows it; the hand
        edit to the generated SKILL.md is reverted, which is why the guard refuses it. A guard
        whose two answers do not match what the next scaffold does is wrong either way.
        """
        owned = self.project / ".ai-badger" / "skills" / "task" / "project-local.md"
        generated = self.project / ".ai-badger" / "skills" / "task" / "SKILL.md"
        kept = owned.read_text(encoding="utf-8")

        self._must(self._scaffold(), "scaffold.py (over the edits)")

        if owned.read_text(encoding="utf-8") != kept:
            self._fail("guard", "project-local.md did not survive the re-scaffold, so the "
                                "guard allows an edit the scaffolder discards")
        if "Hand-edited." in generated.read_text(encoding="utf-8"):
            self._fail("guard", "the hand edit to a generated file survived, so the guard's "
                                "refusal is protecting nothing")

    def rescaffold_and_check_idempotence(self) -> None:
        """A run with nothing changed in between must change nothing but stamps. No exemptions.

        Deliberately after the step above rather than merged into it: an idempotence check that
        has to exempt the files the previous step edited cannot tell a settled tree from a
        churning one, and the exemption list is where a real difference would hide.
        """
        before = self._project_content()

        self._must(self._scaffold(), "scaffold.py (second identical run)")

        after = self._project_content()
        churn = sorted(rel for rel in set(before) | set(after)
                       if before.get(rel) != after.get(rel))
        if churn:
            self._fail("idempotence", f"a second identical scaffold changed {len(churn)} "
                                      f"files beyond stamps: {churn[:10]}")

    # -- 9. teardown ------------------------------------------------------------------------

    def tear_down_the_project(self) -> None:
        """Delete the project and look at what `$HOME` is still holding on to.

        A dangling link inside the project's own namespace is expected and attributable: 0.108.0
        gave `den-refresh --prune-namespaces` the job of clearing it, and that runs from a live
        project, so nothing clears it at the moment the project disappears. A dangling link
        anywhere else is untraceable — no consumer can find the directory to delete, which is
        how 31 of them accumulated.
        """
        namespace = f".hermes/skills/{PROJECT}"
        shutil.rmtree(self.project)
        broken = dangling_links(self.home)
        stray = [rel for rel in broken if not rel.startswith(namespace + "/")
                 and rel != namespace]
        if stray:
            self._fail("teardown", f"$HOME holds dangling links outside {namespace}/, which "
                                   f"no consumer can attribute to a project: {stray}")
        if broken:
            print(f"    note: {len(broken)} links under ~/{namespace}/ now dangle, and stay "
                  "that way until `den-refresh --prune-namespaces` runs from a live project")

    def steps(self):
        """The order a consumer's own goes in: install, look around, work, refresh, leave.

        The `--no-install` run comes first because it is the only state in which "`$HOME`
        gained nothing" is the whole invariant, and it must be measured before anything
        installs.
        """
        return (
            ("stage the plugin cache", self.stage_the_plugin_cache),
            ("create a real git project", self.create_the_project),
            ("detect, author and validate the config", self.author_the_config),
            ("scaffold with --no-install", self.scaffold_without_installing),
            ("install the way a consumer does", self.install_the_way_a_consumer_does),
            ("check the scaffold is complete", self.check_the_scaffold_is_complete),
            ("work in the project", self.work_in_the_project),
            ("re-scaffold over both edits", self.check_the_scaffolder_backs_the_guard),
            ("re-scaffold again and check idempotence", self.rescaffold_and_check_idempotence),
            ("tear the project down", self.tear_down_the_project),
        )

    def run(self) -> int:
        """Every step in order. Returns 0 when the journey found nothing."""
        for label, step in self.steps():
            start = time.time()
            before = len(self.findings)
            step()
            mark = "x" if len(self.findings) > before else "."
            print(f"  {mark} {label} ({time.time() - start:.1f}s)")
        if not self.findings:
            print("\nok - the consumer journey ran clean")
            return 0
        print(f"\nCONSUMER JOURNEY FAILED: {len(self.findings)} findings")
        for finding in self.findings:
            print(f"  - {finding}")
        return 1


def main(argv=None) -> int:
    """Run the journey under a scratch `$HOME` and report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="the framework tree to install from (default: this repo)")
    parser.add_argument("--scratch", help="where to build the throwaway home and project")
    parser.add_argument("--keep", action="store_true",
                        help="leave the scratch directory in place for inspection")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root \
        else Path(__file__).resolve().parent.parent
    scratch = Path(args.scratch).expanduser().resolve() if args.scratch \
        else Path(tempfile.mkdtemp(prefix="ai-badger-journey-"))
    try:
        check_scratch_home(scratch)
        if not bl.is_framework_root(root):
            raise Refusal(f"REFUSING TO RUN: {root} is not an ai-badger framework root")
        scratch.mkdir(parents=True, exist_ok=True)
        journey = Journey(root, scratch)
        (journey.home / ".hermes").mkdir(parents=True)   # a machine that has Hermes installed
        print(f"consumer journey: {root} -> {scratch}")
        rc = journey.run()
    except Refusal as refusal:
        print(f"CONSUMER JOURNEY COULD NOT RUN: {refusal}")
        return 1
    finally:
        if args.keep:
            print(f"kept: {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
