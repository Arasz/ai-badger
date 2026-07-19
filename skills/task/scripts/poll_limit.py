#!/usr/bin/env python3
"""Background usage-limit poller for the /task skill.

Starts as a daemon-friendly foreground process. It watches Claude availability;
when a previous limited state becomes available again, it runs `/auto-wm away 4h`
and resumes active /task sessions discovered from task tracking data, falling back
to Claude's user-level transcript store (~/.claude/projects) when tracking is not
yet populated.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import tracker_lib as lib
except Exception:  # pragma: no cover - keeps importable in isolated harnesses
    lib = None

_CLAUDE_FALLBACKS = (Path.home() / ".local/bin/claude", Path("/usr/local/bin/claude"))
CLAUDE_BIN = shutil.which("claude") or next(
    (str(p) for p in _CLAUDE_FALLBACKS if p.is_file() and (p.stat().st_mode & 0o111)), "claude"
)

def _find_project_root(start: Path) -> Path:
    """Walk up from this script to the repo root (nearest ancestor containing .claude).

    Replaces a hard-coded parents[4] index, which silently broke if the script ever moved to a
    different depth. Falls back to the current working directory when no ancestor has a .claude/.
    """
    for parent in start.parents:
        if (parent / ".claude").is_dir():
            return parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root(Path(__file__).resolve())

LOG_FILE = PROJECT_ROOT / ".claude" / "task-tracking" / "poll_limit.log"
PID_FILE = PROJECT_ROOT / ".claude" / "task-tracking" / "poll_limit.pid"
STATUSLINE_STATE = PROJECT_ROOT / ".claude" / "task-tracking" / "statusline-state.json"
DEFAULT_AVAILABLE_INTERVAL_SECONDS = 300
STATUSLINE_FRESH_SECONDS = 180
LIMIT_WAIT_SCHEDULE_SECONDS = [7200, 1800, 900, 300]
DEFAULT_RESUME_DELAY_SECONDS = 120
PROBE_MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class TargetSession:
    session_id: str
    task_id: str = ""
    transcript_path: str = ""
    source: str = ""


@dataclass
class PollState:
    was_limited: bool | None = None
    limited_checks: int = 0


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    msg = f"{ts} {message}"
    print(msg, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def already_running(pid_file: Path = PID_FILE) -> bool:
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


def write_pid(pid_file: Path = PID_FILE) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def _parse_iso_epoch(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def statusline_state_age_seconds(state: dict) -> float | None:
    captured_at = state.get("capturedAt")
    captured_epoch = _parse_iso_epoch(captured_at)
    if captured_epoch is None:
        return None
    return time.time() - captured_epoch


def check_limit_from_statusline(state_path: Path = STATUSLINE_STATE) -> tuple[bool, str] | None:
    """Use captured statusLine rate-limit metadata only when the capture is fresh."""
    state = _read_json(state_path, {})
    age_seconds = statusline_state_age_seconds(state)
    if age_seconds is None or age_seconds > STATUSLINE_FRESH_SECONDS:
        return None
    five_hour = (state.get("rateLimits") or {}).get("five_hour") or {}
    resets_at = five_hour.get("resets_at")
    used_percentage = five_hour.get("used_percentage")
    if resets_at is None:
        return None
    try:
        reset_epoch = float(resets_at)
    except (TypeError, ValueError):
        return None
    now_epoch = time.time()
    if reset_epoch <= now_epoch:
        return False, "statusline: fresh capture, five_hour reset time passed"
    wait_seconds = int(reset_epoch - now_epoch)
    if used_percentage is None or float(used_percentage) >= 99:
        return True, f"statusline: fresh capture, five_hour reset in {wait_seconds} seconds"
    # Reset is in the future but the window is not exhausted — not limited. (The previous code
    # mislabeled this case as "reset time passed", which was never true here.)
    return False, (f"statusline: fresh capture, five_hour not exhausted "
                   f"(used {used_percentage}%), reset in {wait_seconds} seconds")


def check_limit_with_probe() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "Reply with exactly: ok", "--model", PROBE_MODEL],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, str(exc)
    output = result.stdout + result.stderr
    if result.returncode == 0:
        return False, output
    return "limit" in output.lower(), output


def check_limit() -> tuple[bool, str]:
    """Return (is_limited, diagnostic_output), falling back to the Claude probe when statusLine is stale."""
    statusline_result = check_limit_from_statusline()
    if statusline_result is not None:
        return statusline_result
    return check_limit_with_probe()


def discover_target_sessions(project_root: Path = PROJECT_ROOT, user_claude_dir: Path | None = None) -> list[TargetSession]:
    sessions = _discover_task_sessions(project_root)
    if sessions:
        return sessions
    return _discover_user_claude_sessions(project_root, user_claude_dir or (Path.home() / ".claude"))


def _discover_task_sessions(project_root: Path) -> list[TargetSession]:
    tasks_path = project_root / ".claude" / "task-tracking" / "executed-tasks.json"
    doc = _read_json(tasks_path, {"tasks": []})
    found: list[TargetSession] = []
    for entry in doc.get("tasks", []):
        if entry.get("state") == "FINISHED" or not entry.get("sessionId"):
            continue
        found.append(
            TargetSession(
                session_id=entry["sessionId"],
                task_id=entry.get("taskId", ""),
                transcript_path=entry.get("transcriptPath", ""),
                source="task-tracking",
            )
        )
    return found


def _discover_user_claude_sessions(project_root: Path, user_claude_dir: Path) -> list[TargetSession]:
    projects_dir = user_claude_dir / "projects"
    if not projects_dir.exists():
        return []
    found: dict[str, TargetSession] = {}
    for transcript in projects_dir.rglob("*.jsonl"):
        session_id = _session_id_from_transcript(transcript, project_root)
        if session_id:
            found[session_id] = TargetSession(
                session_id=session_id,
                transcript_path=str(transcript),
                source="claude-projects",
            )
    return list(found.values())


def _session_id_from_transcript(path: Path, project_root: Path) -> str:
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return ""
    for line in reversed(lines[-50:]):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        cwd = record.get("cwd") or record.get("workspace") or record.get("projectPath")
        if cwd and Path(cwd) != project_root:
            continue
        sid = record.get("sessionId") or record.get("session_id")
        if sid:
            return str(sid)
    return path.stem if lines else ""


def run_auto_wm() -> bool:
    log("Running one-shot claude session with /auto-wm away 4h...")
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "/auto-wm away 4h"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log(f"Failed to run auto-wm: {exc}")
        return False
    log(f"auto-wm exited {result.returncode}")
    if result.returncode != 0:
        log(f"auto-wm error: {result.stderr.strip()[:300]}")
    return result.returncode == 0


def resume_session(target: TargetSession) -> bool:
    prompt = "Continue from where this Claude Code session left off."
    if target.task_id:
        tracker = PROJECT_ROOT / ".claude" / "skills" / "task" / "scripts" / "task_tracker.py"
        prompt = f"Run `python3 {tracker} reattach {target.task_id}` first, then continue the /task workflow."
    log(f"Resuming session {target.session_id} ({target.source}{' task ' + target.task_id if target.task_id else ''})...")
    try:
        subprocess.Popen(
            [CLAUDE_BIN, "--resume", target.session_id, "-p", prompt, "--permission-mode", "acceptEdits"],
            cwd=str(PROJECT_ROOT),
            start_new_session=True,
        )
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"Failed to resume {target.session_id}: {exc}")
        return False


def next_limit_wait_seconds(limited_checks: int) -> int:
    index = max(0, limited_checks - 1)
    if index >= len(LIMIT_WAIT_SCHEDULE_SECONDS):
        return LIMIT_WAIT_SCHEDULE_SECONDS[-1]
    return LIMIT_WAIT_SCHEDULE_SECONDS[index]


def poll_once(
    state: PollState,
    limit_checker=check_limit,
    session_discoverer=discover_target_sessions,
    auto_wm_runner=run_auto_wm,
    session_resumer=resume_session,
    sleep_between_resumes=time.sleep,
    resume_delay_seconds: int = DEFAULT_RESUME_DELAY_SECONDS,
) -> int:
    limited, output = limit_checker()
    if state.was_limited is True and limited is False:
        log("Limit reset detected!")
        auto_wm_runner()
        sessions = session_discoverer()
        if sessions:
            log(f"Found {len(sessions)} sessions to resume: {[s.session_id for s in sessions]}")
            for index, target in enumerate(sessions):
                if index:
                    log(f"Waiting {resume_delay_seconds} seconds before next resume...")
                    sleep_between_resumes(resume_delay_seconds)
                session_resumer(target)
        else:
            log("No active task or Claude project sessions found to resume.")
    state.was_limited = limited
    if limited:
        state.limited_checks += 1
        wait_seconds = next_limit_wait_seconds(state.limited_checks)
        log(f"Status: Limited. Next check in {wait_seconds} seconds. {(output or '').strip()[:200]}")
        return wait_seconds
    state.limited_checks = 0
    return DEFAULT_AVAILABLE_INTERVAL_SECONDS


def run_forever(interval_seconds: int | None = None) -> int:
    if already_running():
        log("poll_limit.py is already running; exiting")
        return 0
    write_pid()
    log("Starting Claude limit poller (dynamic interval: 2h, 30m, 15m, then 5m while limited; 5m otherwise)...")
    state = PollState()
    while True:
        try:
            wait_seconds = poll_once(state)
        except Exception as exc:  # noqa: BLE001 - a daemon must outlive transient poll errors
            log(f"poll_once error (continuing): {exc!r}")
            wait_seconds = DEFAULT_AVAILABLE_INTERVAL_SECONDS
        time.sleep(interval_seconds if interval_seconds is not None else wait_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        state = PollState(was_limited=True)
        poll_once(state)
        return 0
    return run_forever(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())