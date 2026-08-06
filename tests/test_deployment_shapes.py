"""Framework-root resolution in the four deployment shapes ai-badger ships into (ADR-0007).

Shapes are built under `tmp_path` with `HOME` pointed at an empty tree: against a real home
the broken shapes pass for the wrong reason, via a stale `~/.ai-badger/framework` cache.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scaffold_helpers import _config

ROOT = Path(__file__).resolve().parents[1]

# A framework tree: everything the root predicates and a scaffold run read.
_FRAMEWORK_TREE = ("features", "schemas", "engine", "tooling", "hooks", "skills",
                   ".claude-plugin", "VERSION", "index.json", "BREAKING_VERSIONS")

# Every entry point that must resolve a framework root before it can do anything, keyed by
# name and given as a path relative to a framework root.
ENTRY_POINTS = {
    "detect": "features/common/skills/welcome-ai-badger/scripts/detect.py",
    "scaffold": "features/common/skills/welcome-ai-badger/scripts/scaffold.py",
    "drift": "features/common/skills/welcome-ai-badger/scripts/drift.py",
    "refresh": "features/common/skills/den-refresh/scripts/refresh.py",
    "detect_additions": "features/common/skills/feed-badger/scripts/detect_additions.py",
    "open_pr": "features/common/skills/feed-badger/scripts/open_pr.py",
    "drift_notice_hook": "features/common/skills/task/scripts/drift_notice_hook.py",
    "mcp_index": "features/common/skills/mcp-index/scripts/mcp_index.py",
    "ai_badger_hooks": "features/common/hooks/ai_badger_hooks.py",
    "learned_skills_sync": "features/common/hooks/learned_skills_sync.py",
}

# Where the scaffold shape puts each entry point; a name absent here is not scaffolded.
SCAFFOLD_PATHS = {
    "detect": ".ai-badger/skills/welcome-ai-badger/scripts/detect.py",
    "scaffold": ".ai-badger/skills/welcome-ai-badger/scripts/scaffold.py",
    "drift": ".ai-badger/skills/welcome-ai-badger/scripts/drift.py",
    "refresh": ".ai-badger/skills/den-refresh/scripts/refresh.py",
    "detect_additions": ".ai-badger/skills/feed-badger/scripts/detect_additions.py",
    "open_pr": ".ai-badger/skills/feed-badger/scripts/open_pr.py",
    "drift_notice_hook": ".ai-badger/skills/task/scripts/drift_notice_hook.py",
    "mcp_index": ".ai-badger/skills/mcp-index/scripts/mcp_index.py",
    "ai_badger_hooks": ".ai-badger/hooks/ai_badger_hooks.py",
}

# The plugin cache is a copy of the whole repo, and Claude Code loads the generated mirror
# under skills/ (ADR-0008) — that copy, not features/, is what actually runs there.
MIRROR_PATHS = {
    "detect": "skills/welcome-ai-badger/scripts/detect.py",
    "scaffold": "skills/welcome-ai-badger/scripts/scaffold.py",
    "drift": "skills/welcome-ai-badger/scripts/drift.py",
    "refresh": "skills/den-refresh/scripts/refresh.py",
    "detect_additions": "skills/feed-badger/scripts/detect_additions.py",
    "open_pr": "skills/feed-badger/scripts/open_pr.py",
    "drift_notice_hook": "skills/task/scripts/drift_notice_hook.py",
    "mcp_index": "skills/mcp-index/scripts/mcp_index.py",
}

# `features/hermes/adjustments/adjust_hooks.py` installs exactly these two into
# ~/.hermes/plugins/ai-badger/ (the Hermes directory-plugin shape).
HERMES_PLUGINS = ("ai_badger_hooks", "learned_skills_sync")

# Entry points whose CLI must be reachable: argparse cannot run if the shim raised at import.
CLI_HELP = ("detect", "scaffold", "drift", "refresh", "detect_additions", "open_pr",
            "learned_skills_sync")

SHAPES = ("checkout", "scaffold", "plugin-cache", "hermes-plugins")

# Imports the module the way its deployment does, then reports the root it resolved.
_PROBE = '''
import importlib.util, json, sys
from pathlib import Path

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("aib_probe_" + path.stem, path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
root = getattr(mod, "FRAMEWORK_ROOT", "__missing__")
print("AIB_ROOT=" + json.dumps(None if root is None else str(root)))
'''


def _copy_framework(dest: Path) -> Path:
    """Copy the framework tree to `dest` — what a checkout and a plugin cache both are."""
    dest.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in _FRAMEWORK_TREE:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=ignore)
        elif src.is_file():
            shutil.copy2(src, dest / name)
    return dest


def _env(home: Path) -> dict:
    """A process environment with an empty home and no `$AI_BADGER` escape hatch."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("AI_BADGER", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def test_the_probe_environment_never_puts_the_real_home_on_pythonpath(tmp_path):
    """An empty home is the premise of every shape test; PYTHONPATH must not smuggle one back.

    Reinstating the developer's own site-packages makes these tests pass for a reason the
    four deployment shapes do not have on a user's machine.
    """
    from conftest import REAL_HOME  # pylint: disable=import-outside-toplevel

    env = _env(tmp_path / "home")

    assert str(REAL_HOME) not in env.get("PYTHONPATH", ""), (
        f"PYTHONPATH reaches back into the real home: {env.get('PYTHONPATH')}")


def _write_config(path: Path) -> Path:
    cfg = _config(stacks=["python"], agents=["claude", "hermes"])
    cfg["frameworkVersion"] = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def shapes(tmp_path_factory) -> dict:
    """Build all four deployment shapes once, under one empty home."""
    base = tmp_path_factory.mktemp("deployment-shapes")
    home = base / "home"
    home.mkdir()

    checkout = _copy_framework(base / "checkout")
    version = (checkout / "VERSION").read_text(encoding="utf-8").strip()
    cache = _copy_framework(
        home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger" / version)

    consumer = base / "consumer"
    consumer.mkdir()
    config = _write_config(base / "config.json")
    proc = subprocess.run(
        [sys.executable, str(checkout / ENTRY_POINTS["scaffold"]),
         "--config", str(config), "--target", str(consumer), "--root", str(checkout),
         "--no-install"],
        capture_output=True, text=True, cwd=str(consumer), env=_env(home), check=False)
    assert proc.returncode == 0, f"scaffold run failed:\n{proc.stdout}\n{proc.stderr}"

    manifest = json.loads(
        (consumer / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frameworkRoot"] == str(checkout), (
        "the scaffold shape can only resolve a root that scaffold.py recorded")

    return {"home": home, "checkout": checkout, "cache": cache, "consumer": consumer,
            "hermes": home / ".hermes" / "plugins"}


def _entry_path(shapes: dict, shape: str, name: str) -> Path:
    """On-disk location of entry point `name` in `shape`, or skip if the shape has no copy."""
    if shape == "checkout":
        return shapes["checkout"] / ENTRY_POINTS[name]
    if shape == "plugin-cache":
        mirrored = shapes["cache"] / MIRROR_PATHS.get(name, "")
        return mirrored if name in MIRROR_PATHS and mirrored.is_file() \
            else shapes["cache"] / ENTRY_POINTS[name]
    if shape == "scaffold":
        if name not in SCAFFOLD_PATHS:
            pytest.skip(f"{name} is not scaffolded into .ai-badger/")
        return shapes["consumer"] / SCAFFOLD_PATHS[name]
    if name not in HERMES_PLUGINS:
        pytest.skip(f"{name} is not installed into ~/.hermes/plugins/")
    return shapes["hermes"] / "ai-badger" / Path(ENTRY_POINTS[name]).name


def _cwd_for(shapes: dict, shape: str) -> Path:
    """A hermes plugin only ever runs inside a project; the others run where they live."""
    return shapes["consumer"] if shape in ("scaffold", "hermes-plugins") else shapes["checkout"]


def _probe_root(shapes: dict, shape: str, path: Path, tmp_path: Path, cwd: Path = None,
                extra_env: dict = None, argv: list = None):
    """Import `path` in a fresh interpreter and return (process, reported root)."""
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    env = _env(shapes["home"])
    env.update(extra_env or {})
    proc = subprocess.run([sys.executable, str(probe), str(path), *(argv or [])],
                          capture_output=True, text=True,
                          cwd=str(cwd or _cwd_for(shapes, shape)), env=env, check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("AIB_ROOT=")]
    reported = json.loads(lines[-1][len("AIB_ROOT="):]) if lines else "__missing__"
    return proc, reported


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_every_entry_point_resolves_the_root_in_all_four_shapes(shapes, name, shape, tmp_path):
    """Each entry point imports and reports a real framework root in each deployment shape."""
    path = _entry_path(shapes, shape, name)
    assert path.is_file(), f"{name} missing from the {shape} shape at {path}"

    proc, reported = _probe_root(shapes, shape, path, tmp_path)
    assert proc.returncode == 0, f"{name} failed to import in the {shape} shape:\n{proc.stderr}"
    assert reported != "__missing__", f"{name} exposes no FRAMEWORK_ROOT in the {shape} shape"
    assert reported is not None, f"{name} resolved no framework root in the {shape} shape"

    resolved = Path(reported)
    assert (resolved / "schemas").is_dir() and (resolved / "features").is_dir(), (
        f"{name} resolved {resolved} in the {shape} shape, which is not a framework root")


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("name", sorted(CLI_HELP))
def test_every_cli_entry_point_reaches_argparse_in_all_four_shapes(shapes, name, shape):
    """`--help` proves argparse is reachable: a shim that raises at import never gets there."""
    path = _entry_path(shapes, shape, name)
    proc = subprocess.run([sys.executable, str(path), "--help"],
                          capture_output=True, text=True, cwd=str(_cwd_for(shapes, shape)),
                          env=_env(shapes["home"]), check=False)
    assert proc.returncode == 0, (
        f"{name} --help failed in the {shape} shape:\n{proc.stdout}\n{proc.stderr}")
    assert "usage:" in proc.stdout


def _shim_text(path: Path) -> str:
    """The `_bootstrap_lib` block of a source file, or "" when it defines none."""
    text = path.read_text(encoding="utf-8")
    start = text.find("def _bootstrap_lib()")
    if start < 0:
        return ""
    end = text.find("    return root.resolve()", start)
    assert end > 0, f"{path} defines _bootstrap_lib but does not end it as the others do"
    return text[start:end]


def test_every_bootstrap_shim_is_the_same_predicate(root):
    """The shim cannot import badger_lib, so it stays duplicated — byte-identical (ADR-0007).

    Covers the catalog and the generated plugin mirror; `.ai-badger/` is this repo's own
    scaffold output, refreshed by re-scaffolding rather than edited.
    """
    sources = [p for tree in ("features", "skills") for p in (root / tree).rglob("*.py")]
    shims = {p: text for p, text in ((p, _shim_text(p)) for p in sources) if text}
    assert len(shims) >= 10, f"expected every entry point to carry the shim, found {len(shims)}"

    assert len(set(shims.values())) == 1, (
        "bootstrap shims disagree:\n" + "\n".join(sorted(str(p) for p in shims)))


def test_no_root_predicate_lives_outside_a_bootstrap_shim(root):
    """`_bootstrap_lib` is the only place allowed to test a path for the engine.

    Byte-identical shims are not enough: a second predicate elsewhere in the same file is
    invisible to that check, and is how the count went from four to five.
    """
    marker = '"badger_lib.py"'
    strays = {}
    for tree in ("features", "skills"):
        for path in (root / tree).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            outside = text.count(marker) - _shim_text(path).count(marker)
            if outside:
                strays[path] = outside

    assert not strays, "root predicate outside _bootstrap_lib:\n" + "\n".join(
        f"  {p} ({n}x)" for p, n in sorted(strays.items()))


def _module_scope_bootstrap_calls(tree: ast.Module) -> list:
    """Top-level statements whose value calls `_bootstrap_lib()`."""
    def calls(node) -> bool:
        return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_bootstrap_lib" for n in ast.walk(node))

    return [stmt for stmt in tree.body
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and calls(stmt)]


def _guards_runtime_error(stmt) -> bool:
    """True when `stmt` is a try/except that catches RuntimeError."""
    if not isinstance(stmt, ast.Try):
        return False
    for handler in stmt.handlers:
        caught = handler.type
        names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
        if any(isinstance(n, ast.Name) and n.id in ("RuntimeError", "Exception") for n in names):
            return True
    return False


def test_every_hermes_plugin_guards_its_module_scope_bootstrap(root):
    """A hook degrades to silence; it never breaks a session.

    Both files land inside ~/.hermes/plugins/ai-badger/, where the recorded root is all that
    answers and it can stop resolving. An unguarded shim there takes the plugin down at import.
    """
    hooks = root / "features" / "common" / "hooks"
    unguarded = []
    checked = 0
    for path in sorted(hooks.glob("*.py")):
        for stmt in _module_scope_bootstrap_calls(ast.parse(path.read_text(encoding="utf-8"))):
            checked += 1
            if not _guards_runtime_error(stmt):
                unguarded.append(path)

    assert checked >= len(HERMES_PLUGINS), (
        f"expected each of {HERMES_PLUGINS} to bootstrap at module scope, found {checked}")
    assert not unguarded, "module-scope _bootstrap_lib() outside a try/except RuntimeError:\n" \
        + "\n".join(f"  {p}" for p in unguarded)


def test_the_shim_and_badger_lib_state_one_predicate(root):
    """One predicate, in two places only because the shim runs before badger_lib exists."""
    def normalise(text: str) -> str:
        return " ".join(text.split())

    predicate = normalise('(path / "schemas").is_dir() and (path / "features").is_dir() '
                          'and (path / "engine" / "badger_lib.py").is_file()')
    lib = normalise((root / "engine" / "badger_lib.py").read_text(encoding="utf-8"))
    shim = normalise(_shim_text(root / ENTRY_POINTS["scaffold"]))

    assert predicate in lib
    assert predicate in shim


def test_hermes_drift_notice_has_a_version_to_compare(shapes, tmp_path):
    """ai_badger_hooks must reach a VERSION from ~/.hermes/plugins/ai-badger/ (ADR-0001 Tier 1)."""
    path = shapes["hermes"] / "ai-badger" / "ai_badger_hooks.py"
    proc, reported = _probe_root(shapes, "hermes-plugins", path, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert reported not in (None, "__missing__")
    assert (Path(reported) / "VERSION").is_file()


def test_the_shim_and_badger_lib_state_one_cache_skew_warning(root):
    """One warning text, in two places only because the shim runs before badger_lib exists."""
    def normalise(text: str) -> str:
        return " ".join(text.split())

    warning = normalise(
        'print(f"ai-badger: {cache} is version {have}, but this project was scaffolded "\n'
        '      f"by {want}. The cache is never updated in place — remove it, or pass "\n'
        '      f"--root <framework checkout>.", file=sys.stderr)')
    lib = normalise((root / "engine" / "badger_lib.py").read_text(encoding="utf-8"))
    shim = normalise(_shim_text(root / ENTRY_POINTS["scaffold"]))

    assert warning in lib
    assert warning in shim


def _stale_cache_shape(base: Path, tmp_path: Path) -> tuple:
    """A home whose only framework is a cache one version behind, and a scaffold that reached it.

    The scaffold's recorded root is gone, so the cache is what answers — the shape the
    maintainer's own machine has been in since 0.13.0.
    """
    home = base / "home"
    cache = _copy_framework(home / ".ai-badger" / "framework")
    (cache / "VERSION").write_text("0.13.0\n", encoding="utf-8")

    consumer = base / "consumer"
    aib = consumer / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(
        json.dumps({"frameworkVersion": "0.35.2", "frameworkRoot": str(tmp_path / "gone")}),
        encoding="utf-8")
    entry = aib / "skills" / "welcome-ai-badger" / "scripts" / "detect.py"
    entry.parent.mkdir(parents=True)
    shutil.copy2(ROOT / ENTRY_POINTS["detect"], entry)
    return home, cache, entry


def test_a_stale_cache_announces_itself_to_the_entry_point_that_reached_for_it(tmp_path):
    """The shim, not badger_lib, is what a scaffolded copy runs before any import happens."""
    home, cache, entry = _stale_cache_shape(tmp_path / "shape", tmp_path)

    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(probe), str(entry)], capture_output=True,
                          text=True, cwd=str(tmp_path), env=_env(home), check=False)

    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("AIB_ROOT=")]
    assert json.loads(lines[-1][len("AIB_ROOT="):]) == str(cache.resolve())
    assert "0.13.0" in proc.stderr and "0.35.2" in proc.stderr


def _hostile_repo(base: Path) -> Path:
    """A cloned repo whose tracked manifest points at a tree of its own, holding a payload."""
    repo = base / "hostile"
    (repo / ".ai-badger").mkdir(parents=True)
    for name in ("schemas", "features", "engine"):
        (repo / "vendor" / name).mkdir(parents=True)
    (repo / ".ai-badger" / "manifest.json").write_text(
        json.dumps({"frameworkVersion": "0.33.0", "frameworkRoot": "vendor", "entries": []}),
        encoding="utf-8")
    (repo / "vendor" / "engine" / "badger_lib.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(base / 'PWNED')!r}).write_text('x', encoding='utf-8')\n", encoding="utf-8")
    return repo


@pytest.mark.parametrize("name", HERMES_PLUGINS)
def test_a_cloned_repo_cannot_steer_a_session_start_hook(shapes, name, tmp_path):
    """A repo's own manifest must never reach the sys.path of a hook that runs on session start.

    The hooks load automatically from ~/.hermes/plugins/, so the working directory is any repo
    the user opened — including one they only cloned.
    """
    repo = _hostile_repo(tmp_path)
    path = shapes["hermes"] / "ai-badger" / f"{name}.py"

    _probe_root(shapes, "hermes-plugins", path, tmp_path, cwd=repo)

    assert not (tmp_path / "PWNED").exists(), (
        f"{name} executed code from the repo it was merely standing in")


@pytest.mark.parametrize("shape", ("checkout", "plugin-cache"))
@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_an_exported_env_var_never_displaces_the_checkout_a_script_lives_in(
        shapes, name, shape, tmp_path):
    """`export AI_BADGER=...` in a shell profile must not pair a foreign engine with this catalog.

    Route B tells users to export it, and several checkouts per machine is normal, so a stale
    export is the common case rather than the exotic one.
    """
    decoy = _copy_framework(tmp_path / "decoy")
    path = _entry_path(shapes, shape, name)

    proc, reported = _probe_root(shapes, shape, path, tmp_path,
                                 extra_env={"AI_BADGER": str(decoy)})

    assert proc.returncode == 0, f"{name} failed to import in the {shape} shape:\n{proc.stderr}"
    expected = shapes["checkout"] if shape == "checkout" else shapes["cache"]
    assert reported == str(expected), (
        f"{name} resolved {reported} in the {shape} shape rather than the tree it lives in")


@pytest.mark.parametrize("name", HERMES_PLUGINS)
def test_a_host_processes_own_argv_is_not_read_as_a_root(shapes, name, tmp_path):
    """These two are imported into the Hermes host, so `--root` in its argv is not ours."""
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    path = shapes["hermes"] / "ai-badger" / f"{name}.py"

    proc, reported = _probe_root(shapes, "hermes-plugins", path, tmp_path,
                                 argv=["--root", str(unrelated)])

    assert proc.returncode == 0, f"{name} broke on the host's argv:\n{proc.stderr}"
    assert reported not in (None, "__missing__")


# The hooks a stranded project still loads; a raise here is a broken session, not a degraded one.
DEGRADING_HOOKS = ("drift_notice_hook", "mcp_index", "ai_badger_hooks", "learned_skills_sync")


def _stranded_shim(source: Path, dest: Path) -> Path:
    """A vendored copy carrying the pre-ADR-0011 predicate, which resolves nothing today.

    The whole source directory comes along: an entry point imports its siblings by bare name.
    """
    shutil.copytree(source.parent, dest.parent,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    text = source.read_text(encoding="utf-8")
    start = text.index("def _bootstrap_lib()")
    end = text.index("    return root.resolve()", start)
    block = text[start:end].replace('"engine"', '"scripts"').replace(
        '    sys.path.insert(0, str(root / "tooling"))\n', "")
    dest.write_text(text[:start] + block + text[end:], encoding="utf-8")
    return dest


@pytest.mark.parametrize("name", DEGRADING_HOOKS)
def test_a_stale_vendored_shim_degrades_rather_than_raising_in_a_hook(name, tmp_path):
    """ADR-0011 ships a breaking predicate; the hooks must go quiet, never break a session."""
    home = tmp_path / "home"
    home.mkdir()
    entry = _stranded_shim(ROOT / ENTRY_POINTS[name],
                           tmp_path / "consumer" / ".ai-badger" / name / f"{name}.py")

    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(probe), str(entry)], capture_output=True,
                          text=True, cwd=str(tmp_path / "consumer"), env=_env(home), check=False)

    assert proc.returncode == 0, f"{name} raised instead of degrading:\n{proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("AIB_ROOT=")]
    assert lines and json.loads(lines[-1][len("AIB_ROOT="):]) is None
