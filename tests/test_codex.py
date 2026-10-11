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
    assert str(tmp_path) not in delivered
    assert 'AI_BADGER_CODEX_HOOK=1' in delivered
    arm.adjust(context(tmp_path))
    assert dst.read_text() == first


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
    nested = tmp_path / 'nested'
    nested.mkdir()
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
