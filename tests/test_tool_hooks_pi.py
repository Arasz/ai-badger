"""pi lets shim write its own project extension, behind the install and check gates (ADR-0039)."""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
import json
import stat
import subprocess
from pathlib import Path

import pytest

import tool_fixtures

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(name="root")
def root_fixture(tmp_path):
    """The framework root under test: the real tree with the synthetic catalog tool added.

    The `tools` feature type ships no tool of its own, so the tests bring their own.
    """
    return tool_fixtures.overlay_root(tmp_path, ROOT)
ARM = 'features/pi/adjustments/adjust_tools.py'
STUB = '''#!/bin/sh
log="$STUB_LOG"
{ printf 'argv=%s\\n' "$*"; printf 'cwd=%s\\n' "$(pwd -P)"
  printf 'telemetry=%s\\n' "$SHIM_TELEMETRY_DISABLED"; printf 'onramp=%s\\n' "$SHIM_ONRAMP_DISABLED"
  if [ -t 0 ]; then printf 'stdin=tty\\n'; else printf 'stdin=%s\\n' "$(cat | wc -c | tr -d ' ')"; fi
} >> "$log"
exit "${STUB_EXIT:-0}"
'''


@pytest.fixture
def stub(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    shim = bin_dir / 'shim'
    shim.write_text(STUB)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / 'stub.log'
    monkeypatch.setenv('PATH', f'{bin_dir}:/usr/bin:/bin')
    monkeypatch.setenv('STUB_LOG', str(log))
    monkeypatch.delenv('SHIM_TELEMETRY_DISABLED', raising=False)
    monkeypatch.delenv('SHIM_ONRAMP_DISABLED', raising=False)
    return log


def context(target, framework_root, *, enabled=True, run=True, install=True, check_ok=True):
    tool = {'meta': {'name': 'shim'}, 'check_ok': check_ok,
            'agents': {'pi': {'mode': 'init', 'arg': 'pi', 'run': run}} if enabled else {}}
    return {'target': target, 'target_dir': target / '.ai-badger', 'framework_root': framework_root,
            'config': {'agents': ['pi']}, 'install': install, 'tools': {'shim': tool}}


def calls(log):
    return log.read_text().split('argv=')[1:] if log.exists() else []


@pytest.fixture
def project(tmp_path):
    path = tmp_path / 'proj'
    path.mkdir()
    return path


def test_init_runs_in_target_with_telemetry_off_and_no_stdin(load_script, project, stub,
                                                             monkeypatch, root):
    arm = load_script(ARM)
    seen = []
    real = subprocess.run
    monkeypatch.setattr(arm.subprocess, 'run', lambda *a, **k: seen.append(k) or real(*a, **k))  # pylint: disable=subprocess-run-check
    result = arm.adjust(context(project, root))
    assert calls(stub) == [f'init --agent pi\ncwd={project.resolve()}\ntelemetry=1\nonramp=1\nstdin=0\n']
    assert seen[0]['timeout'] == 30 and seen[0]['stdin'] is subprocess.DEVNULL
    note = result['notes']
    assert result['applied'] and result['files'] == []
    for fragment in ('trusted project', '/trust', '--approve', 'pi -p', 'global', 'twice'):
        assert fragment in note


@pytest.mark.parametrize('gate', [{'install': False}, {'run': False, 'check_ok': None},
                                  {'run': False, 'check_ok': False}])
def test_gates_print_a_note_instead(load_script, project, stub, root, gate):
    result = load_script(ARM).adjust(context(project, root, **gate))
    assert calls(stub) == []
    assert 'shim init --agent pi' in result['notes']


def test_refused_init_keeps_existing_extension(load_script, project, stub, monkeypatch, root):
    ext = project / '.pi/extensions/shim.ts'
    ext.parent.mkdir(parents=True)
    ext.write_text('// mine\n')
    monkeypatch.setenv('STUB_EXIT', '1')
    result = load_script(ARM).adjust(context(project, root))
    assert len(calls(stub)) == 1
    assert 'existing shim.ts kept' in result['notes']
    assert ext.read_text() == '// mine\n'


def test_opt_out_uninstalls_under_the_same_gates(load_script, project, stub, root):
    ext = project / '.pi/extensions/shim.ts'
    ext.parent.mkdir(parents=True)
    ext.write_text('// SHIM Pi extension\n')
    arm = load_script(ARM)
    assert arm.adjust(context(project, root, enabled=False))['applied']
    assert [c.split('\n')[0] for c in calls(stub)] == ['init --agent pi --uninstall']
    for gate in ({'install': False}, {'check_ok': None}):
        note = arm.adjust(context(project, root, enabled=False, **gate))['notes']
        assert 'shim init --agent pi --uninstall' in note
    assert len(calls(stub)) == 1


def test_opt_out_after_tool_removed_prints_uninstall(load_script, project, stub, root):
    ext = project / '.pi/extensions/shim.ts'
    ext.parent.mkdir(parents=True)
    ext.write_text('// SHIM Pi extension\n')
    ctx = context(project, root)
    ctx['tools'] = {}
    assert 'shim init --agent pi --uninstall' in load_script(ARM).adjust(ctx)['notes']
    assert calls(stub) == []


def test_nothing_to_do_without_arm_or_extension(load_script, project, stub, root):
    result = load_script(ARM).adjust(context(project, root, enabled=False))
    assert not result['applied'] and calls(stub) == []


def test_registered_with_cleanup_on_deselection():
    adjustments = json.loads((ROOT / 'features/pi/adjustments/adjustment.json').read_text())
    entry = next(a for a in adjustments['adjustments'] if a['feature'] == 'tools')
    assert entry == {'feature': 'tools', 'description': entry['description'],
                     'script': 'adjust_tools.py', 'cleanupOnDeselection': True}


def test_scaffold_without_install_notes_and_never_runs(load_script, root, tmp_path, stub,
                                                      monkeypatch):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    target = tmp_path / 'proj'
    target.mkdir()
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=['pi'])
    config['tools'] = {'shim': {'hooks': ['pi']}}
    scaf = build_scaffolder(module, root=root, target=target, config=config, install=False)
    scaf.run()
    assert calls(stub) == []
    assert any("adjustment 'tools' for 'pi'" in n and 'shim init --agent pi' in n
               for n in scaf.notes)
    assert not (target / '.pi/extensions/shim.ts').exists()
