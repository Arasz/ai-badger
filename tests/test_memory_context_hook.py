"""`memory_context_hook.py`: the Claude/Copilot stdin/stdout entry over `memory_context.build()`.

Rows H1-H12 and W2a (plan `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-plan.md` §6, P3a).
In-process rows (H1-H6, H9, H11) load the hook by path via `load_script` and feed it a fake
stdin; subprocess rows (H7, H8, H10, H12) run the real file with `sys.executable` so a mutation
that only "in-process" tooling would hide (bare package-name imports, sys.path leakage) still
shows up here. `memory_context_env` (imported for its autouse effect) supplies the hermetic
HOME/PATH/PYTHONPATH scrub, the fake `ai-raccoon` and the spawn/network guards.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import memory_context_support as support
import memory_context_openrouter as fake_router
from memory_context_openrouter import FakeOpenRouter, reply
from memory_context_support import ROOT, SCRIPTS, memory_context_env  # noqa: F401

HOOK_RELPATH = "features/common/skills/ai-raccoon-memory/scripts/memory_context_hook.py"
HOOK_PATH = ROOT / HOOK_RELPATH
HOOKS_JSON = ROOT / "features" / "common" / "hooks" / "hooks.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "memory_context" / "copilot_user_prompt_payload.json"

# The hook's own private loader key (memory_context_hook.MEMORY_CONTEXT_MODULE_NAME): cleared
# around every test so one test's scaffold layout (or monkeypatched `build`) can never leak into
# the next through the process-global sys.modules cache.
MEMORY_CONTEXT_MODULE_NAME = "ai_badger_memory_context_entry"

PROMPT = "why does the memory context hook stay silent on every prompt"

# Mirrors fake_ai_raccoon.py's DEFAULT_HITS ("hits" mode, the fixture's default) so a test can
# compute the exact block memory_context.build() must produce against the real fake.
DEFAULT_HITS_RESULTS = [
    {"hash": "m-one", "ranking": 1, "path": "/repo/docs/one.md", "snippet": "first memory"},
    {"hash": "m-two", "ranking": 0.5, "path": "/repo/docs/two.md", "snippet": "second memory"},
]
DEFAULT_HITS_CODE = [
    {"hash": "c-one", "ranking": 0.75, "path": "/repo/src/one.py", "snippet": "def one(): pass",
     "lineStart": 1, "lineEnd": 2},
]

MODULE_FILES = ("memory_context.py", "badger_store.py", "openrouter_client.py", "query_pipeline.py")
CATALOG_RESOLVER = ROOT / "features" / "common" / "skills" / "task" / "scripts" / "model_groups.py"
CATALOG_REGISTRY = ROOT / "features" / "common" / "data" / "model-groups.json"

WRAPPER_SOURCE = """\
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("wrapped_memory_context_hook", {hook_path!r})
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
mc = hook._load_memory_context()
mc.SINGLE_BUDGET_SECONDS = {budget!r}
sys.exit(hook.guarded_main())
"""


@pytest.fixture(autouse=True, name="fresh_memory_context_cache")
def _fresh_memory_context_cache():
    """Every test loads its own scaffold; a cached module from a previous one must not leak."""
    sys.modules.pop(MEMORY_CONTEXT_MODULE_NAME, None)
    yield
    sys.modules.pop(MEMORY_CONTEXT_MODULE_NAME, None)


@pytest.fixture(name="hook")
def _hook(load_script):
    return load_script(HOOK_RELPATH)


@pytest.fixture(name="router")
def _router():
    server = FakeOpenRouter()
    yield server
    server.stop()


def _run(hook_module, monkeypatch, payload) -> int:
    """Feed *payload* to the hook's stdin and run it exactly as `__main__` would."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return hook_module.guarded_main()


def _claude_payload(cwd, session_id="sess-1", prompt=PROMPT) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session_id,
            "prompt": prompt, "cwd": str(cwd)}


def _expected_block(prompt=PROMPT):
    module = support.load_module()
    return module.format_block(prompt, DEFAULT_HITS_RESULTS, DEFAULT_HITS_CODE)


def _run_subprocess(hook_path, payload, env, **kwargs):
    return subprocess.run([sys.executable, str(hook_path)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=15, check=False,
                          **kwargs)


def install_scaffold(root: Path, project_id: str = "proj-h12") -> Path:
    """A skill-layout scaffold: the four core modules, the entry, the task resolver, the
    registry and a project id — everything the real entry needs to run the pipeline alone."""
    scripts = root / ".ai-badger" / "skills" / "ai-raccoon-memory" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in (*MODULE_FILES, HOOK_RELPATH.rsplit("/", 1)[-1]):
        shutil.copy(SCRIPTS / name, scripts / name)
    resolver_dir = root / ".ai-badger" / "skills" / "task" / "scripts"
    resolver_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(CATALOG_RESOLVER, resolver_dir / "model_groups.py")
    shutil.copy(CATALOG_REGISTRY, root / ".ai-badger" / "model-groups.json")
    (root / ".ai-badger" / "project-id").write_text(project_id, encoding="utf-8")
    return scripts / HOOK_RELPATH.rsplit("/", 1)[-1]


def _planner_body(queries) -> bytes:
    # TOTAL_QUERIES_MIN (query_pipeline.py) is 2: a single-query plan fails validation and the
    # pipeline falls back to one search on the raw prompt (B12's behaviour), which would make
    # this row indistinguishable from the single-search path it means to exercise.
    plan = {"concepts": [{"name": "ConceptH12", "queries": list(queries)}]}
    return json.dumps({"choices": [{"message": {"role": "assistant",
                                                "content": json.dumps(plan)}}]}).encode()


def _jev_body(count: int) -> bytes:
    return json.dumps({"answers": {f"c{i}": {"type": "score", "score": float(i)}
                                   for i in range(count)}}).encode()


# --------------------------------------------------------------------------------------- H1, H2


def test_h1_claude_payload_gets_the_hookspecificoutput_envelope(hook, monkeypatch, capsys,
                                                                 memory_context_env):
    env = memory_context_env
    project = env.project()
    rc = _run(hook, monkeypatch, _claude_payload(project))
    assert rc == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert set(parsed) == {"hookSpecificOutput"}
    inner = parsed["hookSpecificOutput"]
    assert set(inner) == {"hookEventName", "additionalContext"}
    assert inner["hookEventName"] == "UserPromptSubmit"
    assert inner["additionalContext"] == _expected_block()
    assert len(env.fake.runs()) == 1


def test_h2_copilot_payload_gets_the_flat_shape_with_no_envelope(hook, monkeypatch, capsys,
                                                                  memory_context_env):
    env = memory_context_env
    project = env.project()
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["cwd"] = str(project)
    rc = _run(hook, monkeypatch, payload)
    assert rc == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert set(parsed) == {"additionalContext"}
    assert parsed["additionalContext"] == _expected_block(payload["prompt"])
    call = env.fake.calls()[-1]
    assert call["params"]["arguments"]["sessionId"] == payload["sessionId"]


# -------------------------------------------------------------------------------------------- H3


@pytest.mark.parametrize("mode", ["iserror", "crash"])
def test_h3_expected_failure_states_are_silent_and_unlogged(hook, monkeypatch, capsys,
                                                             memory_context_env, mode):
    env = memory_context_env
    env.fake.mode(mode)
    project = env.project()
    log_path = env.home / ".ai-badger" / "hook-errors.log"
    rc = _run(hook, monkeypatch, _claude_payload(project))
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""
    assert not log_path.exists()
    assert len(env.fake.runs()) == 1


# -------------------------------------------------------------------------------------------- H4


def test_h4_build_raising_is_logged_not_shown(hook, monkeypatch, capsys, memory_context_env):
    env = memory_context_env
    project = env.project()
    memory_context = hook._load_memory_context()  # pylint: disable=protected-access

    def boom(*_args, **_kwargs):
        raise RuntimeError("h4-boom-should-never-print")

    monkeypatch.setattr(memory_context, "build", boom)
    rc = _run(hook, monkeypatch, _claude_payload(project))
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    log_path = env.home / ".ai-badger" / "hook-errors.log"
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "RuntimeError" in text
    assert "h4-boom-should-never-print" not in text
    assert PROMPT not in text
    assert PROMPT not in captured.err


# -------------------------------------------------------------------------------------------- H5


@pytest.mark.parametrize("stdin_text", ["not json at all", "[1, 2, 3]", ""])
def test_h5_odd_stdin_is_silent_with_no_spawn(hook, monkeypatch, capsys, memory_context_env,
                                              stdin_text):
    env = memory_context_env
    log_path = env.home / ".ai-badger" / "hook-errors.log"
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    rc = hook.guarded_main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""
    assert not log_path.exists()
    assert env.fake.runs() == []


# -------------------------------------------------------------------------------------------- H6


def test_h6_payload_cwd_beats_claude_project_dir_absent_cwd_falls_back(hook, monkeypatch,
                                                                       memory_context_env):
    env = memory_context_env
    project_a = env.project(project_id="id-a", name="proj-a")
    project_b = env.project(project_id="id-b", name="proj-b")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_b))

    _run(hook, monkeypatch, _claude_payload(project_a, session_id="sess-h6a"))
    assert env.fake.calls()[-1]["params"]["arguments"]["projectId"] == "id-a"

    no_cwd = {"hook_event_name": "UserPromptSubmit", "session_id": "sess-h6b", "prompt": PROMPT}
    _run(hook, monkeypatch, no_cwd)
    assert env.fake.calls()[-1]["params"]["arguments"]["projectId"] == "id-b"


# -------------------------------------------------------------------------------------------- H7


def test_h7_subprocess_entry_runs_the_real_pipeline(memory_context_env):
    env = memory_context_env
    project = env.project()
    payload = _claude_payload(project)
    result = _run_subprocess(HOOK_PATH, payload, dict(os.environ))
    assert result.returncode == 0
    parsed = json.loads(result.stdout.strip())
    assert parsed["hookSpecificOutput"]["additionalContext"] == _expected_block()
    assert len(env.fake.runs()) == 1


# -------------------------------------------------------------------------------------------- H8


def _write_wrapper(path: Path, budget: float) -> None:
    path.write_text(WRAPPER_SOURCE.format(hook_path=str(HOOK_PATH), budget=budget),
                    encoding="utf-8")


@pytest.mark.parametrize("mode", ["hang", "drip"])
def test_h8_a_lowered_budget_still_exits_quickly_and_reaps_the_fake(memory_context_env, tmp_path,
                                                                    mode):
    env = memory_context_env
    env.fake.mode(mode)
    project = env.project()
    wrapper = tmp_path / "wrapper.py"
    _write_wrapper(wrapper, 0.3)
    payload = _claude_payload(project, session_id=f"sess-h8-{mode}")

    started = time.monotonic()
    result = _run_subprocess(wrapper, payload, dict(os.environ))
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 3.0
    assert result.stdout == ""
    for run in env.fake.runs():
        assert support.pid_gone(run["pid"])


# -------------------------------------------------------------------------------------------- H9


def test_h9_hook_copied_alone_without_its_sibling_is_silent(tmp_path, monkeypatch, capsys):
    lone_dir = tmp_path / "lone"
    lone_dir.mkdir()
    shutil.copy(HOOK_PATH, lone_dir / "memory_context_hook.py")
    spec = importlib.util.spec_from_file_location(
        "lone_memory_context_hook", lone_dir / "memory_context_hook.py")
    hook_alone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_alone)

    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "sess-h9",
              "prompt": PROMPT, "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = hook_alone.guarded_main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""


# ------------------------------------------------------------------------------------------- H10


def test_h10_closed_stdout_never_crashes(memory_context_env):
    env = memory_context_env
    project = env.project()
    payload = _claude_payload(project, session_id="sess-h10")
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, str(HOOK_PATH)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    proc.stdout.close()  # the host hung up before reading anything
    try:
        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()
        rc = proc.wait(timeout=15)
        stderr = proc.stderr.read()
    finally:
        proc.stderr.close()
    assert rc == 0
    assert "Traceback" not in stderr
    assert len(env.fake.runs()) == 1


# ------------------------------------------------------------------------------------------- H11


def test_h11_a_prompt_marker_passes_through_unstripped(hook, monkeypatch, memory_context_env):
    env = memory_context_env
    project = env.project()
    prompt = ("f: please check whether the memory context hook and the prompt markers hook "
              "can coexist safely on one UserPromptSubmit event")
    _run(hook, monkeypatch, _claude_payload(project, session_id="sess-h11", prompt=prompt))
    call = env.fake.calls()[-1]
    assert call["params"]["arguments"]["query"] == prompt
    assert "f:" in call["params"]["arguments"]["query"]


# ------------------------------------------------------------------------------------------- H12


def test_h12_pipeline_through_the_real_entry_in_a_scaffold_layout(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    query_one = "memory context hook scaffold resolution walkthrough"
    query_two = "memory context hook scaffold task resolver lookup"
    mem_hit = {"hash": "h12-m1", "ranking": 2, "path": "/repo/docs/h12-one.md",
              "snippet": "the scaffold-shaped memory hit"}
    code_hit = {"hash": "h12-c1", "ranking": 1, "path": "/repo/src/h12.py",
               "snippet": "def h12(): pass", "lineStart": 1, "lineEnd": 2}
    env.fake.hits({query_one: {"results": [mem_hit], "code": []},
                  query_two: {"results": [], "code": [code_hit]}})
    router.script(fake_router.CHAT_PATH, reply(200, _planner_body([query_one, query_two])))
    router.script(fake_router.DECISIONS_PATH, reply(200, _jev_body(2)))

    project = env.root / "h12-project"
    hook_path = install_scaffold(project)
    # A cwd with none of the scaffold's files: a sibling resolved from the process cwd instead
    # of from the copied entry's own __file__ would find nothing here.
    elsewhere = env.root / "h12-elsewhere"
    elsewhere.mkdir()

    payload = _claude_payload(project, session_id="sess-h12")
    proc_env = dict(os.environ)
    proc_env["OPENROUTER_API_KEY"] = "sk-test-h12"
    proc_env["AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE"] = router.url

    result = _run_subprocess(hook_path, payload, proc_env, cwd=str(elsewhere))

    assert result.returncode == 0
    parsed = json.loads(result.stdout.strip())
    block = parsed["hookSpecificOutput"]["additionalContext"]
    expected = support.load_module().format_block(PROMPT, [mem_hit], [code_hit])
    assert block == expected

    chat_requests = [r for r in router.requests if r["path"] == fake_router.CHAT_PATH]
    decision_requests = [r for r in router.requests if r["path"] == fake_router.DECISIONS_PATH]
    assert len(chat_requests) == 1
    assert len(decision_requests) >= 1
    assert "sk-test-h12" not in result.stdout
    assert "sk-test-h12" not in result.stderr
    assert not env.guards.marker.exists()


# -------------------------------------------------------------------------------------------- W2a


def test_w2a_hooks_json_timeout_exceeds_the_pipeline_total_plus_grace():
    """Claude's UserPromptSubmit host default is 30s with no documented maximum
    (code.claude.com/docs/en/hooks, cited by the plan's feasibility review) — well under this
    hook's own worst case (the 90s pipeline budget plus the 0.5s proxy-close grace), so the
    explicit `timeout` below must outlast every module budget, not just be present."""
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    entries = [h for group in hooks["hooks"]["UserPromptSubmit"] for h in group["hooks"]
              if "memory_context_hook.py" in h["command"]]
    assert len(entries) == 1
    timeout = entries[0].get("timeout")
    assert isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
    module = support.load_module()
    threshold = max(module.SINGLE_BUDGET_SECONDS, module.PIPELINE_TOTAL_SECONDS) + \
        module.GRACE_SECONDS
    assert timeout > threshold
