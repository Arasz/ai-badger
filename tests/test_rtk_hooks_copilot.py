"""Copilot owns one `.github/hooks/<tool>-rewrite.json` per opted-in tool (ADR-0039)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARM = 'features/copilot/adjustments/adjust_tools.py'
COMMAND = "env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c 'true'"


def context(target, enabled=True):
    return {'target': target, 'target_dir': target / '.ai-badger', 'framework_root': ROOT,
            'config': {'agents': ['copilot']},
            'tools': {'rtk': {'agents': {'copilot': {
                'mode': 'native', 'arg': 'copilot', 'command': COMMAND}}}} if enabled else {}}


def test_writes_the_pascal_case_shape_rtk_writes(load_script, tmp_path):
    result = load_script(ARM).adjust(context(tmp_path))
    dst = tmp_path / '.github/hooks/rtk-rewrite.json'
    assert json.loads(dst.read_text()) == {'version': 1, 'hooks': {'PreToolUse': [
        {'type': 'command', 'command': COMMAND, 'cwd': '.', 'timeout': 5}]}}
    assert 'matcher' not in dst.read_text() and 'preToolUse' not in dst.read_text()
    assert result['applied'] and result['files'] == ['.github/hooks/rtk-rewrite.json']
    for fragment in ('VS Code', 'Copilot CLI', '1.0.73', 'transparent', 'JetBrains',
                     'deny-with-suggestion'):
        assert fragment in result['notes']


def test_idempotent(load_script, tmp_path):
    arm = load_script(ARM)
    arm.adjust(context(tmp_path))
    before = (tmp_path / '.github/hooks/rtk-rewrite.json').read_bytes()
    assert arm.adjust(context(tmp_path))['files'] == ['.github/hooks/rtk-rewrite.json']
    assert (tmp_path / '.github/hooks/rtk-rewrite.json').read_bytes() == before
    assert sorted(p.name for p in (tmp_path / '.github/hooks').iterdir()) == ['rtk-rewrite.json']


def test_unmarked_file_preserved_with_note(load_script, tmp_path):
    dst = tmp_path / '.github/hooks/rtk-rewrite.json'
    dst.parent.mkdir(parents=True)
    own = '{"version":1,"hooks":{"PreToolUse":[{"type":"command","command":"rtk hook copilot"}]}}'
    dst.write_text(own)
    arm = load_script(ARM)
    result = arm.adjust(context(tmp_path))
    assert not result['applied'] and 'rtk-rewrite.json' in result['notes']
    assert dst.read_text() == own
    arm.adjust(context(tmp_path, enabled=False))
    assert dst.read_text() == own


def test_opt_out_deletes_only_marked_files(load_script, tmp_path):
    arm = load_script(ARM)
    hooks = tmp_path / '.github/hooks'
    hooks.mkdir(parents=True)
    (hooks / 'ai-badger-hooks.json').write_text('{"version":1}')
    (hooks / 'other-rewrite.json').write_text('{"hooks":{"PreToolUse":[{"command":"other"}]}}')
    arm.adjust(context(tmp_path))
    assert arm.adjust(context(tmp_path, enabled=False))['applied']
    assert sorted(p.name for p in hooks.iterdir()) == ['ai-badger-hooks.json', 'other-rewrite.json']


def test_scaffold_records_generated_file_and_cleans_on_deselection(load_script, root, tmp_path,
                                                                  monkeypatch):
    import badger_lib as bl
    from scaffold_helpers import _config, build_scaffolder
    index = load_script('tooling/index_build.py').build_index(root)
    monkeypatch.setattr(bl, 'read_index', lambda _: index)
    module = load_script('features/common/skills/welcome-ai-badger/scripts/scaffold.py')
    config = _config(stacks=['python'], agents=['copilot'])
    config['tools'] = {'rtk': {'hooks': ['copilot']}}
    hooks = tmp_path / '.github/hooks'
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    instructions = tmp_path / '.github/copilot-instructions.md'
    # Enabling a tool adds exactly its {{TOOLS_INSTRUCTIONS}} block (s5b) and nothing else.
    block = (root / 'features/common/tools/rtk/tool.md').read_text().strip() + '\n\n'
    assert instructions.read_text().count(block) == 1
    without = {'ai-badger-hooks.json': (hooks / 'ai-badger-hooks.json').read_bytes(),
               'copilot-instructions.md': instructions.read_text().replace(block, '').encode()}
    dst = hooks / 'rtk-rewrite.json'
    assert 'AI_BADGER_TOOL=rtk' in dst.read_text()
    manifest = json.loads((tmp_path / '.ai-badger/manifest.json').read_text())
    assert any(entry.get('target') == '.github/hooks/rtk-rewrite.json'
               for entries in manifest.values() if isinstance(entries, list)
               for entry in entries if isinstance(entry, dict))
    config['tools'] = {}
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    assert not dst.exists()
    assert {p.name: p.read_bytes() for p in (hooks / 'ai-badger-hooks.json', instructions)} == without
    config['tools'] = {'rtk': {'hooks': ['copilot']}}
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    assert dst.exists()
    operator = hooks / 'other-rewrite.json'
    operator.write_text('{"hooks":{"PreToolUse":[{"command":"rtk hook copilot"}]}}')
    config['agents'] = ['claude']
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    assert not dst.exists()
    assert operator.exists()
