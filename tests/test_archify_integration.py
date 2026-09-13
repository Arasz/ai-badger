"""Cross-package integration: the vendored archify skill arrives and works.

Scaffolds a scratch consumer with the real Scaffolder (``conftest.make_scaffolder``)
and proves the archify packet and the diagram policy arrive in the delivered copy
and work from it. Every expected value is computed with the stdlib
(``hashlib``/``shutil``/``json``) — never with the vendor tool's helpers, the
detector under test, or any production oracle.

Hermes note: Hermes discovery requires a scaffold run with install enabled — the
``~/.hermes/skills/<project>/`` namespace symlinks are only written when
``install=True``. These tests use the ``--no-install``-equivalent defaults
(``install=False``), so they assert the ``.ai-badger/skills`` delivery, not the
Hermes symlink.

Node legs (dependency presence, doctor, deliver) skip with a stated reason and a
re-enable condition when ``node`` is absent on a dev machine, and FAIL instead of
skipping when ``CI`` is set but ``node`` is missing, so broken CI provisioning
goes red rather than green.

Receipt keys (``ok``, ``validation.checkCount``,
``validation.compositionProfile``, ...) were verified against the upstream tool
before asserting: the receipt literal built by ``commandDeliver`` in
``features/common/skills/archify/bin/archify.mjs``
(``{schemaVersion, ok, command, type, input, output, specification{sha256,bytes},
artifact{sha256,bytes}, validation{checksPassed, checkCount, compositionProfile,
compositionStatus, errors, warnings}}``), the nine ``addCheck`` calls in
``features/common/skills/archify/scripts/check-render-output.mjs``
(``single_svg``, ``finite_svg``, ``orthogonal_arrows``,
``label_route_clearance``, ``relationship_crossings``,
``relationship_corridors``, ``container_border_runs``, ``route_rhythm``,
``legend_clearance``), and the handoff line
``validation: 9/9 showcase, 0 errors, 0 warnings`` in
``features/common/skills/archify/references/delivery-contract.md``. Doctor exit
codes were verified in the same ``bin/archify.mjs``: ``commandDoctor`` sets
``exitCode`` 0 or 1 only, never 2 — exit 2 is ``visual-check``'s Chrome-absent
code, so these tests assert ``rc == 0`` exactly and never ``rc in (0, 2)``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scaffold_helpers import _config

CATALOG_SKILL = Path("features") / "common" / "skills" / "archify"
CATALOG_INVARIANT = Path("features") / "common" / "invariants" / "archify-diagrams.md"
DEPENDENCY_SCRIPT = "features/common/skills/welcome-ai-badger/scripts/dependency_check.py"
DELIVER_EXAMPLE = Path("examples") / "web-app.architecture.json"
DOC_MEMBERS = (
    "features/common/skills/documentation/references/scaffold-documentation/SKILL.md",
    "features/common/skills/documentation/references/update-documentation/SKILL.md",
)
GENERATED_AT = "2026-09-13T00:00:00Z"


def _require_node() -> str:
    """Absolute node path, or skip (dev) / fail (CI) when node is absent."""
    node = shutil.which("node")
    if node is None:
        reason = ("node not on PATH — install Node.js 18+ (https://nodejs.org) and "
                  "re-run to enable the archify node legs")
        if os.environ.get("CI"):
            pytest.fail(f"CI provisioned no node, but the archify legs need it: {reason}")
        pytest.skip(reason)
    return node


def _scaffold_archify(make_scaffolder) -> Path:
    """A scratch consumer with the archify skill delivered, via the real scaffolder."""
    target = make_scaffolder.target
    make_scaffolder(config=_config(agents=["claude"]), skills=["archify"]).run(
        generated_at=GENERATED_AT)
    return target


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_files(tree: Path) -> set[str]:
    return {p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()}


def _invariants_section(claude_md: str) -> str:
    """Text between '## Non-negotiable invariants' and the next '## ' heading."""
    start = claude_md.index("## Non-negotiable invariants")
    rest = claude_md[start + len("## Non-negotiable invariants"):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_delivered_skill_matches_catalog_file_by_file(make_scaffolder, root):
    """The scaffolded copy is the catalog tree, byte for byte (stdlib oracle only)."""
    target = _scaffold_archify(make_scaffolder)
    delivered = target / ".ai-badger" / "skills" / "archify"
    assert delivered.is_dir(), (
        "the scaffolder delivered no .ai-badger/skills/archify/ — "
        "is archify still scope-default and resolvable from the configured stacks?")
    catalog = root / CATALOG_SKILL
    assert catalog.is_dir(), f"catalog packet missing at {catalog}"
    delivered_files = _relative_files(delivered)
    catalog_files = _relative_files(catalog)
    assert delivered_files, "the delivered archify tree holds no files"
    assert catalog_files, "the catalog archify tree holds no files"
    assert delivered_files == catalog_files, (
        f"file sets differ: missing={sorted(catalog_files - delivered_files)} "
        f"extra={sorted(delivered_files - catalog_files)}")
    mismatched = sorted(rel for rel in catalog_files
                        if _sha256(delivered / rel) != _sha256(catalog / rel))
    assert mismatched == [], f"byte mismatch vs the catalog tree: {mismatched}"


def test_invariant_title_and_link_reach_claude_md(make_scaffolder, root):
    """The policy title and its rationale link land in the Non-negotiable section."""
    source = root / CATALOG_INVARIANT
    assert source.is_file(), f"invariant source missing at {source}"
    title = source.read_text(encoding="utf-8").strip().splitlines()[0].lstrip("#").strip()
    assert title, f"{source} opens with an empty heading"
    target = _scaffold_archify(make_scaffolder)
    delivered = target / ".ai-badger" / "invariants" / "archify-diagrams.md"
    assert delivered.is_file(), (
        "archify-diagrams.md was not copied to .ai-badger/invariants/ — "
        "is it listed under common.invariants in index.json?")
    assert _sha256(delivered) == _sha256(source), "delivered invariant bytes differ"
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))
    assert f"- **{title}**" in section, (
        f"title {title!r} not found under '## Non-negotiable invariants' — "
        f"a bare 'archify' mention elsewhere would not satisfy this")
    assert "→ `.ai-badger/invariants/archify-diagrams.md`" in section, (
        "the invariant summary must link to the copy carrying the rationale")


def test_dependency_check_reports_node_present(load_script, root, tmp_path):
    """With node on PATH and nothing stubbed: no hint, node already present."""
    _require_node()
    dc = load_script(DEPENDENCY_SCRIPT)
    consumer = tmp_path / "consumer"
    consumer.mkdir(parents=True, exist_ok=True)
    result = dc.run_dependency_check(root, consumer, features=["archify"])
    assert shutil.which("node") is not None, "sanity: the test's own probe lost node mid-run"
    assert result["hints"] == [], f"node is present but hints were reported: {result['hints']}"
    assert "node" in result["already_present"], (
        f"node is present but not reported: {result}")
    assert result["errors"] == [], f"unexpected errors: {result['errors']}"


@pytest.mark.parametrize("member", DOC_MEMBERS)
def test_documentation_members_put_archify_before_mermaid(root, member):
    """Each documentation mandate authors with archify first, Mermaid as the fallback."""
    path = root / member
    assert path.is_file(), f"documentation member missing at {path}"
    mandate = [line for line in path.read_text(encoding="utf-8").splitlines()
               if "archify" in line]
    assert mandate, f"{member}: no mandate line mentions archify"
    for line in mandate:
        assert "Mermaid" in line, (
            f"{member}: mandate names archify but not the Mermaid fallback: {line.strip()}")
        assert line.index("archify") < line.index("Mermaid"), (
            f"{member}: the Mermaid fallback precedes archify in the mandate: {line.strip()}")


def test_doctor_exits_zero_from_delivered_copy(make_scaffolder):
    """doctor runs green from the scaffolded copy. rc == 0 exactly (never 2)."""
    node = _require_node()
    target = _scaffold_archify(make_scaffolder)
    binary = target / ".ai-badger" / "skills" / "archify" / "bin" / "archify.mjs"
    assert binary.is_file(), f"delivered binary missing at {binary}"
    proc = subprocess.run([node, str(binary), "doctor"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (
        f"doctor failed with rc={proc.returncode} (doctor returns 0 or 1 only):\n"
        f"{proc.stdout}\n{proc.stderr}")


def test_deliver_architecture_showcase_receipt(make_scaffolder):
    """deliver exits 0 with ok:true, 9 artifact checks, showcase profile, real HTML."""
    node = _require_node()
    target = _scaffold_archify(make_scaffolder)
    delivered = target / ".ai-badger" / "skills" / "archify"
    binary = delivered / "bin" / "archify.mjs"
    example = delivered / DELIVER_EXAMPLE
    assert binary.is_file(), f"delivered binary missing at {binary}"
    assert example.is_file(), f"vendored example missing at {example}"
    out_html = target / "archify-showcase.html"
    proc = subprocess.run(
        [node, str(binary), "deliver", "architecture", str(example), str(out_html),
         "--quality", "showcase", "--json"],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (
        f"deliver failed with rc={proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
    receipt = json.loads(proc.stdout)
    assert receipt["ok"] is True, f"receipt ok is not true: {receipt}"
    validation = receipt["validation"]
    assert validation["checkCount"] == 9, (
        f"expected exactly 9 artifact checks, got {validation['checkCount']}: {validation}")
    assert validation["checksPassed"] == 9, (
        f"expected 9/9 checks passed, got {validation['checksPassed']}: {validation}")
    assert validation["compositionProfile"] == "showcase", (
        f"expected the showcase composition profile: {validation}")
    assert validation["errors"] == 0, f"receipt reports errors: {validation}"
    assert validation["warnings"] == 0, f"receipt reports warnings: {validation}"
    assert out_html.is_file(), f"deliver exited 0 but wrote no HTML at {out_html}"
    assert out_html.stat().st_size > 0, f"deliver wrote an empty HTML at {out_html}"
