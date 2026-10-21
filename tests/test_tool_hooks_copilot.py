"""Copilot owns one `.github/hooks/<tool>-rewrite.json` per opted-in tool (ADR-0039)."""
import json

import pytest

import tool_fixtures
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(name="root")
def root_fixture(tmp_path):
    """The framework root under test: the real tree with the synthetic catalog tool added.

    The `tools` feature type ships no tool of its own, so the tests bring their own.
    """
    return tool_fixtures.overlay_root(tmp_path, ROOT)
ARM = 'features/copilot/adjustments/adjust_tools.py'
COMMAND = "env AI_BADGER_TOOL=shim SHIM_TELEMETRY_DISABLED=1 sh -c 'true'"


def context(target, enabled=True):
    return {'target': target, 'target_dir': target / '.ai-badger', 'framework_root': ROOT,
            'config': {'agents': ['copilot']},
            'tools': {'shim': {'agents': {'copilot': {
                'mode': 'native', 'arg': 'copilot', 'command': COMMAND}}}} if enabled else {}}


def test_writes_the_pascal_case_shape_shim_writes(load_script, tmp_path):
    result = load_script(ARM).adjust(context(tmp_path))
    dst = tmp_path / '.github/hooks/shim-rewrite.json'
    assert json.loads(dst.read_text()) == {'version': 1, 'hooks': {'PreToolUse': [
        {'type': 'command', 'command': COMMAND, 'cwd': '.', 'timeout': 5}]}}
    assert 'matcher' not in dst.read_text() and 'preToolUse' not in dst.read_text()
    assert result['applied'] and result['files'] == ['.github/hooks/shim-rewrite.json']
    # What shim 1.0.1 emits and says, as measured live; no version floor nobody sourced.
    for fragment in ('VS Code', 'Copilot CLI', 'modifiedArgs', 'deny-with-suggestion',
                     'unverified'):
        assert fragment in result['notes']
    assert '1.0.73' not in result['notes'] and 'JetBrains' not in result['notes']


def test_idempotent(load_script, tmp_path):
    arm = load_script(ARM)
    arm.adjust(context(tmp_path))
    before = (tmp_path / '.github/hooks/shim-rewrite.json').read_bytes()
    assert arm.adjust(context(tmp_path))['files'] == ['.github/hooks/shim-rewrite.json']
    assert (tmp_path / '.github/hooks/shim-rewrite.json').read_bytes() == before
    assert sorted(p.name for p in (tmp_path / '.github/hooks').iterdir()) == ['shim-rewrite.json']


def test_unmarked_file_preserved_with_note(load_script, tmp_path):
    dst = tmp_path / '.github/hooks/shim-rewrite.json'
    dst.parent.mkdir(parents=True)
    own = '{"version":1,"hooks":{"PreToolUse":[{"type":"command","command":"shim hook copilot"}]}}'
    dst.write_text(own)
    arm = load_script(ARM)
    result = arm.adjust(context(tmp_path))
    assert not result['applied'] and 'shim-rewrite.json' in result['notes']
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
    config['tools'] = {'shim': {'hooks': ['copilot']}}
    hooks = tmp_path / '.github/hooks'
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    instructions = tmp_path / '.github/copilot-instructions.md'
    # Enabling a tool adds exactly its {{TOOLS_INSTRUCTIONS}} block (s5b) and nothing else.
    block = (root / 'features/common/tools/shim/tool.md').read_text().strip() + '\n\n'
    assert instructions.read_text().count(block) == 1
    without = {'ai-badger-hooks.json': (hooks / 'ai-badger-hooks.json').read_bytes(),
               'copilot-instructions.md': instructions.read_text().replace(block, '').encode()}
    dst = hooks / 'shim-rewrite.json'
    assert 'AI_BADGER_TOOL=shim' in dst.read_text()
    manifest = json.loads((tmp_path / '.ai-badger/manifest.json').read_text())
    assert any(entry.get('target') == '.github/hooks/shim-rewrite.json'
               for entries in manifest.values() if isinstance(entries, list)
               for entry in entries if isinstance(entry, dict))
    config['tools'] = {}
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    assert not dst.exists()
    assert {p.name: p.read_bytes() for p in (hooks / 'ai-badger-hooks.json', instructions)} == without
    config['tools'] = {'shim': {'hooks': ['copilot']}}
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    assert dst.exists()
    operator = hooks / 'other-rewrite.json'
    operator.write_text('{"hooks":{"PreToolUse":[{"command":"shim hook copilot"}]}}')
    config['agents'] = ['claude']
    build_scaffolder(module, root=root, target=tmp_path, config=config).run()
    assert not dst.exists()
    assert operator.exists()
