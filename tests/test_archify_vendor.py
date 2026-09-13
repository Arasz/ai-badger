"""Provenance gate for the vendored Archify diagram skill (v2.16.0).

The packet under features/common/skills/archify/ is upstream tt-a1i/archify bytes plus
ai-badger adaptations (SKILL.md frontmatter/body, VENDOR.md, vendor.json,
THIRD_PARTY_NOTICES.md backfill). tooling/vendor_archify.py --check proves the tree still
matches vendor.json; --revendor rebuilds it from a release zip verified against the
command-line sha literal. Every oracle here is disk bytes + hashlib + literals — never the
tool's own helpers computing the expected values.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import _test_write

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "engine", ROOT / "gates"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))
import badger_lib as bl
from skills_lint import skill_files, skills_lint

TOOL = ROOT / "tooling" / "vendor_archify.py"
ARCHIFY = ROOT / "features" / "common" / "skills" / "archify"
VENDOR_JSON = ARCHIFY / "vendor.json"
SKILL_MD = ARCHIFY / "SKILL.md"

# Independent oracles: literals from the plan contract and VENDOR.md, never from vendor.json.
EXPECTED_TAG = "v2.16.0"
EXPECTED_COMMIT = "c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de"
EXPECTED_ASSET_SHA = "4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46"
EXPECTED_UPSTREAM_COUNT = 76
EXPECTED_MANIFEST_FILES = 75  # 76 upstream files minus the adapted SKILL.md
EXTRA_FILES = {"THIRD_PARTY_NOTICES.md", "VENDOR.md", "vendor.json"}
FORBIDDEN_SEGMENTS = ("test", "package-lock.json")
SIX_EXEMPTION_PATTERNS = (
    "features/*/skills/*/schemas/*.json",
    "features/*/skills/*/examples/*.json",
    "features/*/skills/*/brand-marks/*.json",
    "features/*/skills/*/package.json",
    "features/*/skills/*/skill-release.json",
    "features/*/skills/*/vendor.json",
)


def _run_tool(*args: str) -> subprocess.CompletedProcess:
    assert TOOL.is_file(), f"{TOOL} does not exist — the provenance tool was never written"
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          check=False)


def _out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout + proc.stderr


def _copy_tree_to(tmp_path: Path) -> tuple[Path, Path]:
    """The real archify tree copied under a synthetic framework root in tmp_path."""
    dest = tmp_path / "framework" / "features" / "common" / "skills" / "archify"
    shutil.copytree(ARCHIFY, dest)
    return tmp_path / "framework", dest


def _synthetic_zip(tmp_path: Path, name: str, files: dict[str, bytes],
                   symlinks: dict[str, str] | None = None) -> tuple[Path, str]:
    """A fake release zip; returns (path, its real sha256 for --expect-sha256)."""
    zpath = tmp_path / name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in files.items():
            zf.writestr(f"archify/{rel}", data)
        for rel, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(f"archify/{rel}")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, target.encode("utf-8"))
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    return zpath, digest


SYNTHETIC_SKILL = """---
name: archify
description: synthetic fixture, never shipped
---
# Synthetic

See `references/authoring-contract.md` for details.
"""

SYNTHETIC_PACKAGE = json.dumps({"name": "archify", "version": "0.0.0-test",
                                "scripts": {"build": "nope"},
                                "devDependencies": {"nope": "1.0.0"},
                                "engines": {"node": ">=18"}})


def _synthetic_files(extra: dict[str, bytes] | None = None) -> dict[str, bytes]:
    files = {"SKILL.md": SYNTHETIC_SKILL.encode("utf-8"),
             "package.json": SYNTHETIC_PACKAGE.encode("utf-8"),
             "bin/archify.mjs": b"#!/usr/bin/env node\n",
             "test/evil.txt": b"must be excluded",
             "package-lock.json": b"must be excluded",
             "scripts/generate-x.mjs": b"must be excluded"}
    files.update(extra or {})
    return files


# ------------------------------------------------------------------ QA-1: subject first


def test_archify_skill_md_exists_and_passes_lint():
    """The lint test asserts its subject first: a missing archify dir is red, not vacuous."""
    assert SKILL_MD.is_file(), f"{SKILL_MD} does not exist — the packet was never vendored"
    subjects = {p.parent.name for p in skill_files(ROOT)}
    assert "archify" in subjects, "skill_files() does not see archify; the lint cannot judge it"
    archify_violations = [v for v in skills_lint(ROOT) if "/archify/" in v]
    assert archify_violations == [], f"archify lint violations: {archify_violations}"


# ------------------------------------------------- QA-2: disk-enumerated file set, count 76


def _disk_files() -> set[str]:
    return {p.relative_to(ARCHIFY).as_posix() for p in ARCHIFY.rglob("*") if p.is_file()}


def test_file_set_is_disk_enumerated_with_literal_count_76():
    """The expected set comes from the disk (rglob), not from the manifest under test."""
    assert ARCHIFY.is_dir(), "the packet directory does not exist"
    disk = _disk_files()
    manifest = json.loads(VENDOR_JSON.read_text(encoding="utf-8"))
    on_disk_upstream = disk - EXTRA_FILES
    assert len(on_disk_upstream) == EXPECTED_UPSTREAM_COUNT, (
        f"expected {EXPECTED_UPSTREAM_COUNT} upstream files on disk, found "
        f"{len(on_disk_upstream)}")
    assert set(manifest["files"]) | {"SKILL.md"} == on_disk_upstream, (
        f"manifest files + SKILL.md != disk: "
        f"missing={sorted(on_disk_upstream - set(manifest['files']) - {'SKILL.md'})} "
        f"phantom={sorted(set(manifest['files']) - on_disk_upstream)}")
    assert len(manifest["files"]) == EXPECTED_MANIFEST_FILES, (
        f"expected {EXPECTED_MANIFEST_FILES} byte-identical manifest entries "
        f"(76 minus the adapted SKILL.md), found {len(manifest['files'])}")
    assert "SKILL.md" not in manifest["files"], "SKILL.md is adapted; it must not sit in files"
    for rel in sorted(on_disk_upstream):
        parts = rel.split("/")
        assert "test" not in parts, f"upstream test/ shipped: {rel}"
        assert "package-lock.json" not in parts, f"package-lock.json shipped: {rel}"
        assert not (parts[0] == "scripts" and parts[-1].startswith("generate-")
                    and parts[-1].endswith(".mjs")), f"generate script shipped: {rel}"


def test_listed_files_are_byte_identical_to_the_manifest():
    """Every files[] hash recomputed from disk bytes with hashlib, not via the tool."""
    manifest = json.loads(VENDOR_JSON.read_text(encoding="utf-8"))
    mismatched = [rel for rel, digest in manifest["files"].items()
                  if hashlib.sha256((ARCHIFY / rel).read_bytes()).hexdigest() != digest]
    assert mismatched == [], f"hash mismatch vs vendor.json: {mismatched}"


def test_no_vendored_path_matches_skill_exclude_patterns():
    """A future re-vendor must not ship files the scaffold would silently drop."""
    disk = _disk_files()
    assert disk, "the packet directory is empty or missing"
    offending = sorted(rel for rel in disk
                       if bl.excluded_by_patterns(rel, bl.SKILL_EXCLUDE_PATTERNS))
    assert offending == [], f"vendored paths the scaffold would drop: {offending}"


# ------------------------------------------------------- vendor.json shape + provenance


def test_vendor_json_shape_and_pinned_provenance():
    """The manifest carries the pinned origin; the asset sha here is information only."""
    manifest = json.loads(VENDOR_JSON.read_text(encoding="utf-8"))
    upstream = manifest["upstream"]
    assert upstream["repo"] == "https://github.com/tt-a1i/archify"
    assert upstream["tag"] == EXPECTED_TAG
    assert upstream["commit"] == EXPECTED_COMMIT
    assert upstream["asset"] == "archify.zip"
    assert upstream["asset_sha256"] == EXPECTED_ASSET_SHA
    assert upstream["staged_by"].strip(), "staged_by must name the staging procedure"
    assert set(manifest["extra_files"]) == EXTRA_FILES
    adapted = manifest["adapted"]["SKILL.md"]
    assert set(adapted) >= {"upstream_body_sha256", "frontmatter_sha256"}


# ------------------------------------------------- adapted SKILL.md: literal-split oracle


def _split_skill(text: str) -> tuple[str, str, str]:
    parts = text.split("---", 2)
    assert len(parts) == 3 and parts[0] == "", "SKILL.md must open with a --- fence"
    return parts[0], parts[1], parts[2]


def test_adapted_frontmatter_hash_recomputed_with_literal_split():
    """frontmatter_sha256 recomputed from text.split("---", 2)[1] with hashlib."""
    manifest = json.loads(VENDOR_JSON.read_text(encoding="utf-8"))
    _, frontmatter, _ = _split_skill(SKILL_MD.read_text(encoding="utf-8"))
    assert hashlib.sha256(frontmatter.encode("utf-8")).hexdigest() == \
        manifest["adapted"]["SKILL.md"]["frontmatter_sha256"]
    for key in ("name: archify", "version: 2.16.0", "author: tt-a1i", "license: MIT",
                "scope: default"):
        assert key in frontmatter, f"frontmatter missing {key!r}"
    assert "platforms:" in frontmatter and "linux" in frontmatter
    assert "hermes:" in frontmatter and "tags:" in frontmatter and \
        "related_skills:" in frontmatter


def test_adapted_description_names_the_mermaid_fallback():
    """Plugin-only consumers see frontmatter first: the description must name Mermaid."""
    desc = bl.skill_description(SKILL_MD)
    assert desc and desc.startswith("Use when"), "description must start with 'Use when'"
    assert len(desc) <= 1024, f"description is {len(desc)} chars > 1024"
    assert "Mermaid" in desc, "description must name the Mermaid fallback"


def test_adapted_body_keeps_upstream_prose_and_adds_the_contract_sections():
    """Body = upstream prose + line-82 fix + When NOT to Use + Gotchas + fallback."""
    _, _, body = _split_skill(SKILL_MD.read_text(encoding="utf-8"))
    assert "# Archify" in body, "upstream body prose lost"
    assert "## When NOT to Use" in body
    assert "## Gotchas" in body
    assert "ARCHIFY_UPDATE_CHECK_DISABLED=1" in body
    assert "meta.quality_profile" in body
    assert "for details when you need field enums or spacing math" in body, \
        "the line-82 adjacency fix is missing its explicit condition"
    assert "See `references/authoring-contract.md` for details." not in body, \
        "the unconditioned line-82 mention is still present"
    assert "Mermaid" in body, "the Mermaid-fallback statement is missing"
    assert "default for committed architecture" in body
    assert len(body.splitlines()) <= 500, "body exceeds the 500-line lint cap"
    assert len(body) / 4 <= 5000, "body exceeds the 5000-token proxy lint cap"


# ------------------------------------------------------------------ --check behaviour


def test_check_is_green_on_the_clean_tree_and_names_the_origin_check():
    """--check exit 0; the success line points at --revendor as the only origin check."""
    proc = _run_tool("--check", "--root", str(ROOT))
    assert proc.returncode == 0, f"--check failed on the clean tree:\n{_out(proc)}"
    assert f"ok archify vendor {EXPECTED_TAG} {EXPECTED_UPSTREAM_COUNT} files" in proc.stdout
    assert "--revendor" in proc.stdout and "--expect-sha256" in proc.stdout


def _planted_run(tmp_path: Path, mutate) -> subprocess.CompletedProcess:
    tmproot, dest = _copy_tree_to(tmp_path)
    mutate(dest)
    return _run_tool("--check", "--root", str(tmproot))


def test_check_reports_changed_missing_and_extra():
    """Planted drift/missing/extra each fail --check with the offending relpath named."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = json.loads(VENDOR_JSON.read_text(encoding="utf-8"))
        victim = sorted(manifest["files"])[0]

        proc = _planted_run(tmp_path / "a", lambda d: _test_write(
            d / victim, (d / victim).read_bytes() + b"\n"))
        assert proc.returncode == 1, f"byte flip not detected:\n{_out(proc)}"
        assert f"CHANGED {victim}" in _out(proc)

        proc = _planted_run(tmp_path / "b", lambda d: (d / victim).unlink())
        assert proc.returncode == 1, f"deletion not detected:\n{_out(proc)}"
        assert f"MISSING {victim}" in _out(proc)

        proc = _planted_run(tmp_path / "c", lambda d: _test_write(d / "smuggled.txt", "x"))
        assert proc.returncode == 1, f"extra file not detected:\n{_out(proc)}"
        assert "EXTRA smuggled.txt" in _out(proc)


def test_check_rejects_an_adapted_body_tamper_and_a_frontmatter_tamper():
    """A byte flipped in the SKILL.md body or frontmatter -> CHANGED SKILL.md."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = json.loads(VENDOR_JSON.read_text(encoding="utf-8"))
        fm_hash = manifest["adapted"]["SKILL.md"]["frontmatter_sha256"]

        def flip_body(dest: Path) -> None:
            skill = dest / "SKILL.md"
            _test_write(skill, skill.read_text(encoding="utf-8") + "\n<!-- tampered -->\n")

        proc = _planted_run(tmp_path / "a", flip_body)
        assert proc.returncode == 1, f"body tamper not detected:\n{_out(proc)}"
        assert "CHANGED SKILL.md" in _out(proc)

        def flip_frontmatter(dest: Path) -> None:
            skill = dest / "SKILL.md"
            text = skill.read_text(encoding="utf-8")
            assert "author: tt-a1i" in text
            _test_write(skill, text.replace("author: tt-a1i", "author: mallory", 1))

        proc = _planted_run(tmp_path / "b", flip_frontmatter)
        assert proc.returncode == 1, f"frontmatter tamper not detected:\n{_out(proc)}"
        assert "CHANGED SKILL.md" in _out(proc)
        assert fm_hash, "sanity: the test read a frontmatter hash"


# ------------------------------------------------- QA-3: the forged-packet test (the big one)


def test_revendor_refuses_a_forged_packet_even_when_the_manifest_agrees(tmp_path: Path):
    """The expected sha comes from the CLI literal, never from the file being replaced.

    A forged zip plus a forged vendor.json that agree with each other must still be
    refused when --expect-sha256 carries the true v2.16.0 literal: the origin anchor lives
    outside the thing it verifies, and --revendor must fail before any write.
    """
    zpath, forged_sha = _synthetic_zip(tmp_path, "forged.zip", _synthetic_files())
    assert forged_sha != EXPECTED_ASSET_SHA, "sanity: the forged zip must differ from v2.16.0"

    target = tmp_path / "framework" / "features" / "common" / "skills" / "archify"
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    _test_write(sentinel, "untouched\n")
    forged_manifest = {"upstream": {"repo": "https://github.com/tt-a1i/archify",
                                    "tag": EXPECTED_TAG, "commit": EXPECTED_COMMIT,
                                    "asset": "archify.zip", "asset_sha256": forged_sha,
                                    "staged_by": "forged"},
                       "files": {"sentinel.txt": hashlib.sha256(b"untouched\n").hexdigest()},
                       "adapted": {"SKILL.md": {"upstream_body_sha256": "0" * 64,
                                                "frontmatter_sha256": "0" * 64}},
                       "extra_files": ["THIRD_PARTY_NOTICES.md", "VENDOR.md", "vendor.json"]}
    _test_write(target / "vendor.json", json.dumps(forged_manifest))

    before = sorted(p.relative_to(target).as_posix() for p in target.rglob("*"))
    proc = _run_tool("--revendor", str(zpath), "--expect-sha256", EXPECTED_ASSET_SHA,
                     "--root", str(tmp_path / "framework"))
    assert proc.returncode == 2, f"forged packet accepted:\n{_out(proc)}"
    after = sorted(p.relative_to(target).as_posix() for p in target.rglob("*"))
    assert after == before, "the tree was touched despite the refusal"
    assert sentinel.read_text(encoding="utf-8") == "untouched\n"


def test_revendor_happy_path_then_check_is_green(tmp_path: Path):
    """Mechanism end-to-end on a synthetic packet: verify, exclude, clean, adapt, check."""
    zpath, digest = _synthetic_zip(tmp_path, "real.zip", _synthetic_files())
    tmproot = tmp_path / "framework"
    proc = _run_tool("--revendor", str(zpath), "--expect-sha256", digest,
                     "--root", str(tmproot))
    assert proc.returncode == 0, f"synthetic revendor failed:\n{_out(proc)}"
    dest = tmproot / "features" / "common" / "skills" / "archify"
    assert not (dest / "test" / "evil.txt").exists(), "test/ was not excluded"
    assert not (dest / "package-lock.json").exists(), "package-lock.json was not excluded"
    assert not (dest / "scripts" / "generate-x.mjs").exists(), "generate-*.mjs not excluded"
    package = json.loads((dest / "package.json").read_text(encoding="utf-8"))
    assert "scripts" not in package and "devDependencies" not in package, \
        "package.json was not cleaned"
    assert package["engines"] == {"node": ">=18"}, "package.json cleaning dropped kept keys"
    skill = (dest / "SKILL.md").read_text(encoding="utf-8")
    assert "## Gotchas" in skill and "## When NOT to Use" in skill, "adaptation not applied"
    regenerated = json.loads((dest / "vendor.json").read_text(encoding="utf-8"))
    assert regenerated["upstream"]["asset_sha256"] == digest, \
        "regenerated manifest must record the verified zip, not a constant"
    _test_write(dest / "VENDOR.md", "synthetic fixture\n")
    _test_write(dest / "THIRD_PARTY_NOTICES.md", "synthetic fixture\n")
    proc = _run_tool("--check", "--root", str(tmproot))
    assert proc.returncode == 0, f"--check failed right after --revendor:\n{_out(proc)}"


def test_revendor_refuses_symlinks_and_a_dirty_target(tmp_path: Path):
    """A zip carrying a symlink, or a target with uncommitted changes, -> exit 2 untouched."""
    zpath, digest = _synthetic_zip(tmp_path, "link.zip", _synthetic_files(),
                                   symlinks={"evil-link": "/etc/passwd"})
    tmproot = tmp_path / "framework"
    proc = _run_tool("--revendor", str(zpath), "--expect-sha256", digest,
                     "--root", str(tmproot))
    assert proc.returncode == 2, f"symlink zip accepted:\n{_out(proc)}"
    assert not (tmproot / "features").exists(), "the tree was touched despite the refusal"

    zpath, digest = _synthetic_zip(tmp_path, "clean.zip", _synthetic_files())
    subprocess.run(["git", "init", "-q", str(tmproot)], check=True)
    subprocess.run(["git", "-C", str(tmproot), "config", "user.email", "t@example.com"],
                   check=True)
    subprocess.run(["git", "-C", str(tmproot), "config", "user.name", "T"], check=True)
    dest = tmproot / "features" / "common" / "skills" / "archify"
    dest.mkdir(parents=True)
    _test_write(dest / "VENDOR.md", "v\n")
    _test_write(dest / "THIRD_PARTY_NOTICES.md", "t\n")
    _test_write(dest / "SKILL.md", "s\n")
    _test_write(dest / "vendor.json", "{}\n")
    subprocess.run(["git", "-C", str(tmproot), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmproot), "commit", "-qm", "base"], check=True)
    _test_write(dest / "SKILL.md", "dirty\n")
    proc = _run_tool("--revendor", str(zpath), "--expect-sha256", digest,
                     "--root", str(tmproot))
    assert proc.returncode == 2, f"dirty target accepted:\n{_out(proc)}"
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "dirty\n", \
        "the dirty tree was touched despite the refusal"


# ------------------------------------------------- PKG-1c coordination: exemption necessity


def test_validate_py_exempts_the_six_archify_json_shapes_and_each_is_necessary(root: Path):
    """The orchestrator's PKG-1c patterns exist, each matches >=1 file, each is necessary.

    Reads the patterns from tooling/validate.py (no edit in this lane): delete one added
    pattern in an in-memory copy and unschemad_feature_json must go non-empty, proving the
    exemption carries its weight rather than decorating the file.
    """
    import importlib.util
    validate_path = root / "tooling" / "validate.py"
    text = validate_path.read_text(encoding="utf-8")
    for pattern in SIX_EXEMPTION_PATTERNS:
        assert pattern in text, (
            f"tooling/validate.py has no {pattern!r} exemption yet — PKG-1c has not landed; "
            f"this lane does not edit that file")
    spec = importlib.util.spec_from_file_location("aib_validate_archify", validate_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for pattern in SIX_EXEMPTION_PATTERNS:
        matched = sorted(root.glob(pattern))
        archify_matched = [p for p in matched
                           if "skills/archify" in p.relative_to(root).as_posix()]
        assert archify_matched, f"{pattern!r} matches no archify file — a vacuous exemption"
    reduced = dict(module.FEATURE_JSON_WITHOUT_SCHEMA)
    victim = SIX_EXEMPTION_PATTERNS[0]
    del reduced[victim]
    original = module.FEATURE_JSON_WITHOUT_SCHEMA
    module.FEATURE_JSON_WITHOUT_SCHEMA = reduced
    try:
        gaps = module.unschemad_feature_json(root)
    finally:
        module.FEATURE_JSON_WITHOUT_SCHEMA = original
    assert gaps, (f"deleting {victim!r} changed nothing — the exemption is unnecessary")
    assert any("skills/archify" in gap for gap in gaps), (
        f"the gap is not about archify: {gaps[:5]}")


# ------------------------------------------------- provenance prose + backfill markers


def test_third_party_notices_backfilled_and_vendor_md_names_the_origin():
    """THIRD_PARTY_NOTICES.md is an ai-badger extra (v2.16.0 ships none); VENDOR.md says so."""
    notice = ARCHIFY / "THIRD_PARTY_NOTICES.md"
    assert notice.is_file() and notice.stat().st_size > 0
    text = notice.read_text(encoding="utf-8")
    assert "Simple Icons" in text, "the notice does not cover the embedded brand marks"
    vendor_md = (ARCHIFY / "VENDOR.md").read_text(encoding="utf-8")
    assert EXPECTED_ASSET_SHA in vendor_md, "VENDOR.md must pin the release asset sha"
    assert "--revendor" in vendor_md and "--expect-sha256" in vendor_md, \
        "VENDOR.md must document the exact re-vendor command"
    assert "extra" in vendor_md.lower(), "VENDOR.md must record the notice as an ai-badger extra"
    assert EXPECTED_COMMIT in vendor_md, "VENDOR.md must pin the upstream commit"
