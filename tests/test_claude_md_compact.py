"""Tests for skills/task/scripts/claude_md_compact.py.

Exercises the CLAUDE.md size-budget check end-to-end via main(): no CLAUDE.md present, within
budget, over budget (chars or lines), and --max-chars/--max-lines overrides.

tracker_lib is cached in sys.modules and shared across every loaded script in the whole test
session (load_script only re-executes the requested script, not its `import tracker_lib`
dependency), so every test here snapshots lib.CLAUDE_MD_MAX_CHARS/LINES via monkeypatch before
calling main(). main() unconditionally reassigns those two globals from its argparse defaults
(`lib.CLAUDE_MD_MAX_CHARS = args.max_chars`), which is a *permanent* mutation of the shared
module unless something restores it — without the snapshot, a custom --max-chars in one test
would leak into whichever test (in this file or another) runs next.
"""
from __future__ import annotations

import json
import sys

import pytest


@pytest.fixture
def compact(tmp_path, load_script, monkeypatch):
    module = load_script("features/common/skills/task/scripts/claude_md_compact.py")
    monkeypatch.setattr(module.lib, "CLAUDE_MD", tmp_path / "CLAUDE.md")
    monkeypatch.setattr(module.lib, "CLAUDE_MD_MAX_CHARS", module.lib.CLAUDE_MD_MAX_CHARS)
    monkeypatch.setattr(module.lib, "CLAUDE_MD_MAX_LINES", module.lib.CLAUDE_MD_MAX_LINES)
    return module


def _run(module, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["claude_md_compact.py", *args])
    return module.main()


def test_missing_claude_md_reports_zero_and_is_within_budget(compact, monkeypatch, capsys):
    rc = _run(compact, monkeypatch, [])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert stats["chars"] == 0
    assert stats["lines"] == 0
    assert stats["overBudget"] is False


def test_claude_md_within_default_budget_exits_zero(compact, monkeypatch, capsys, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Notes\n\nShort and sweet.\n", encoding="utf-8")

    rc = _run(compact, monkeypatch, [])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["overBudget"] is False


def test_claude_md_over_char_budget_exits_one(compact, monkeypatch, capsys, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x" * 20000, encoding="utf-8")

    rc = _run(compact, monkeypatch, [])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert stats["overBudget"] is True
    assert stats["chars"] > stats["maxChars"]
    assert stats["lines"] <= stats["maxLines"]


def test_claude_md_over_line_budget_exits_one(compact, monkeypatch, capsys, tmp_path):
    text = "\n".join(f"line {i}" for i in range(200))
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")

    rc = _run(compact, monkeypatch, [])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert stats["overBudget"] is True
    assert stats["lines"] > stats["maxLines"]
    assert stats["chars"] <= stats["maxChars"]


def test_custom_max_chars_override_lowers_the_budget(compact, monkeypatch, capsys, tmp_path):
    # "short text" is comfortably within every default budget on its own.
    (tmp_path / "CLAUDE.md").write_text("short text", encoding="utf-8")

    rc = _run(compact, monkeypatch, ["--max-chars", "5"])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert stats["maxChars"] == 5
    assert stats["overBudget"] is True


def test_custom_max_lines_override_raises_the_budget(compact, monkeypatch, capsys, tmp_path):
    # 200 lines trips the *default* 110-line budget; a generous override should clear it.
    text = "\n".join(f"line {i}" for i in range(200))
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")

    rc = _run(compact, monkeypatch, ["--max-lines", "500"])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert stats["maxLines"] == 500
    assert stats["overBudget"] is False
