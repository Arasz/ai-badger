"""Tests for skills/task/scripts/claude_md_compact.py.

Exercises the CLAUDE.md size-budget check end-to-end via main(): no CLAUDE.md present, within
budget, over budget (chars or lines), and --max-chars/--max-lines overrides.

tracker_lib is cached in sys.modules and shared across every loaded script in the whole test
session (load_script only re-executes the requested script, not its `import tracker_lib`
dependency), so the fixture redirects lib.CLAUDE_MD and lib.CONFIG_JSON at tmp_path. CONFIG_JSON
matters because doc_budget() reads a project's agentDocs override from it — left pointing at
this repo's own config, these tests would assert against whatever budget ai-badger happens to
declare.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys

import pytest
from conftest import _test_write


@pytest.fixture
def compact(tmp_path, load_script, monkeypatch):
    module = load_script("features/common/skills/task/scripts/claude_md_compact.py")
    monkeypatch.setattr(module.lib, "CLAUDE_MD", tmp_path / "CLAUDE.md")
    monkeypatch.setattr(module.lib, "CONFIG_JSON", tmp_path / ".ai-badger" / "config.json")
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
    _test_write(tmp_path / "CLAUDE.md", "# Notes\n\nShort and sweet.\n", encoding="utf-8")

    rc = _run(compact, monkeypatch, [])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["overBudget"] is False


def test_claude_md_over_char_budget_exits_one(compact, monkeypatch, capsys, tmp_path):
    # Derived from the shipped default, not pinned: a raised default must not quietly make the
    # input fit and turn this into a test that cannot fail.
    _test_write(tmp_path / "CLAUDE.md", "x" * (compact.lib.CLAUDE_MD_MAX_CHARS + 1), encoding="utf-8")

    rc = _run(compact, monkeypatch, [])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert stats["overBudget"] is True
    assert stats["chars"] > stats["maxChars"]
    assert stats["lines"] <= stats["maxLines"]


def test_claude_md_over_line_budget_exits_one(compact, monkeypatch, capsys, tmp_path):
    text = "\n".join(f"line {i}" for i in range(compact.lib.CLAUDE_MD_MAX_LINES + 1))
    _test_write(tmp_path / "CLAUDE.md", text, encoding="utf-8")

    rc = _run(compact, monkeypatch, [])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert stats["overBudget"] is True
    assert stats["lines"] > stats["maxLines"]
    assert stats["chars"] <= stats["maxChars"]


def test_custom_max_chars_override_lowers_the_budget(compact, monkeypatch, capsys, tmp_path):
    # "short text" is comfortably within every default budget on its own.
    _test_write(tmp_path / "CLAUDE.md", "short text", encoding="utf-8")

    rc = _run(compact, monkeypatch, ["--max-chars", "5"])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert stats["maxChars"] == 5
    assert stats["overBudget"] is True


def test_custom_max_lines_override_raises_the_budget(compact, monkeypatch, capsys, tmp_path):
    # One line over the default trips it; a generous override should clear it. Both numbers are
    # derived, so raising the default cannot turn this into a test that passes without the flag.
    over_default = compact.lib.CLAUDE_MD_MAX_LINES + 1
    override = over_default * 2
    text = "\n".join(f"line {i}" for i in range(over_default))
    _test_write(tmp_path / "CLAUDE.md", text, encoding="utf-8")

    rc = _run(compact, monkeypatch, ["--max-lines", str(override)])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert stats["maxLines"] == override
    assert stats["overBudget"] is False


def test_a_cli_budget_beats_the_projects_agentDocs_override(  # pylint: disable=invalid-name
        compact, monkeypatch, capsys, tmp_path):  # spells the config key, so camelCase stays
    # A project's own agentDocs.maxLines (120) must not shadow an explicit CLI override (500).
    text = "\n".join(f"line {i}" for i in range(200))
    _test_write(tmp_path / "CLAUDE.md", text, encoding="utf-8")
    (tmp_path / ".ai-badger").mkdir()
    _test_write(tmp_path / ".ai-badger" / "config.json", json.dumps({"agentDocs": {"maxLines": 120}}), encoding="utf-8")

    rc = _run(compact, monkeypatch, ["--max-lines", "500"])

    stats = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert stats["maxLines"] == 500
