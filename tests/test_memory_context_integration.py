"""The memory-context hook as the catalog ships it: manifest arms, generated wiring, and the
wired command strings run against the fakes.

Rows I1-I11 (plan `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-plan.md` §6, P4). Every
scaffold row runs the real Scaffolder into the test's temp HOME, so the Hermes plugin dir and
the pi extension dir it installs are scratch copies. `memory_context_env` (imported for its
autouse effect) supplies the env scrub, the fake `ai-raccoon`, and the spawn and network guards.
"""
# pylint: disable=redefined-outer-name  # the shared autouse fixture is requested by name
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import memory_context_openrouter as fake_router
import memory_context_support as support
import scaffold_helpers
from memory_context_openrouter import FakeOpenRouter, reply
from memory_context_support import ROOT, memory_context_env  # noqa: F401
from memory_context_support import forget_modules_a_test_imported  # noqa: F401  (autouse)

HOOKS_DIR = ROOT / "features" / "common" / "hooks"
MANIFEST = HOOKS_DIR / "hooks-manifest.json"
ADAPTER_DIR = ROOT / "features" / "pi" / "adjustments" / "adapter"
PI_HOOKS_ADJUSTER = ROOT / "features" / "pi" / "adjustments" / "adjust_hooks.py"
PAYLOAD_FIXTURE = ROOT / "tests" / "fixtures" / "memory_context" / "copilot_user_prompt_payload.json"
WELCOME_SCRIPTS = ROOT / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts"

ENTRY = "memory_context_hook.py"
MARKERS = "user_prompt_hook.py"
NEW_FILES = ("memory_context.py", "openrouter_client.py", "query_pipeline.py", ENTRY)
HERMES_MODULES = ("memory_context.py", "openrouter_client.py", "query_pipeline.py",
                  "model_groups.py", "ai_badger_hooks.py")
ALL_AGENTS = ["claude", "copilot", "hermes", "pi"]
SKILLS = ["ai-raccoon-memory", "prompt-markers", "task"]
HOOK_NAME = "memory-context"

PROMPT = "why does the memory context hook stay silent in a freshly scaffolded project"
HITS = {"results": [{"hash": "i-m1", "ranking": 1, "path": "/repo/docs/integration.md",
                     "snippet": "integration memory snippet"}],
        "code": [{"hash": "i-c1", "ranking": 0.5, "path": "/repo/src/integration.py",
                  "snippet": "def integration(): pass", "lineStart": 1, "lineEnd": 2}]}
SIBLING_PREFIX = "ai_badger_memory_context__"
HERMES_LOAD_PREFIX = "ai_badger_test_integration_hooks_"


# ------------------------------------------------------------------------------ helpers


def _script_of(command: str) -> str:
    """The trailing `*.py` a wired command runs, by filename (never a substring match)."""
    found = re.findall(r"([\w.-]+\.py)", command)
    return found[-1] if found else ""


def _claude_commands(target: Path, event: str = "UserPromptSubmit") -> list:
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [h for entry in settings.get("hooks", {}).get(event, []) for h in entry["hooks"]]


def _copilot_commands(target: Path, event: str = "userPromptSubmitted") -> list:
    path = target / ".github" / "hooks" / "ai-badger-hooks.json"
    return json.loads(path.read_text(encoding="utf-8"))["hooks"].get(event, [])


def _ours(hooks: list, key: str) -> list:
    return [h for h in hooks if _script_of(h.get(key, "")) == ENTRY]


def _scaffold(env, monkeypatch, *, agents=None, skills=None, exclude=None, target=None) -> Path:
    """Run the real Scaffolder, installing user-scope files into the test's temp HOME."""
    monkeypatch.setenv("HERMES_HOME", str(env.home / ".hermes"))
    for entry in (str(WELCOME_SCRIPTS), str(ROOT / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(
        "ai_badger_test_integration_scaffold", ROOT / scaffold_helpers.SCAFFOLD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = target or env.root / "proj"
    target.mkdir(parents=True, exist_ok=True)
    config = scaffold_helpers._config(  # pylint: disable=protected-access
        stacks=["python"], agents=list(agents or ALL_AGENTS))
    if exclude:
        config["exclude"] = {"skills": list(exclude)}
    scaffolder = scaffold_helpers.build_scaffolder(
        module, root=ROOT, target=target, config=config, skills=list(skills or SKILLS),
        install=True)
    scaffolder.run(generated_at="2026-09-28T00:00:00Z")
    return target


def _validate(load_script):
    return load_script("tooling/validate.py")


def _catalog_copy(tmp_root: Path) -> Path:
    """The hooks manifest dir and the plugin-root hooks.json, copied so a row can break them."""
    hooks = tmp_root / "features" / "common" / "hooks"
    hooks.mkdir(parents=True)
    for name in ("hooks-manifest.json", "hooks.json", "ai_badger_hooks.py"):
        shutil.copy(HOOKS_DIR / name, hooks / name)
    (tmp_root / "hooks").mkdir()
    shutil.copy(ROOT / "hooks" / "hooks.json", tmp_root / "hooks" / "hooks.json")
    return hooks


def _manifest_entry(manifest: dict) -> dict:
    entries = [h for h in manifest["hooks"] if h.get("name") == HOOK_NAME]
    assert len(entries) == 1, [h.get("name") for h in manifest["hooks"]]
    return entries[0]


def _fake_bin_extras(env) -> Path:
    """A marker-writing `pi` beside the fake `ai-raccoon`; returns the marker path."""
    marker = env.root / "pi-ran"
    pi = env.fake.bin_dir / "pi"
    pi.write_text(f"#!/bin/sh\necho ran > {marker}\n", encoding="utf-8")
    pi.chmod(0o755)
    return marker


def _child_env(**extra) -> dict:
    proc_env = dict(os.environ)
    proc_env.pop("CLAUDE_PROJECT_DIR", None)
    proc_env.update(extra)
    return proc_env


def _block(prompt: str, hits=None) -> str:
    hits = hits or HITS
    return support.load_module().format_block(prompt, hits["results"], hits["code"])


@pytest.fixture(name="router")
def _router():
    server = FakeOpenRouter()
    yield server
    server.stop()


@pytest.fixture(name="hermes_reset", autouse=True)
def _hermes_reset():
    """Hide every memory-context module a previous row loaded; restore them afterwards."""
    def ours(key):
        return (key.startswith(SIBLING_PREFIX) or key.startswith(HERMES_LOAD_PREFIX)
                or key == "ai_badger_memory_context")
    saved = {key: sys.modules.pop(key) for key in list(sys.modules) if ours(key)}
    yield
    for key in [key for key in sys.modules if ours(key)]:
        del sys.modules[key]
    sys.modules.update(saved)


# ------------------------------------------------------------------------------ I1, I2


def test_i1_the_manifest_entry_has_claude_copilot_and_hermes_arms_and_no_pi(load_script,
                                                                            tmp_path):
    entry = _manifest_entry(json.loads(MANIFEST.read_text(encoding="utf-8")))
    agents = entry["agents"]
    assert set(agents) == {"claude", "copilot", "hermes"}
    assert agents["claude"] == {"type": "hooks-json", "entry": "hooks.json",
                                "event": "UserPromptSubmit", "script": ENTRY}
    assert agents["copilot"] == {"type": "hooks-json", "entry": "hooks.json",
                                 "event": "userPromptSubmitted", "script": ENTRY}
    assert agents["hermes"] == {"type": "plugin", "entry": "ai_badger_hooks.py",
                                "method": "pre_llm_call"}

    validate = _validate(load_script)
    assert not [g for g in validate.hooks_manifest_agent_gaps(ROOT) if HOOK_NAME in g]
    hooks = _catalog_copy(tmp_path)
    for dropped in ("claude", "copilot", "hermes"):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        del _manifest_entry(manifest)["agents"][dropped]
        (hooks / "hooks-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        gaps = [g for g in validate.hooks_manifest_agent_gaps(tmp_path) if HOOK_NAME in g]
        assert len(gaps) == 1 and f"'{dropped}'" in gaps[0], gaps


def test_i2_every_arm_resolves_and_a_deleted_command_is_a_claude_and_copilot_gap(load_script,
                                                                                tmp_path):
    validate = _validate(load_script)
    assert validate.hooks_manifest_unresolved(ROOT) == []

    hooks = _catalog_copy(tmp_path)
    assert validate.hooks_manifest_unresolved(tmp_path) == []
    source = json.loads((hooks / "hooks.json").read_text(encoding="utf-8"))
    for group in source["hooks"]["UserPromptSubmit"]:
        group["hooks"] = [h for h in group["hooks"] if _script_of(h["command"]) != ENTRY]
    (hooks / "hooks.json").write_text(json.dumps(source), encoding="utf-8")

    gaps = validate.hooks_manifest_unresolved(tmp_path)
    assert len(gaps) == 2, gaps
    assert all(HOOK_NAME in g for g in gaps), gaps
    assert {agent for agent in ("claude", "copilot") for g in gaps if f"'{agent}'" in g} == \
        {"claude", "copilot"}


# ------------------------------------------------------------------------------ I3, I4


def _hook_wiring(load_script):
    for entry in (str(WELCOME_SCRIPTS), str(ROOT / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    ctx_mod = load_script(
        "features/common/skills/welcome-ai-badger/scripts/scaffold_context.py")
    wiring = load_script("features/common/skills/welcome-ai-badger/scripts/hook_wiring.py")
    return ctx_mod, wiring, load_script("engine/badger_lib.py")


def _wire_claude(load_script, target: Path, exclude=None):
    ctx_mod, wiring, bl = _hook_wiring(load_script)
    config = scaffold_helpers._config(agents=["claude"])  # pylint: disable=protected-access
    if exclude:
        config["exclude"] = {"skills": list(exclude)}
    ctx = ctx_mod.ScaffoldContext(root=ROOT, target=target, aib=target / ".ai-badger",
                                  config=config, index={}, stacks=[], skills=[],
                                  excluded=bl.exclusions(config))
    wiring.HookWiring(ctx).wire()
    return ctx


def _place_entry(target: Path) -> None:
    scripts = target / ".ai-badger" / "skills" / "ai-raccoon-memory" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / ENTRY).write_text("", encoding="utf-8")


def test_i3_claude_wiring_is_guarded_keeps_timeout_100_and_skips_an_absent_script(
        load_script, tmp_path):
    target = tmp_path / "wired"
    _place_entry(target)
    _wire_claude(load_script, target)

    ours = _ours(_claude_commands(target), "command")
    assert len(ours) == 1
    assert ours[0]["timeout"] == 100
    assert ours[0]["command"].startswith("if [ -f ")
    assert ('"${CLAUDE_PROJECT_DIR}/.ai-badger/skills/ai-raccoon-memory/scripts/'
            f'{ENTRY}"') in ours[0]["command"]

    bare = tmp_path / "bare"
    (bare / ".ai-badger").mkdir(parents=True)
    ctx = _wire_claude(load_script, bare)
    assert [n for n in ctx.notes if ENTRY in n and "not scaffolded" in n and "skipped" in n]
    settings = bare / ".claude" / "settings.json"
    if settings.exists():
        assert not _ours(_claude_commands(bare), "command")


def test_i4_a_declined_skill_is_not_wired_for_claude(load_script, tmp_path):
    target = tmp_path / "declined"
    _place_entry(target)  # a declined skill's stale copy may still sit on disk
    ctx = _wire_claude(load_script, target, exclude=["ai-raccoon-memory"])

    settings = target / ".claude" / "settings.json"
    if settings.exists():
        assert not _ours(_claude_commands(target), "command")
    assert [n for n in ctx.notes if "ai-raccoon-memory" in n and "declined" in n]


@pytest.mark.xfail(strict=True, reason=(
    "features/copilot/adjustments/adjust_hooks.py ignores config.exclude: a declined skill's "
    "command is still generated, and its existence guard answers every prompt with a "
    "'not found - hook skipped' systemMessage. Tracked in #535."))
def test_i4_a_declined_skill_is_not_wired_for_copilot(memory_context_env, monkeypatch):
    target = _scaffold(memory_context_env, monkeypatch, agents=["copilot"],
                       exclude=["ai-raccoon-memory"])
    assert not _ours(_copilot_commands(target), "bash")


# ------------------------------------------------------------------------------ I5


def test_i5_copilot_keeps_its_neighbours_and_carries_a_timeout_above_the_budget(
        memory_context_env, monkeypatch):
    target = _scaffold(memory_context_env, monkeypatch, agents=["copilot"],
                       skills=[*SKILLS, "mcp-index", "send-message"])
    hooks = _copilot_commands(target)
    scripts = {_script_of(h["bash"]) for h in hooks}
    assert {ENTRY, MARKERS, "context_enrichment_hook.py", "message_delivery_hook.py"} <= scripts

    ours = _ours(hooks, "bash")
    assert len(ours) == 1
    module = support.load_module()
    floor = max(module.SINGLE_BUDGET_SECONDS, module.PIPELINE_TOTAL_SECONDS) + \
        module.GRACE_SECONDS
    assert ours[0]["timeoutSec"] > floor


# ------------------------------------------------------------------------------ I6


def _run_claude_command(target: Path, env_extra: dict, cwd: Path, payload: dict):
    command = _ours(_claude_commands(target), "command")[0]["command"]
    command = command.replace("${CLAUDE_PROJECT_DIR}", str(target))
    return subprocess.run(["/bin/sh", "-c", command], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(cwd), timeout=30,
                          check=False, env=_child_env(**env_extra))


def test_i6_the_wired_claude_command_prints_the_envelope(memory_context_env, monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits({PROMPT: HITS})
    target = _scaffold(env, monkeypatch)
    pi_marker = _fake_bin_extras(env)
    empty = env.root / "empty-cwd"
    empty.mkdir()
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "i6-session",
               "prompt": PROMPT, "cwd": str(target)}

    result = _run_claude_command(target, {}, empty, payload)

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout.strip())
    assert "systemMessage" not in parsed
    assert parsed == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": _block(PROMPT)}}
    assert len(env.fake.runs()) == 1
    assert not pi_marker.exists()

    off = _run_claude_command(target, {"AI_BADGER_MEMORY_CONTEXT": "0"}, empty,
                              dict(payload, session_id="i6-off"))
    assert off.returncode == 0
    assert off.stdout == ""
    assert len(env.fake.runs()) == 1


# ------------------------------------------------------------------------------ I7


def _planner_body(queries) -> bytes:
    plan = {"concepts": [{"name": "IntegrationI7", "queries": list(queries)}]}
    return json.dumps({"choices": [{"message": {"role": "assistant",
                                                "content": json.dumps(plan)}}]}).encode()


def _jev_body(count: int) -> bytes:
    return json.dumps({"answers": {f"c{i}": {"type": "score", "score": float(i)}
                                   for i in range(count)}}).encode()


def test_i7_the_generated_copilot_command_prints_flat_context_through_the_pipeline(
        memory_context_env, monkeypatch, router):
    env = memory_context_env
    env.fake.mode("perquery")
    query_one = "scaffolded copilot memory context planned query one"
    query_two = "scaffolded copilot memory context planned query two"
    mem_hit = {"hash": "i7-m1", "ranking": 2, "path": "/repo/docs/i7.md",
               "snippet": "the scaffolded copilot memory hit"}
    code_hit = {"hash": "i7-c1", "ranking": 1, "path": "/repo/src/i7.py",
                "snippet": "def i7(): pass", "lineStart": 1, "lineEnd": 2}
    env.fake.hits({query_one: {"results": [mem_hit], "code": []},
                   query_two: {"results": [], "code": [code_hit]}})
    router.script(fake_router.CHAT_PATH, reply(200, _planner_body([query_one, query_two])))
    router.script(fake_router.DECISIONS_PATH, reply(200, _jev_body(2)))
    target = _scaffold(env, monkeypatch, agents=["copilot"])
    pi_marker = _fake_bin_extras(env)
    payload = json.loads(PAYLOAD_FIXTURE.read_text(encoding="utf-8"))
    payload["cwd"] = str(target)
    command = _ours(_copilot_commands(target), "bash")[0]["bash"]

    result = subprocess.run(
        ["/bin/bash", "-c", command], input=json.dumps(payload), capture_output=True,
        text=True, cwd=str(target), timeout=30, check=False,
        env=_child_env(OPENROUTER_API_KEY="sk-test-i7",
                       AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE=router.url))

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout.strip())
    expected = support.load_module().format_block(payload["prompt"], [mem_hit], [code_hit])
    assert parsed == {"additionalContext": expected}
    assert len([r for r in router.requests if r["path"] == fake_router.CHAT_PATH]) == 1
    assert [r for r in router.requests if r["path"] == fake_router.DECISIONS_PATH]
    assert {c["params"]["arguments"]["sessionId"] for c in env.fake.calls()} == \
        {payload["sessionId"]}
    assert len(env.fake.runs()) == 1
    assert "sk-test-i7" not in result.stdout + result.stderr
    assert not pi_marker.exists()


# ------------------------------------------------------------------------------ I8


def _adapter_hook_keys() -> set:
    """Every `hooks.<Key>` / `hooks?.<Key>` / `hooks["Key"]` the pi adapter reads."""
    keys = set()
    for source in ADAPTER_DIR.glob("*.ts"):
        text = source.read_text(encoding="utf-8")
        keys.update(re.findall(r"hooks\??\.([A-Z]\w+)", text))
        keys.update(re.findall(r"hooks\[\s*[\"'](\w+)[\"']\s*\]", text))
    return keys


def _pi_copy_list() -> list:
    tree = PI_HOOKS_ADJUSTER.read_text(encoding="utf-8")
    block = re.search(r"hook_scripts\s*=\s*\[(.*?)\]", tree, re.S)
    assert block, "pi adjuster's hook_scripts list not found"
    return re.findall(r"[\"']([\w.]+)[\"']", block.group(1))


def test_i8_pi_executes_none_of_the_new_files(memory_context_env, monkeypatch):
    env = memory_context_env
    entry = _manifest_entry(json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert "pi" not in entry["agents"]

    index_ts = (ADAPTER_DIR / "index.ts").read_text(encoding="utf-8")
    spawned = re.findall(r"\bspawn\(", index_ts)
    assert len(spawned) == 1  # the one shared runner; its scripts come from the lines below
    assert re.search(r'DELIVERY_SCRIPT\s*=\s*\[".ai-badger",\s*"hooks",\s*'
                     r'"message_delivery_hook.py"\]', index_ts)
    assert _adapter_hook_keys() <= {"PreToolUse", "PostToolUse"}, _adapter_hook_keys()
    for source in ADAPTER_DIR.glob("*"):
        text = source.read_text(encoding="utf-8")
        assert not [name for name in NEW_FILES if name in text], source.name
    assert not set(_pi_copy_list()) & set(NEW_FILES)

    composed = _scaffold(env, monkeypatch)
    wired = json.loads((composed / ".ai-badger" / "hooks" / "hooks.json").read_text(
        encoding="utf-8"))
    for event in ("PreToolUse", "PostToolUse"):
        for group in wired["hooks"].get(event, []):
            for hook in group["hooks"]:
                assert _script_of(hook["command"]) not in NEW_FILES, hook
    pi_extension = env.home / ".pi" / "agent" / "extensions" / "ai-badger"
    assert (pi_extension / "index.ts").is_file()
    assert not [p for p in pi_extension.rglob("*") if p.name in NEW_FILES]
    assert not [p for p in (composed / ".pi").rglob("*") if p.name in NEW_FILES]

    pi_only = _scaffold(env, monkeypatch, agents=["pi"], target=env.root / "pi-only")
    assert (pi_only / ".ai-badger" / "hooks").is_dir()
    assert not (pi_only / ".ai-badger" / "hooks" / "memory_context.py").exists()
    assert not [p for p in (pi_only / ".ai-badger" / "hooks").iterdir() if p.name in NEW_FILES]


# ------------------------------------------------------------------------------ I9, I10


def test_i9_a_composed_scaffold_wires_claude_copilot_and_both_hermes_dirs(memory_context_env,
                                                                          monkeypatch):
    env = memory_context_env
    target = _scaffold(env, monkeypatch)

    assert len(_ours(_claude_commands(target), "command")) == 1
    assert len(_ours(_copilot_commands(target), "bash")) == 1
    skill_scripts = target / ".ai-badger" / "skills" / "ai-raccoon-memory" / "scripts"
    for name in NEW_FILES:
        assert (skill_scripts / name).is_file(), name
    plugin = env.home / ".hermes" / "plugins" / "ai-badger"
    for directory in (target / ".ai-badger" / "hooks", plugin):
        for name in HERMES_MODULES:
            assert (directory / name).is_file(), f"{directory}: {name}"


def test_i10_scaffolding_twice_leaves_one_entry_per_event_per_agent(memory_context_env,
                                                                    monkeypatch):
    env = memory_context_env
    target = _scaffold(env, monkeypatch)
    _scaffold(env, monkeypatch, target=target)

    claude = [_script_of(h["command"]) for h in _claude_commands(target)]
    copilot = [_script_of(h["bash"]) for h in _copilot_commands(target)]
    for script in (ENTRY, MARKERS):
        assert claude.count(script) == 1, claude
        assert copilot.count(script) == 1, copilot


# ------------------------------------------------------------------------------ I11


def test_i11_the_installed_hermes_plugin_injects_the_block(memory_context_env, monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits({PROMPT: HITS})
    target = _scaffold(env, monkeypatch, agents=["hermes"])
    plugin = (env.home / ".hermes" / "plugins" / "ai-badger").resolve()
    key = HERMES_LOAD_PREFIX + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(key, plugin / "ai_badger_hooks.py")
    hooks = importlib.util.module_from_spec(spec)
    sys.modules[key] = hooks
    spec.loader.exec_module(hooks)
    monkeypatch.chdir(target)
    try:
        result = hooks.pre_llm_inject_context(
            session_id="i11-session", user_message=PROMPT, conversation_history=[],
            is_first_turn=True, model="m", platform="cli")
    finally:
        hooks.reset_memory_context_memo()

    assert plugin in Path(sys.modules[key].__file__).resolve().parents
    module = sys.modules["ai_badger_memory_context"]
    assert plugin in Path(module.__file__).resolve().parents
    context = (result or {}).get("context") or ""
    assert context.endswith(_block(PROMPT) + "\n" + hooks.MEMORY_CONTEXT_END)
    assert len(env.fake.runs()) == 1
