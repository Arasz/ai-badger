"""Codex tool hook composition and opt-out contracts."""
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def context(target, enabled=True):
    return {'target': target, 'target_dir': target / '.ai-badger',
            'framework_root': ROOT, 'config': {'agents': ['codex']},
            'tools': {'rtk': {'agents': {'codex': {
                'mode': 'native', 'arg': 'codex', 'command': 'env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c true'
            }}}} if enabled else {}}


def handlers(path):
    return json.loads(path.read_text())['hooks']['PreToolUse']


@pytest.mark.parametrize('order', [('hooks', 'tools', 'hooks'), ('tools', 'hooks', 'tools')])
def test_marked_hook_composes_in_both_orders(load_script, tmp_path, order):
    arms = {name: load_script(f'features/codex/adjustments/adjust_{name}.py')
            for name in ('hooks', 'tools')}
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    user = {'type': 'command', 'command': 'echo operator'}
    dst.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [user]}]}}))
    for name in order:
        arms[name].adjust(context(tmp_path))
    groups = handlers(dst)
    commands = [h['command'] for group in groups for h in group['hooks']]
    assert commands.count(user['command']) == 1
    assert sum('AI_BADGER_TOOL=rtk' in command for command in commands) == 1
    rtk = next(group for group in groups if any('AI_BADGER_TOOL=rtk' in h['command'] for h in group['hooks']))
    assert rtk == {'matcher': 'Bash', 'hooks': [{
        'type': 'command', 'command': context(tmp_path)['tools']['rtk']['agents']['codex']['command'],
        'timeout': 5}]}
    before = dst.read_bytes()
    arms['tools'].adjust(context(tmp_path))
    assert dst.read_bytes() == before
    arms['tools'].adjust(context(tmp_path, enabled=False))
    assert handlers(dst) == [{'matcher': 'Bash', 'hooks': [user]}]


@pytest.mark.parametrize('content', ['{broken', '{"hooks": []}', '{"hooks": {"PreToolUse": [1]}}'])
def test_malformed_hooks_preserved(load_script, tmp_path, content):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    dst.write_text(content)
    assert not arm.adjust(context(tmp_path))['applied']
    assert dst.read_text() == content


def test_symlinked_codex_preserved(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (tmp_path / '.codex').symlink_to(elsewhere, target_is_directory=True)
    assert not arm.adjust(context(tmp_path))['applied']
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize('route', [{}, {'tools': {}}, {'agents': ['claude']}],
                         ids=['still-opted-in', 'tool-removed', 'codex-deselected'])
def test_a_scaffold_removes_the_entry_an_earlier_native_release_wired(
        load_script, root, tmp_path, monkeypatch, route):
    """rtk is propose-only for Codex, so an entry 0.195.0 wired goes; the operator's stays."""
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=['codex'])
    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['git-work', 'commit-reminder']).run()
    dst = tmp_path / '.codex/hooks.json'
    existing = json.loads(dst.read_text())
    existing['hooks'].setdefault('Stop', []).append({'hooks': [{'command': 'operator'}]})
    existing['hooks'].setdefault('PreToolUse', []).append({'matcher': 'Bash', 'hooks': [
        {'type': 'command', 'command': 'env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c true',
         'timeout': 5}]})
    dst.write_text(json.dumps(existing))
    config['tools'] = {'rtk': {'hooks': ['codex']}}
    config.update(route)

    build_scaffolder(module, root=root, target=tmp_path, config=config,
                     skills=['git-work', 'commit-reminder']).run()

    assert 'AI_BADGER_TOOL=rtk' not in dst.read_text()
    assert json.loads(dst.read_text())['hooks']['Stop'] == [{'hooks': [{'command': 'operator'}]}]
    assert not (tmp_path / 'RTK.md').exists()
    doc = tmp_path / 'AGENTS.md'
    assert not doc.exists() or '@RTK.md' not in doc.read_text()


def test_codex_notice_and_no_config_change(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    config = tmp_path / '.codex/config.toml'
    config.parent.mkdir()
    config.write_text('model = "operator"\n')
    note = arm.adjust(context(tmp_path))['notes']
    for fragment in ('trust', '/hooks', 'allow', 'classifier', 'writable_roots'):
        assert fragment in note
    assert config.read_text() == 'model = "operator"\n'


def test_every_tool_with_a_codex_arm_is_wired(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    ctx = context(tmp_path)
    ctx['tools']['other'] = {'agents': {'codex': {
        'mode': 'native', 'arg': 'codex', 'command': 'env AI_BADGER_TOOL=other sh -c true'}}}
    ctx['tools']['hermes-only'] = {'agents': {'hermes': {'mode': 'propose', 'arg': 'hermes'}}}
    assert arm.adjust(ctx)['applied']
    commands = [h['command'] for group in handlers(tmp_path / '.codex/hooks.json')
                for h in group['hooks']]
    assert commands == [ctx['tools']['rtk']['agents']['codex']['command'],
                        'env AI_BADGER_TOOL=other sh -c true']


def test_no_tools_and_no_file_writes_nothing(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    assert not arm.adjust(context(tmp_path, enabled=False))['applied']
    assert not (tmp_path / '.codex').exists()


def test_wired_entry_already_last_is_left_untouched(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    arm.adjust(context(tmp_path))
    dst = tmp_path / '.codex/hooks.json'
    before = dst.read_bytes()
    arm.adjust(context(tmp_path))
    assert dst.read_bytes() == before
    assert sorted(p.name for p in dst.parent.iterdir()) == ['hooks.json']


def test_the_marked_group_is_moved_last_after_a_framework_group_is_appended(load_script, tmp_path):
    arm = load_script('features/codex/adjustments/adjust_tools.py')
    arm.adjust(context(tmp_path))
    path = tmp_path / '.codex/hooks.json'
    data = json.loads(path.read_text())
    guard = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'echo guard'}]}
    data['hooks']['PreToolUse'].append(guard)
    path.write_text(json.dumps(data))

    arm.adjust(context(tmp_path))

    groups = json.loads(path.read_text())['hooks']['PreToolUse']
    assert groups[0] == guard
    assert 'AI_BADGER_TOOL=rtk' in groups[-1]['hooks'][0]['command']
    assert len(groups) == 2


def test_adjust_hooks_inserts_framework_groups_ahead_of_a_marked_tool_group(load_script, tmp_path):
    guard = tmp_path / '.ai-badger/skills/git-work/scripts/git_internals_guard.py'
    guard.parent.mkdir(parents=True)
    guard.write_text('')
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    tool = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'timeout': 5, 'command':
                                          'env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c true'}]}
    dst.write_text(json.dumps({'hooks': {'PreToolUse': [tool]}}))

    load_script('features/codex/adjustments/adjust_hooks.py').adjust(context(tmp_path, enabled=False))

    groups = handlers(dst)
    assert groups[-1] == tool
    assert any('git_internals_guard' in h['command'] for h in groups[0]['hooks'])


def test_a_propose_arm_removes_the_wired_entry_and_says_why(load_script, tmp_path):
    dst = tmp_path / '.codex/hooks.json'
    dst.parent.mkdir()
    dst.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
        {'type': 'command', 'command': 'env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c true'}]}]}}))
    ctx = context(tmp_path)
    ctx['tools']['rtk']['agents']['codex'] = {'mode': 'propose', 'arg': 'codex'}

    result = load_script('features/codex/adjustments/adjust_tools.py').adjust(ctx)

    assert 'AI_BADGER_TOOL' not in dst.read_text()
    # A local `rtk init --codex` edits the generated AGENTS.md; only the user-wide init is safe.
    assert 'approval' in result['notes'] and '`rtk init -g --codex`' in result['notes']
    assert 'user-wide' in result['notes'] and 'edits the generated AGENTS.md' in result['notes']
