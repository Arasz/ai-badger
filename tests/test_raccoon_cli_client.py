"""tests/test_raccoon_cli_client.py — the ai-raccoon CLI client in project_id.py.

The client is driven by tests/raccoon_cli_fake.py, a scriptable fake executable installed
on PATH with HOME and the invocation log redirected to tmp. Every test names its proving
mutation: the one edit that turns it red. Exit codes come from project_id's constants —
test_exit_code_literals_are_defined_once enforces that — so renumbering stays a one-place
edit.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import ast
import re
import shlex
import time
import tokenize
from pathlib import Path

import pytest

from raccoon_cli_fake import FakeRaccoon, raccoon_cli_fake  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCES = [Path(__file__).resolve(), ROOT / "tests" / "raccoon_cli_fake.py"]
SOURCE = ROOT / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts" / "project_id.py"

GUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def project_id_script(load_script):
    return load_script("features/common/skills/welcome-ai-badger/scripts/project_id.py")


@pytest.fixture
def memory_context_script(load_script):
    return load_script("features/common/skills/ai-raccoon-memory/scripts/memory_context.py")


# ------------------------------------------------------------------ lookup: hits
def test_lookup_hit_legacy_non_guid_token(project_id_script, raccoon_cli_fake):
    """A legacy raw-text id is a hit; register/check accept them as written.

    Mutation: validate the hit token as a uuid, or as anything but ID_TOKEN.fullmatch.
    """
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK, "stdout": "ab12-legacy\n"})

    result = project_id_script.lookup_project_id("demo")

    assert (result.kind, result.id, result.note) == ("hit", "ab12-legacy", None)


def test_lookup_hit_guid(project_id_script, raccoon_cli_fake):
    """Mutation: return kind 'malformed' for a canonical guid line."""
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK, "stdout": GUID + "\n"})

    result = project_id_script.lookup_project_id("demo")

    assert (result.kind, result.id, result.note) == ("hit", GUID, None)


def test_lookup_hit_crlf_line(project_id_script, raccoon_cli_fake):
    """A Windows console writes CRLF; the one line is still one line.

    Mutation: require exactly '\\n' (a '\\r' then fails ID_TOKEN and every Windows hit is
    'malformed').
    """
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK,
                                 "stdout": "ab12-legacy\r\n"})

    result = project_id_script.lookup_project_id("demo")

    assert (result.kind, result.id, result.note) == ("hit", "ab12-legacy", None)


# ------------------------------------------------------------------ lookup: malformed
@pytest.mark.parametrize("stdout", [
    "one\ntwo\n",       # two lines
    "\n",               # one empty line
    "ab12-le",          # no line ending at all — the case a .strip() parser passes
    "bad$token\n",      # a token outside ID_TOKEN
    "a" * 5000 + "\n",  # over 4 KiB
])
def test_lookup_malformed_reply(project_id_script, raccoon_cli_fake, stdout):
    """Mutation: loosen the parser to stdout.strip() (the missing-ending case goes 'hit')."""
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK, "stdout": stdout})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "malformed"
    assert result.id is None
    assert result.note
    assert "not one valid project id" in result.note


# ------------------------------------------------------------------ lookup: failures
def test_lookup_not_found_is_silent(project_id_script, raccoon_cli_fake):
    """18 on get means no project has that name; that is the reuse-miss, not a warning.

    Mutation: attach the unregistered-project note to 'not-found'.
    """
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_PROJECT_UNKNOWN,
                                 "stdout": "", "stderr": "no project named demo\n"})

    result = project_id_script.lookup_project_id("demo")

    assert (result.kind, result.id, result.note) == ("not-found", None, None)


def test_lookup_ambiguous_names_the_listed_ids(project_id_script, raccoon_cli_fake):
    """19 carries its candidates on stderr, after a header; match per line, not position.

    Mutation: parse stdout for candidates (the contract puts them on stderr), or drop the
    'stays silent' sentence.
    """
    stderr = ("Candidates for 'demo':\n"
              + GUID + "\n"
              "ab12-legacy\n")
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_PROJECT_AMBIGUOUS,
                                 "stdout": "", "stderr": stderr})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "ambiguous"
    assert result.id is None
    assert GUID in result.note
    assert "ab12-legacy" in result.note
    assert "stays silent" in result.note


def test_lookup_ambiguous_without_parsable_ids(project_id_script, raccoon_cli_fake):
    """Mutation: crash or claim a list when stderr carries none."""
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_PROJECT_AMBIGUOUS,
                                 "stdout": "",
                                 "stderr": "Candidates:\n(no ids listed)\n"})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "ambiguous"
    assert "stays silent" in result.note
    assert GUID not in result.note
    assert "ab12-legacy" not in result.note


def test_lookup_unparseable_is_the_upgrade_note(project_id_script, raccoon_cli_fake):
    """Exit 11 is the installed 1.56.1's answer to `project id get`; a 1.57.0+ verb change
    reaches the same branch. Mutation: fold 11 into the generic band note (the version
    string disappears from the warning).
    """
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_UNPARSEABLE, "stdout": "",
                                 "stderr": "Unrecognized command or argument 'project'.\n"})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "unavailable"
    assert "1.57.0" in result.note
    assert "did not recognise" in result.note


@pytest.mark.parametrize("offset", [0, 1])
def test_lookup_key_band_is_unavailable(project_id_script, raccoon_cli_fake, offset):
    """20-29 is ai-raccoon's Key category; it is never 'not-found' or 'ambiguous'.

    Mutation: match a band before the specific codes (20 would read as not-found, 21 as
    ambiguous, and the flow would mint and register a project instead of warning).
    """
    code = project_id_script.KEY_BAND[offset]
    raccoon_cli_fake.script(get={"exit": code})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "unavailable"
    assert "bank" in result.note
    assert "key" in result.note


@pytest.mark.parametrize("anchor", ["band-start", "reach-start"])
def test_lookup_server_band_is_unavailable(project_id_script, raccoon_cli_fake, anchor):
    """30-69 is Bank/Port/Server/Reach: unreachable, start failed, too old.

    Mutation: shrink SERVER_BAND to range(30,60) — the Reach code 60 falls to the generic
    note and loses the server wording. (The reach anchor is deliberately independent of
    SERVER_BAND, so the mutation cannot move the code it selects.)
    """
    code = (project_id_script.SERVER_BAND[0] if anchor == "band-start"
            else project_id_script.REACH_BAND[0])
    raccoon_cli_fake.script(get={"exit": code})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "unavailable"
    assert "server" in result.note


def test_lookup_internal_timeout_is_reported_as_a_timeout(project_id_script, raccoon_cli_fake):
    """95 is Internal.Timeout; the note says timed out, not 'failed'.

    Mutation: drop the TIMEOUT_CODE branch.
    """
    raccoon_cli_fake.script(get={"exit": project_id_script.TIMEOUT_CODE})

    result = project_id_script.lookup_project_id("demo")

    assert result.kind == "unavailable"
    assert "timed out" in result.note


def test_lookup_process_timeout_kills_the_fake(project_id_script, raccoon_cli_fake):
    """A hung CLI must not hang the scaffold.

    Mutation: drop timeout= from subprocess.run (this sleeps 5 s, then the fake's empty
    stdout reads 'malformed' instead of 'unavailable').
    """
    raccoon_cli_fake.script(get={"exit": project_id_script.EXIT_OK,
                                 "stdout": "ab12-legacy\n", "sleep": 5})
    started = time.monotonic()

    result = project_id_script.lookup_project_id("demo", timeout=0.5)

    elapsed = time.monotonic() - started
    assert result.kind == "unavailable"
    assert "did not answer" in result.note
    assert elapsed < 3


def test_lookup_missing_executable_is_silent(project_id_script, raccoon_cli_fake,
                                             monkeypatch):
    """A repo that never uses ai-raccoon must not be nagged on every scaffold.

    Mutation: give 'missing' a note.
    """
    monkeypatch.setenv("PATH", "")

    result = project_id_script.lookup_project_id("demo")

    assert (result.kind, result.id, result.note) == ("missing", None, None)
    assert raccoon_cli_fake.arcs() == []


def test_lookup_switch_off_makes_no_call(project_id_script, raccoon_cli_fake, monkeypatch):
    """AI_BADGER_RACCOON_REGISTER=0 is the kill switch; nothing is executed.

    Mutation: read the switch as a truthy value (any non-empty string disables).
    """
    monkeypatch.setenv(project_id_script.REGISTER_SWITCH, "0")

    result = project_id_script.lookup_project_id("demo")

    assert (result.kind, result.id, result.note) == ("off", None, None)
    assert raccoon_cli_fake.arcs() == []


# ------------------------------------------------------------------ register
def test_register_ok_argv_is_exact(project_id_script, raccoon_cli_fake):
    """`--quiet` before the verb, one argv list, no shell.

    Mutation: drop '--quiet', or build one shell string.
    """
    raccoon_cli_fake.script(register={"exit": project_id_script.EXIT_OK,
                                      "stdout": f"registered {GUID}\n"})

    assert project_id_script.register_project_id(GUID, "demo") is None
    assert raccoon_cli_fake.arcs() == [[
        raccoon_cli_fake.exe, "--quiet", "project", "id", "register", GUID, "--name", "demo"]]


def test_register_retired_tells_a_human_and_does_not_retry(project_id_script,
                                                           raccoon_cli_fake):
    """18 on register means the id is retired; a retry cannot fix it.

    Mutation: fall through to the generic band note, or retry once.
    """
    raccoon_cli_fake.script(register={"exit": project_id_script.EXIT_PROJECT_UNKNOWN,
                                      "stderr": "the id is retired\n"})

    note = project_id_script.register_project_id(GUID, "demo")

    assert note
    assert "retired" in note
    assert GUID in note
    assert len(raccoon_cli_fake.arcs()) == 1


def test_register_failure_notes_name_the_command(project_id_script, raccoon_cli_fake):
    """Every non-ok band leaves the operator the exact command to rerun by hand.

    Mutation: drop the shlex.join command from one band's note, or drop --name from it.
    """
    command = shlex.join(["ai-raccoon", "project", "id", "register", GUID, "--name", "demo"])
    codes = [project_id_script.EXIT_UNPARSEABLE, project_id_script.KEY_BAND[0],
             project_id_script.SERVER_BAND[-1], project_id_script.TIMEOUT_CODE,
             project_id_script.EXIT_NOT_GUID]
    for code in codes:
        raccoon_cli_fake.script(register={"exit": code})
        note = project_id_script.register_project_id(GUID, "demo")
        assert note, code
        assert command in note, code
    assert len(raccoon_cli_fake.arcs()) == len(codes)


def test_register_empty_name_omits_the_flag(project_id_script, raccoon_cli_fake):
    """Mutation: always append --name (an empty --name reaches the CLI)."""
    raccoon_cli_fake.script(register={"exit": project_id_script.EXIT_OK})

    project_id_script.register_project_id(GUID, "")

    assert raccoon_cli_fake.arcs() == [[
        raccoon_cli_fake.exe, "--quiet", "project", "id", "register", GUID]]


def test_register_switch_off_makes_no_call(project_id_script, raccoon_cli_fake, monkeypatch):
    """The switch lives in one place: checking it in lookup alone would leave the
    present-file register path reaching the real bank from tests and gates.

    Mutation: check the switch in lookup_project_id only.
    """
    monkeypatch.setenv(project_id_script.REGISTER_SWITCH, "0")

    assert project_id_script.register_project_id(GUID, "demo") is None
    assert raccoon_cli_fake.arcs() == []


def test_register_missing_executable_is_silent(project_id_script, raccoon_cli_fake,
                                               monkeypatch):
    """Mutation: give register's missing-executable case a note (nag on every den-refresh)."""
    monkeypatch.setenv("PATH", "")

    assert project_id_script.register_project_id(GUID, "demo") is None
    assert raccoon_cli_fake.arcs() == []


# ------------------------------------------------------------------ the find_executable twin
def _touch_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


def test_find_raccoon_twin_absolute_entry(project_id_script, memory_context_script,
                                          tmp_path):
    """find_raccoon mirrors memory_context.find_executable; this pins the copies together.

    Mutation: drop the absolute-entry filter in one copy.
    """
    bin_dir = tmp_path / "tools"
    _touch_executable(bin_dir / "ai-raccoon")
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path / "home")}

    assert project_id_script.find_raccoon(env) == str(bin_dir / "ai-raccoon")
    assert memory_context_script.find_executable(env, env["HOME"]) == str(bin_dir / "ai-raccoon")


def test_find_raccoon_twin_ignores_relative_entries(project_id_script, memory_context_script,
                                                    tmp_path, monkeypatch):
    """A relative PATH entry would resolve against whatever cwd the scaffold ran in.

    Mutation: keep relative entries (both copies would find <cwd>/rel/ai-raccoon).
    """
    monkeypatch.chdir(tmp_path)
    _touch_executable(tmp_path / "rel" / "ai-raccoon")
    env = {"PATH": "rel", "HOME": str(tmp_path / "home")}

    assert project_id_script.find_raccoon(env) is None
    assert memory_context_script.find_executable(env, env["HOME"]) is None


def test_find_raccoon_twin_dotnet_fallback(project_id_script, memory_context_script, tmp_path):
    """Mutation: drop the ~/.dotnet/tools fallback in one copy."""
    home = tmp_path / "home"
    _touch_executable(home / ".dotnet" / "tools" / "ai-raccoon")
    env = {"PATH": "", "HOME": str(home)}

    assert project_id_script.find_raccoon(env) == str(home / ".dotnet" / "tools" / "ai-raccoon")
    assert memory_context_script.find_executable(env, env["HOME"]) == \
        str(home / ".dotnet" / "tools" / "ai-raccoon")


def test_find_raccoon_twin_neither(project_id_script, memory_context_script, tmp_path):
    """Mutation: invent a fallback the twin does not have."""
    env = {"PATH": "", "HOME": str(tmp_path / "empty")}

    assert project_id_script.find_raccoon(env) is None
    assert memory_context_script.find_executable(env, env["HOME"]) is None


# ------------------------------------------------------------------ exit codes defined once
def _number_tokens(path: Path):
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.NUMBER and re.fullmatch(r"(0|[1-9][0-9]*)", token.string):
                yield token


def _string_tokens(path: Path):
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type != tokenize.STRING:
                continue
            try:
                value = ast.literal_eval(token.string)
            except (SyntaxError, ValueError):
                continue
            if isinstance(value, str):
                yield token, value


def test_exit_code_literals_are_defined_once():
    """Exit codes live in project_id.py's constants block, not in tests or elsewhere.

    Mutation: write a code as a two-digit int literal in a test (or outside the block), or
    as a two-digit string for FAKE_RACCOON_CLI_EXIT. The old shell check missed the string
    form and passed with a missing file; this asserts existence first.
    """
    for path in [*TEST_SOURCES, SOURCE]:
        assert path.is_file(), f"missing {path}"
    for path in TEST_SOURCES:
        bad_ints = [token.string for token in _number_tokens(path)
                    if len(token.string) == 2]
        assert not bad_ints, f"{path.name}: two-digit int literals {bad_ints}"
        bad_strings = [value for _token, value in _string_tokens(path)
                       if re.fullmatch(r"[1-9][0-9]", value)]
        assert not bad_strings, f"{path.name}: two-digit string literals {bad_strings}"

    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    begin = next(idx for idx, line in enumerate(lines) if "exit codes begin" in line)
    end = next(idx for idx, line in enumerate(lines) if "exit codes end" in line)
    outside = [token.string for token in _number_tokens(SOURCE)
               if len(token.string) == 2 and not begin <= token.start[0] - 1 <= end]
    assert not outside, f"project_id.py: 2-digit int literals outside the block: {outside}"
    bad_strings = [value for _token, value in _string_tokens(SOURCE)
                   if re.fullmatch(r"[1-9][0-9]", value)]
    assert not bad_strings, f"project_id.py: two-digit string literals {bad_strings}"