"""Publish a verified subset of Codex command hooks without changing trust."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
import shlex
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_paths import symlink_parent  # pylint: disable=wrong-import-position

# Each entry names a protocol-compatible script, not an entire Claude event.
SCRIPTS = {
    'prompt-markers/scripts/user_prompt_hook.py': ('UserPromptSubmit', None),
    'git-work/scripts/git_config_health_hook.py': ('SessionStart', 'startup|resume'),
    'git-work/scripts/git_internals_guard.py': ('PreToolUse', '^Bash$'),
    'ai-raccoon-memory/scripts/memory_first_gate_hook.py': ('PreToolUse', '^Bash$'),
    'ai-raccoon-memory/scripts/memory_first_gate_post_hook.py':
        ('PostToolUse', '^(mcp__.+__)?memory_search$'),
}
PREFIX = 'env AI_BADGER_CODEX_HOOK=1 '
RUNNER = (
    "import os,pathlib,runpy,sys; "
    "root=pathlib.Path(sys.argv[1]); "
    "os.environ['AI_BADGER_PROJECT_DIR']=str(root); "
    "script=root/'.ai-badger'/sys.argv[2]; "
    "sys.exit(0) if not script.is_file() or not script.resolve().is_relative_to(root) "
    "or any(p.is_symlink() for p in (script,*script.parents) if p!=root and root in p.parents) else None; "
    "sys.exit(0) if any(p.is_symlink() for tree in (script.parent.parent,root/'.ai-badger/hooks') "
    "for p in (tree,*tree.rglob('*'))) else None; "
    "sys.path.insert(0,str(script.parent)); "
    "runpy.run_path(str(script),run_name='__main__')"
)


def _ours(handler: dict[str, Any]) -> bool:
    command = handler.get('command', '')
    return isinstance(command, str) and command.startswith(PREFIX) and any(
        script in command for script in SCRIPTS)


def _is_tool(framework_root: Path):
    """`tool_hooks.is_ours`: whether a command is a catalog tool's marked hook (ADR-0039)."""
    scripts = Path(framework_root) / 'features/common/skills/welcome-ai-badger/scripts'
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import tool_hooks  # pylint: disable=import-outside-toplevel
    return tool_hooks.is_ours


def _add(groups: list, entry: dict, is_tool) -> None:
    """Insert a framework group ahead of the first tool group, so the tool hook stays last."""
    at = next((i for i, group in enumerate(groups)
               if any(is_tool(h.get('command')) for h in group.get('hooks', []))), len(groups))
    groups.insert(at, entry)


def adjust(context: dict[str, Any]) -> dict[str, Any]:
    """Merge compatible hooks, prune owned declines, and leave malformed config untouched."""
    selected = ('codex' in context['config'].get('agents', [])
                and context['config'].get('codexScope', 'project') == 'project')
    dst = context['target'] / '.codex/hooks.json'
    if symlink_parent(dst, context['target']):
        return {'applied': False, 'files': [], 'notes': 'Codex config discovery symlink preserved'}
    try:
        existing = json.loads(dst.read_text()) if dst.exists() else {'hooks': {}}
        if not isinstance(existing, dict) or not isinstance(existing.get('hooks', {}), dict):
            raise ValueError('hooks must be an object')
        hooks = existing.setdefault('hooks', {}) if selected else existing.get('hooks', {})
        for event, groups in hooks.items():
            if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks', []), list) or any(not isinstance(h, dict) for h in g.get('hooks', [])) for g in groups):
                raise ValueError(f'invalid hook groups for {event}')
        source = context['target_dir'] / 'hooks/hooks.json'
        if not source.exists():
            source = context['framework_root'] / 'features/common/hooks/hooks.json'
        incoming = json.loads(source.read_text()).get('hooks', {}) if selected else {}
    except (ValueError, OSError, AttributeError) as exc:
        return {'applied': False, 'files': [], 'notes': f'Codex hooks preserved: {exc}'}
    for event, groups in list(hooks.items()):
        clean = []
        for group in groups:
            handlers = [h for h in group.get('hooks', []) if not _ours(h)]
            if handlers or not group.get('hooks'):
                clean.append(group if handlers == group.get('hooks', []) else dict(group, hooks=handlers))
        hooks[event] = clean
    declined = set(context['config'].get('exclude', {}).get('skills', []))
    is_tool = _is_tool(context['framework_root'])
    gate_adapter = context['target_dir'] / 'hooks/codex_memory_first_gate_post_hook.py'
    pre_gate_adapter = context['target_dir'] / 'hooks/codex_memory_first_gate_hook.py'
    if selected and 'ai-raccoon-memory/scripts/memory_first_gate_post_hook.py' in SCRIPTS:
        adapter_source = (context['framework_root'] /
                          'features/codex/adjustments/memory_first_gate_post_hook.py')
        if adapter_source.is_file():
            gate_adapter.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_source, gate_adapter)
    if selected and 'ai-raccoon-memory/scripts/memory_first_gate_hook.py' in SCRIPTS:
        adapter_source = (context['framework_root'] /
                          'features/codex/adjustments/memory_first_gate_codex_hook.py')
        if adapter_source.is_file():
            pre_gate_adapter.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adapter_source, pre_gate_adapter)
    for script, (event, matcher) in (SCRIPTS.items() if selected else []):
        if script.split('/', maxsplit=1)[0] in declined:
            continue
        is_credit_observer = script.endswith('memory_first_gate_post_hook.py')
        is_memory_gate = script.endswith('memory_first_gate_hook.py')
        path = (gate_adapter if is_credit_observer else pre_gate_adapter if is_memory_gate
                else context['target_dir'] / 'skills' / script)
        if not path.is_file():
            continue
        for group in incoming.get(event, []):
            handler = next((h for h in group.get('hooks', []) if script in h.get('command', '')), None)
            if handler is None:
                continue
            path_argument = ('hooks/codex_memory_first_gate_post_hook.py'
                             if is_credit_observer else 'hooks/codex_memory_first_gate_hook.py'
                             if is_memory_gate else f'skills/{script}')
            command = (PREFIX + 'python3 -I -c ' + shlex.quote(RUNNER) + ' '
                       + shlex.quote(str(context['target'].resolve())) + ' '
                       + shlex.quote(path_argument))
            if is_credit_observer:
                shared_path = context['target_dir'] / 'skills' / script
                command += ' ' + shlex.quote(str(shared_path.resolve()))
            elif is_memory_gate:
                shared_path = context['target_dir'] / 'skills' / script
                command += ' ' + shlex.quote(str(shared_path.resolve()))
            delivered = {'type': 'command', 'command': command}
            if 'timeout' in handler:
                delivered['timeout'] = handler['timeout']
            entry = {'hooks': [delivered]}
            if matcher:
                entry['matcher'] = matcher
            _add(hooks.setdefault(event, []), entry, is_tool)
            break
    new = json.dumps(existing, indent=2) + '\n'
    if not dst.exists() and not any(hooks.values()):
        return {'applied': False, 'files': [], 'notes': 'No compatible hooks delivered'}
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not selected and existing == json.loads(dst.read_text()):
        return {'applied': False, 'files': [], 'notes': 'No owned hooks to remove'}
    if not dst.exists() or dst.read_text() != new:
        dst.write_text(new, encoding='utf-8')
    return {'applied': True, 'files': [],
            'notes': 'Codex hooks require project trust and /hooks review; prompt markers, Git health, Bash Git storage guard, memory-first PreToolUse gate, and its PostToolUse memory-search credit observer are wired; unsupported hooks remain unported'}
