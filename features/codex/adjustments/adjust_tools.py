"""Merge each opted-in tool's marked PreToolUse entry into .codex/hooks.json (ADR-0039)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_paths import symlink_parent  # pylint: disable=wrong-import-position

EVENT = 'PreToolUse'
PROPOSAL = ('{tool} is not wired for Codex: its hook answers permissionDecision allow, so a '
            'rewritten command skips the Codex approval prompt and its safe/dangerous classifiers. '
            'Wire it yourself with `{tool} init --{arg}` only if that approval does not matter.')
NOTE = ('Codex tool hooks need project trust and /hooks approval; rtk-wrapped commands are '
        'auto-allowed (permissionDecision allow) and bypass the Codex approval prompt and its '
        'safe/dangerous classifiers; optional: if rtk history fails with SQLITE_CANTOPEN in the '
        'workspace-write sandbox, add rtk\'s data directory (~/Library/Application Support/rtk '
        'on macOS, ~/.local/share/rtk on Linux) to [sandbox_workspace_write] writable_roots in '
        'config.toml yourself; config.toml is not changed')


def _scripts(framework_root: Path) -> None:
    scripts = framework_root / 'features/common/skills/welcome-ai-badger/scripts'
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))


def _load(dst: Path) -> dict[str, Any]:
    existing = json.loads(dst.read_text(encoding='utf-8')) if dst.exists() else {'hooks': {}}
    if not isinstance(existing, dict) or not isinstance(existing.get('hooks', {}), dict):
        raise ValueError('hooks must be an object')
    for event, groups in existing.get('hooks', {}).items():
        if not isinstance(groups, list) or any(
                not isinstance(g, dict) or not isinstance(g.get('hooks', []), list)
                or any(not isinstance(h, dict) for h in g.get('hooks', [])) for g in groups):
            raise ValueError(f'invalid hook groups for {event}')
    return existing


def _entry(command: str) -> dict[str, Any]:
    return {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]}


def _merge(hooks: dict[str, Any], wanted: list[dict[str, Any]], is_ours) -> None:
    """Drop every marked entry, then append the wanted ones last.

    Last, so the rewriter never sits ahead of a guard; the hooks adjustment inserts its groups
    ahead of a marked group, so a rerun yields the same bytes. The tool's event keeps its key.
    """
    for event, groups in list(hooks.items()):
        clean = []
        for group in groups:
            handlers = [h for h in group.get('hooks', []) if not is_ours(h.get('command'))]
            if handlers or not group.get('hooks'):
                clean.append(group if handlers == group.get('hooks', []) else dict(group, hooks=handlers))
        if clean or not groups or (event == EVENT and wanted):
            hooks[event] = clean
        else:
            del hooks[event]
    if wanted:
        hooks.setdefault(EVENT, []).extend(wanted)


def adjust(context: dict[str, Any]) -> dict[str, Any]:
    """Add one marked entry per native Codex arm, remove the rest, and note each proposal."""
    result = _wire(context)
    proposals = [PROPOSAL.format(tool=name, arg=arm.get('arg', 'codex'))
                 for name, tool in (context.get('tools') or {}).items()
                 if (arm := (tool.get('agents') or {}).get('codex')) and arm.get('mode') == 'propose']
    if proposals:
        result['notes'] = '; '.join([result['notes'], *proposals])
    return result


def _wire(context: dict[str, Any]) -> dict[str, Any]:
    _scripts(Path(context['framework_root']))
    import config_guard  # pylint: disable=import-outside-toplevel
    from tool_hooks import is_ours  # pylint: disable=import-outside-toplevel

    dst = context['target'] / '.codex/hooks.json'
    if symlink_parent(dst, context['target']):
        return {'applied': False, 'files': [], 'notes': 'Codex config discovery symlink preserved'}
    commands = [arm['command'] for tool in context.get('tools', {}).values()
                if (arm := tool.get('agents', {}).get('codex')) and arm.get('mode') == 'native']
    try:
        existing = _load(dst)
    except (ValueError, OSError) as exc:
        return {'applied': False, 'files': [], 'notes': f'Codex hooks preserved: {exc}'}
    if not dst.exists() and not commands:
        return {'applied': False, 'files': [], 'notes': 'No tool hooks for Codex'}
    hooks = existing.setdefault('hooks', {})
    before = json.dumps(existing)
    _merge(hooks, [_entry(command) for command in commands], is_ours)
    if json.dumps(existing) == before:
        return {'applied': bool(commands), 'files': [], 'notes': NOTE if commands else 'No tool hooks for Codex'}
    config_guard.write_json_with_backup(dst, existing)
    return {'applied': True, 'files': [], 'notes': NOTE if commands else 'Codex tool hooks removed'}
