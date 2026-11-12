"""semantica is cut out of ai-badger: decisions live in ai-raccoon (ADR-0048).

A removal is a deletion, so the honest guard is a negative one. Each parse-based case also
proves its parser still reads something real (a survivor), so an empty parse cannot pass.

Two groups, selected by name: ``test_source_*`` pins the source tree (catalog, hooks, engine,
tests) and ``test_tree_*`` pins every tracked file, generated output included.

HISTORY keeps the record and is not the target: ADRs, changelog, work records, the frozen
retrieval eval corpus, ai-raccoon's own manual checklist, and this file.
"""
from __future__ import annotations

import ast
import json
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path

import badger_store
from conftest import ROOT

PATTERN = re.compile(r"semantica(?!lly)", re.I)
THIS = Path(__file__).resolve().relative_to(ROOT).as_posix()
HISTORY = (
    "docs/adr/",
    "docs/changelog/",
    "docs/work/",
    ".ai-badger/state.json",
    "features/common/retrieval/eval/eval_index.json",
    "features/ai-raccoon/skills/ai-raccoon-manual-checklist/",
    "tests/fixtures/retired-semantica-shapes.json",
    "tests/fixtures/build_retired_semantica_shapes.py",
    "tests/test_stack_mcp_retired_catalog.py",
    THIS,
)
SOURCE_ROOTS = ("features/", "engine/", "tooling/", "tests/")
# A cleanup list must name what it deletes; only those exact literals are exempt in that file.
TOMBSTONES = {
    "features/hermes/adjustments/adjust_hooks.py": ('"export_semantica_graph.py"',),
    "features/common/stack-mcp.json": (
        '{"name": "semantica", "command": "python3 -m semantica.mcp_server", "declare": true,'
        ' "availability": {"command": "python3"}}',
        '{"name": "semantica", "command": "semantica mcp start", "declare": true,'
        ' "availability": {"command": "semantica"}}',
        '{"name": "semantica", "command": "semantica-mcp", "declare": true,'
        ' "availability": {"command": "semantica-mcp"}}',
        '{"name": "semantica", "command": "semantica-mcp", "declare": true,'
        ' "env": {"SEMANTICA_DISABLE_PROGRESS": "1"}, "availability": {"command": "semantica-mcp"}}',
    ),
}


def _tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                         capture_output=True).stdout.decode("utf-8")
    return [path for path in out.split("\0") if path]


def _in_history(path: str) -> bool:
    return any(path == entry or path.startswith(entry) for entry in HISTORY)


def _offenders(paths) -> list[str]:
    found = []
    for path in paths:
        if _in_history(path):
            continue
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for literal in TOMBSTONES.get(path, ()):
            text = text.replace(literal, "", 1)
        if PATTERN.search(text):
            found.append(path)
    return found


def _module_assignment(relpath: str, name: str):
    """The literal value assigned to *name* at module level in *relpath*, parsed, not imported."""
    tree = ast.parse((ROOT / relpath).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not assigned in {relpath}")


def _matches(values) -> list[str]:
    return [value for value in values if PATTERN.search(value)]


# ---------------------------------------------------------------- the catalog

def test_source_catalog_holds_no_semantica_server():
    """The MCP catalog entry is gone; its ai-raccoon neighbour is still there."""
    assert (ROOT / "features/common/mcp/ai-raccoon").is_dir()
    assert not (ROOT / "features/common/mcp/semantica").exists()


def test_source_catalog_holds_no_semantica_skill():
    """The knowledge-graph skill is gone; ai-raccoon-memory takes its job."""
    assert (ROOT / "features/common/skills/ai-raccoon-memory").is_dir()
    assert not (ROOT / "features/common/skills/semantica-knowledge-graph").exists()


def test_source_catalog_holds_no_semantica_template():
    """The graph-dump template is gone; other templates remain."""
    templates = ROOT / "features/common/templates"
    assert any(templates.iterdir())
    assert not (templates / "semantica-graph.json.tmpl").exists()


def test_source_stack_mcp_declares_no_semantica_server():
    """Every stack-mcp.json parses to server names: survivors present, semantica only retired."""
    names = []
    for path in sorted(ROOT.glob("features/*/stack-mcp.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        names += [server.get("name", "") for server in data.get("servers", [])]

    assert {"ai-raccoon", "code-review-graph"} <= set(names)
    assert not _matches(names)

    retired = json.loads((ROOT / "features/common/stack-mcp.json")
                         .read_text(encoding="utf-8"))["retired"]
    assert len(retired) == 4, "semantica is tombstoned once per shipped launch"
    assert {server["name"] for server in retired} == {"semantica"}


def test_source_hooks_manifest_registers_no_semantica_hook():
    """The manifest's hook names hold the memory-grade survivor and no semantica hook."""
    data = json.loads((ROOT / "features/common/hooks/hooks-manifest.json")
                      .read_text(encoding="utf-8"))
    names = [hook["name"] for hook in data["hooks"]]

    assert "memory-first-gate" in names
    assert not _matches(names)


def test_source_hooks_json_runs_no_semantica_command():
    """Every hooks.json command is read; the commit-reminder survivor stays, no semantica."""
    data = json.loads((ROOT / "features/common/hooks/hooks.json").read_text(encoding="utf-8"))
    commands = [hook.get("command", "") for groups in data["hooks"].values()
                for group in groups for hook in group.get("hooks", [])]

    assert any("commit_reminder_hook.py" in command for command in commands)
    assert not _matches(commands)


def test_source_hermes_install_list_drops_the_export_module():
    """Hermes no longer installs the export module and deletes the stale copy it left."""
    relpath = "features/hermes/adjustments/adjust_hooks.py"
    shared = _module_assignment(relpath, "SHARED_SKILL_MODULES")
    removed = _module_assignment(relpath, "REMOVED_MODULES")
    names = [part for pair in shared for part in pair]

    assert names
    assert not _matches(names)
    assert "export_semantica_graph.py" in removed


def test_source_requirements_name_no_semantica_package():
    """engine/requirements.txt keeps jsonschema and drops the wrapper's package."""
    lines = (ROOT / "engine/requirements.txt").read_text(encoding="utf-8").splitlines()
    names = [re.split(r"[\s<>=!~;\[]", line.strip(), maxsplit=1)[0] for line in lines
             if line.strip() and not line.strip().startswith("#")]

    assert "jsonschema" in names
    assert not _matches(names)


def test_source_user_store_has_no_semantica_family():
    """The user DB registry and its DDL lose the nudge table; memory_first stays."""
    assert "memory_first" in badger_store.USER_FAMILIES
    assert "semantica_nudge" not in badger_store.USER_FAMILIES
    assert not any("semantica_nudge" in statement for statement in badger_store._DDL)  # pylint: disable=protected-access


def test_source_context_enrichment_exports_no_semantica_name():
    """context_enrichment's public names drop the nudge helpers; the tool ranker stays."""
    names = _module_assignment("features/common/retrieval/context_enrichment.py", "__all__")

    assert "find_relevant_tools" in names
    assert not _matches(names)


def test_source_prompt_hooks_emit_no_semantica_nudge():
    """Neither the Claude prompt hook nor the Hermes plugin names semantica."""
    hook = "features/common/skills/mcp-index/scripts/context_enrichment_hook.py"
    plugin = "features/common/hooks/ai_badger_hooks.py"

    assert "context_enrichment" in (ROOT / hook).read_text(encoding="utf-8")
    assert _offenders([hook, plugin]) == []


def test_source_gitignore_has_no_semantica_staging_dir():
    """.gitignore drops the session-graph staging dir."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert text.strip()
    assert not PATTERN.search(text)


def test_source_tree_names_no_semantica_outside_history():
    """No tracked non-Markdown file under features/engine/tooling/tests names semantica."""
    paths = [path for path in _tracked()
             if path.startswith(SOURCE_ROOTS) and not path.endswith(".md")]

    assert "engine/badger_store.py" in paths
    assert _offenders(paths) == []


def test_source_store_leaves_legacy_nudge_state_alone(tmp_path, monkeypatch):
    """Legacy nudge files and table survive a full migrate and doctor scan untouched."""
    root = tmp_path / "user-root"
    monkeypatch.setenv(badger_store.USER_ROOT_ENV, str(root))
    monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(tmp_path / "debug"))
    # awm families follow the real home, not USER_ROOT: pin it so migrate() never touches it.
    monkeypatch.setattr(badger_store, "_DEFAULT_HOME", tmp_path / "home")

    badger_store.open_user().close()
    db_path = badger_store.user_db_path()
    assert db_path.parent == root
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS semantica_nudge (session_id TEXT PRIMARY KEY,"
                     " payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.close()
    legacy = root / "semantica-nudge"
    legacy.mkdir(parents=True)
    seeded = [legacy / str(uuid.uuid4()) for _ in range(2)]
    for path in seeded:
        path.write_bytes(b"")

    store = badger_store.open_user()
    try:
        for family in badger_store.USER_FAMILIES.values():
            store.migrate(family.table)
    finally:
        store.close()
    rows = badger_store.doctor_scan(db_path, badger_store.USER_FAMILIES)

    assert rows, "doctor_scan reported no family at all"
    assert sorted(legacy.iterdir()) == sorted(seeded)
    assert not [path for path in legacy.iterdir() if ".migrated" in path.name]
    assert not [row for row in rows if "semantica-nudge" in row["path"]]


# ---------------------------------------------------------------- the whole tree

def test_tree_names_no_semantica_outside_history():
    """No tracked file — generated skills, scaffold, agent files, docs — names semantica."""
    paths = _tracked()

    assert "README.md" in paths and "CLAUDE.md" in paths
    assert _offenders(paths) == []
