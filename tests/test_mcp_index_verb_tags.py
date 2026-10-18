"""Leading-verb tags for tool names, and `validate` refusing the placeholder intent.

The 2026-10-18 host-tools smoke left 59 tools `general`, nearly all named `<verb>_<object>` with
the verbs below. A name may infer an *action*, never a technology (#171, changelog 0.51.0), and
only the first `_`/`-` token counts, so `budget` is not `get`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

TD = "features/common/skills/mcp-index/scripts/tool_descriptions.py"
SCRIPT = "features/common/skills/mcp-index/scripts/mcp_index.py"
VALID = {"read", "write", "run", "search", "files", "browser", "build", "database", "sql",
         "refactoring", "semantic", "diagnostic", "tracing", "opentelemetry", "navigation",
         "terminal"}


@pytest.mark.parametrize("name, expected", [
    *[(f"{verb}_thing", ["read"]) for verb in
      ("get", "list", "fetch", "download", "export", "describe")],
    ("whoami", ["read"]),
    ("hf_whoami", ["general"]),  # only the leading token is a verb
    ("query-docs", ["read", "search"]),
    ("search_items", ["read", "search"]),
    *[(f"{verb}_thing", ["write"]) for verb in
      ("create", "update", "delete", "add", "upload", "set", "patch")],
    *[(f"{verb}_thing", ["run"]) for verb in ("cancel", "pause", "resume", "start", "stop")],
    ("Get_Thing", ["read"]),
])
def test_a_leading_verb_names_the_action(load_script, name, expected):
    td = load_script(TD)

    assert td.auto_tags(name, "srv", VALID) == expected


@pytest.mark.parametrize("name", ["budget_report", "targets", "settings_page", "address_book",
                                  "startup_banner", "listing_page", "stopwatch"])
def test_a_verb_inside_a_word_is_not_a_verb(load_script, name):
    td = load_script(TD)

    assert td.auto_tags(name, "srv", VALID) == ["general"]


def test_a_verb_never_infers_a_technology(load_script):
    td = load_script(TD)

    assert set(td.auto_tags("get_dotnet_info", "srv", VALID)) == {"read"}


def test_the_placeholder_intent_is_one_shared_template(load_script):
    td = load_script(TD)

    text = td.heuristic_intent("frob", "")

    assert text == td.PLACEHOLDER_INTENT.format(name="frob")
    assert td.is_placeholder(text)
    assert not td.is_placeholder("Describe what frob does to the cache.")


def test_validate_fails_an_index_holding_the_placeholder(load_script, tmp_path, capsys):
    mod = load_script(SCRIPT)
    index = {"version": "0.1.0", "generated_at": "2026-10-18T00:00:00Z", "sources": [
        {"name": "s", "status": "ok", "tools": {
            "frob": {"tags": ["read"], "intent": mod.td.PLACEHOLDER_INTENT.format(name="frob"),
                     "origin": "heuristic"}}}]}
    (tmp_path / ".ai-badger").mkdir()
    (tmp_path / ".ai-badger" / "mcp-tools.json").write_text(json.dumps(index), encoding="utf-8")

    assert mod.main(["validate", "--target", str(tmp_path)]) == 1

    assert "s:frob: intent is a placeholder" in capsys.readouterr().err
    assert Path(tmp_path / ".ai-badger" / "mcp-tools.json").exists()
