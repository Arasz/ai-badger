"""Adapt the unchanged AWM policy to Codex hook events."""
from __future__ import annotations

import io
import json
import runpy
import shlex
import sys
from pathlib import Path

SHELL_TOOLS = {'Bash', 'exec_command', 'functions.exec_command'}
QUESTION_TOOLS = {'AskUserQuestion', 'request_user_input', 'functions.request_user_input'}


def main(source: Path) -> None:
    """Approve supported shell permission requests; defer all unrecognized input."""
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        return
    event = payload.get('hook_event_name')
    if event not in {'PreToolUse', 'PermissionRequest', 'UserPromptSubmit'}:
        return
    gate_source = source.with_name('awm_gate.py')
    gate = runpy.run_path(str(gate_source))
    if event == 'UserPromptSubmit':
        context = runpy.run_path(str(source.with_name('awm_context.py')))
        state = context['load_state']()
        found = gate['entry_for'](state, payload.get('cwd'))
        if not found:
            return
        project, entry = found
        if gate['expired'](entry):
            return
        mode = entry.get('mode', 'away')
        command = 'python3 ' + shlex.quote(str(source.parent.parent / 'scripts/awm.py'))
        text = (f'[auto-wm] {mode.upper()} MODE ACTIVE. Supported shell calls may be '
                'approved at PermissionRequest after scope, expiry and denylist checks. '
                'Other tools retain normal permissions. '
                + ('Question calls reaching PreToolUse are denied while away. '
                   if mode == 'away' else 'The user is available for questions. ')
                + f'Register significant decisions with: {command} decision "<what and why>"')
        print(json.dumps({'hookSpecificOutput': {'hookEventName': event,
                                                 'additionalContext': text}}))
        return
    tool = payload.get('tool_name')
    data = payload.get('tool_input')
    if not isinstance(data, dict):
        return
    if tool in QUESTION_TOOLS:
        if event != 'PreToolUse':
            return
        payload['tool_name'] = 'AskUserQuestion'
    elif tool in SHELL_TOOLS:
        key = 'command' if tool == 'Bash' else 'cmd'
        if not isinstance(data.get(key), str) or not data[key].strip():
            return
        directories = [data[name] for name in ('workdir', 'cwd') if name in data]
        if any(not isinstance(value, str) or not value.strip()
               or not Path(value).is_absolute() for value in directories):
            return
        if len(set(directories)) > 1:
            return
        if directories:
            payload['cwd'] = str(Path(directories[0]).resolve())
        payload['tool_name'] = 'Bash'
        payload['tool_input'] = dict(data, command=data[key])
    else:
        return
    original_log = gate['log_event']
    pending = []
    def log_event(kind, *args):
        if kind == 'auto_approve':
            pending.append((kind, *args))
        else:
            original_log(kind, *args)
    def emit(decision, reason):
        if decision == 'allow' and event == 'PermissionRequest':
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': event, 'decision': {'behavior': 'allow'}}}))
            for args in pending:
                original_log(*args)
        elif decision == 'deny' and event == 'PreToolUse' and tool in QUESTION_TOOLS:
            command = 'python3 ' + shlex.quote(str(source.parent.parent / 'scripts/awm.py'))
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': event, 'permissionDecision': 'deny',
                'permissionDecisionReason': 'AWM away mode: no user is available. '
                    f'Choose the best option and record it with {command} decision "...".'}}))
    # runpy functions retain their own globals; rebinding the returned mapping is insufficient.
    gate.update(emit=emit, log_event=log_event)
    gate['main'].__globals__.update(emit=emit, log_event=log_event)
    previous = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        gate['main']()
    finally:
        sys.stdin = previous


if __name__ == '__main__':
    try:
        main(Path(sys.argv[1]))
    except Exception:  # pylint: disable=broad-exception-caught
        # A broken adapter must defer to Codex's normal permission flow.
        pass
