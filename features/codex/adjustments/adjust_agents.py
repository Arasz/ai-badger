"""Deliver native Codex TOML personas, preserving operator files."""
from __future__ import annotations

import json
import sys
from pathlib import Path
import re
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_paths import symlink_parent  # pylint: disable=wrong-import-position

import frontmatter as fm

HEADER = '# Managed by ai-badger; source: .ai-badger/agents/'


def adjust(context: dict[str, Any]) -> dict[str, Any]:
    """Emit standalone agents with parent model inheritance and safe ownership pruning."""
    if 'codex' not in context['config'].get('agents', []):
        return {'applied': False, 'files': [], 'notes': 'codex not selected'}
    directory = context['target'] / '.codex/agents'
    if symlink_parent(directory, context['target']):
        return {'applied': False, 'files': [], 'notes': 'Codex agents discovery symlink preserved'}
    directory.mkdir(parents=True, exist_ok=True)
    files, refused, selected = [], [], set()
    for persona in context.get('personas', []):
        name = persona.get('name', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
            continue
        selected.add(name + '.toml')
        dst = directory / (name + '.toml')
        if dst.is_symlink() or dst.exists() and not dst.read_text().startswith(HEADER):
            refused.append(name)
            continue
        delivered = context['target_dir'] / 'agents' / (name + '.md')
        src = delivered if delivered.is_file() else context['framework_root'] / persona['path']
        split = fm.split(src.read_text(encoding='utf-8'))
        meta = split.fields()
        values = {'name': name, 'description': meta.get('description', f'AI persona: {name}'),
                  'developer_instructions': split.body.strip()}
        if name in {'architect', 'code-reviewer', 'qa'}:
            values['sandbox_mode'] = 'read-only'
        text = HEADER + name + '.md\n' + ''.join(
            f'{key} = {json.dumps(value, ensure_ascii=False)}\n' for key, value in values.items())
        dst.write_text(text, encoding='utf-8')
        files.append(f'.codex/agents/{name}.toml')
    if context.get('prune', True):
        for dst in directory.glob('*.toml'):
            if not dst.is_symlink() and dst.name not in selected and dst.read_text().startswith(HEADER):
                dst.unlink()
    return {'applied': bool(files), 'files': files,
            'notes': f'Codex agents inherit parent model; preserved operator collisions: {refused}'}
