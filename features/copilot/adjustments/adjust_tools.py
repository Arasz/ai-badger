"""Own one `.github/hooks/<tool>-rewrite.json` per opted-in tool (ADR-0039).

The file carries the PascalCase `PreToolUse` shape `rtk init --copilot` writes, with the
guarded command in place of the bare `rtk hook copilot`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HOOKS = '.github/hooks'
NOTE = ('{files}: rtk answers VS Code Copilot Chat with updatedInput and Copilot CLI with '
        'modifiedArgs (a rewrite), though its own install text calls Copilot CLI '
        'deny-with-suggestion; live Copilot behaviour is unverified')


def _modules(framework_root: Path):
    scripts = framework_root / 'features/common/skills/welcome-ai-badger/scripts'
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import config_guard  # pylint: disable=import-outside-toplevel
    import tool_hooks  # pylint: disable=import-outside-toplevel
    return config_guard, tool_hooks


def _marked(path: Path, is_ours) -> bool:
    """True when every PreToolUse handler in *path* carries the tool marker."""
    try:
        handlers = json.loads(path.read_text(encoding='utf-8'))['hooks']['PreToolUse']
        return bool(handlers) and all(is_ours(h.get('command')) for h in handlers)
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        return False


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Write each wanted tool file, refuse unmarked ones, delete marked files nobody wants."""
    config_guard, tool_hooks = _modules(Path(context['framework_root']))
    target = Path(context['target'])
    hooks = target / HOOKS
    wanted = {f'{name}-rewrite.json': arm['command']
              for name, tool in (context.get('tools') or {}).items()
              if (arm := (tool.get('agents') or {}).get('copilot')) and arm.get('mode') == 'native'}
    files: List[str] = []
    notes: List[str] = []
    changed = False
    for name, command in wanted.items():
        dst = hooks / name
        if dst.exists() and not _marked(dst, tool_hooks.is_ours):
            notes.append(f'{HOOKS}/{name} exists and was not written by ai-badger — left as is')
            continue
        data = {'version': 1, 'hooks': {'PreToolUse': [
            {'type': 'command', 'command': command, 'cwd': '.', 'timeout': 5}]}}
        changed |= config_guard.write_json_with_backup(dst, data)
        files.append(f'{HOOKS}/{name}')
    for stale in sorted(hooks.glob('*-rewrite.json')) if hooks.is_dir() else []:
        if stale.name not in wanted and _marked(stale, tool_hooks.is_ours):
            stale.unlink()
            changed = True
            notes.append(f'{HOOKS}/{stale.name} removed')
    if files:
        notes.insert(0, NOTE.format(files=', '.join(files)))
    return {'applied': bool(files) or changed, 'files': files,
            'notes': '; '.join(notes) or 'No tool hooks for Copilot'}
