"""Native Codex resources and preservation contracts."""
import json
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pathlib import Path

import pytest


def context(tmp_path, **extra):
    data = {'config': {'agents': ['codex']}, 'target': tmp_path,
            'target_dir': tmp_path / '.ai-badger', 'framework_root': Path(__file__).resolve().parents[1]}
    data.update(extra)
    return data


def test_distinctive_detection(load_script, tmp_path, monkeypatch):
    detect = load_script('features/common/skills/welcome-ai-badger/scripts/detect.py')
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: tmp_path / 'home'))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    (tmp_path / 'AGENTS.md').write_text('shared')
    assert 'codex' not in detect.detect_agents(tmp_path)
    (tmp_path / '.codex').mkdir()
    assert 'codex' in detect.detect_agents(tmp_path)
    (tmp_path / '.codex').rmdir()
    custom = tmp_path / 'custom-home'
    custom.mkdir()
    monkeypatch.setenv('CODEX_HOME', str(custom))
    assert 'codex' in detect.detect_agents(tmp_path)


def test_codex_plugin_publishes_user_skills_and_native_hooks(root):
    plugin = json.loads((root / '.codex-plugin/plugin.json').read_text())
    assert plugin['skills'] == './skills/'
    assert plugin['hooks'] == './hooks/codex-hooks.json'
    assert (root / 'skills/welcome-ai-badger/SKILL.md').is_file()
    hooks = json.loads((root / plugin['hooks'][2:]).read_text())['hooks']
    assert {'UserPromptSubmit', 'SessionStart', 'PreToolUse', 'PostToolUse'} <= set(hooks)
    commands = [handler['command'] for groups in hooks.values() for group in groups
                for handler in group['hooks']]
    assert all('${PLUGIN_ROOT}' in command for command in commands)
    assert all('CLAUDE_PROJECT_DIR' not in command for command in commands)
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('codex_adjust_hooks',
        root / 'features/codex/adjustments/adjust_hooks.py')
    adjustment = module_from_spec(spec)
    spec.loader.exec_module(adjustment)
    bundled_scripts = {command.split('${PLUGIN_ROOT}/skills/', 1)[1].split('"', 1)[0]
                       for command in commands if '${PLUGIN_ROOT}/skills/' in command
                       and 'features/codex/adjustments/memory_first_gate_post_hook.py'
                       not in command}
    post_hook = 'ai-raccoon-memory/scripts/memory_first_gate_post_hook.py'
    assert bundled_scripts == set(adjustment.SCRIPTS) - {post_hook}
    assert all((root / 'skills' / relative).is_file() for relative in bundled_scripts)
    assert any('features/codex/adjustments/memory_first_gate_post_hook.py' in command
               and f'${{PLUGIN_ROOT}}/skills/{post_hook}' in command
               for command in commands)
    packaged_skills = {path.parent.name for path in (root / 'skills').glob('*/SKILL.md')}
    catalog_skills = {path.parent.name for path in
                      (root / 'features/common/skills').glob('*/SKILL.md')
                      if 'scope: optIn' not in path.read_text()}
    assert catalog_skills <= packaged_skills
    marketplace = json.loads((root / '.agents/plugins/marketplace.json').read_text())
    assert marketplace['name'] == 'ai-badger-codex'
    assert marketplace['plugins'][0]['name'] == plugin['name']
    plugin_root = root / marketplace['plugins'][0]['source']['path'][2:]
    assert plugin_root == root
    assert (plugin_root / '.codex-plugin/plugin.json').is_file()
    for relative in (plugin['skills'], plugin['hooks']):
        assert (plugin_root / relative.removeprefix('./')).exists()


def test_codex_instruction_scaffold_targets_only_agents_file(root):
    data = json.loads((root / 'features/codex/scaffolding.json').read_text())
    assert [entry['target'] for entry in data['files']] == ['AGENTS.md']


def test_every_codex_adjusted_hook_resolves_to_catalog_registration(load_script, root):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    registrations = json.loads(
        (root / 'features/common/hooks/hooks.json').read_text())['hooks']
    registered = {
        handler['command']
        for groups in registrations.values()
        for group in groups
        for handler in group.get('hooks', [])
    }
    for relative in arm.SCRIPTS:
        assert any(command.endswith(f'/features/common/skills/{relative}"')
                   for command in registered)
        assert (root / 'features/common/skills' / relative).is_file()
def test_skills_links_preserve_user_and_prune_owned(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_skills.py')
    for name in ['first', 'stale', 'user']:
        skill = tmp_path / '.ai-badger/skills' / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text(name)
    user = tmp_path / '.agents/skills/user'
    user.mkdir(parents=True)
    (user / 'SKILL.md').write_text('operator')
    arm.adjust(context(tmp_path, skills=['first', 'stale', 'user']))
    arm.adjust(context(tmp_path, skills=['first', 'user']))
    assert (tmp_path / '.agents/skills/first').is_symlink()
    assert not (tmp_path / '.agents/skills/stale').is_symlink()
    assert (user / 'SKILL.md').read_text() == 'operator'


def test_user_plugin_scope_removes_project_skill_links(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_skills.py')
    skill = tmp_path / '.ai-badger/skills/shared'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('shared')
    arm.adjust(context(tmp_path, skills=['shared']))
    assert (tmp_path / '.agents/skills/shared').is_symlink()

    ctx = context(tmp_path, skills=['shared'])
    ctx['config']['codexScope'] = 'user'
    arm.adjust(ctx)

    assert not (tmp_path / '.agents/skills/shared').exists()


def test_catalog_skills_have_one_delivery_for_selected_scope(load_script, root, tmp_path,
                                                             monkeypatch):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    skills = sorted(path.parent.name for path in
                    (root / 'features/common/skills').glob('*/SKILL.md')
                    if 'scope: optIn' not in path.read_text())
    config = _config(stacks=['python'], agents=['codex'])

    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=skills).run()
    links = tmp_path / '.agents/skills'
    assert {entry.name for entry in links.iterdir()} == set(skills)
    assert all(entry.is_symlink() for entry in links.iterdir())

    config['codexScope'] = 'user'
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=skills).run()
    assert list(links.iterdir()) == []
    plugin_skills = {path.parent.name for path in (root / 'skills').glob('*/SKILL.md')}
    assert set(skills) <= plugin_skills
    effective = set(entry.name for entry in links.iterdir()) | (set(skills) & plugin_skills)
    assert effective == set(skills)


def test_native_persona_inherits_model_preserves_collision(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_agents.py')
    src = tmp_path / 'persona.md'
    src.write_text('---\nname: architect\ndescription: Planning\nmodel: opus\n---\n\nBody "quotes" \\ path')
    ctx = context(tmp_path, personas=[{'name': 'architect', 'path': str(src)}])
    arm.adjust(ctx)
    dst = tmp_path / '.codex/agents/architect.toml'
    parsed = tomllib.loads(dst.read_text())
    assert parsed == {'name': 'architect', 'description': 'Planning', 'sandbox_mode': 'read-only',
                      'developer_instructions': 'Body "quotes" \\ path'}
    dst.write_text('name = "operator"\n')
    arm.adjust(ctx)
    assert dst.read_text() == 'name = "operator"\n'


def test_mcp_preserves_config_and_scope(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_mcp.py')
    dst = tmp_path / '.codex/config.toml'
    dst.parent.mkdir()
    original = '# operator\nmodel = "custom"\n[mcp_servers.mine]\ncommand = "mine"\n'
    dst.write_text(original)
    ctx = context(tmp_path, mcp_declarations={
        'local': {'command': 'python3 "path with spaces.py"', 'env': {'X': 'value'}, 'scope': 'project'},
        'remote': {'url': 'https://example.test/mcp', 'tools': ['one']},
        'global': {'command': 'never', 'scope': 'user'}, 'mine': {'command': 'replacement'}})
    arm.adjust(ctx)
    first = dst.read_text()
    assert first.startswith(original)
    servers = tomllib.loads(first)['mcp_servers']
    assert servers['local']['args'] == ['path with spaces.py']
    assert servers['local']['env'] == {'X': 'value'}
    assert servers['remote']['enabled_tools'] == ['one']
    assert servers['mine']['command'] == 'mine'
    assert 'global' not in servers
    arm.adjust(ctx)
    assert dst.read_text() == first
    ctx['mcp_declined'] = ['local']
    arm.adjust(ctx)
    assert 'local' not in tomllib.loads(dst.read_text())['mcp_servers']


def test_invalid_toml_is_preserved(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_mcp.py')
    dst = tmp_path / '.codex/config.toml'
    dst.parent.mkdir()
    dst.write_text('invalid = [')
    result = arm.adjust(context(tmp_path, mcp_declarations={'new': {'command': 'python3'}}))
    assert not result['applied']
    assert dst.read_text() == 'invalid = ['


def test_hook_subset_and_user_preservation(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    src = tmp_path / '.ai-badger/hooks/hooks.json'
    src.parent.mkdir(parents=True)
    command = 'python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py"'
    src.write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': command}]}],
        'PreToolUse': [{'matcher': 'Edit|Write', 'hooks': [{'type': 'command', 'command': 'patch-guard'}]}]}}))
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    user = {'type': 'command', 'command': 'operator'}
    dst.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [user]}]}}))
    script = tmp_path / '.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py'
    script.parent.mkdir(parents=True)
    script.write_text('pass')
    arm.adjust(context(tmp_path))
    first = dst.read_text()
    parsed = json.loads(first)['hooks']
    assert parsed['Stop'][0]['hooks'] == [user]
    assert 'PreToolUse' not in parsed
    delivered = parsed['UserPromptSubmit'][0]['hooks'][0]['command']
    assert '${CLAUDE_PROJECT_DIR}' not in delivered
    assert 'CLAUDE_PROJECT_DIR' not in arm.RUNNER
    assert 'CLAUDE_HOME' not in arm.RUNNER
    assert str(tmp_path.resolve()) in delivered
    assert 'python3 -I -c' in delivered
    assert 'AI_BADGER_CODEX_HOOK=1' in delivered
    arm.adjust(context(tmp_path))
    assert dst.read_text() == first


def test_memory_first_gate_uses_native_pre_tool_hook(load_script, tmp_path, monkeypatch, capsys):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    hook = load_script(
        'features/common/skills/ai-raccoon-memory/scripts/memory_first_gate_hook.py')
    target_dir = tmp_path / '.ai-badger'
    scripts = target_dir / 'skills/ai-raccoon-memory/scripts'
    scripts.mkdir(parents=True)
    (scripts / 'memory_first_gate_hook.py').write_text('adapter')

    arm.adjust(context(tmp_path, target_dir=target_dir,
                       skills=['ai-raccoon-memory']))

    hooks = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']
    pre = next(group for group in hooks['PreToolUse'] if group.get('matcher') == '^Bash$')
    assert 'memory_first_gate_hook.py' in pre['hooks'][0]['command']

    seen = {}
    denial = {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
              'permissionDecision': 'deny', 'permissionDecisionReason': 'memory first'}}
    def deny(host, tool_name, tool_input, session_id, cwd=''):
        seen.update(host=host, tool_name=tool_name, tool_input=tool_input, cwd=cwd)
        return denial
    monkeypatch.setattr(hook.gate, 'decide', deny)
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO(json.dumps({
        'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
        'tool_input': {'command': 'rg secret'}, 'cwd': str(tmp_path)})))
    assert hook.main() == 0
    assert json.loads(capsys.readouterr().out) == denial
    assert seen == {'host': 'claude', 'tool_name': 'Bash',
                    'tool_input': {'command': 'rg secret'}, 'cwd': str(tmp_path)}


def test_memory_first_gate_post_hook_credits_codex_mcp_search(load_script, monkeypatch):
    hook = load_script(
        'features/common/skills/ai-raccoon-memory/scripts/memory_first_gate_post_hook.py')
    seen = {}
    monkeypatch.setattr(hook.gate, 'record_search', lambda session: seen.update(session=session))
    monkeypatch.setattr(hook.gate, 'project_id', lambda cwd: f'project:{cwd}')
    monkeypatch.setattr(hook.gate, 'credit_search',
                        lambda project, args, failed: seen.update(
                            project=project, args=args, failed=failed))
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO(json.dumps({
        'hook_event_name': 'PostToolUse', 'tool_name': 'mcp__ai_raccoon__memory_search',
        'tool_input': {'query': 'memory first gate'}, 'session_id': 'turn-1',
        'cwd': '/repo'})))

    assert hook.main() == 0
    assert seen == {'session': 'turn-1', 'project': 'project:/repo',
                    'args': {'query': 'memory first gate'}, 'failed': False}


def test_project_post_hook_uses_codex_adjustment_adapter(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    target_dir = tmp_path / '.ai-badger'
    hooks_dir = target_dir / 'hooks'
    hooks_dir.mkdir(parents=True)
    shared = target_dir / 'skills/ai-raccoon-memory/scripts/memory_first_gate_post_hook.py'
    shared.parent.mkdir(parents=True)
    shared.write_text('pass')
    hooks_file = hooks_dir / 'hooks.json'
    hooks_file.write_text(json.dumps({'hooks': {'PostToolUse': [{
        'matcher': '^(mcp__.+__)?memory_search$', 'hooks': [{
            'type': 'command', 'command': f'python3 "${{CLAUDE_PLUGIN_ROOT}}/features/common/skills/{shared.relative_to(target_dir / "skills")}"'
        }]}]}}))

    arm.adjust(context(tmp_path, target_dir=target_dir, skills=['ai-raccoon-memory']))

    adapter = hooks_dir / 'codex_memory_first_gate_post_hook.py'
    assert adapter.is_file()
    registered = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']['PostToolUse'][0]
    assert registered['matcher'] == '^(mcp__.+__)?memory_search$'
    assert 'hooks/codex_memory_first_gate_post_hook.py' in registered['hooks'][0]['command']
    assert str(shared) in registered['hooks'][0]['command']


@pytest.mark.parametrize('response,should_forward', [
    ({'isError': True, 'content': []}, False),
    ({'isError': False, 'content': []}, True),
])
def test_codex_memory_credit_adapter_filters_failed_tool_response(
        load_script, tmp_path, monkeypatch, response, should_forward):
    import io
    adapter = load_script('features/codex/adjustments/memory_first_gate_post_hook.py')
    observed = tmp_path / 'observed.json'
    shared = tmp_path / 'shared.py'
    shared.write_text(
        'import json, os, sys\n'
        'from pathlib import Path\n'
        'Path(os.environ["OBSERVED"]).write_text(sys.stdin.read())\n')
    payload = {'hook_event_name': 'PostToolUse', 'tool_name': 'mcp__ai_raccoon__memory_search',
               'tool_input': {'query': 'needle'}, 'tool_response': response}
    monkeypatch.setenv('OBSERVED', str(observed))
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(payload)))
    monkeypatch.setattr('sys.argv', ['codex_adapter.py', str(shared)])

    assert adapter.main() == 0
    assert observed.exists() is should_forward
    if should_forward:
        assert json.loads(observed.read_text()) == payload


def test_user_plugin_scope_removes_project_hooks_but_keeps_operator_hooks(
        load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    operator = {'type': 'command', 'command': 'operator-hook'}
    managed = {'type': 'command', 'command': arm.PREFIX + 'python3 example.py prompt-markers/scripts/user_prompt_hook.py'}
    dst.write_text(json.dumps({'hooks': {
        'Stop': [{'hooks': [operator]}],
        'UserPromptSubmit': [{'hooks': [managed]}]
    }}))
    ctx = context(tmp_path)
    ctx['config']['codexScope'] = 'user'

    arm.adjust(ctx)

    hooks = json.loads(dst.read_text())['hooks']
    assert hooks['Stop'][0]['hooks'] == [operator]
    assert hooks.get('UserPromptSubmit', []) == []


@pytest.mark.parametrize('agents', [['codex'], ['codex', 'pi'], ['pi', 'codex']])
def test_scaffold_native_discovery_and_repeat(load_script, root, tmp_path, monkeypatch, agents):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=agents)
    config['include'] = {'skills': ['git-work', 'prompt-markers']}
    runner = build_scaffolder(module, root=root, target=tmp_path, config=config,
                               skills=['prompt-markers', 'git-work'])
    runner.run()
    instruction = tmp_path / ('AGENTS.override.md' if 'pi' in agents else 'AGENTS.md')
    text = instruction.read_text()
    canonical = tmp_path / '.ai-badger' / instruction.name
    assert canonical.is_file(), 'managed instruction header must name an existing source copy'
    assert 'TDD is mandatory' in canonical.read_text()
    assert 'Non-negotiable invariants' in text
    assert 'TDD is mandatory' in text
    assert 'Path-specific instructions' in text
    assert '.ai-badger/instructions/python.instructions.md' in text
    assert (tmp_path / '.agents/skills/prompt-markers/SKILL.md').is_file()
    assert (tmp_path / '.codex/agents/architect.toml').is_file()
    assert (tmp_path / '.codex/hooks.json').is_file()
    assert (tmp_path / '.codex/config.toml').is_file()
    assert 'task-graph' in tomllib.loads((tmp_path / '.codex/config.toml').read_text())['mcp_servers']
    hook = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']
    assert 'UserPromptSubmit' in hook and 'PreToolUse' in hook
    for agent in (tmp_path / '.codex/agents').glob('*.toml'):
        assert 'model' not in tomllib.loads(agent.read_text())
    instruction.write_text(text.replace('TDD is mandatory', 'STALE RULE').replace('<!-- Project-specific overrides go here (survives re-scaffold) -->', 'Custom preserved instructions'))
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in (tmp_path / '.codex').rglob('*') if p.is_file()}
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['prompt-markers', 'git-work']).run()
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in (tmp_path / '.codex').rglob('*') if p.is_file()}
    assert after == before
    assert 'Custom preserved instructions' in instruction.read_text()
    assert 'TDD is mandatory' in instruction.read_text()
    assert 'STALE RULE' not in instruction.read_text()


def test_unmanaged_override_warning(load_script, root, tmp_path, monkeypatch):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    override = tmp_path / 'AGENTS.override.md'
    override.write_text('operator instructions')
    runner = build_scaffolder(module, root=root, target=tmp_path,
                               config=_config(stacks=['python'], agents=['codex', 'pi']))
    runner.run()
    assert override.read_text() == 'operator instructions'
    assert any('masks Codex AGENTS.md' in note for note in runner.notes)


@pytest.mark.parametrize('bad', ['mcp_servers = "string"', 'features = "string"'])
def test_wrong_toml_shapes_preserved(load_script, tmp_path, bad):
    arm = load_script('features/codex/adjustments/adjust_mcp.py')
    dst = tmp_path / '.codex/config.toml'
    dst.parent.mkdir()
    dst.write_text(bad)
    assert not arm.adjust(context(tmp_path, mcp_declarations={'new': {'command': 'python3'}}))['applied']
    assert dst.read_text() == bad


@pytest.mark.parametrize('bad', [[], {'hooks': []}])
def test_wrong_hook_shapes_preserved(load_script, tmp_path, bad):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    text = json.dumps(bad)
    dst.write_text(text)
    assert not arm.adjust(context(tmp_path))['applied']
    assert dst.read_text() == text


def test_codex_agent_override_schema(root):
    import jsonschema
    schema = json.loads((root / 'schemas/stack-mcp.schema.json').read_text())
    jsonschema.validate({'servers': [{'name': 'example', 'command': 'python3', 'declare': True,
                                    'agentOverrides': {'codex': {'args': ['native']}}}]}, schema)


def test_native_hook_allow_deny_context_subprocess(load_script, root, tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=['codex'])
    config['include'] = {'skills': ['git-work', 'prompt-markers']}
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['git-work', 'prompt-markers']).run()
    hooks = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']
    # Exercise the generated registration from a nested working directory.
    moved = tmp_path.with_name(tmp_path.name + ' moved project')
    tmp_path.rename(moved)
    tmp_path = moved
    # Moving changes the approved root; refresh registrations before hook review.
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['git-work', 'prompt-markers']).run()
    hooks = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']
    nested = tmp_path / 'nested'
    nested.mkdir()
    (nested / 'pathlib.py').write_text("raise RuntimeError('UNREVIEWED_CWD_IMPORT')\n")
    fake = nested / '.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py'
    fake.parent.mkdir(parents=True)
    fake.write_text("print('UNREVIEWED_NESTED_SCRIPT')\n")
    (nested / '.ai-badger/config.json').write_text('{}')
    fake_guard = nested / '.ai-badger/skills/git-work/scripts/git_internals_guard.py'
    fake_guard.parent.mkdir(parents=True)
    fake_guard.write_text("print('{}')\n")
    environment = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'])
    def fire(event, payload):
        command = hooks[event][0]['hooks'][0]['command']
        result = subprocess.run(command, shell=True, cwd=nested, env=environment,
                                input=json.dumps(payload), text=True, capture_output=True, check=True)
        assert 'hook failed' not in result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else {}
    deny = fire('PreToolUse', {'tool_name': 'Bash', 'tool_input': {'command': 'echo bad > .git/config'}, 'cwd': str(tmp_path)})
    assert deny['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert fire('PreToolUse', {'tool_name': 'Bash', 'tool_input': {'command': 'git status'}, 'cwd': str(tmp_path)}) == {}
    injected = fire('UserPromptSubmit', {'prompt': 'h: inspect native resources', 'cwd': str(tmp_path)})
    assert injected['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
    assert injected['hookSpecificOutput']['additionalContext']


def test_stale_persona_owned_only(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_agents.py')
    src = tmp_path / 'persona.md'
    src.write_text('---\nname: architect\ndescription: Planning\n---\nBody')
    ctx = context(tmp_path, personas=[{'name': 'architect', 'path': str(src)}])
    arm.adjust(ctx)
    user = tmp_path / '.codex/agents/user.toml'
    user.write_text('name = "user"\n')
    ctx['personas'] = []
    arm.adjust(ctx)
    assert not (tmp_path / '.codex/agents/architect.toml').exists()
    assert user.read_text() == 'name = "user"\n'


def test_declined_owned_hooks_removed(load_script, root, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    script = tmp_path / '.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py'
    script.parent.mkdir(parents=True)
    script.write_text('pass')
    ctx = context(tmp_path)
    arm.adjust(ctx)
    ctx['config']['exclude'] = {'skills': ['prompt-markers']}
    arm.adjust(ctx)
    assert not json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']['UserPromptSubmit']


@pytest.mark.parametrize('arm_name', ['agents', 'skills', 'mcp', 'hooks'])
def test_native_directory_symlink_preserved(load_script, tmp_path, arm_name):
    arm = load_script(f'features/codex/adjustments/adjust_{arm_name}.py')
    outside = tmp_path / 'outside'
    outside.mkdir()
    discovery = tmp_path / ('.agents' if arm_name == 'skills' else '.codex')
    discovery.symlink_to(outside, target_is_directory=True)
    source = tmp_path / '.ai-badger/skills/first'
    source.mkdir(parents=True)
    (source / 'SKILL.md').write_text('first')
    result = arm.adjust(context(tmp_path, skills=['first'], mcp_declarations={'new': {'command': 'python3'}}))
    assert not result['applied']
    assert list(outside.iterdir()) == []
    assert discovery.is_symlink()


def test_owned_mcp_suffix_context_is_not_changed(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_mcp.py')
    dst = tmp_path / '.codex/config.toml'
    dst.parent.mkdir()
    original = arm.START + '[mcp_servers.old]\ncommand = "old"\n' + arm.END + 'custom_setting = "preserve me"\n'
    dst.write_text(original)
    result = arm.adjust(context(tmp_path, mcp_declarations={'new': {'command': 'python3'}}))
    assert not result['applied']
    assert dst.read_text() == original


def test_manifest_history_does_not_own_user_skill_replacement(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_skills.py')
    skill = tmp_path / '.ai-badger/skills/first'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('framework')
    (tmp_path / '.ai-badger/manifest.json').write_text(json.dumps({'entries': [{'target': '.agents/skills/first'}]}))
    user = tmp_path / '.agents/skills/first'
    user.mkdir(parents=True)
    (user / 'SKILL.md').write_text('operator replacement')
    arm.adjust(context(tmp_path, skills=['first']))
    assert not user.is_symlink()
    assert (user / 'SKILL.md').read_text() == 'operator replacement'


@pytest.mark.parametrize('arm_name,rel', [('agents', '.codex/agents/architect.toml'), ('mcp', '.codex/config.toml'), ('hooks', '.codex/hooks.json')])
def test_native_output_symlink_preserved(load_script, tmp_path, arm_name, rel):
    arm = load_script(f'features/codex/adjustments/adjust_{arm_name}.py')
    outside = tmp_path / 'operator'
    outside.write_text('# operator\n')
    dst = tmp_path / rel
    dst.parent.mkdir(parents=True)
    dst.symlink_to(outside)
    src = tmp_path / 'persona.md'
    src.write_text('---\nname: architect\ndescription: Planning\n---\nBody')
    arm.adjust(context(tmp_path, mcp_declarations={'new': {'command': 'python3'}},
                       personas=[{'name': 'architect', 'path': str(src)}]))
    assert outside.read_text() == '# operator\n'
    assert dst.is_symlink()


@pytest.mark.parametrize('rel', ['AGENTS.md', 'AGENTS.override.md'])
def test_native_instruction_symlink_preserved(load_script, root, tmp_path, monkeypatch, rel):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    outside = tmp_path / 'operator instructions'
    original = '<!-- Managed by ai-badger. Source of truth: .ai-badger/AGENTS.md. -->\nExternal instructions'
    outside.write_text(original)
    dst = tmp_path / rel
    dst.symlink_to(outside)
    runner = build_scaffolder(module, root=root, target=tmp_path, overwrite=True,
                               config=_config(stacks=['python'], agents=['pi', 'codex']))
    runner.run()
    assert outside.read_text() == original
    assert dst.is_symlink()


def test_union_config_is_not_recorded_as_owned(load_script, root, tmp_path, monkeypatch):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=['codex'])
    config['include'] = {'skills': ['git-work', 'prompt-markers']}
    build_scaffolder(module, root=root, target=tmp_path, config=config, skills=['git-work', 'prompt-markers']).run()
    manifest = json.loads((tmp_path / '.ai-badger/manifest.json').read_text())
    targets = {entry['target'] for entry in manifest['entries']}
    assert '.codex/hooks.json' not in targets
    assert '.codex/config.toml' not in targets


def test_declined_skill_link_removed_even_without_delivered_skills(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_skills.py')
    skill = tmp_path / '.ai-badger/skills/first'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('first')
    arm.adjust(context(tmp_path, skills=['first']))
    ctx = context(tmp_path, skills=[], prune=False)
    ctx['config']['exclude'] = {'skills': ['first']}
    arm.adjust(ctx)
    assert not (tmp_path / '.agents/skills/first').is_symlink()


@pytest.mark.parametrize('stacks', [['python'], ['python', 'codex']])
def test_deselect_codex_cleans_owned_merged_entries(load_script, root, tmp_path, monkeypatch, stacks):
    """Whole-file pruning cannot own merged config, nor a still-detected codex stack."""
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=stacks, agents=['codex'])
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['git-work', 'prompt-markers']).run()
    assert list((tmp_path / '.codex/agents').glob('*.toml'))
    dst = tmp_path / '.codex/config.toml'
    operator = '[mcp_servers.operator]\ncommand = "operator-command"\n'
    dst.write_text(operator + dst.read_text())
    hooks_path = tmp_path / '.codex/hooks.json'
    hooks = json.loads(hooks_path.read_text())
    user = {'type': 'command', 'command': 'echo operator'}
    hooks['hooks'].setdefault('Stop', []).append({'hooks': [user]})
    hooks_path.write_text(json.dumps(hooks))
    assert '# ai-badger:mcp-start' in dst.read_text()
    assert 'AI_BADGER_CODEX_HOOK=1' in hooks_path.read_text()

    config['agents'] = ['claude']
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['git-work', 'prompt-markers']).run()

    assert dst.read_text() == operator
    remaining = json.loads(hooks_path.read_text())
    assert remaining['hooks']['Stop'][-1]['hooks'] == [user]
    assert 'AI_BADGER_CODEX_HOOK=1' not in hooks_path.read_text()
    links = tmp_path / '.agents/skills'
    assert not any(entry.is_symlink() for entry in links.iterdir())
    assert not list((tmp_path / '.codex/agents').glob('*.toml'))


def test_deselect_codex_removes_only_owned_skill_links(load_script, tmp_path):
    """A directory symlink escapes manifest pruning, so deselection must unlink it here."""
    arm = load_script('features/codex/adjustments/adjust_skills.py')
    skill = tmp_path / '.ai-badger/skills/first'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('first')
    arm.adjust(context(tmp_path, skills=['first']))
    discovery = tmp_path / '.agents/skills'
    assert (discovery / 'first').is_symlink()
    (discovery / 'operator').mkdir()
    (discovery / 'elsewhere').symlink_to(tmp_path / '.ai-badger')

    result = arm.adjust(context(tmp_path, config={'agents': ['claude']}, skills=[]))

    assert not (discovery / 'first').is_symlink()
    assert (discovery / 'operator').is_dir()
    assert (discovery / 'elsewhere').is_symlink()
    assert result['files'] == []


def test_deselect_codex_removes_only_owned_persona_files(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_agents.py')
    directory = tmp_path / '.codex/agents'
    directory.mkdir(parents=True)
    (directory / 'architect.toml').write_text(arm.HEADER + 'architect.md\nname = "architect"\n')
    (directory / 'operator.toml').write_text('name = "operator"\n')
    (directory / 'linked.toml').symlink_to(directory / 'architect.toml')

    result = arm.adjust(context(tmp_path, config={'agents': ['claude']}))

    assert sorted(p.name for p in directory.iterdir()) == ['linked.toml', 'operator.toml']
    assert result['files'] == []


def test_deselect_codex_survives_skill_link_loop(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_skills.py')
    skill = tmp_path / '.ai-badger/skills/first'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('first')
    arm.adjust(context(tmp_path, skills=['first']))
    loop = tmp_path / '.agents/skills/loop'
    loop.symlink_to(loop)

    arm.adjust(context(tmp_path, config={'agents': ['claude']}, skills=[]))

    assert not (tmp_path / '.agents/skills/first').is_symlink()
    assert loop.is_symlink()


@pytest.mark.parametrize('arm_name,rel,operator', [
    ('mcp', '.codex/config.toml', '# user layout\n[mcp_servers.user]\ncommand="user"\n'),
    ('hooks', '.codex/hooks.json', '{ "hooks": {"Stop": [{"matcher": "operator"}]}}\n'),
    ('hooks', '.codex/hooks.json', '{ "operatorMetadata": "untouched" }\n'),
    ('hooks', '.codex/hooks.json', '{ "hooks": { "Stop": [{"hooks": [{"command": "operator"}]}]}}\n'),
])
def test_deselection_preserves_operator_bytes_and_missing_files(
        load_script, tmp_path, arm_name, rel, operator):
    arm = load_script(f'features/codex/adjustments/adjust_{arm_name}.py')
    ctx = context(tmp_path, config={'agents': []})
    arm.adjust(ctx)
    dst = tmp_path / rel
    assert not dst.exists()
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(operator)
    arm.adjust(ctx)
    assert dst.read_text() == operator
    dst.write_text('malformed [')
    arm.adjust(ctx)
    assert dst.read_text() == 'malformed ['


def test_bound_hook_refuses_script_symlink_escape(load_script, tmp_path):
    import subprocess
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    script = tmp_path / '.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py'
    script.parent.mkdir(parents=True)
    outside = tmp_path.parent / (tmp_path.name + '-outside.py')
    outside.write_text("print('ESCAPED_HOOK_EXECUTED')\n")
    script.symlink_to(outside)
    arm.adjust(context(tmp_path))
    command = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
    result = subprocess.run(command, shell=True, cwd=tmp_path, text=True,
                            input='{}', capture_output=True, check=True)
    assert result.stdout == ''


def test_bound_hook_refuses_helper_symlink_escape(load_script, root, tmp_path):
    import shutil
    import subprocess
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    directory = tmp_path / '.ai-badger/skills/git-work/scripts'
    shutil.copytree(root / 'features/common/skills/git-work/scripts', directory)
    outside = tmp_path.parent / (tmp_path.name + '-helper.py')
    outside.write_text("print('ESCAPED_HELPER_EXECUTED')\n")
    helper = directory / 'shell_parser.py'
    helper.unlink()
    helper.symlink_to(outside)
    arm.adjust(context(tmp_path))
    command = json.loads((tmp_path / '.codex/hooks.json').read_text())['hooks']['PreToolUse'][0]['hooks'][0]['command']
    result = subprocess.run(command, shell=True, cwd=tmp_path, text=True,
                            input='{}', capture_output=True, check=True)
    assert result.stdout == ''
