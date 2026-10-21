"""rtk is cut out of ai-badger: nothing the framework ships knows the name.

A removal is a deletion, so the honest guard is a negative one. The catalog holds no rtk
tool, no shipped source names it, no live document mentions it, and the shared helpers
treat an `rtk` command as the ordinary unknown program it now is — the shell lexer does
not read it as a wrapper, the test-economy hook does not strip it, and the memory-first
gate does not take it for a repo search.

The history is not the target: `docs/adr/`, `docs/changelog/` and `docs/work/` keep the
record of what shipped, and this test says nothing about them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import ROOT

RTK = re.compile(r"\brtk\b")
CATALOG = "features/common/tools/rtk"
HISTORY = ("adr", "changelog", "work")


def _text_files(root: Path, suffix: str):
    """Every file under *root* with *suffix*, skipping the hidden and vendored trees."""
    for path in sorted(root.rglob(f"*{suffix}")):
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts) or "node_modules" in parts:
            continue
        if path.is_file():
            yield path


def _mentions(path: Path) -> bool:
    try:
        return bool(RTK.search(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


# ---------------------------------------------------------------- the catalog

def test_the_catalog_holds_no_rtk_tool():
    """No rtk directory in the feature tree, and no rtk item in the built index."""
    assert not (ROOT / CATALOG).exists()
    assert not list((ROOT / "features").glob("*/tools/rtk"))

    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    tools = [item for stack in index.get("stacks", {}).values()
             for item in stack.get("tools", [])]

    assert "rtk" not in {item.get("name") for item in tools}
    assert "rtk" not in (ROOT / "index.json").read_text(encoding="utf-8")


def test_no_shipped_source_names_rtk():
    """The framework's own tree — code and skill documents alike — carries no rtk."""
    offenders = [str(path.relative_to(ROOT)) for path in _text_files(ROOT / "features", ".py")
                 if _mentions(path)]
    offenders += [str(path.relative_to(ROOT)) for path in _text_files(ROOT / "features", ".md")
                  if _mentions(path)]

    assert not offenders, f"rtk still named in: {offenders}"


def test_no_live_document_names_rtk():
    """The live documentation says nothing about rtk; the history keeps the record."""
    offenders = []
    for path in _text_files(ROOT / "docs", ".md"):
        if path.relative_to(ROOT / "docs").parts[0] in HISTORY:
            continue
        if _mentions(path):
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, f"rtk still named in: {offenders}"


def test_no_other_test_file_names_rtk():
    """The suites that covered rtk are gone; this guard is the only file that names it."""
    here = Path(__file__).resolve()
    offenders = [str(path.relative_to(ROOT)) for path in _text_files(ROOT / "tests", ".py")
                 if path.resolve() != here and _mentions(path)]

    assert not offenders, f"rtk still named in: {offenders}"


# ---------------------------------------------------------------- the behaviour

def test_the_shell_lexer_reads_rtk_as_an_ordinary_program(load_script):
    """rtk is no wrapper: `rtk rm x` runs a program called rtk, and rm is its argument."""
    sp = load_script("features/common/skills/git-work/scripts/shell_parser.py")

    assert "rtk" not in sp.WRAPPERS
    (command,) = sp.parse("rtk rm x")

    assert command.program == "rtk"
    assert command.args == ("rm", "x")


def test_the_test_economy_hook_no_longer_strips_an_rtk_prefix(load_script):
    """A prefixed command is not a test run any more; the bare one still is."""
    economy = load_script("features/common/skills/test-economy/scripts/suite_economy.py")

    assert economy.is_test_run("rtk python3 -m pytest -q") is None
    assert economy.is_test_run("python3 -m pytest -q")["runner"] == "pytest"


def test_the_memory_gate_no_longer_reads_an_rtk_call_as_a_repo_search(load_script, monkeypatch,
                                                                      tmp_path):
    """`rtk rg` is not a grep the gate captures; a bare `rg` still is."""
    monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(tmp_path / "debug"))
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    gate = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(gate, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setattr(gate, "SEARCHED_DIR", tmp_path / "memory-first-searched", raising=False)
    launched = []
    monkeypatch.setattr(gate.subprocess, "Popen",
                        lambda *args, **kwargs: launched.append(args))

    assert gate.capture_greps("Bash", {"command": "rtk rg -n needle src/file.py"}) == []
    assert not launched, "an rtk-prefixed grep was captured"

    assert gate.capture_greps("Bash", {"command": "rg -n needle src/file.py"})
    assert len(launched) == 1
