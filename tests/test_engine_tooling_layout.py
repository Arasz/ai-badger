"""The engine/ + tooling/ split (ADR-0011): what the shims import versus what a maintainer runs."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE_MODULES = ("badger_lib.py", "framework_copies.py", "unsafe_literals.py")
TOOLING_SCRIPTS = ("index_build.py", "install_plugins.py", "retrieval_eval.py",
                   "sync_plugin_skills.py", "validate.py", "version_sync.py")

# The three skills the recoverability argument in ADR-0011 rests on: each must document the
# framework's own copy, never the vendored one a stale shim would have bricked.
RECOVERY_SKILLS = ("welcome-ai-badger", "den-refresh", "feed-badger")

INVOCATION_RE = re.compile(r'python3\s+"([^"]+\.py)"')


def test_the_engine_holds_the_library_every_shim_imports(root):
    """engine/ is the root predicate's anchor; no Python is left in scripts/.

    Emptiness, not absence: git cannot delete an untracked directory on checkout, so every
    existing clone keeps a `scripts/__pycache__` this test must not fail on.
    """
    assert sorted(p.name for p in (root / "engine").glob("*.py")) == sorted(ENGINE_MODULES)
    assert not list((root / "scripts").glob("*.py")), (
        "scripts/ was split into engine/ and tooling/")


def test_the_engine_modules_share_one_sys_path_entry(load_script):
    """One sys.path entry serves them all; splitting them fails the Hermes plugin load
    (ADR-0011)."""
    loaded = [load_script(f"engine/{name}") for name in ENGINE_MODULES]

    parents = {Path(module.__file__).parent for module in loaded}
    assert len(parents) == 1
    assert parents.pop().name == "engine"


def test_every_tooling_script_lives_in_the_tooling_directory(root):
    """Maintainer tooling is not the engine; a stray file here is one the shims cannot reach."""
    assert sorted(p.name for p in (root / "tooling").glob("*.py")) == sorted(TOOLING_SCRIPTS)


@pytest.mark.parametrize("name", TOOLING_SCRIPTS)
def test_every_tooling_script_resolves_the_engine_from_its_new_home(root, name):
    """Each tooling script needs parent.parent / "engine"; an ImportError here is the risk."""
    proc = subprocess.run([sys.executable, str(root / "tooling" / name), "--help"],
                          cwd=str(root), capture_output=True, text=True, check=False)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"{name}: exit {proc.returncode}\n{combined}"
    assert "Traceback" not in combined and "ImportError" not in combined, f"{name}: {combined}"


def test_the_root_predicate_anchors_on_the_engine(root, load_script, tmp_path):
    """is_framework_root and every shim must name the same file, or a consumer is stranded."""
    lib = load_script("engine/badger_lib.py")
    assert lib.is_framework_root(root)

    old_layout = tmp_path / "old"
    for name in ("schemas", "features", "scripts"):
        (old_layout / name).mkdir(parents=True)
    (old_layout / "scripts" / "badger_lib.py").write_text("", encoding="utf-8")
    assert not lib.is_framework_root(old_layout)


def _bootstrap_blocks(root: Path):
    """Every `_bootstrap_lib()` body under features/ and skills/, keyed by path."""
    blocks = {}
    for tree in ("features", "skills"):
        for path in (root / tree).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            start = text.find("def _bootstrap_lib()")
            if start < 0:
                continue
            end = text.find("    return root.resolve()", start)
            blocks[path] = text[start:end]
    return blocks


def test_every_bootstrap_shim_inserts_both_the_engine_and_the_tooling_directory(root):
    """scaffold.py bare-imports install_plugins, which lands in tooling/ (ADR-0011)."""
    blocks = _bootstrap_blocks(root)
    assert len(blocks) >= 10, f"expected every entry point to carry the shim, found {len(blocks)}"

    missing = sorted(str(p) for p, text in blocks.items()
                     if 'root / "engine"' not in text or 'root / "tooling"' not in text)
    assert not missing, "shims that do not put both engine/ and tooling/ on sys.path:\n" + \
        "\n".join(missing)

    stale = sorted(str(p) for p, text in blocks.items() if '"scripts"' in text)
    assert not stale, "shims still naming scripts/:\n" + "\n".join(stale)


@pytest.mark.parametrize("skill", RECOVERY_SKILLS)
def test_every_documented_recovery_invocation_names_a_framework_path(root, skill):
    """A stranded project is repaired by the framework's copy; pointing at .ai-badger/ ends that."""
    text = (root / "features" / "common" / "skills" / skill / "SKILL.md").read_text(
        encoding="utf-8")
    vendored = [m for m in INVOCATION_RE.findall(text) if ".ai-badger/" in m]
    assert not vendored, f"{skill} documents a vendored entry point: {vendored}"
