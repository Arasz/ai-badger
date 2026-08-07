#!/usr/bin/env python3
"""Fail when re-scaffolding this repo against itself would change anything but a stamp.

Issue #206: `features/**` moved, nobody re-ran the scaffolder, and `.ai-badger/` kept
describing a tree that no longer existed — through a tagged release. Detection already
existed (`drift.py`); enforcement did not.

The check is a reproduction, not a comparison of recorded hashes: the tracked +
untracked-unignored tree is copied to a throwaway directory, the welcome-ai-badger
scaffolder is re-run there against that copy, and every resulting difference is a finding.
The tree under `--root` is only ever read.

Stamp churn is exempt because it is not staleness: `frameworkVersion`, `frameworkCommit`,
`frameworkDirty`, `generatedAt` and `configHash` in JSON, and the `Scaffolded by ai-badger
<version>` line in the agent-discovery markdown. A version bump alone must not fail this.

Each finding is classified, resolving the ambiguity drift.py cannot (issue #206): a source
that no longer hashes to what the manifest recorded means the framework moved ahead of the
mirror (stale), and one that still matches it would re-scaffold to what the last run wrote,
so the difference was made in the target here (hand-edited).

Usage: scaffold_freshness_guard.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

CONFIG = ".ai-badger/config.json"
MANIFEST = ".ai-badger/manifest.json"
SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"

# The environment the re-scaffold needs, printed with the remediation because an operator who
# omits it re-scaffolds a different tree: the MCP availability gate probes the host PATH, so a
# machine without `hermes` on it drops that server from .github/mcp.json and the guard then
# rejects the tree its own advice produced.
RESCAFFOLD_ENV = {"AI_BADGER_MCP_AVAILABILITY": "all"}
# Guard-only containment. The scaffolder writes user-global Hermes state (the plugin under
# plugins/, the skill namespace under skills/), and this run happens in a directory that is
# about to be deleted — it must not reach the operator's own Hermes home.
HERMES_HOME_ENV = "HERMES_HOME"

# Keys the scaffolder re-stamps on every run; their value says when it ran, not what it wrote.
STAMP_KEYS = frozenset({"frameworkVersion", "frameworkCommit", "frameworkDirty",
                        "generatedAt", "configHash"})
STAMP_LINE_RE = re.compile(r"(Scaffolded by ai-badger )\S+")
STAMP_LINE_SUB = r"\1<version>"

# Bytecode the re-scaffold's own imports leave behind, never part of any scaffolded output.
NOISE_PARTS = frozenset({"__pycache__"})
NOISE_SUFFIXES = (".pyc",)

STALE = "stale"
HAND_EDITED = "hand-edited"
UNCLASSIFIED = "regenerates differently"


class Refusal(RuntimeError):
    """The guard could not reach a verdict, which is never the same as a pass."""


class Finding(NamedTuple):
    """One path the re-scaffold would change, and why it moved."""

    path: str
    change: str
    verdict: str

    def line(self) -> str:
        """One rendered report row."""
        return f"    {self.path}  ({self.change}, {self.verdict})"


# ------------------------------------------------------------------------------ the copy


def tracked_and_untracked(root: Path) -> List[str]:
    """Every path git reports as tracked or untracked-but-not-ignored, repo-relative."""
    try:
        proc = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"],
                              cwd=str(root), capture_output=True, check=False)
    except OSError as exc:
        raise Refusal(f"GIT COMMAND FAILED in {root}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise Refusal(f"GIT COMMAND FAILED in {root}: {detail}")
    return [chunk.decode("utf-8") for chunk in proc.stdout.split(b"\0") if chunk]


def ignored_in(root: Path, paths: Sequence[str]) -> frozenset:
    """The subset of *paths* this repo's .gitignore rules exclude (e.g. a generated .mcp.json)."""
    if not paths:
        return frozenset()
    proc = subprocess.run(["git", "check-ignore", "--stdin"], cwd=str(root), check=False,
                          input="\n".join(paths), capture_output=True, text=True)
    return frozenset(line for line in proc.stdout.splitlines() if line)


def copy_into(root: Path, relatives: Sequence[str], dest: Path) -> None:
    """Reproduce *relatives* under *dest*, preserving symlinks rather than following them."""
    for rel in relatives:
        src, dst = root / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(str(src)), str(dst))
        elif src.is_file():
            shutil.copy2(src, dst)


def rescaffold_argv(python: str, scaffold: str, config: str, target: str,
                    root: str) -> List[str]:
    """The scaffolder command line — one builder, so the printed advice is what the guard ran."""
    return [python, scaffold, "--config", config, "--target", target, "--root", root,
            "--no-install", "--skills", ""]


def remediation() -> str:
    """The command that makes a stale tree fresh: the guard's own, environment included."""
    argv = rescaffold_argv("python3", SCAFFOLD, CONFIG, ".", ".")
    assignments = [f"{key}={value}" for key, value in sorted(RESCAFFOLD_ENV.items())]
    return " ".join(assignments + [shlex.quote(arg) for arg in argv])


def rescaffold(work: Path) -> None:
    """Re-run the scaffolder inside the throwaway copy, against that copy.

    The re-scaffold runs with `AI_BADGER_MCP_AVAILABILITY=all` so the comparison is
    deterministic: the scaffold's MCP availability gate probes the host PATH (a machine with
    `hermes` installed emits the Hermes MCP block, CI does not), which would otherwise make
    the guard's verdict depend on the host that runs it. Forcing every declared server
    available reproduces the committed tree — it was scaffolded on a hermes machine.
    """
    env = dict(os.environ, **RESCAFFOLD_ENV)
    env[HERMES_HOME_ENV] = str(work.parent / "hermes-home")
    proc = subprocess.run(
        rescaffold_argv(sys.executable, str(work / SCAFFOLD), str(work / CONFIG),
                        str(work), str(work)),
        cwd=str(work), capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0:
        raise Refusal("SCAFFOLDER FAILED on a copy of this tree "
                      f"(exit {proc.returncode}):\n{proc.stdout}{proc.stderr}")


def is_noise(rel: str) -> bool:
    """True for compiled bytecode the re-scaffold's own imports produced."""
    parts = rel.split("/")
    return bool(NOISE_PARTS.intersection(parts)) or rel.endswith(NOISE_SUFFIXES)


def files_under(work: Path) -> List[str]:
    """Every file and symlink in the scaffolded copy, repo-relative. Symlinked dirs are leaves."""
    found = []
    for path in work.rglob("*"):
        if path.is_symlink() or path.is_file():
            rel = path.relative_to(work).as_posix()
            if not is_noise(rel):
                found.append(rel)
    return found


# ------------------------------------------------------------------------- the comparison


def strip_stamps(value: Any) -> Any:
    """A copy of parsed JSON with every stamp key removed, at any depth."""
    if isinstance(value, dict):
        return {k: strip_stamps(v) for k, v in value.items() if k not in STAMP_KEYS}
    if isinstance(value, list):
        return [strip_stamps(item) for item in value]
    return value


def normalized(path: Path) -> Any:
    """File content with stamp churn removed: parsed-and-stripped JSON, or de-stamped text."""
    raw = path.read_bytes()
    if path.suffix == ".json":
        try:
            return json.dumps(strip_stamps(json.loads(raw.decode("utf-8"))), sort_keys=True)
        except (UnicodeDecodeError, ValueError):
            pass
    try:
        return STAMP_LINE_RE.sub(STAMP_LINE_SUB, raw.decode("utf-8"))
    except UnicodeDecodeError:
        return raw


def same_content(left: Path, right: Path) -> bool:
    """True when the two paths carry the same content once stamps are normalized away."""
    if left.is_symlink() or right.is_symlink():
        if not (left.is_symlink() and right.is_symlink()):
            return False
        return os.readlink(str(left)) == os.readlink(str(right))
    return normalized(left) == normalized(right)


# ---------------------------------------------------------------------- the classification


def owning_entry(manifest: Dict[str, Any], rel: str) -> Optional[Dict[str, Any]]:
    """The manifest entry whose target is *rel* or the directory containing it."""
    best: Optional[Dict[str, Any]] = None
    best_len = -1
    for entry in manifest.get("entries", []):
        target = entry.get("target")
        if not target:
            continue
        if (rel == target or rel.startswith(target + "/")) and len(target) > best_len:
            best, best_len = entry, len(target)
    return best


def hashes_source(feature: str) -> bool:
    """Whether this feature type records its source's hash rather than the written file's."""
    try:
        return bl.feature_type(feature).hashes_source
    except KeyError:
        return False


def _moved(path: Path, recorded: Optional[str], as_dir: bool) -> Optional[bool]:
    """Whether *path* still hashes to what the manifest recorded, or None if unanswerable."""
    if not recorded or not path.exists():
        return None
    if as_dir:
        if not path.is_dir():
            return None
        exclude = bl.SKILL_EXCLUDE_PATTERNS + ["extensions"]
        return bl.dir_content_hash(path, exclude=exclude)["content_hash"] != recorded
    return bl.sha256_file(path) != recorded


def classify(root: Path, manifest: Dict[str, Any], rel: str) -> str:
    """Read a difference as an unrefreshed mirror, an edited one, or neither.

    Asked of the source wherever the manifest records it: a source still matching that record
    would re-scaffold to exactly what the last run wrote, so a difference can only have come
    from the target — and a source that has moved is the mirror falling behind. `hash` is not
    used for a skill, because the scaffolder records it before it has finished writing that
    directory, so it does not answer "what is on disk" for every skill.
    """
    entry = owning_entry(manifest, rel)
    if entry is None:
        return UNCLASSIFIED
    recorded_source = entry.get("sourceHash")
    if recorded_source is None and hashes_source(entry.get("feature", "")):
        recorded_source = entry.get("hash")
    if recorded_source is None:
        moved = _moved(root / entry["target"], entry.get("hash"), as_dir=False)
        return UNCLASSIFIED if moved is None else (HAND_EDITED if moved else STALE)
    moved = _moved(root / entry["source"], recorded_source, as_dir="sourceHash" in entry)
    return UNCLASSIFIED if moved is None else (STALE if moved else HAND_EDITED)


# --------------------------------------------------------------------------------- verdict


def collect(root: Path) -> Tuple[List[Finding], int]:
    """Every difference a re-scaffold of *root* would introduce, and the paths compared."""
    present = tracked_and_untracked(root)
    if not (root / CONFIG).is_file():
        raise Refusal(f"{root} has no {CONFIG}: there is no scaffold here to check. "
                      "Run the welcome-ai-badger scaffolder before this guard.")
    if not present:
        raise Refusal(f"git listed no files in {root}; an empty tree proves nothing about "
                      "freshness, so this is a refusal rather than a pass.")

    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8")) \
        if (root / MANIFEST).is_file() else {}
    before = [rel for rel in present if not is_noise(rel)]

    holder = tempfile.mkdtemp(prefix="scaffold-freshness-")
    try:
        work = Path(holder) / "work"
        work.mkdir()
        copy_into(root, present, work)
        rescaffold(work)
        after = files_under(work)
        findings = differences(root, work, manifest, before, after)
    finally:
        shutil.rmtree(holder, ignore_errors=True)
    return findings, len(set(before) | set(after))


def differences(root: Path, work: Path, manifest: Dict[str, Any],
            before: Sequence[str], after: Sequence[str]) -> List[Finding]:
    """Diff the tree against its re-scaffolded copy, path by path."""
    kept, produced = set(before), set(after)
    new = sorted(produced - kept)
    findings = []
    for rel in sorted(set(new) - ignored_in(root, new)):
        findings.append(Finding(rel, "the re-scaffold writes it; the tree has not got it",
                                classify(root, manifest, rel)))
    for rel in sorted(kept - produced):
        findings.append(Finding(rel, "the re-scaffold no longer writes it",
                                classify(root, manifest, rel)))
    for rel in sorted(kept & produced):
        if not same_content(root / rel, work / rel):
            findings.append(Finding(rel, "content differs",
                                    classify(root, manifest, rel)))
    return findings


def check(root: Path) -> int:
    """Run the scaffold-freshness guard; print its verdict; return 0 pass / 1 fail."""
    findings, compared = collect(root)
    if not findings:
        print(f"{compared} path(s) compared against a re-scaffold of this tree; only version "
              f"stamps differ — PASS")
        return 0

    print(f"SCAFFOLD FRESHNESS GUARD FAILED: re-scaffolding this repo against itself would "
          f"change {len(findings)} of {compared} path(s):")
    for finding in findings:
        print(finding.line())
    print("Re-scaffold this repo against itself and commit the result:")
    print(f"    {remediation()}")
    return 1


def main(argv=None) -> int:
    """CLI entry point: run the scaffold-freshness guard against --root."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()
    try:
        return check(root)
    except Refusal as refusal:
        print(f"SCAFFOLD FRESHNESS GUARD COULD NOT RUN: {refusal}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
