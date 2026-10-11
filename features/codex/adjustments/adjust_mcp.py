"""Merge project MCP servers through an appended owned TOML block."""
from __future__ import annotations

import json
import sys
from pathlib import Path
import shlex
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_paths import symlink_parent  # pylint: disable=wrong-import-position

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

START = '# ai-badger:mcp-start\n'
END = '# ai-badger:mcp-end\n'


def _entry(server: dict[str, Any]) -> dict[str, Any]:
    if server.get('command'):
        parts = [server['command']] if 'args' in server else shlex.split(server['command'])
        if not parts:
            raise ValueError('empty MCP command')
        entry = {'command': parts[0], 'args': parts[1:] + server.get('args', [])}
    elif server.get('url'):
        entry = {'url': server['url']}
    else:
        raise ValueError('MCP declaration needs command or url')
    for key in ('cwd', 'env', 'bearer_token_env_var', 'http_headers', 'enabled_tools', 'disabled_tools'):
        if server.get(key):
            entry[key] = server[key]
    if server.get('tools') and server['tools'] != ['*']:
        entry['enabled_tools'] = server['tools']
    return entry


def _value(value: Any) -> str:
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(k) + ' = ' + _value(v) for k, v in value.items()) + '}'
    return json.dumps(value, ensure_ascii=False)


def adjust(context: dict[str, Any]) -> dict[str, Any]:
    """Preserve unmanaged bytes and server collisions; validate before any write."""
    selected = 'codex' in context['config'].get('agents', [])
    dst = context['target'] / '.codex/config.toml'
    if symlink_parent(dst, context['target']):
        return {'applied': False, 'files': [], 'notes': 'Codex config discovery symlink preserved'}
    text = dst.read_text(encoding='utf-8') if dst.exists() else ''
    if tomllib is None:
        return {'applied': False, 'files': [], 'notes': 'Python 3.10 requires tomli for safe TOML parsing; config preserved'}
    try:
        parsed = tomllib.loads(text)
        if not all(isinstance(parsed.get(key, {}), dict) for key in ('mcp_servers', 'features')):
            raise ValueError('mcp_servers and features must be TOML tables')
        if text.count(START) != text.count(END) or text.count(START) > 1:
            raise ValueError('ambiguous managed MCP block')
        base, suffix = text, ''
        if START in text:
            base, rest = text.split(START, 1)
            _, suffix = rest.split(END, 1)
            following = next((line.strip() for line in suffix.splitlines() if line.strip() and not line.lstrip().startswith('#')), '')
            if following and not following.startswith('['):
                raise ValueError('operator suffix depends on managed TOML table context')
        existing = tomllib.loads(base + suffix).get('mcp_servers', {})
        sections = []
        declined = set(context.get('mcp_declined', []))
        declarations = context.get('mcp_declarations', {}) if selected else {}
        for name, server in sorted(declarations.items()):
            if name in declined or name in existing or server.get('scope', 'project') != 'project':
                continue
            entry = _entry(server)
            sections.append('[mcp_servers.' + json.dumps(name) + ']\n' + ''.join(
                key + ' = ' + _value(value) + '\n' for key, value in entry.items()))
        new = base
        if sections:
            new += ('' if not new or new.endswith('\n') else '\n') + START + '\n'.join(sections) + END
        new += suffix
        tomllib.loads(new)
    except (ValueError, TypeError) as exc:
        return {'applied': False, 'files': [], 'notes': f'Codex MCP config preserved: {exc}'}
    if new != text:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(new, encoding='utf-8')
    return {'applied': bool(sections or new != text), 'files': [],
            'notes': 'Project MCP declarations only; existing operator servers preserved; user-scoped declarations require operator setup'}
