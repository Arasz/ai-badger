#!/usr/bin/env python3
"""call-behaviorist CLI: switch ai-badger's own debug audit log on and off.

  behaviorist.py on [DURATION] [--project]   enable (user-wide by default)
  behaviorist.py off                          disable
  behaviorist.py status                       mode, scope, remaining, log size
  behaviorist.py tail [N]                     last N records
  behaviorist.py clear                        truncate the log

Debug is user-scoped by default: every project logs. `--project` narrows it to the current
working directory. See docs/design/debug-mode-and-call-behaviorist.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import debug_log as dl  # pylint: disable=import-error
except ImportError:  # pragma: no cover - vendored copy is missing
    print("call-behaviorist: debug_log.py not found beside this script", file=sys.stderr)
    raise

DEFAULT_DURATION = "4h"
DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")
MAX_DURATION_SECONDS = 24 * 3600

# The component this tool logs its own lifecycle under. Those records are bookkeeping,
# never evidence about a hook.
TOOL_COMPONENT = "call-behaviorist"


def parse_duration(text: str) -> int:
    """'4h', '90m', '1h30m', or a bare number of hours -> seconds."""
    text = text.strip().lower()
    if text.isdigit():
        seconds = int(text) * 3600
    else:
        match = DURATION_RE.match(text)
        if not match or (match.group(1) is None and match.group(2) is None):
            raise ValueError(f"cannot parse duration {text!r} (use 4h, 90m, 1h30m)")
        seconds = int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return min(seconds, MAX_DURATION_SECONDS)


def cmd_on(duration: str, project_scoped: bool) -> int:
    seconds = parse_duration(duration)
    expires = dl.now() + timedelta(seconds=seconds)
    state = {
        "enabled": True,
        "scope": dl.SCOPE_PROJECT if project_scoped else dl.SCOPE_USER,
        "project": str(Path.cwd()) if project_scoped else None,
        "enabled_at": dl.iso(dl.now()),
        "expires_at": dl.iso(expires),
    }
    dl.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    dl.STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    # pylint: disable=protected-access
    dl._own_only(dl.DEBUG_DIR)
    dl._own_only(dl.STATE_FILE)
    where = state["project"] if project_scoped else "every project"
    print(f"debug logging ON for {where}, expires {state['expires_at']}")
    print(f"records: {dl.AUDIT_FILE}")
    dl.log_event(TOOL_COMPONENT, "enabled", project=state["project"], scope=state["scope"])
    return 0


def cmd_off() -> int:
    if not dl.STATE_FILE.exists():
        print("debug logging is already off.")
        return 0
    dl.log_event(TOOL_COMPONENT, "disabled")
    dl.STATE_FILE.write_text(json.dumps({"enabled": False}, indent=2) + "\n", encoding="utf-8")
    print("debug logging OFF.")
    return 0


def _line_count() -> int:
    try:
        return sum(1 for _ in dl.AUDIT_FILE.open("r", encoding="utf-8"))
    except OSError:
        return 0


def cmd_status() -> int:
    state = dl._state()  # pylint: disable=protected-access
    if state is None:
        print("debug logging: OFF")
    else:
        scope = state.get("scope", dl.SCOPE_USER)
        target = state.get("project") or "every project"
        print(f"debug logging: ON ({scope} — {target})")
        print(f"expires: {state.get('expires_at', 'never')}")
    print(f"records: {_line_count()} in {dl.AUDIT_FILE}")
    return 0


def cmd_tail(count: int) -> int:
    if not dl.AUDIT_FILE.exists():
        print("no records yet.")
        return 0
    lines = dl.AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-count:]
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        fixed = (dl.KEY_TS, dl.KEY_COMPONENT, dl.KEY_EVENT, dl.KEY_VERSION)
        extra = " ".join(f"{dl.KEY_NAMES.get(k, k)}={v}" for k, v in rec.items()
                         if k not in fixed)
        print(f"{rec[dl.KEY_TS]}  {rec[dl.KEY_COMPONENT]:<40} {rec[dl.KEY_EVENT]:<8} "
              f"v{rec[dl.KEY_VERSION]}  {extra}")
    return 0


ENABLE_HINT = ("nothing observed yet — run `behaviorist.py on 4h`, work normally, "
               "then analyze again")


def _read_records(project=None):
    """Every parseable record, optionally narrowed to one project."""
    try:
        lines = dl.AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if project and rec.get(dl.KEY_PROJECT) not in (None, project):
            continue
        records.append(rec)
    return records


def _evidence(records) -> list:
    """Records that say something about a hook.

    The tool's own `enabled`/`disabled`/`cleared` lines are bookkeeping: they prove the log
    exists, never that anything was observed.
    """
    return [r for r in records if r.get(dl.KEY_COMPONENT) != TOOL_COMPONENT]


SCRIPT_RE = re.compile(r'([^\s"\']+/)?([A-Za-z0-9_\-]+)\.py')
PROJECT_DIR_VARS = ("${CLAUDE_PROJECT_DIR}", "$CLAUDE_PROJECT_DIR")

# Read in order; a script registered in more than one of them is still one component.
# The first two are what Claude Code actually runs. The third is ai-badger's own declaration
# and the only project-level record where hooks register elsewhere (Hermes, Copilot).
HOOK_SOURCES = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".ai-badger/hooks/hooks.json",
)


def _script_path(project, command):
    """(project-relative name, absolute path) for the script a hook command runs, or None."""
    match = SCRIPT_RE.search(command)
    if not match:
        return None
    raw = (match.group(1) or "") + match.group(2) + ".py"
    for var in PROJECT_DIR_VARS:
        raw = raw.replace(var, str(project))
    path = Path(raw)
    if not path.is_absolute():
        path = Path(project) / path
    try:
        name = path.resolve().relative_to(Path(project).resolve()).as_posix()
    except (OSError, ValueError):
        name = raw
    return name, path


def _wired_hooks(project) -> dict:
    """project-relative script path -> absolute path, for every registered hook.

    Keyed by path, not filename: two skills can ship the same hook filename, and collapsing
    them hides one's silence behind the other's excuse.
    """
    found = {}
    for source in HOOK_SOURCES:
        try:
            data = json.loads((Path(project) / source).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entries in (data.get("hooks") or {}).values():
            for entry in entries or []:
                for hook in entry.get("hooks") or []:
                    script = _script_path(project, hook.get("command", ""))
                    if script:
                        found.setdefault(script[0], script[1])
    return found


def expected_components(project) -> list:
    """Components a registered project should produce records for.

    Derived from what is actually registered. A component absent from here is not judged; one
    present here and silent is the finding this tool exists for.
    """
    return sorted(_wired_hooks(project))


def is_instrumented(script_path) -> bool:
    """True when the script actually calls the debug logger.

    A wired hook with no logging call *cannot* produce records, so its silence says nothing
    about health. Reporting that as a failure would make the whole report untrustworthy.
    """
    try:
        return "debug_log" in Path(script_path).read_text(encoding="utf-8")
    except OSError:
        return False


DECLARED_COMPONENT = re.compile(r"""^COMPONENT\s*=\s*["']([^"']+)["']""", re.MULTILINE)


def _component_stem(expected: str) -> str:
    """The name a wired script logs under: its filename stem, or the name as given."""
    return expected[:-len(".py")].rsplit("/", 1)[-1] if expected.endswith(".py") else expected


def declared_component(script_path) -> str:
    """The name the script logs under, read from its `COMPONENT = "..."`, or empty.

    A filename is not an identity: `prompt-markers/…/user_prompt_hook.py` logs as
    `prompt_markers_hook`, and matching on the stem reports a live hook as never observed.
    """
    try:
        found = DECLARED_COMPONENT.search(Path(script_path).read_text(encoding="utf-8"))
    except OSError:
        return ""
    return found.group(1) if found else ""


def _component_key(expected: str, script_path=None) -> str:
    """What `expected` is expected to log under — its declared name, else its filename stem."""
    return (declared_component(script_path) if script_path else "") or _component_stem(expected)


def _matches(key: str, component: str) -> bool:
    """True when `component` is `key`, or `key` qualified by a phase.

    Observed names may be phase-qualified (`session_start_hook/drift`). Matching is on the
    whole key, not a prefix fragment, so `hooks/alpha` never satisfies `hooks/never`.
    """
    return component == key or component.startswith(key + "/")


def _observed(records) -> dict:
    """component -> {count, events, versions}."""
    seen = {}
    for rec in records:
        name = rec.get(dl.KEY_COMPONENT)
        if not name:
            continue
        entry = seen.setdefault(name, {"count": 0, "events": {}, "versions": []})
        entry["count"] += 1
        event = rec.get(dl.KEY_EVENT, "?")
        entry["events"][event] = entry["events"].get(event, 0) + 1
        version = rec.get(dl.KEY_VERSION)
        if version and version not in entry["versions"]:
            entry["versions"].append(version)
    return seen


def _finding(kind, component, severity, detail, **extra):
    finding = {"kind": kind, "component": component, "severity": severity, "detail": detail}
    finding.update(extra)
    return finding


def analyze(project, expected=None) -> dict:
    """Compare what a project should do against what it was observed doing."""
    wired = _wired_hooks(project) if expected is None else {}
    expected = list(expected if expected is not None else sorted(wired))
    records = _evidence(_read_records(project))
    observed = _observed(records)
    keys = {name: _component_key(name, wired.get(name)) for name in expected}
    findings = []
    for name in expected:
        if any(_matches(keys[name], seen) for seen in observed):
            continue
        script = wired.get(name)
        if script and not is_instrumented(script):
            findings.append(_finding(
                "not_instrumented", name, "low",
                "wired but calls no debug logger, so it cannot produce records — "
                "its silence says nothing about health",
            ))
        elif records:
            # Vacuous without evidence: with nothing observed, everything is trivially silent.
            findings.append(_finding(
                "never_observed", name, "high",
                "wired and instrumented, but produced no record — "
                "it may never load or never fire",
            ))
    for name, entry in sorted(observed.items()):
        if expected and not any(_matches(key, name) for key in keys.values()):
            findings.append(_finding(
                "unexpected_component", name, "low",
                "produced records but is not among the components this project wires",
            ))
        # The sentinel means "no VERSION found above the code that ran" — an absent number,
        # not a second one. Counting it as a version manufactures skew wherever a scaffolded
        # project's records land in the log.
        versions = [v for v in entry["versions"] if v != dl.VERSION_UNKNOWN]
        if len(versions) > 1:
            findings.append(_finding(
                "version_skew", name, "high",
                "ran at more than one framework version — copies disagree "
                "(plugin cache vs .ai-badger/ scaffold)",
                versions=sorted(versions),
            ))
        starts = entry["events"].get("start", 0)
        skips = entry["events"].get("skip", 0)
        if starts and skips >= starts:
            findings.append(_finding(
                "always_skipped", name, "medium",
                f"fired {starts} time(s) and exited early every time — live but doing nothing",
                starts=starts, skips=skips,
            ))

    if not records:
        health = "unknown"
    elif any(f["severity"] == "high" for f in findings):
        health = "degraded"
    elif findings:
        health = "warn"
    else:
        health = "ok"

    stamps = [r.get(dl.KEY_TS) for r in records if r.get(dl.KEY_TS)]
    return {
        "project": project,
        "health": health,
        "window": {
            "records": len(records),
            "from": min(stamps) if stamps else None,
            "to": max(stamps) if stamps else None,
        },
        "expected": expected,
        "observed": observed,
        "findings": findings,
        "hint": ENABLE_HINT if not records else "",
    }


def cmd_analyze(project, as_json: bool) -> int:
    report = analyze(project or str(Path.cwd()))
    if as_json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"ai-badger health: {report['health'].upper()}  ({report['window']['records']} "
          f"record(s) for {report['project']})")
    if report["hint"]:
        print(report["hint"])
    for finding in report["findings"]:
        print(f"  [{finding['severity']}] {finding['kind']}: {finding['component']}")
        print(f"      {finding['detail']}")
    if not report["findings"] and report["window"]["records"]:
        print("  no findings — every wired component produced records")
    return 0


def cmd_clear() -> int:
    if dl.AUDIT_FILE.exists():
        dl.AUDIT_FILE.write_text("", encoding="utf-8")
        dl._own_only(dl.AUDIT_FILE)  # pylint: disable=protected-access
    dl.log_event(TOOL_COMPONENT, "cleared")
    print("audit log cleared.")
    return 0


def main(argv=None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    on = sub.add_parser("on", help="enable debug logging")
    on.add_argument("duration", nargs="?", default=DEFAULT_DURATION)
    on.add_argument("--project", action="store_true",
                    help="limit to the current directory (default: every project)")
    sub.add_parser("off", help="disable debug logging")
    sub.add_parser("status", help="show mode, scope and record count")
    tail = sub.add_parser("tail", help="show the last records")
    tail.add_argument("count", nargs="?", type=int, default=20)
    sub.add_parser("clear", help="truncate the audit log")
    analyse = sub.add_parser("analyze", help="health state and findings for a project")
    analyse.add_argument("--project", default=None)
    analyse.add_argument("--json", action="store_true", dest="as_json",
                         help="machine-readable report, for an agent to turn into a report")

    args = parser.parse_args(argv)
    if args.command == "on":
        try:
            return cmd_on(args.duration, args.project)
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
    if args.command == "off":
        return cmd_off()
    if args.command == "tail":
        return cmd_tail(args.count)
    if args.command == "clear":
        return cmd_clear()
    if args.command == "analyze":
        return cmd_analyze(args.project, args.as_json)
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
