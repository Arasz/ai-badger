"""F2: tooling/validate.py's hooks_manifest_unresolved(root).

Every manifest arm must resolve to a real command, callback or event — never a silent gap
accepted through a generator's own discovery fallback. hooks_manifest_agent_gaps (F1) proves an
agent is *named*; this proves the thing it names actually *exists*. The recurring shape this
guards against is the same one F1 guards against: a hook wired in the manifest, tested, and
scaffolded, that never actually fires because nothing in hooks.json (or the Hermes plugin file)
answers to it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List

from conftest import ROOT, _test_write


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, json.dumps(data, indent=2), encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, text, encoding="utf-8")
    return path


def _manifest(root: Path, hooks: List[Dict], manifest_dir: str = "features/demo/hooks") -> Path:
    return _write_json(root / manifest_dir / "hooks-manifest.json", {"hooks": hooks})


def _hooks_json(root: Path, events: Dict[str, Iterable[str]],
                 manifest_dir: str = "features/demo/hooks") -> Path:
    """One hooks.json entry per command, grouped under its event — the shape the real
    catalog's own hooks.json uses."""
    hooks = {event: [{"hooks": [{"type": "command", "command": c}]} for c in commands]
              for event, commands in events.items()}
    return _write_json(root / manifest_dir / "hooks.json", {"hooks": hooks})


def _hermes_stub(root: Path, body: str, manifest_dir: str = "features/demo/hooks") -> Path:
    return _write_text(root / manifest_dir / "hooks_stub.py", body)


REAL_REGISTER_STUB = (
    "def real_callback(ctx):\n"
    "    pass\n\n\n"
    "def orphan_callback(ctx):\n"
    "    pass\n\n\n"
    "def register(ctx):\n"
    "    ctx.register_hook(\"real_event\", real_callback)\n"
)

COMMENTED_REGISTER_STUB = (
    '# ctx.register_hook("fake_event", fake_callback)\n'
    'NOTE = """\n'
    'ctx.register_hook("also_fake", also_fake_callback)\n'
    '"""\n\n\n'
    "def real_callback(ctx):\n"
    "    pass\n\n\n"
    "def register(ctx):\n"
    "    ctx.register_hook(\"real_event\", real_callback)\n"
)


def _load(load_script, relpath: str):
    return load_script(relpath)


# ------------------------------------------------------------------------------------ V1


def test_v1_real_manifest_resolves_clean(root, load_script):
    validate = _load(load_script, "tooling/validate.py")

    assert validate.hooks_manifest_unresolved(root) == []


def test_v1_deleting_a_command_from_a_tmp_copy_produces_exactly_two_gaps(root, load_script,
                                                                          tmp_path):
    validate = _load(load_script, "tooling/validate.py")
    fw = tmp_path / "framework"
    src = root / "features" / "common" / "hooks"
    dst = fw / "features" / "common" / "hooks"
    dst.mkdir(parents=True)
    for name in ("hooks-manifest.json", "hooks.json", "ai_badger_hooks.py"):
        dst_file = dst / name
        _write_text(dst_file, (src / name).read_text(encoding="utf-8"))
    _write_text(fw / "hooks" / "hooks.json", (root / "hooks" / "hooks.json")
                .read_text(encoding="utf-8"))

    hooks_data = json.loads((dst / "hooks.json").read_text(encoding="utf-8"))
    hooks_data["hooks"]["UserPromptSubmit"] = [
        entry for entry in hooks_data["hooks"]["UserPromptSubmit"]
        if not any(h.get("command", "").rstrip('"').endswith("context_enrichment_hook.py")
                   for h in entry.get("hooks", []))
    ]
    _write_json(dst / "hooks.json", hooks_data)

    gaps = validate.hooks_manifest_unresolved(fw)

    assert len(gaps) == 2, gaps
    assert any("claude" in g for g in gaps), gaps
    assert any("copilot" in g for g in gaps), gaps
    assert not any("hermes" in g for g in gaps), gaps


# ------------------------------------------------------------------------------------ V2


def test_v2_claude_arm_with_no_command_is_one_gap_naming_file_hook_agent_event_script(
        tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    manifest_path = _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "demo_hook.py"}}},
    ])
    _hooks_json(tmp_path, {})  # no commands at all

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps
    gap = gaps[0]
    assert str(manifest_path.relative_to(tmp_path)) in gap or "hooks-manifest.json" in gap
    assert "demo-hook" in gap
    assert "claude" in gap
    assert "SessionStart" in gap
    assert "demo_hook.py" in gap


# ------------------------------------------------------------------------------------ V3


def test_v3_command_under_a_different_event_is_a_gap(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "demo_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"Stop": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/demo_hook.py"']})

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


# ------------------------------------------------------------------------------------ V4


def test_v4_a_command_matching_only_by_suffix_is_a_gap(tmp_path, load_script):
    """not_memory_context_hook.py ends with the script name but is not it — the generators'
    own `endswith` rule alone would wrongly accept it."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "memory_context_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"SessionStart": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/not_memory_context_hook.py"']})

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


def test_v4_two_commands_ending_with_the_same_suffix_is_a_gap(tmp_path, load_script):
    """Two distinct files that both end with the script name are ambiguous, not a resolve."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "memory_context_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"SessionStart": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/memory_context_hook.py"',
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/x_memory_context_hook.py"']})

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


def test_v4_the_exact_matching_command_alone_resolves(tmp_path, load_script):
    """Control: with only the correct file present, there is no gap."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "memory_context_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"SessionStart": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/memory_context_hook.py"']})

    assert validate.hooks_manifest_unresolved(tmp_path) == []


def test_v4_a_command_wired_twice_under_different_matchers_is_not_ambiguous(tmp_path,
                                                                             load_script):
    """The real catalog wires memory_grade_hook.py under two matchers on PostToolUse — the
    literal command is identical both times, so this must resolve, not read as 'several'."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "PostToolUse", "script": "memory_grade_hook.py"}}},
    ])
    cmd = 'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/memory_grade_hook.py"'
    _write_json(tmp_path / "features/demo/hooks/hooks.json", {"hooks": {"PostToolUse": [
        {"matcher": "memory_search", "hooks": [{"type": "command", "command": cmd}]},
        {"matcher": "Read|ReadFile", "hooks": [{"type": "command", "command": cmd}]},
    ]}})

    assert validate.hooks_manifest_unresolved(tmp_path) == []


# ------------------------------------------------------------------------------------ V5


def test_v5_copilot_event_maps_through_copilot_to_source_event(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"copilot": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "sessionStart", "script": "demo_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"SessionStart": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/demo_hook.py"']})

    assert validate.hooks_manifest_unresolved(tmp_path) == []


def test_v5_an_unmapped_copilot_event_is_a_gap(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"copilot": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "postToolUseFailure", "script": "demo_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"PostToolUseFailure": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/demo_hook.py"']})

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


# ------------------------------------------------------------------------------------ V6


def test_v6_plugin_hooks_json_resolves_against_root_hooks_hooks_json(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "drift-notice", "agents": {"claude": {
            "type": "plugin-hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "drift_notice_hook.py"}}},
    ])
    _write_json(tmp_path / "hooks" / "hooks.json", {"hooks": {"SessionStart": [
        {"hooks": [{"type": "command",
                     "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/.../drift_notice_hook.py"'}]}]}})

    assert validate.hooks_manifest_unresolved(tmp_path) == []


def test_v6_a_hooks_json_arm_present_only_at_root_is_a_gap(tmp_path, load_script):
    """A plain hooks-json arm must resolve against the manifest-relative hooks.json, never the
    repo-root one — conflating the two files is exactly the exception the plugin type carries."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "demo_hook.py"}}},
    ])
    _hooks_json(tmp_path, {})  # manifest-relative hooks.json has nothing
    _write_json(tmp_path / "hooks" / "hooks.json", {"hooks": {"SessionStart": [
        {"hooks": [{"type": "command",
                     "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/demo_hook.py"'}]}]}})

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


# ------------------------------------------------------------------------------------ V7


def test_v7_an_arm_resolvable_only_via_skill_discovery_is_a_gap(tmp_path, load_script):
    """No discovery-fallback exemption: a script present nowhere in hooks.json is a gap, even
    though an older generator would have found it by scanning the skill's own scripts/ dir."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "UserPromptSubmit", "script": "discovery_only_hook.py"}}},
    ])
    _hooks_json(tmp_path, {"UserPromptSubmit": []})

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


# ------------------------------------------------------------------------------------ V8


def test_v8_hermes_arm_resolves_on_event_string_or_callback_name_else_gaps(tmp_path,
                                                                            load_script):
    validate = _load(load_script, "tooling/validate.py")
    _hermes_stub(tmp_path, REAL_REGISTER_STUB)
    _manifest(tmp_path, [
        {"name": "by-event", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "real_event"}}},
        {"name": "by-callback", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "real_callback"}}},
        {"name": "defined-not-registered", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "orphan_callback"}}},
        {"name": "never-defined", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "totally_unknown"}}},
    ])

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 2, gaps
    assert any("orphan_callback" in g for g in gaps), gaps
    assert any("totally_unknown" in g for g in gaps), gaps
    assert not any("by-event" in g or "by-callback" in g for g in gaps), gaps


# ------------------------------------------------------------------------------------ V9


def test_v9_a_registration_inside_a_comment_or_string_does_not_count(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _hermes_stub(tmp_path, COMMENTED_REGISTER_STUB)
    _manifest(tmp_path, [
        {"name": "commented", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "fake_event"}}},
        {"name": "stringed", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "also_fake"}}},
        {"name": "real", "agents": {"hermes": {
            "type": "plugin", "entry": "hooks_stub.py", "method": "real_event"}}},
    ])

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 2, gaps
    assert any("fake_event" in g for g in gaps), gaps
    assert any("also_fake" in g for g in gaps), gaps


# ------------------------------------------------------------------------------------ V10


def test_v10_unknown_arm_type_is_a_gap_not_a_crash(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "mystery", "entry": "hooks.json"}}},
    ])

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps
    assert "mystery" in gaps[0]


def test_v10_unreadable_entry_is_a_gap_not_a_crash(tmp_path, load_script):
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "demo_hook.py"}}},
    ])
    # no hooks.json written at all: entry names a file that does not exist

    gaps = validate.hooks_manifest_unresolved(tmp_path)

    assert len(gaps) == 1, gaps


# ------------------------------------------------------------------------------------ V11


def test_v11_entry_resolves_relative_to_the_manifests_own_directory(tmp_path, load_script):
    """A manifest under features/demo/hooks/ must resolve against ITS OWN directory, never a
    hard-coded features/common/hooks/."""
    validate = _load(load_script, "tooling/validate.py")
    _manifest(tmp_path, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "demo_hook.py"}}},
    ], manifest_dir="features/demo/hooks")
    _hooks_json(tmp_path, {"SessionStart": [
        'python3 "${CLAUDE_PLUGIN_ROOT}/features/demo/hooks/demo_hook.py"']},
        manifest_dir="features/demo/hooks")
    # A decoy at features/common/hooks/ that resolves nothing — proves the check did not fall
    # back to a hard-coded path.
    _write_json(tmp_path / "features/common/hooks/hooks.json", {"hooks": {}})

    assert validate.hooks_manifest_unresolved(tmp_path) == []


# ------------------------------------------------------------------------------------ V12


def test_v12_validate_all_exits_non_zero_on_a_gap(tmp_path, load_script, root, capsys):
    import shutil
    validate = _load(load_script, "tooling/validate.py")
    fw = tmp_path / "framework"
    shutil.copytree(root / "schemas", fw / "schemas")
    _manifest(fw, [
        {"name": "demo-hook", "agents": {"claude": {
            "type": "hooks-json", "entry": "hooks.json",
            "event": "SessionStart", "script": "demo_hook.py"}}},
    ], manifest_dir="features/common/hooks")
    _hooks_json(fw, {}, manifest_dir="features/common/hooks")
    _write_text(fw / "features" / "common" / "skills" / "demo-skill" / "SKILL.md", (
        "---\nname: demo-skill\ndescription: >-\n  Use when a validate.py --all fixture needs a"
        " lint-clean skill.\nversion: 1.0.0\nauthor: ai-badger\nlicense: MIT\n"
        "platforms: [linux, macos, windows]\nscope: default\nmetadata:\n  hermes:\n"
        "    tags: [meta]\n    related_skills: []\n---\n# Demo skill\n\n## Gotchas\n\n"
        "No environment-specific gotchas known.\n"))

    rc = validate.main(["--all", "--root", str(fw)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "hooks-manifest resolution" in out


# ------------------------------------------------------------------------------------ V14


def test_v14_rewiring_prompt_markers_collapses_a_stale_entry(load_script):
    """Claude side: a target already holding a literally different command for
    user_prompt_hook.py must end up with exactly one entry after re-wire, not two."""
    scripts_dir = str(ROOT / "features/common/skills/welcome-ai-badger/scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    hook_wiring = load_script(
        "features/common/skills/welcome-ai-badger/scripts/hook_wiring.py")
    stale = ('if [ -f "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/prompt-markers/scripts/'
             'user_prompt_hook.py" ]; then python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/'
             'prompt-markers/scripts/user_prompt_hook.py"; else echo '
             '\'{"systemMessage": "ai-badger: stale"}\'; fi')
    fresh = ('python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/prompt-markers/scripts/'
             'user_prompt_hook.py"')
    existing = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": stale}]}]}
    new = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": fresh}]}]}

    hook_wiring.merge_hooks(existing, new)

    ids = [hook_wiring.skill_script_id(h.get("command", ""))
           for entry in existing["UserPromptSubmit"] for h in entry.get("hooks", [])]
    assert ids.count("prompt-markers/scripts/user_prompt_hook.py") == 1, ids


# ------------------------------------------------------------------------------------ V15


def test_v15_copilot_wires_user_prompt_hook_once_with_timeout_ten(root, load_script, tmp_path):
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    # A discovery-path candidate, present so a pre-fix run still finds *something* to wire
    # (and thus fails on the timeoutSec assertion, not on a missing fixture).
    skill_scripts = target / ".ai-badger" / "skills" / "prompt-markers" / "scripts"
    skill_scripts.mkdir(parents=True)
    _write_text(skill_scripts / "user_prompt_hook.py", "")

    result = adjust_hooks.adjust({
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["prompt-markers", "mcp-index"],
    })

    assert result["applied"]
    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    matching = [h for h in hooks["hooks"]["userPromptSubmitted"]
                if h["bash"].rstrip('"').endswith("user_prompt_hook.py")
                or "user_prompt_hook.py" in h["bash"]]
    assert len(matching) == 1, matching
    assert matching[0]["timeoutSec"] == 10, matching


# ------------------------------------------------------------------------------------ V16


def test_v16_sibling_fixture_helpers_resolve_cleanly_under_f2(root, load_script, tmp_path):
    """The three helpers that write a miniature manifest for validate.py --all's own tests
    (test_every_check_can_fail.py, test_validate.py, test_skills_lint.py) must each also write
    an F2-resolving hooks.json — otherwise every one of those "clean tree" controls would fail
    for a reason unrelated to what they test."""
    validate = _load(load_script, "tooling/validate.py")

    checks = load_script("tests/test_every_check_can_fail.py")
    work = tmp_path / "every_check"
    checks._hooks_manifest(work, checks.VALIDATE.HOOK_CAPABLE_AGENTS)
    assert validate.hooks_manifest_unresolved(work) == []

    tv = load_script("tests/test_validate.py")
    work2 = tmp_path / "test_validate"
    tv._write_hooks_manifest(work2)
    assert validate.hooks_manifest_unresolved(work2) == []

    tsl = load_script("tests/test_skills_lint.py")
    work3 = tmp_path / "test_skills_lint"
    tsl._write_hooks_manifest(work3)
    assert validate.hooks_manifest_unresolved(work3) == []
