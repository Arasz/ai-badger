#!/usr/bin/env python3
"""Vendor the upstream Archify diagram skill packet and keep the copy honest.

Two modes with deliberately different trust roots (QA-4):

  --check [--root DIR]   Offline gate. Recomputes every sha256 in vendor.json from the
                         on-disk tree, revalidates the adapted SKILL.md, and fails on any
                         MISSING / EXTRA / CHANGED file or any vendored path a scaffold
                         would silently drop (badger_lib.SKILL_EXCLUDE_PATTERNS). Exit 0
                         clean, 1 divergence. Never touches the network and never reads
                         the expected release-asset sha: the asset sha in vendor.json is
                         information only, not a verification target (QA-3).
  --revendor <zip> --expect-sha256 <sha> [--root DIR] [--tag T] [--commit C]
                         Origin operation. Verifies the zip against the COMMAND-LINE sha
                         literal first — before anything else, and never against the sha
                         recorded in the vendor.json being replaced, so a forged zip plus
                         a forged manifest that agree with each other are still refused.
                         Then stages to a temp dir (upstream exclusion rules + symlink
                         refusal + package.json cleaning + deterministic SKILL.md
                         adaptation), replaces the tree, and regenerates vendor.json.
                         Refuses a dirty target. Exit 0 staged, 2 on any failure, with the
                         tree untouched.

Usage: vendor_archify.py --check [--root <dir>]
       vendor_archify.py --revendor <archify.zip> --expect-sha256 <sha256>
                         [--root <dir>] [--tag <tag>] [--commit <sha>]
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

UPSTREAM_REPO = "https://github.com/tt-a1i/archify"
UPSTREAM_ASSET = "archify.zip"
SKILL_REL = Path("features") / "common" / "skills" / "archify"
ADAPTATION_REV = 1

# Files this tool manages prose for, never hashed against upstream: the manifest itself,
# the provenance document, and the backfilled license notice (v2.16.0 ships none).
EXTRA_FILES = ("THIRD_PARTY_NOTICES.md", "VENDOR.md", "vendor.json")

# Exclusion rules mirroring upstream scripts/stage-clean-skill.mjs at tag v2.16.0
# (EXCLUDED_FILES + the test/ branch + EXCLUDED_SEGMENTS + .validator-check-*), applied to
# the release zip instead of a git checkout. One deliberate generalisation, recorded in
# VENDOR.md: the two named generate-*.mjs files are matched as a glob, so a future
# generator the tag adds is excluded the same way rather than shipped by accident.
EXCLUDED_TOP_FILES = {"package-lock.json"}
EXCLUDED_TOP_DIRS = {"test"}
EXCLUDED_SEGMENTS = {".DS_Store", ".hive", ".workbuddy", "node_modules"}
EXCLUDED_PREFIX = ".validator-check-"


def excluded(rel: str) -> bool:
    """True when upstream's stager would drop `rel` (posix, relative to the skill root)."""
    parts = rel.split("/")
    if parts[0] in EXCLUDED_TOP_FILES and len(parts) == 1:
        return True
    if parts[0] in EXCLUDED_TOP_DIRS:
        return True
    if len(parts) == 2 and parts[0] == "scripts" and fnmatch.fnmatch(parts[1], "generate-*.mjs"):
        return True
    return any(seg in EXCLUDED_SEGMENTS or seg.startswith(EXCLUDED_PREFIX) for seg in parts)


# ----------------------------------------------------------------- SKILL.md adaptation

# The one adjacency-dependent references/ mention (upstream line 82): it passes the lint
# only because the previous line happens to contain "When needed". The fix pins an explicit
# condition onto the mention line itself.
ORIGINAL_TAIL = "See `references/authoring-contract.md` for details."
FIXED_TAIL = ("See `references/authoring-contract.md` for details "
              "when you need field enums or spacing math.")

FRONTMATTER_TEMPLATE = """name: archify
description: >-
  Use when the user asks to visualize system architecture, infrastructure, cloud/security
  topology, technical workflows, API call sequences, request lifecycles, data pipelines or
  state machines — or to convert/beautify a Mermaid diagram — as a polished standalone HTML
  diagram. Archify is the default for committed architecture, workflow, sequence, data-flow,
  and lifecycle deliverables; fall back to Mermaid when Node.js 18+ or the skill is
  unavailable, when the diagram must render inline in committed Markdown, or when the user
  asks for text.
version: {version}
author: tt-a1i
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [diagrams, architecture, workflows, visualization, mermaid]
    related_skills: [documentation, task, differential-feature-refactor, complete-project-scope-code-review]"""

APPENDIX_BLOCK = """## When NOT to Use

Archify is the default for committed architecture, workflow, sequence, data-flow, and
lifecycle deliverables. Use Mermaid instead when Node.js 18+ or this skill is unavailable,
when the diagram must render inline in committed Markdown, or when the user explicitly asks
for Mermaid source or plain text.

Do not reach for Archify for throwaway inline sketches, for prose without a diagram, or for
diagram kinds outside its five renderers (architecture, workflow, sequence, dataflow,
lifecycle) — describe those in text or Mermaid and say which renderer gap forced the choice.

## Gotchas

- The packaged update checker is pinned, not live: this vendored copy never self-updates.
  Silence its notice with `ARCHIFY_UPDATE_CHECK_DISABLED=1`; never mutate the skill to chase
  a newer upstream — re-vendor instead (see `VENDOR.md`).
- `visual-check` exit 2 means Chrome/Chromium was unavailable and the receipt is `skipped`,
  not failed. Only exit 0 is a pass and only exit 1 is overflow or capture failure.
- A failed `deliver` preserves the previous artifact, so never run `visual-check` on that
  path afterward: it would inspect the stale last-good HTML, not the failed candidate.
- `meta.quality_profile` must be spelled exactly; omitting or misspelling it silently drops
  out of showcase validation before any geometry is judged.
- A `validate` receipt with 4 artifact checks is basic validation, never showcase acceptance:
  a showcase pass reports all 9 artifact checks with 0 composition errors and 0 warnings.
"""

# The adapted body is fixed_upstream_body + APPENDIX_TAIL, so --check strips exactly this
# suffix and reverses exactly the one-line fix to recover the upstream body it hashes.
APPENDIX_TAIL = "\n" + APPENDIX_BLOCK


class VendorError(Exception):
    """A refusal with the tree untouched (--revendor exits 2; --check exits 1)."""


def split_skill(text: str) -> Tuple[str, str, str]:
    """Split SKILL.md on the literal `---` delimiter: (head, frontmatter, body).

    The same literal rule the tests use (text.split("---", 2)), documented in VENDOR.md so
    the hashes below are reproducible without this module: frontmatter_sha256 covers parts[1]
    verbatim (surrounding newlines included), upstream_body_sha256 covers the pristine
    upstream parts[2].
    """
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0] != "":
        raise VendorError("SKILL.md does not open with a --- frontmatter fence")
    return parts[0], parts[1], parts[2]


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of bytes (hashlib, no helper indirection)."""
    return hashlib.sha256(data).hexdigest()


def adapt_skill_md(upstream_text: str, version: str) -> Tuple[str, str, str]:
    """Adapt upstream SKILL.md deterministically (adaptation rev 1).

    Returns (adapted_text, upstream_body_sha256, frontmatter_sha256). Raises VendorError
    when the single adaptation anchor is absent or ambiguous — a silent no-op adaptation
    would ship an unconditioned references/ mention, so mismatch refuses instead.
    """
    _, _, upstream_body = split_skill(upstream_text)
    if upstream_body.count(ORIGINAL_TAIL) != 1:
        raise VendorError(
            f"adaptation anchor found {upstream_body.count(ORIGINAL_TAIL)} times, "
            f"expected exactly once — upstream SKILL.md drifted under this tool")
    fixed_body = upstream_body.replace(ORIGINAL_TAIL, FIXED_TAIL, 1)
    frontmatter = FRONTMATTER_TEMPLATE.format(version=version)
    adapted = "---\n" + frontmatter + "\n---" + fixed_body + APPENDIX_TAIL
    # The split below must round-trip, or --check could never validate what this wrote.
    _, check_fm, check_body = split_skill(adapted)
    assert check_fm == "\n" + frontmatter + "\n", "adaptation broke the frontmatter split"
    assert check_body == fixed_body + APPENDIX_TAIL, "adaptation broke the body split"
    return (adapted, sha256_bytes(upstream_body.encode("utf-8")),
            sha256_bytes(check_fm.encode("utf-8")))


def check_skill_md(text: str, record: Dict[str, str]) -> List[str]:
    """Validate adapted SKILL.md against its vendor.json record; [] when clean.

    Reverses the adaptation (strip the known appendix, un-apply the one-line fix) and
    hashes the recovered upstream body: tampering anywhere — frontmatter, appendix, or
    upstream prose — breaks one of the two comparisons.
    """
    problems: List[str] = []
    try:
        _, frontmatter, body = split_skill(text)
    except VendorError as exc:
        return [f"CHANGED SKILL.md ({exc})"]
    if sha256_bytes(frontmatter.encode("utf-8")) != record.get("frontmatter_sha256"):
        problems.append("CHANGED SKILL.md (frontmatter)")
        return problems
    if not body.endswith(APPENDIX_TAIL):
        return ["CHANGED SKILL.md (body: adaptation appendix missing or altered)"]
    core = body[:-len(APPENDIX_TAIL)]
    if core.count(FIXED_TAIL) != 1:
        return ["CHANGED SKILL.md (body: line-82 condition missing or altered)"]
    recovered = core.replace(FIXED_TAIL, ORIGINAL_TAIL, 1)
    if sha256_bytes(recovered.encode("utf-8")) != record.get("upstream_body_sha256"):
        problems.append("CHANGED SKILL.md (body)")
    return problems


def clean_package_json(data: bytes) -> bytes:
    """Drop `scripts` + `devDependencies`, as upstream's stager does (2-space JSON)."""
    package = json.loads(data.decode("utf-8"))
    package.pop("scripts", None)
    package.pop("devDependencies", None)
    return (json.dumps(package, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ------------------------------------------------------------------ treeurls and hashes


def skill_dir(root: Path) -> Path:
    """The vendored tree under a framework root."""
    return root / SKILL_REL


def disk_files(directory: Path) -> Dict[str, Path]:
    """Every file under `directory` keyed by posix relpath, sorted by construction site."""
    return {p.relative_to(directory).as_posix(): p
            for p in sorted(directory.rglob("*")) if p.is_file()}


def load_manifest(directory: Path) -> Dict:
    """vendor.json, or a VendorError naming why the tree cannot be verified."""
    manifest_path = directory / "vendor.json"
    if not manifest_path.is_file():
        raise VendorError(f"MISSING vendor.json in {directory}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise VendorError(f"CHANGED vendor.json (unparseable: {exc})") from exc


# ------------------------------------------------------------------ --check


def run_check(root: Path) -> Tuple[int, List[str]]:
    """Offline verification; returns (exit_code, report_lines)."""
    directory = skill_dir(root)
    if not directory.is_dir():
        return 1, [f"MISSING {SKILL_REL.as_posix()} (the packet was never vendored)"]
    try:
        manifest = load_manifest(directory)
    except VendorError as exc:
        return 1, [str(exc)]
    problems: List[str] = []
    if manifest.get("adaptation_rev") != ADAPTATION_REV:
        problems.append(
            f"CHANGED vendor.json (adaptation_rev {manifest.get('adaptation_rev')!r} != "
            f"tool ADAPTATION_REV {ADAPTATION_REV} — re-vendor)")
    on_disk = disk_files(directory)
    files = manifest.get("files", {})
    extra = set(manifest.get("extra_files", []))
    if set(extra) != set(EXTRA_FILES):
        problems.append(f"CHANGED vendor.json (extra_files {sorted(extra)} != {list(EXTRA_FILES)})")
    expected = set(files) | {"SKILL.md"} | set(EXTRA_FILES)
    for rel in sorted(set(expected) - set(on_disk)):
        problems.append(f"MISSING {rel}")
    for rel in sorted(set(on_disk) - set(expected)):
        problems.append(f"EXTRA {rel}")
    for rel in sorted(set(files) & set(on_disk)):
        if sha256_bytes(on_disk[rel].read_bytes()) != files[rel]:
            problems.append(f"CHANGED {rel}")
    if "SKILL.md" in on_disk:
        try:
            record = manifest.get("adapted", {}).get("SKILL.md", {})
            problems.extend(check_skill_md(on_disk["SKILL.md"].read_text(encoding="utf-8"),
                                           record))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            problems.append(f"CHANGED SKILL.md (unreadable: {exc})")
    for rel in sorted(on_disk):
        if bl.excluded_by_patterns(rel, bl.SKILL_EXCLUDE_PATTERNS):
            problems.append(f"EXCLUDED {rel} (matches SKILL_EXCLUDE_PATTERNS — "
                            f"the scaffold would silently drop it)")
    if problems:
        return 1, ["ARCHIFY VENDOR CHECK FAILED", *[f"    {p}" for p in problems]]
    tag = manifest.get("upstream", {}).get("tag", "?")
    count = len(files) + 1  # files[] plus the adapted SKILL.md
    return 0, [f"ok archify vendor {tag} {count} files",
               "origin check only: python3 tooling/vendor_archify.py "
               "--revendor <archify.zip> --expect-sha256 <sha256>"]


# ------------------------------------------------------------------ --revendor


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def stage_zip(zpath: Path, staging: Path) -> Dict[str, bytes]:
    """Unpack + filter the release zip into `staging`; returns {relpath: bytes} staged.

    Refuses symlinks, absolute paths and `..` escapes before writing anything outside the
    staging dir (the caller removes the staging dir on failure; the real tree is untouched
    until the final rename).
    """
    try:
        zf = zipfile.ZipFile(zpath)
    except (zipfile.BadZipFile, OSError) as exc:
        raise VendorError(f"cannot read zip {zpath}: {exc}") from exc
    with zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        tops = {n.split("/")[0] for n in names if "/" in n}
        if len(tops) != 1:
            raise VendorError(
                f"unexpected zip layout: {sorted(tops)} — expected one top-level directory")
        top = next(iter(tops))
        staged: Dict[str, bytes] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            if _is_symlink(info):
                raise VendorError(f"refusing to stage symlink from the zip: {info.filename}")
            rel = info.filename
            if not rel.startswith(top + "/"):
                raise VendorError(f"zip entry outside {top}/: {rel}")
            rel = rel[len(top) + 1:]
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                raise VendorError(f"refusing unsafe zip path: {info.filename}")
            if excluded(rel):
                continue
            if rel in staged:
                raise VendorError(f"duplicate zip entry: {info.filename}")
            with zf.open(info) as fh:
                staged[rel] = fh.read()
    if "SKILL.md" not in staged or "package.json" not in staged:
        raise VendorError("zip is not an archify packet: SKILL.md or package.json missing")
    for rel, data in staged.items():
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return staged


def target_is_dirty(target: Path) -> bool:
    """True when git reports uncommitted changes under an existing target.

    A nonexistent target is a fresh vendor (nothing to protect); a target outside any work
    tree has no baseline to be dirty against. Both proceed.
    """
    if not target.exists():
        return False
    proc = subprocess.run(["git", "status", "--porcelain", "--", str(target)],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                capture_output=True, text=True, check=False, cwd=str(
                                    target if target.is_dir() else target.parent))
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        raise VendorError(f"cannot assess target cleanliness: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def build_manifest(staged: Dict[str, bytes], adapted_hashes: Tuple[str, str], tag: str,
                   commit: str, asset_sha256: str, staged_by: str) -> Dict:
    """vendor.json content: upstream pin + per-file hashes + adaptation record."""
    files = {rel: sha256_bytes(data) for rel, data in sorted(staged.items())
             if rel != "SKILL.md" and rel not in EXTRA_FILES}
    upstream_body_sha256, frontmatter_sha256 = adapted_hashes
    return {
        "upstream": {"repo": UPSTREAM_REPO, "tag": tag, "commit": commit,
                     "asset": UPSTREAM_ASSET, "asset_sha256": asset_sha256,
                     "staged_by": staged_by},
        "adaptation_rev": ADAPTATION_REV,
        "files": files,
        "adapted": {"SKILL.md": {"upstream_body_sha256": upstream_body_sha256,
                                 "frontmatter_sha256": frontmatter_sha256}},
        "extra_files": list(EXTRA_FILES),
    }


def run_revendor(zpath: Path, expect_sha256: str, root: Path, tag: str | None,
                 commit: str | None) -> Tuple[int, List[str]]:
    """Origin operation; returns (exit_code, report_lines). Exit 2 on any failure."""
    try:
        digest = sha256_bytes(zpath.read_bytes())
    except OSError as exc:
        return 2, [f"cannot read zip {zpath}: {exc}"]
    # The origin anchor: the command-line literal, verified before anything else and never
    # read from the vendor.json being replaced (QA-3).
    if digest != expect_sha256.lower():
        return 2, [f"refusing: zip sha256 {digest} != --expect-sha256 {expect_sha256}"]
    target = skill_dir(root)
    try:
        if target_is_dirty(target):
            return 2, [f"refusing: {target} has uncommitted changes — commit or stash first"]
    except VendorError as exc:
        return 2, [str(exc)]
    with tempfile.TemporaryDirectory(prefix="archify-revendor-") as tmp:
        staging = Path(tmp) / "staged"
        staging.mkdir()
        try:
            staged = stage_zip(zpath, staging)
            package = json.loads(staged["package.json"].decode("utf-8"))
            version = package.get("version")
            if not version:
                raise VendorError("staged package.json carries no version")
            staged["package.json"] = clean_package_json(staged["package.json"])
            adapted_text, upstream_body_sha, frontmatter_sha = adapt_skill_md(
                staged["SKILL.md"].decode("utf-8"), version)
            staged["SKILL.md"] = adapted_text.encode("utf-8")
            manifest = build_manifest(
                staged, (upstream_body_sha, frontmatter_sha),
                tag or f"v{version}", commit or "",
                asset_sha256=digest,
                staged_by=("upstream scripts/stage-clean-skill.mjs exclusion rules, "
                           "applied in Python by tooling/vendor_archify.py"))
            staged["vendor.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False)
                                     + "\n").encode("utf-8")
            # ai-badger extras survive a re-vendor when the zip does not provide them.
            if target.is_dir():
                for extra in EXTRA_FILES:
                    if extra == "vendor.json" or extra in staged:
                        continue
                    on_disk = target / extra
                    if on_disk.is_file():
                        staged[extra] = on_disk.read_bytes()
            for rel, data in staged.items():
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            replace_tree(target, staging)
        except VendorError as exc:
            return 2, [str(exc)]
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            return 2, [f"re-vendor failed: {exc}"]
    try:
        manifest = load_manifest(target)
        count = len(manifest.get("files", {})) + 1
    except VendorError:
        count = "?"
    return 0, [f"ok archify revendor {tag or 'v?'} {count} files"]


def replace_tree(target: Path, staging: Path) -> None:
    """Move `staging` over `target` with a rollback copy; raises VendorError on failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.parent / (target.name + ".revendor-prev")
    if backup.exists():
        raise VendorError(f"stale rollback dir {backup} — remove it by hand and retry")
    try:
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(staging, target)
        except OSError:
            if backup.exists():
                os.replace(backup, target)
            raise
    except OSError as exc:
        raise VendorError(f"could not replace {target}: {exc}") from exc
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


# ------------------------------------------------------------------ CLI


def main(argv=None) -> int:
    """CLI entry point: --check (exit 0/1) or --revendor (exit 0/2)."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="Offline gate: verify the on-disk tree against vendor.json.")
    parser.add_argument("--revendor", metavar="ZIP",
                        help="Origin op: rebuild the tree from a release zip.")
    parser.add_argument("--expect-sha256", metavar="SHA",
                        help="Required with --revendor: the release asset sha under test, "
                             "as a command-line literal (never read from vendor.json).")
    parser.add_argument("--tag", help="Upstream tag the zip was fetched from "
                                      "(default: v<staged package.json version>).")
    parser.add_argument("--commit", default="",
                        help="Upstream commit the zip was staged from (recorded as given).")
    parser.add_argument("--root", help="Framework root (default: auto-detect).")
    args = parser.parse_args(argv)

    if bool(args.check) == bool(args.revendor):
        parser.error("provide exactly one of --check or --revendor")
    root = Path(args.root).resolve() if args.root else bl.find_root()

    if args.check:
        if args.expect_sha256 or args.tag or args.commit:
            parser.error("--check takes no --expect-sha256/--tag/--commit")
        code, lines = run_check(root)
        print("\n".join(lines))
        return code

    if not args.expect_sha256:
        parser.error("--revendor requires --expect-sha256 <sha256>")
    code, lines = run_revendor(Path(args.revendor), args.expect_sha256, root, args.tag,
                               args.commit)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
