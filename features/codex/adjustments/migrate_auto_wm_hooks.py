"""Explicitly retire legacy Codex AWM hooks after native plugin installation."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path


def legacy(command: object) -> bool:
    """Recognize only a direct Python invocation of a known legacy AWM hook."""
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if len(words) != 2 or not re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(words[0]).name):
        return False
    path = words[1]
    roots = ('~/.claude/skills/auto-wm/hooks/',
             str(Path.home() / '.claude/skills/auto-wm/hooks') + '/')
    return any(path == root + name for root in roots
               for name in ('awm_gate.py', 'awm_context.py'))


def migrate(config: Path, plugin_root: Path) -> bool:
    """Back up and remove recognized handlers only when replacement assets are usable."""
    plugin = json.loads((plugin_root / '.codex-plugin/plugin.json').read_text())
    if plugin.get('hooks') != './hooks/codex-hooks.json':
        raise ValueError('native AWM hook manifest is not registered')
    manifest = json.loads((plugin_root / 'hooks/codex-hooks.json').read_text())
    for event, source in (('PreToolUse', 'awm_gate.py'),
                          ('PermissionRequest', 'awm_gate.py'),
                          ('UserPromptSubmit', 'awm_context.py')):
        expected = ('python3 "${PLUGIN_ROOT}/features/codex/adjustments/auto_wm_hook.py" '
                    f'"${{PLUGIN_ROOT}}/skills/auto-wm/hooks/{source}"')
        if not any(h.get('command') == expected for group in manifest['hooks'].get(event, [])
                   for h in group.get('hooks', [])):
            raise ValueError(f'missing native AWM {event} hook')
    for relative in ('features/codex/adjustments/auto_wm_hook.py',
                     'skills/auto-wm/hooks/awm_gate.py', 'skills/auto-wm/hooks/awm_context.py',
                     'skills/auto-wm/hooks/shell_parser.py', 'skills/auto-wm/scripts/badger_store.py',
                     'skills/auto-wm/scripts/awm.py'):
        if not (plugin_root / relative).is_file():
            raise ValueError(f'missing replacement asset: {relative}')
    original = config.read_text()
    document = json.loads(original)
    changed = False
    for event, groups in document.get('hooks', {}).items():
        retained = []
        for group in groups:
            handlers = group.get('hooks', [])
            cleaned = [handler for handler in handlers if not legacy(handler.get('command'))]
            changed |= cleaned != handlers
            if cleaned or not handlers:
                retained.append(dict(group, hooks=cleaned) if cleaned != handlers else group)
        document['hooks'][event] = retained
    if not changed:
        return False
    backup = config.with_name(config.name + '.auto-wm.bak')
    # Never replace a previous migration's recovery copy.
    with backup.open('x', encoding='utf-8') as stream:
        stream.write(original)
    config.write_text(json.dumps(document, indent=2) + '\n')
    return True


def main() -> None:
    """Run only when explicitly requested by an operator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-root', required=True, type=Path)
    parser.add_argument('--config', type=Path, default=Path.home() / '.codex/hooks.json')
    args = parser.parse_args()
    print(json.dumps({'changed': migrate(args.config, args.plugin_root)}))


if __name__ == '__main__':
    main()
