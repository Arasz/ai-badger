"""The rtk guard: the hook command ai-badger wires for Claude and Codex instead of `rtk hook <agent>`.

Each case runs the shipped hook command the way a harness does — through a shell, the hook JSON
on stdin — with stub `rtk` and `codex` binaries on a PATH of tmp_path and /usr/bin:/bin. The rtk
stub answers `rtk rewrite` with the exit code a case names (and a separate one when
RTK_REWRITE_HOST=openclaw); the codex stub answers `codex execpolicy check` by matching argv
against the rule-file prefixes it is handed.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RTK = ROOT / "features/common/tools/rtk"
SCRIPTS = ROOT / "features/common/skills/welcome-ai-badger/scripts"

RTK_STUB = f"""#!{sys.executable}
import os, sys
cmd = sys.argv[2]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(repr((sys.argv[1], cmd, os.environ.get("RTK_REWRITE_HOST"))) + "\\n")
host = os.environ.get("RTK_REWRITE_HOST")
if os.environ.get("STUB_INHERITED"):
    code = 0 if host == "openclaw" else 3
else:
    code = int(os.environ["STUB_OPENCLAW" if host == "openclaw" else "STUB_CODE"])
if code in (0, 3):
    print(os.environ.get("STUB_OUT", "\\n".join("rtk " + line for line in cmd.split("\\n"))))
elif code == 2 and os.environ.get("STUB_MESSAGE"):
    print(os.environ["STUB_MESSAGE"])
sys.exit(code)
"""

CODEX_STUB = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
assert args[:2] == ["execpolicy", "check"], args
sep = args.index("--")
files = [args[i + 1] for i in range(2, sep) if args[i] == "--rules"]
argv = args[sep + 1:]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(repr(("codex", files, argv)) + "\\n")
prefixes = [line.split() for f in files for line in open(f) if line.strip()]
hits = [p for p in prefixes if argv[:len(p)] == p]
print(json.dumps({{"matchedRules": [{{"prefix": h}} for h in hits]}} if hits else {{}}))
sys.exit(int(os.environ.get("STUB_CODEX_EXIT", "0")))
"""


def _guard_source() -> str:
    meta = json.loads((RTK / "meta.json").read_text(encoding="utf-8"))
    return (RTK / meta["hooks"]["claude"]["guard"]).read_text(encoding="utf-8")


def hook_command(agent: str) -> str:
    """The marked hook command for *agent*, built from the guard meta.json names."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import tool_hooks  # pylint: disable=import-outside-toplevel
    meta = json.loads((RTK / "meta.json").read_text(encoding="utf-8"))
    spec = meta["hooks"][agent]
    return tool_hooks.guarded_command(
        "rtk", spec["arg"], (RTK / spec["guard"]).read_text(encoding="utf-8"))


class Box:
    """A tmp project with a git root, a CODEX_HOME, stub binaries and a call log."""

    def __init__(self, base: Path):
        self.base = base
        self.repo = base / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.codex_home = base / "codex-home"
        self.codex_home.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        self.log = base / "calls.log"
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(base / "home"),
                    "CODEX_HOME": str(self.codex_home), "STUB_LOG": str(self.log),
                    "STUB_CODE": "3", "STUB_OPENCLAW": "0"}
        self.stub("rtk", RTK_STUB)
        self.stub("codex", CODEX_STUB)

    def stub(self, name: str, body: str, mode: int = 0o755) -> None:
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(mode)

    def rule(self, layer: Path, prefix: str) -> None:
        rules = layer / "rules"
        rules.mkdir(parents=True, exist_ok=True)
        with (rules / "default.rules").open("a", encoding="utf-8") as handle:
            handle.write(prefix + "\n")

    def run(self, agent: str, command: str, cwd: Path | None = None, **env: str):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "cwd": str(cwd or self.repo), "tool_input": {"command": command}}
        proc = subprocess.run(["/bin/sh", "-c", hook_command(agent)], input=json.dumps(event),
                              capture_output=True, text=True, env={**self.env, **env},
                              cwd=str(cwd or self.repo), timeout=30, check=False)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout) if proc.stdout else None

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return [ast.literal_eval(line) for line in self.log.read_text().splitlines()]


@pytest.fixture(name="box")
def box_fixture(tmp_path) -> Box:
    return Box(tmp_path)


def _rewrite(output: dict | None) -> str | None:
    return None if output is None else output["hookSpecificOutput"]["updatedInput"]["command"]


def _decision(output: dict) -> str | None:
    return output["hookSpecificOutput"].get("permissionDecision")


# -- the wiring ---------------------------------------------------------------------------

def test_meta_points_claude_and_codex_at_one_guard_script():
    meta = json.loads((RTK / "meta.json").read_text(encoding="utf-8"))
    assert meta["hooks"]["claude"]["guard"] == meta["hooks"]["codex"]["guard"]
    assert (RTK / meta["hooks"]["claude"]["guard"]).is_file()
    assert "guard" not in meta["hooks"]["copilot"]


def test_the_hook_command_keeps_the_marker_and_never_calls_rtk_hook():
    for agent in ("claude", "codex"):
        command = hook_command(agent)
        assert command.startswith("env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c ")
        assert "rtk hook" not in command


def test_without_rtk_on_path_the_hook_exits_zero_silently(box):
    (box.bin / "rtk").unlink()
    for agent in ("claude", "codex"):
        assert box.run(agent, "git status") is None
    assert box.calls() == []


# -- Claude adapter -----------------------------------------------------------------------

def test_claude_an_ask_matched_command_is_left_unrewritten(box):
    assert box.run("claude", "git push origin main", STUB_CODE="3", STUB_OPENCLAW="3") is None
    assert [c[2] for c in box.calls()] == [None, "openclaw"]


def test_claude_exit_0_rewrites_and_allows(box):
    out = box.run("claude", "git status", STUB_CODE="0")
    assert _rewrite(out) == "rtk git status"
    assert _decision(out) == "allow"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_claude_exit_3_without_an_ask_rule_rewrites_and_leaves_the_decision_to_claude(box):
    out = box.run("claude", "git status", STUB_CODE="3", STUB_OPENCLAW="0")
    assert _rewrite(out) == "rtk git status"
    assert _decision(out) is None


def test_claude_an_inherited_rtk_rewrite_host_never_turns_into_an_allow(box):
    """Review-driven: the session exports RTK_REWRITE_HOST=openclaw and no allow rule covers it."""
    out = box.run("claude", "git status", STUB_INHERITED="1", RTK_REWRITE_HOST="openclaw")
    assert _rewrite(out) == "rtk git status"
    assert _decision(out) is None
    assert box.calls()[0][2] is None, "the first rewrite inherited RTK_REWRITE_HOST"


@pytest.mark.parametrize("code, message", [("1", ""), ("2", ""), ("2", "rtk: denied by pipeline")])
def test_claude_exit_1_or_2_emits_nothing(box, code, message):
    assert box.run("claude", "git status", STUB_CODE=code, STUB_MESSAGE=message) is None


def test_claude_a_rewrite_identical_to_the_original_emits_nothing(box):
    assert box.run("claude", "rtk git status", STUB_CODE="0", STUB_OUT="rtk git status") is None


def test_claude_hands_a_multi_line_command_to_rtk_whole(box):
    """rtk's own matcher sees the second line (checked live); the guard must not split it."""
    command = "git status\ngit push origin main"
    assert box.run("claude", command, STUB_CODE="3", STUB_OPENCLAW="3") is None
    assert [c[1] for c in box.calls()] == [command, command]


# -- Codex adapter ------------------------------------------------------------------------

def test_codex_without_rule_files_rewrites_with_the_mandatory_allow(box):
    out = box.run("codex", "git push origin main")
    assert _rewrite(out) == "rtk git push origin main"
    assert _decision(out) == "allow"
    assert not any(c[0] == "codex" for c in box.calls())


def test_codex_a_user_rule_naming_the_command_leaves_it_unrewritten(box):
    box.rule(box.codex_home, "git push")
    assert box.run("codex", "git push origin main") is None
    assert ("codex", [str(box.codex_home / "rules/default.rules")],
            ["git", "push", "origin", "main"]) in box.calls()


def test_codex_a_project_rule_is_found_from_a_subdirectory_cwd(box):
    box.rule(box.repo / ".codex", "git push")
    sub = box.repo / "src" / "deep"
    sub.mkdir(parents=True)
    assert box.run("codex", "git push origin main", cwd=sub) is None


def test_codex_a_rule_for_another_command_still_rewrites(box):
    box.rule(box.codex_home, "rm")
    out = box.run("codex", "git status")
    assert _rewrite(out) == "rtk git status" and _decision(out) == "allow"


def test_codex_a_chain_with_one_matched_segment_is_left_unrewritten(box):
    box.rule(box.codex_home, "git push")
    assert box.run("codex", "git status && git push origin main") is None
    assert [c[2] for c in box.calls() if c[0] == "codex"] == [
        ["git", "status"], ["git", "push", "origin", "main"]]


@pytest.mark.parametrize("command", [
    "FOO=1 git status", "git status && GIT_TRACE=1 git log", "git add *.py", "ls src/?.txt",
    "if true; then git status; fi", "for f in a; do git status; done",
])
def test_codex_text_codex_does_not_split_is_left_unrewritten(box, command):
    """Review-driven: Codex judges assignments, globs and control flow as one shell invocation."""
    box.rule(box.codex_home, "rm")
    assert box.run("codex", command) is None
    assert not [c for c in box.calls() if c[0] == "codex"]


def test_codex_a_second_line_is_never_hidden_from_the_rules(box):
    """Review-driven: shlex reads a newline as whitespace, which would merge both lines."""
    box.rule(box.codex_home, "git push")
    assert box.run("codex", "git status\ngit push origin main") is None


@pytest.mark.parametrize("command", [
    "git push origin main > out.txt", "(git push origin main)", "git push $(echo origin) main",
    "git push `echo origin` main", "git push origin main &", "git push 'origin",
])
def test_codex_shell_text_that_is_not_a_plain_chain_is_left_unrewritten(box, command):
    box.rule(box.codex_home, "rm")
    assert box.run("codex", command) is None


@pytest.mark.parametrize("command, rewritten", [
    ("bash -c 'git push origin main'", "bash -c 'rtk git push origin main'"),
    ("env git push origin main", "env rtk git push origin main"),
    ("time git push origin main", "time rtk git push origin main"),
], ids=["shell-wrapper", "env-wrapper", "time-wrapper"])
def test_codex_a_rewrite_inside_a_wrapper_is_left_unrewritten(box, command, rewritten):
    """rtk 1.0.1 rewrites inside these wrappers (checked live), where the argv check cannot see."""
    box.rule(box.codex_home, "git push")
    assert box.run("codex", command, STUB_OUT=rewritten) is None


def test_codex_a_rewrite_that_renames_the_command_still_passes(box):
    box.rule(box.codex_home, "rm")
    out = box.run("codex", "cat README.md && git status",
                  STUB_OUT="rtk read README.md && rtk git status")
    assert _rewrite(out) == "rtk read README.md && rtk git status"


def test_codex_missing_with_rule_files_fails_closed(box):
    box.rule(box.codex_home, "rm")
    (box.bin / "codex").unlink()
    assert box.run("codex", "git status") is None


def test_codex_not_executable_with_rule_files_fails_closed(box):
    box.rule(box.codex_home, "rm")
    box.stub("codex", CODEX_STUB, mode=0o644)
    assert box.run("codex", "git status") is None


def test_codex_a_failing_policy_check_fails_closed(box):
    box.rule(box.codex_home, "rm")
    assert box.run("codex", "git status", STUB_CODEX_EXIT="1") is None
