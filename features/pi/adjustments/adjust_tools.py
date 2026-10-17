"""Let each opted-in tool write its own pi project extension (ADR-0039 decision 4).

`<tool> init --agent pi` runs in the target with stdin closed and telemetry off, only when
install is enabled and the tool's check passed; otherwise the command is printed. Opt-out runs
`--uninstall` under the same gates. Never `--auto-patch`, never `-g`.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

TIMEOUT = 30
LOADED = ('{ext} loads only in a trusted project (/trust, or --approve per run); headless pi -p '
          'skips it unless trust is saved. If a global {tool} pi extension is also installed '
          '(~/.pi/agent/extensions), commands are rewritten twice')


def _catalog_init_tools(framework_root: Path) -> List[str]:
    names = []
    for meta in sorted(framework_root.glob('features/*/tools/*/meta.json')):
        try:
            data = json.loads(meta.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        if (data.get('hooks') or {}).get('pi', {}).get('mode') == 'init':
            names.append(data.get('name', meta.parent.name))
    return names


def _run(tool: str, argv: List[str], target: Path) -> str:
    """Run the tool; '' on success, otherwise the reason."""
    prefix = tool.upper().replace('-', '_')
    env = dict(os.environ, **{f'{prefix}_TELEMETRY_DISABLED': '1', f'{prefix}_ONRAMP_DISABLED': '1'})
    try:
        proc = subprocess.run([tool, *argv], cwd=str(target), env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (subprocess.SubprocessError, OSError) as exc:
        return type(exc).__name__
    return '' if proc.returncode == 0 else f'exit {proc.returncode}'


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Install wanted extensions, uninstall unwanted ones, or print the command a gate held back."""
    target = Path(context['target'])
    tools = context.get('tools') or {}
    install = bool(context.get('install'))
    notes: List[str] = []
    ran = False
    for name in dict.fromkeys([*tools, *_catalog_init_tools(Path(context['framework_root']))]):
        tool = tools.get(name) or {}
        arm = (tool.get('agents') or {}).get('pi') or {}
        ext = f'.pi/extensions/{name}.ts'
        if arm.get('mode') == 'init':
            argv = ['init', '--agent', arm.get('arg', 'pi')]
            if not (install and arm.get('run')):
                notes.append(f'run `{name} {" ".join(argv)}` in this project once install is '
                             f'enabled and {name} is on PATH')
                continue
            failure = _run(name, argv, target)
            ran = True
            notes.append(f'existing {name}.ts kept ({name} refused to replace it: {failure})'
                         if failure else LOADED.format(ext=ext, tool=name))
        elif (target / ext).exists():
            argv = ['init', '--agent', 'pi', '--uninstall']
            if not (install and tool.get('check_ok') is True):
                notes.append(f'{ext} is still installed; run `{name} {" ".join(argv)}` to remove it')
                continue
            failure = _run(name, argv, target)
            ran = True
            notes.append(f'{name} uninstall failed ({failure}); {ext} left in place'
                         if failure else f'{ext} removed')
    return {'applied': ran, 'files': [], 'notes': '; '.join(notes) or 'No tool extensions for pi'}
