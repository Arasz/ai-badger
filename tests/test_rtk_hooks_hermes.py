"""Hermes is proposal-only for tools: it prints the user-wide init and owns nothing (ADR-0039)."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARM = 'features/hermes/adjustments/adjust_tools.py'


def context(target, enabled=True):
    return {'target': target, 'target_dir': target / '.ai-badger', 'framework_root': ROOT,
            'config': {'agents': ['hermes']}, 'install': True,
            'tools': {'rtk': {'agents': {'hermes': {'mode': 'propose', 'arg': 'hermes'}}}}
            if enabled else {}}


def tree(path):
    return {str(p.relative_to(path)): p.read_bytes() if p.is_file() else None
            for p in sorted(path.rglob('*'))}


@pytest.mark.parametrize('hermes_home', [None, 'custom-hermes'])
def test_note_proposes_user_wide_init(load_script, tmp_path, monkeypatch, hermes_home):
    if hermes_home:
        monkeypatch.setenv('HERMES_HOME', str(tmp_path / hermes_home))
    else:
        monkeypatch.delenv('HERMES_HOME', raising=False)
    result = load_script(ARM).adjust(context(tmp_path))
    note = result['notes']
    assert result['files'] == []
    assert 'rtk init -g --agent hermes --auto-patch' in note
    assert (str(tmp_path / hermes_home) if hermes_home else '~/.hermes') in note
    for fragment in ('user-wide', 'rtk-rewrite', 'rtk-prefixed', 'enabled: []'):
        assert fragment in note
    assert list(tmp_path.iterdir()) == []


def test_no_hermes_arm_no_note(load_script, tmp_path):
    result = load_script(ARM).adjust(context(tmp_path, enabled=False))
    assert not result['applied'] and 'rtk init' not in result['notes']


@pytest.mark.parametrize('execute', [False, True])
def test_scaffold_leaves_sandboxed_homes_unchanged(load_script, root, tmp_path, monkeypatch,
                                                   execute):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    home, hermes_home, project = (tmp_path / name for name in ('home', 'hermes', 'proj'))
    for path in (home, hermes_home, project):
        path.mkdir()
    (hermes_home / 'config.yaml').write_text('plugins:\n  enabled: []\n')
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('HERMES_HOME', str(hermes_home))
    before = (tree(home), tree(hermes_home))
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=['hermes'])
    config['tools'] = {'rtk': {'hooks': ['hermes']}}
    scaf = build_scaffolder(module, root=root, target=project, config=config, execute=execute)
    ran = []
    scaf.tools.run = lambda argv, **_: ran.append(argv) or subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(scaf, 'install_plugins', lambda: [])
    monkeypatch.setattr(scaf, '_check_dependencies',
                        lambda: {'installed': [], 'errors': [], 'hints': []})
    monkeypatch.setattr(module.subprocess, 'run',
                        lambda argv, **_: subprocess.CompletedProcess(argv, 0, '', ''))
    scaf.run()
    assert (tree(home), tree(hermes_home)) == before
    assert any('rtk init -g --agent hermes --auto-patch' in note for note in scaf.notes)
    assert all('init' not in ' '.join(argv) for argv in ran)
    assert bool(ran) is execute
