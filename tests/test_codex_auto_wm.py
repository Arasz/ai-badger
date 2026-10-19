"""Codex AWM protocol boundaries."""
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'features/codex/adjustments/auto_wm_hook.py'
SOURCE = ROOT / 'features/claude/skills/auto-wm/hooks/awm_gate.py'


def adapter():
    spec = importlib.util.spec_from_file_location('codex_awm', ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(event='PreToolUse', tool='exec_command', tool_input=None, mode='away'):
    module = adapter()
    events = []
    namespace = {}
    def main():
        payload = json.load(module.sys.stdin)
        namespace['log_event']('auto_approve', 'safe')
        namespace['emit']('allow', 'approved')
    namespace.update(main=main, log_event=lambda *args: events.append(args))
    payload = {'hook_event_name': event, 'tool_name': tool,
               'tool_input': {'cmd': 'pwd'} if tool_input is None else tool_input}
    output = io.StringIO()
    with patch.object(module.runpy, 'run_path', return_value=namespace), \
         patch.object(module.sys, 'stdin', io.StringIO(json.dumps(payload))), \
         patch.object(module.sys, 'stdout', output):
        module.main(SOURCE)
    return output.getvalue(), events


def test_pretool_never_emits_unsupported_allow_or_approval_audit():
    assert invoke() == ('', [])


def test_permission_request_native_approval_and_one_audit():
    output, events = invoke('PermissionRequest')
    assert json.loads(output) == {'hookSpecificOutput': {
        'hookEventName': 'PermissionRequest', 'decision': {'behavior': 'allow'}}}
    assert len(events) == 1


@pytest.mark.parametrize('tool,data', [('apply_patch', {'patch': 'x'}),
    ('functions.apply_patch', {'patch': 'x'}), ('unknown', {}), ('mcp__x__read', {}),
    ('exec_command', []), ('exec_command', {'cmd': 1}), ('exec_command', {})])
def test_unknown_and_malformed_defer(tool, data):
    assert invoke('PermissionRequest', tool, data) == ('', [])


def test_real_gate_scope_denylist_and_audit(tmp_path):
    import os
    import subprocess
    import sys
    import sqlite3
    project = tmp_path / 'project'
    project.mkdir()
    user = tmp_path / 'user'
    env = dict(os.environ, AI_BADGER_USER_ROOT=str(user), HOME=str(tmp_path / 'home'))
    scripts = SOURCE.parent.parent / 'scripts'
    seed = ('import sys;sys.path.insert(0,sys.argv[1]);import badger_store;'
            's=badger_store.open_user();s.kv_set("awm_state",sys.argv[2],'
            '{"enabled":True,"mode":"away","expires_at":"2099-01-01T00:00:00+00:00"});s.close()')
    subprocess.run([sys.executable, '-c', seed, str(scripts), str(project)], env=env, check=True)
    def call(event, tool='exec_command', data=None, cwd=None):
        result = subprocess.run([sys.executable, str(ADAPTER), str(SOURCE)],
            input=json.dumps({'hook_event_name': event, 'tool_name': tool,
                              'tool_input': data or {'cmd': 'pwd'}, 'cwd': str(cwd or project)}),
            text=True, capture_output=True, env=env, check=True)
        return result.stdout
    assert call('PreToolUse') == ''
    for cmd in ('rm -rf x', 'curl https://example.com', 'git push --force'):
        assert call('PermissionRequest', data={'cmd': cmd}) == ''
    assert call('PermissionRequest', cwd=tmp_path) == ''
    assert call('PermissionRequest', data={'cmd': 'pwd', 'workdir': str(tmp_path)}) == ''
    assert call('PermissionRequest', data={'cmd': 'pwd', 'workdir': []}) == ''
    assert call('PermissionRequest', data={'cmd': 'pwd', 'workdir': '../'}) == ''
    assert call('PermissionRequest', tool='functions.apply_patch') == ''
    assert json.loads(call('PermissionRequest'))['hookSpecificOutput']['decision'] == {'behavior': 'allow'}
    assert json.loads(call('PreToolUse', 'request_user_input'))['hookSpecificOutput']['permissionDecision'] == 'deny'
    banner = json.loads(call('UserPromptSubmit'))['hookSpecificOutput']['additionalContext']
    assert 'PermissionRequest' in banner and '~/.claude' not in banner
    assert call('UserPromptSubmit', cwd=tmp_path) == ''
    dbs = list(user.rglob('*.db'))
    assert len(dbs) == 1
    with sqlite3.connect(dbs[0]) as db:
        rows = db.execute('select * from awm_decisions').fetchall()
        assert sum('auto_approve' in str(row) for row in rows) == 1


def migration_module():
    spec = importlib.util.spec_from_file_location('awm_migrate',
        ADAPTER.with_name('migrate_auto_wm_hooks.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_mixed_groups_and_requires_assets(tmp_path):
    import shutil
    module = migration_module()
    package = tmp_path / 'plugin'
    package.mkdir()
    (package / '.codex-plugin').mkdir()
    plugin_manifest = package / '.codex-plugin/plugin.json'
    plugin_manifest.write_text(json.dumps({'hooks': './hooks/codex-hooks.json'}))
    (package / 'hooks').mkdir()
    shutil.copy(ROOT / 'hooks/codex-hooks.json', package / 'hooks/codex-hooks.json')
    config = tmp_path / 'hooks.json'
    original = {'operator': True, 'hooks': {'PreToolUse': [{'matcher': '.*', 'operator': 9,
        'hooks': [{'type': 'command', 'command': 'python3 ~/.claude/skills/auto-wm/hooks/awm_gate.py'},
                  {'type': 'command', 'command': 'rtk hook'}]}],
        'UserPromptSubmit': [{'hooks': [{'command': 'python3 ~/.claude/skills/auto-wm/hooks/awm_context.py'}]}]}}
    config.write_text(json.dumps(original))
    with pytest.raises(ValueError, match='missing replacement asset'):
        module.migrate(config, package)
    assert json.loads(config.read_text()) == original
    for relative in ('features/codex/adjustments/auto_wm_hook.py',
                     'skills/auto-wm/hooks/awm_gate.py', 'skills/auto-wm/hooks/awm_context.py',
                     'skills/auto-wm/hooks/shell_parser.py', 'skills/auto-wm/scripts/badger_store.py',
                     'skills/auto-wm/scripts/awm.py'):
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('replacement')
    plugin_manifest.write_text(json.dumps({'hooks': './hooks/other.json'}))
    with pytest.raises(ValueError, match='not registered'):
        module.migrate(config, package)
    assert json.loads(config.read_text()) == original
    plugin_manifest.write_text(json.dumps({'hooks': './hooks/codex-hooks.json'}))
    assert module.migrate(config, package)
    result = json.loads(config.read_text())
    assert result['operator'] and result['hooks']['PreToolUse'][0]['operator'] == 9
    assert result['hooks']['PreToolUse'][0]['hooks'] == [{'type': 'command', 'command': 'rtk hook'}]
    assert result['hooks']['UserPromptSubmit'] == []
    assert json.loads(config.with_name('hooks.json.auto-wm.bak').read_text()) == original
    assert not module.migrate(config, package)


@pytest.mark.parametrize('command', ['python3 /tmp/auto-wm/hooks/awm_gate.py',
    'python3 ~/.claude/skills/auto-wm/hooks/awm_gate.py --extra',
    'python3 ~/.claude/skills/auto-wm/hooks/awm_gate.py; echo x',
    'env python3 ~/.claude/skills/auto-wm/hooks/awm_gate.py'])
def test_migration_leaves_unrecognized_commands(command):
    assert not migration_module().legacy(command)


@pytest.mark.parametrize('mode,enabled,expiry,cwd,broad', [
    ('away', False, '2099-01-01T00:00:00+00:00', True, False),
    ('away', True, '2000-01-01T00:00:00+00:00', True, False),
    ('away', True, '2099-01-01T00:00:00+00:00', False, False),
    ('away', True, '2099-01-01T00:00:00+00:00', True, True),
])
def test_context_scope_expiry_and_off_are_silent(tmp_path, mode, enabled, expiry, cwd, broad):
    module = adapter()
    namespace = module.runpy.run_path(str(SOURCE))
    project = '/' if broad else str(tmp_path)
    state = {'projects': {project: {'mode': mode, 'enabled': enabled, 'expires_at': expiry}}}
    payload = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(tmp_path if cwd else tmp_path.parent)}
    output = io.StringIO()
    with patch.object(module.runpy, 'run_path', side_effect=[namespace, {'load_state': lambda: state}]), \
         patch.object(module.sys, 'stdin', io.StringIO(json.dumps(payload))), \
         patch.object(module.sys, 'stdout', output):
        module.main(SOURCE)
    assert output.getvalue() == ''


@pytest.mark.parametrize('scope', ['user', 'excluded', 'deselected'])
def test_project_awm_hooks_are_idempotent_and_removed(load_script, tmp_path, scope):
    arm = load_script('features/codex/adjustments/adjust_hooks.py')
    target_dir = tmp_path / '.ai-badger'
    source = target_dir / 'skills/auto-wm/hooks'
    source.mkdir(parents=True)
    for name in ('awm_gate.py', 'awm_context.py'):
        (source / name).write_text('')
    context = {'target': tmp_path, 'target_dir': target_dir, 'framework_root': ROOT,
               'config': {'agents': ['codex']}}
    arm.adjust(context)
    hooks = tmp_path / '.codex/hooks.json'
    first = hooks.read_text()
    arm.adjust(context)
    assert hooks.read_text() == first
    document = json.loads(first)
    assert sum('codex_auto_wm_hook.py' in h['command']
               for groups in document['hooks'].values() for g in groups for h in g['hooks']) == 3
    if scope == 'user':
        context['config']['codexScope'] = 'user'
    elif scope == 'excluded':
        context['config']['exclude'] = {'skills': ['auto-wm']}
    else:
        context['config']['agents'] = []
    arm.adjust(context)
    assert 'codex_auto_wm_hook.py' not in hooks.read_text()


def test_missing_source_defers_subprocess(tmp_path):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(ADAPTER), str(tmp_path / 'missing.py')],
        input=json.dumps({'hook_event_name': 'PermissionRequest', 'tool_name': 'exec_command',
                          'tool_input': {'cmd': 'pwd'}}), text=True, capture_output=True)
    assert result.returncode == 0 and result.stdout == ''


def test_plugin_commands_use_native_adapter():
    hooks = json.loads((ROOT / 'hooks/codex-hooks.json').read_text())['hooks']
    for event in ('PreToolUse', 'PermissionRequest', 'UserPromptSubmit'):
        commands = [h['command'] for group in hooks[event] for h in group['hooks']
                    if 'auto_wm_hook.py' in h['command']]
        assert len(commands) == 1
        assert '${PLUGIN_ROOT}/features/codex/adjustments/auto_wm_hook.py' in commands[0]
        assert '${PLUGIN_ROOT}/skills/auto-wm/hooks/' in commands[0]
