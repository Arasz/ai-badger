"""Propose each opted-in tool's user-wide Hermes init; never run it, never write (ADR-0039).

Hermes has no project scope, so the init always lands in `${HERMES_HOME:-~/.hermes}`.
"""
from __future__ import annotations

import os
from typing import Any, Dict

NOTE = ('`{tool} init -g --agent {arg} --auto-patch` is user-wide: it writes {home} '
        '(plugins/{tool}-rewrite and config.yaml) and enables the {tool}-rewrite plugin for every '
        'Hermes session, so ai-badger\'s gates may see {tool}-prefixed commands. Run it yourself '
        'if you want it; `{tool} init -g --agent {arg} --auto-patch --uninstall` later leaves '
        '`enabled: []` in config.yaml. ai-badger wrote nothing.')


def adjust(context: Dict[str, Any]) -> Dict[str, Any]:
    """Print the init proposal for every tool with a Hermes propose arm."""
    home = os.environ.get('HERMES_HOME') or '~/.hermes'
    notes = [NOTE.format(tool=name, arg=arm.get('arg', 'hermes'), home=home)
             for name, tool in (context.get('tools') or {}).items()
             if (arm := (tool.get('agents') or {}).get('hermes')) and arm.get('mode') == 'propose']
    if not notes:
        return {'applied': False, 'files': [], 'notes': 'No tool proposals for Hermes'}
    return {'applied': True, 'files': [], 'notes': ' '.join(notes)}
