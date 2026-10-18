"""rtk PreToolUse hook for Claude and Codex that keeps the host's rules on the original command.

Runs ``rtk rewrite`` and prints the rewrite only when no host rule names the command the model
asked for; otherwise prints nothing, so the host judges and runs the original. Usage:
``rtk_guard.py claude|codex`` with the hook JSON on stdin. ai-badger inlines this file into the
hook command (ADR-0039), so it must stay one stdlib-only file.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

CHAIN = {"&&", "||", ";", "|"}
ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
KEYWORDS = {"if", "then", "elif", "else", "fi", "for", "while", "until", "do", "done", "case",
            "esac", "select", "function", "{", "}", "!", "[[", "]]"}
TIMEOUT = 4


def rewrite(cmd, cwd, host=None):
    """``(exit code, rewrite)`` from ``rtk rewrite``; RTK_REWRITE_HOST is set only when asked."""
    env = {k: v for k, v in os.environ.items() if k != "RTK_REWRITE_HOST"}
    if host:
        env["RTK_REWRITE_HOST"] = host
    run = subprocess.run(["rtk", "rewrite", cmd], cwd=cwd, env=env, capture_output=True,
                         text=True, timeout=TIMEOUT, check=False)
    return run.returncode, run.stdout.strip()


def segments(cmd):
    """The argv of each command in a one-line chain of plain words, the text Codex splits itself.

    None when the text is anything else: a newline, a redirect, a subshell, a background job,
    an expansion, a glob, a leading NAME=value, control flow or an unterminated quote.
    """
    if "\n" in cmd or "\r" in cmd:
        return None
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    out, cur = [], []
    for tok in tokens:
        if tok in CHAIN:
            out.append(cur)
            cur = []
        elif set(tok) <= set("&|;<>()") or set(tok) & set("$`*?"):
            return None
        elif not cur and (ASSIGN.match(tok) or tok in KEYWORDS):
            return None
        else:
            cur.append(tok)
    out.append(cur)
    return out if all(out) else None


def only_prefixed(cmd, out):
    """True when the rewrite only puts ``rtk`` in front of whole commands of the original.

    A rewrite inside a wrapper (``bash -c``, ``env``, ``time``) changes words a per-command
    rule check never saw, so it does not count.
    """
    before, after = segments(cmd), segments(out)
    if before is None or after is None or len(before) != len(after):
        return False
    return all(a == b or a[0] == "rtk" for b, a in zip(before, after))


def codex_rule_files(cwd):
    """Rule files from $CODEX_HOME (default ~/.codex) and each .codex/ from cwd up to the git root."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
    layers = [home]
    here = Path(cwd).resolve()
    for folder in (here, *here.parents):
        if (folder / ".codex").is_dir() and folder / ".codex" != home:
            layers.append(folder / ".codex")
        if (folder / ".git").exists():
            break
    return [f for layer in layers for f in sorted((layer / "rules").glob("*.rules"))]


def codex_may_rewrite(cmd, out, cwd):
    """True when no Codex rule names any command in the original; fails closed when unknowable."""
    files = codex_rule_files(cwd)
    if not files:
        return True
    parts = segments(cmd)
    codex = shutil.which("codex")
    if parts is None or not only_prefixed(cmd, out) or not codex or not os.access(codex, os.X_OK):
        return False
    rules = [a for f in files for a in ("--rules", str(f))]
    for argv in parts:
        run = subprocess.run([codex, "execpolicy", "check", *rules, "--", *argv],
                             capture_output=True, text=True, timeout=TIMEOUT, check=False)
        if run.returncode != 0 or json.loads(run.stdout or "{}").get("matchedRules"):
            return False
    return True


def decide(host, event):
    """The hook output for *event*, or None to hand the original command to the host."""
    cmd = (event.get("tool_input") or {}).get("command") or ""
    cwd = event.get("cwd") or os.getcwd()
    code, out = rewrite(cmd, cwd)
    if code not in (0, 3) or not out or out == cmd:
        return None
    if host == "claude":
        if code == 3 and rewrite(cmd, cwd, "openclaw")[0] == 3:
            return None
        decision = "allow" if code == 0 else None
    elif host == "codex":
        if not codex_may_rewrite(cmd, out, cwd):
            return None
        decision = "allow"
    else:
        return None
    hso = {"hookEventName": "PreToolUse", "updatedInput": {**event["tool_input"], "command": out}}
    if decision:
        hso["permissionDecision"] = decision
        hso["permissionDecisionReason"] = "rtk rewrite"
    return {"hookSpecificOutput": hso}


def main():
    """Read the hook JSON on stdin and print the hook output, if any."""
    output = decide(sys.argv[1] if len(sys.argv) > 1 else "", json.load(sys.stdin))
    if output:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
