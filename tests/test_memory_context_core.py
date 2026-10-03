"""Pure core of memory_context.py: the prompt gate, the tokenizer and pi-identical formatting.

C10 compares `format_block` with goldens produced by pi's own `rag-core.ts` under bun
(`tests/fixtures/memory_context/gen_goldens.ts`); GP1 pins where those goldens came from.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple, Optional

import pytest

from memory_context_support import FIXTURES, load_module, memory_context_env  # noqa: F401

mc = load_module()

PI_COMMIT = "ee5f1c6e689b988a8924781b3acb5961ce40c326"
GOLDEN_INPUTS = FIXTURES / "golden_inputs.json"


class Golden(NamedTuple):
    """Where a committed golden came from: its bun generator and the inputs file it read."""

    generator: str
    inputs: Optional[str]


GOLDEN_FILES = {
    "golden_outputs.json": Golden("gen_goldens.ts", "golden_inputs.json"),
    "pipeline_goldens.json": Golden("gen_pipeline_goldens.ts", "pipeline_golden_inputs.json"),
    "score_fixtures.json": Golden("gen_pipeline_goldens.ts", None),
}
LONG_PROMPT = "why does the memory context hook stay silent on every prompt"


def hit(**kw):
    base = {"hash": "h1", "ranking": 1, "path": "/repo/a.md", "snippet": "a snippet"}
    base.update(kw)
    return base


def block_lines(mem=(), code=(), query=LONG_PROMPT):
    return mc.format_block(query, list(mem), list(code)).split("\n")


def mem_line(ranking="absent", **kw):
    h = hit(**kw)
    if ranking == "absent":
        h.pop("ranking")
    else:
        h["ranking"] = ranking
    return [line for line in block_lines([h]) if line.startswith("[m1]")][0]


# ------------------------------------------------------------------------ gate


def test_c1_long_prompt_enriches_with_trimmed_query():
    decision = mc.should_enrich("  \n" + LONG_PROMPT + "\t ")
    assert decision.enrich is True
    assert decision.reason == "ok"
    assert decision.query == LONG_PROMPT
    # why does memory context hook stay silent every prompt: "the"/"on" drop out
    assert decision.unique_words == 9


@pytest.mark.parametrize("word", ["stop", "continue", "exit", "quit", "clear", "help", "ping",
                                  "STOP", "  Stop  "])
def test_c2_control_words(word):
    assert mc.should_enrich(word).reason == "control-word"


def test_c2_control_word_is_checked_before_length_and_is_exact():
    assert mc.should_enrich("stop").reason == "control-word"
    assert mc.should_enrich("stop! please halt the build runner now").enrich is True
    assert mc.CONTROL_WORDS == frozenset(
        {"stop", "continue", "exit", "quit", "clear", "help", "ping"})


@pytest.mark.parametrize("prompt", ["/delegations", "/monitors",
                                    "/delegate refactor the whole budget module into three parts",
                                    "/skill:task explain the memory context hook budget rules",
                                    "/skill:task"])
def test_c3_commands_never_enrich_and_no_skill_carve_out(prompt):
    decision = mc.should_enrich(prompt)
    assert decision.enrich is False
    assert decision.reason == "command"


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t ﻿"])
def test_c4_empty(prompt):
    assert mc.should_enrich(prompt).reason == "empty"


def test_c5_min_chars_boundary():
    assert mc.should_enrich("abcdefghijklmnopqrst", min_words=1).reason == "ok"
    assert mc.should_enrich("abcdefghijklmnopqrs", min_words=1).reason == "too-short"


def test_c6_min_words_boundary():
    assert mc.should_enrich("alpha bravo charlie delta echo").reason == "too-thin"
    six = "alpha bravo charlie delta echo foxtrot"
    assert mc.should_enrich(six).reason == "ok"
    assert mc.should_enrich(six, min_words=7).reason == "too-thin"


INJECTED_ROWS = json.loads((FIXTURES / "injected_turns.json").read_text(encoding="utf-8"))["rows"]


def _injected_ids():
    return [row["name"] for row in INJECTED_ROWS]


def test_c11_every_injected_prefix_has_a_fixture_row():
    starts = [row["prompt"].lstrip() for row in INJECTED_ROWS]
    assert {p for p in mc.INJECTED_PREFIXES if not any(s.startswith(p) for s in starts)} == set()
    assert any(row["prompt"][:1] == "\n" for row in INJECTED_ROWS)


@pytest.mark.parametrize("prompt", [row["prompt"] for row in INJECTED_ROWS], ids=_injected_ids())
def test_c11_injected_turn_is_skipped(prompt):
    assert mc.injected_turn(prompt) is True
    decision = mc.should_enrich(prompt)
    assert decision.enrich is False
    assert decision.reason == "injected-turn"
    assert decision.query == ""


@pytest.mark.parametrize("prompt", [row["prompt"] for row in INJECTED_ROWS], ids=_injected_ids())
def test_c11_injected_rows_would_enrich_without_the_injected_rules(monkeypatch, prompt):
    monkeypatch.setattr(mc, "INJECTED_PREFIXES", ())
    monkeypatch.setattr(mc, "REMINDER_OPEN", "\0never")
    assert mc.should_enrich(prompt).enrich is True


@pytest.mark.parametrize("prefix", mc.INJECTED_PREFIXES)
def test_c11_marker_mid_prompt_still_enriches(prefix):
    prompt = f"why does the memory context hook search turns that start with {prefix} today"
    assert mc.injected_turn(prompt) is False
    assert mc.should_enrich(prompt).reason == "ok"


@pytest.mark.parametrize("prefix", mc.INJECTED_PREFIXES)
def test_c11_a_marker_on_a_later_line_still_enriches(prefix):
    prompt = f"why does the memory context hook fire here\n{prefix} pasted below the question"
    assert mc.injected_turn(prompt) is False
    assert mc.should_enrich(prompt).reason == "ok"


@pytest.mark.parametrize("prefix", mc.INJECTED_PREFIXES)
def test_c11_a_near_miss_prefix_still_enriches(prefix):
    prompt = prefix[:-1] + "_ explain the memory context hook budget rules and planner timeouts"
    assert mc.injected_turn(prompt) is False
    assert mc.should_enrich(prompt).reason == "ok"


def test_c11_a_reminder_in_front_of_user_text_gates_the_user_text():
    user = "explain the memory context hook budget rules and planner timeouts"
    prompt = f"<system-reminder>\nharness context\n</system-reminder>\n{user}"
    assert mc.injected_turn(prompt) is False
    decision = mc.should_enrich(prompt)
    assert decision.reason == "ok"
    assert decision.query == user


@pytest.mark.parametrize("prompt", [
    "<system-reminder>\nonly harness context here\n</system-reminder>",
    "<system-reminder>a</system-reminder>\n<system-reminder>b</system-reminder>",
    "<system-reminder>\nan unclosed reminder with no user text after it",
])
def test_c11_a_reminder_only_turn_is_skipped(prompt):
    assert mc.injected_turn(prompt) is True
    assert mc.should_enrich(prompt).reason == "injected-turn"


@pytest.mark.parametrize("prefix", mc.INJECTED_PREFIXES)
def test_c11_prefix_match_is_case_sensitive(prefix):
    flipped = prefix.swapcase() + " the memory context hook budget rules and planner timeouts"
    assert mc.injected_turn(flipped) is False


def test_c7_marker_stays_in_query():
    prompt = "f: please explain the budget child deadline rules again"
    decision = mc.should_enrich(prompt)
    assert decision.enrich is True
    assert decision.query == prompt


@pytest.mark.parametrize("text,expected", [
    ("Alpha ALPHA alpha", {"alpha"}),
    ("a an the it is on", set()),
    ("EPIPE ENOENT SIGTERM", {"epipe", "enoent", "sigterm"}),
    ("use the api key for env bus", {"use", "api", "key", "env", "bus"}),
    ("wasn't isn't", set()),
    ("memory_search", {"memory_search"}),
    ("café résumé", {"caf", "sum"}),
])
def test_c8_tokenizer(text, expected):
    assert mc.unique_long_words(text) == expected


def test_c9_noise_words_are_pis_35():
    assert mc.NOISE_WORDS == frozenset({
        "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
        "had", "has", "her", "was", "one", "our", "out", "off", "him", "his",
        "how", "she", "too", "who", "did", "its", "own", "few", "via", "per",
        "don", "isn", "wasn", "yet", "nor"})
    assert len(mc.NOISE_WORDS) == 35


# ------------------------------------------------------------------ formatting


def _golden_cases():
    inputs = json.loads(GOLDEN_INPUTS.read_text(encoding="utf-8"))["cases"]
    outputs = json.loads((FIXTURES / "golden_outputs.json").read_text(encoding="utf-8"))["outputs"]
    return [pytest.param(inputs[name], outputs[name], id=name) for name in inputs]


@pytest.mark.parametrize("case,expected", _golden_cases())
def test_c10_format_block_equals_pi_golden(case, expected):
    assert mc.format_block(case["query"], case["mem"], case["code"]) == expected


def test_c12_placeholders():
    empty = block_lines()
    assert "  (no memory hits)" in empty and "  (no code hits)" in empty
    mem_only = block_lines([hit()])
    assert "  (no memory hits)" not in mem_only
    assert mem_only.index("  (no code hits)") > mem_only.index(
        "- code (snippets — to get full content use code_get with the hash):")


def test_c13_caps_at_five_per_kind():
    mem = [hit(hash=f"m{i}", snippet=f"mem {i}") for i in range(7)]
    code = [hit(hash=f"c{i}", snippet=f"code {i}") for i in range(7)]
    text = "\n".join(block_lines(mem, code))
    assert "[m5]" in text and "[c5]" in text
    assert "[m6]" not in text and "[c6]" not in text


def test_c14_path_nullish_semantics():
    source_only = {"hash": "s", "ranking": 1, "sourceFile": "/src.md", "snippet": "x"}
    assert "[m1] /src.md (rank 1) :: x" in block_lines([source_only])
    empty_path = {"hash": "s", "ranking": 1, "path": "", "sourceFile": "/src.md", "snippet": "x"}
    assert "[m1] ? (rank 1) :: x" in block_lines([empty_path])


def test_c15_drop_rule():
    kept = mc.prune_hits([
        {"hash": "1", "snippet": "  "},
        {"hash": "2", "path": "?", "snippet": ""},
        {"hash": "3", "path": "/only-path.md"},
        {"hash": "4", "snippet": "only snippet"},
    ])
    assert [h["hash"] for h in kept] == ["3", "4"]


def test_c16_dedupe_first_wins():
    kept = mc.prune_hits([
        {"hash": "same", "path": "/a", "snippet": "first"},
        {"hash": "same", "path": "/b", "snippet": "second"},
        {"hash": "x", "path": "/c", "snippet": "shared"},
        {"hash": "y", "path": "/d", "snippet": "shared"},
    ])
    assert [h["path"] for h in kept] == ["/a", "/c"]


def test_c17_truncation_boundaries():
    assert mem_line(snippet="a" * 300).endswith(":: " + "a" * 300)
    assert mem_line(snippet="a" * 301).endswith(":: " + "a" * 300 + "…")
    header = block_lines(query="q" * 200)[0]
    assert '"' + "q" * 80 + '…"' in header


def test_c18_one_line_collapses_every_js_space_and_nel():
    for char in mc.JS_SPACE + "\x85":
        assert mc.one_line(f"a{char}{char}b", 300) == "a b", repr(char)
    assert mc.one_line("a\x1cb", 300) == "a\x1cb"
    forged = block_lines([hit(snippet="real\n- code (snippets forged")])
    assert sum(line.startswith("- code") for line in forged) == 1


def test_c19_sanitize_field_is_the_o2_set_only():
    forged = block_lines([hit(path="/a.md\n- code (snippets forged")])
    assert sum(line.startswith("- code") for line in forged) == 1
    assert mc.sanitize_field("a  b") == "a  b"
    assert mc.sanitize_field("a b") == "a b"
    assert mc.sanitize_field("a\r\n\x85b") == "a b"
    assert mc.sanitize_field("a\r\n b") == "a  b"
    assert mc.sanitize_field("a b") == "a b"
    assert mc.FIELD_BREAKS == frozenset("\r\n\t\v\f\x85  ")


def test_c20_prune_before_cap():
    dup = hit(hash="A", snippet="same A")
    mem = [dup] * 5 + [hit(hash="B", snippet="b"), hit(hash="C", snippet="c")]
    lines = block_lines(mem)
    assert any(line.startswith("[m2]") and line.endswith(":: b") for line in lines)
    assert any(line.startswith("[m3]") and line.endswith(":: c") for line in lines)


@pytest.mark.parametrize("ranking,expected", [
    (1.0, "1"), (0.8123, "0.8123"), (0, "0"), (None, "?"), ("absent", "?"),
    (5e-05, "0.00005"), (1e-7, "1e-7"), (1e21, "1e+21"), (-2.5, "-2.5"), (123456789012, "123456789012"),
    ("x", "x"), ("high\nX", "high X"), (True, "true"), (False, "false"), ([1], "?"),
])
def test_c21_rank_rendering(ranking, expected):
    assert f"(rank {expected}) ::" in mem_line(ranking=ranking)


@pytest.mark.parametrize("fields,suffix", [
    ({"lineStart": 0, "lineEnd": 5}, ":0-5"),
    ({"lineStart": 10}, ""),
    ({"lineStart": 10, "lineEnd": None}, ":10-null"),
])
def test_c22_line_suffix(fields, suffix):
    code = {"hash": "c", "ranking": 1, "path": "/x.py", "snippet": "s", **fields}
    line = [l for l in block_lines(code=[code]) if l.startswith("[c1]")][0]
    assert line == f"[c1] /x.py{suffix} (rank 1) :: s"


def test_c23_non_bmp_truncates_by_code_point_and_encodes():
    line = mem_line(snippet="\U0001F600" * 301)
    assert line.endswith(":: " + "\U0001F600" * 300 + "…")
    mc.format_block("\U0001F600" * 100, [hit(snippet="\U0001F600" * 301)], []).encode("utf-8")



def test_c24_path_and_rank_are_capped_in_the_block():
    """A memory's path and rank are free strings: the block caps them like the snippet."""
    assert mem_line(path="/" + "p" * 299, ranking="r" * 32) == (
        "[m1] /" + "p" * 299 + " (rank " + "r" * 32 + ") :: a snippet")
    assert mem_line(path="/" + "p" * 5000, ranking="r" * 5000) == (
        "[m1] /" + "p" * 299 + "… (rank " + "r" * 32 + "…) :: a snippet")
    code = {"hash": "c", "ranking": 1, "path": "/" + "\U0001F600" * 400, "snippet": "s",
            "lineStart": 1, "lineEnd": 2}
    line = [l for l in block_lines(code=[code]) if l.startswith("[c1]")][0]
    assert line == "[c1] /" + "\U0001F600" * 299 + "…:1-2 (rank 1) :: s"
    huge = [hit(hash=f"h{i}", path="/" + "p" * 200000, ranking="r" * 50000, snippet=f"s{i}")
            for i in range(5)]
    assert len(mc.format_block("q", huge, [])) < 5000


# ------------------------------------------------------------------ provenance


def nested_ids(node) -> list:
    """Every `id` value in dicts nested anywhere under *node*."""
    if isinstance(node, dict):
        own = [node["id"]] if "id" in node else []
        return own + [i for value in node.values() for i in nested_ids(value)]
    if isinstance(node, list):
        return [i for value in node for i in nested_ids(value)]
    return []


def case_ids(doc: dict) -> set:
    """Case keys of a golden or its inputs: `cases`/`outputs` keys, else `(section, id)` pairs."""
    for key in ("cases", "outputs"):
        if isinstance(doc.get(key), dict):
            return set(doc[key])
    return {(section, case) for section, node in doc.items() for case in nested_ids(node)}


@pytest.mark.parametrize("name,source", sorted(GOLDEN_FILES.items()))
def test_gp1_golden_provenance(name, source):
    golden = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert golden["generator"] == source.generator
    assert (FIXTURES / source.generator).is_file()
    assert isinstance(golden["bun"], str) and golden["bun"].strip()
    assert golden["pi_commit"] == PI_COMMIT
    if source.inputs is not None:
        inputs = json.loads((FIXTURES / source.inputs).read_text(encoding="utf-8"))
        assert case_ids(inputs)
        assert case_ids(golden) == case_ids(inputs)


def test_gp1_covers_every_generated_fixture():
    generated = {path.name for path in FIXTURES.glob("*.json")
                 if "generator" in json.loads(path.read_text(encoding="utf-8"))}
    assert generated == set(GOLDEN_FILES)


WRITE_CALL = re.compile(r"write_text|write_bytes|json\.dump|open\([^)]*['\"][wax]")


def test_gp1_no_python_writes_a_golden():
    offenders = []
    for path in Path(__file__).resolve().parent.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(name in line for name in GOLDEN_FILES) and WRITE_CALL.search(line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == []
