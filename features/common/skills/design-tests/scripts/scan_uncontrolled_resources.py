#!/usr/bin/env python3
"""Grep for the isolation controls `design-tests` Stage 4 declares — time, network, fs, env,
random, shared state — across the test files a design or review pass just produced or is judging.

Categories and patterns are MoE-4-benchmark.md §5.5(a)'s C#/TS lists, transcribed verbatim; the
five isolation controls are `references/universal.md` group `T1-ISO-*`. Python 3 stdlib only —
this file ships to every scaffolded consumer project, which never has ai-badger's own `engine/`
on its path (ADR-0005).

A hit is a finding, not a disqualification: an integration test may legitimately need a real
port, and a file whose setup demonstrably neutralises the hit (`FakeTimeProvider`, a fake-timer
call, an MSW handler) is downgraded to `mitigated` rather than dropped, so a reader can still see
what was controlled and how. The two wall-clock-*assertion* rows are never mitigable — asserting
elapsed time is wrong regardless of what else the file does (T1-ISO-01).

Usage: scan_uncontrolled_resources.py <path>... [--json]
  <path>...  one or more files or directories; directories are scanned recursively for
             .cs/.ts/.tsx/.js files, skipping node_modules/bin/obj/dist/build/.git.
  --json     emit a JSON array of findings instead of the one-line-per-finding text form.

Exit code is always 0 — findings are data for a human or the benchmark harness to read, never a
gate a scripted caller should branch on.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

SKIP_DIR_NAMES = {"node_modules", "bin", "obj", "dist", "build", ".git", "__pycache__"}
CS_EXTENSIONS = {".cs"}
TS_EXTENSIONS = {".ts", ".tsx", ".js"}
ALL_EXTENSIONS = CS_EXTENSIONS | TS_EXTENSIONS

BLOCKER = "blocker"
MAJOR = "major"
MITIGATED = "mitigated"

# Mitigation groups: a marker found anywhere in the raw file text downgrades every hit in that
# group, in that file, to `mitigated`. Limited to the three concrete examples MoE-4 §5.5(a) names
# — a fake clock, a fake-timer call, an MSW handler — rather than inventing more (ask-if-simpler).
TIME_MITIGATION_RE = re.compile(
    r"FakeTimeProvider|useFakeTimers|vi\.useFakeTimers|jest\.useFakeTimers")
NETWORK_MITIGATION_RE = re.compile(r"server\.use\(|setupServer\(|\bmsw\b")
MITIGATION_GROUPS = {
    "wall-clock-now": TIME_MITIGATION_RE,
    "sleep-or-delay": TIME_MITIGATION_RE,
    "network": NETWORK_MITIGATION_RE,
}
NEVER_MITIGABLE = {"wall-clock-assertion"}


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    category: str
    severity: str
    snippet: str
    mitigated: bool


# category -> (severity, applicable_extensions, [regex, ...])
_CATEGORIES: List[Tuple[str, str, frozenset, List[str]]] = [
    ("wall-clock-now", MAJOR, frozenset(CS_EXTENSIONS), [
        r"DateTime\.(Now|UtcNow|Today)", r"DateTimeOffset\.(Now|UtcNow)", r"TimeProvider\.System",
    ]),
    ("wall-clock-now", MAJOR, frozenset(TS_EXTENSIONS), [
        r"Date\.now\(\)", r"new\s+Date\s*\(\s*\)",
    ]),
    ("stopwatch", MAJOR, frozenset(CS_EXTENSIONS), [
        r"new\s+Stopwatch", r"Stopwatch\.StartNew", r"\.ElapsedMilliseconds", r"\.Elapsed\b",
    ]),
    ("sleep-or-delay", MAJOR, frozenset(CS_EXTENSIONS), [
        r"Thread\.Sleep", r"Task\.Delay\s*\(\s*[0-9]",
    ]),
    ("sleep-or-delay", MAJOR, frozenset(TS_EXTENSIONS), [
        r"\bsetTimeout\b", r"\bsetInterval\b", r"await\s+new\s+Promise\(r\s*=>\s*setTimeout",
    ]),
    ("unseeded-random", MAJOR, frozenset(CS_EXTENSIONS), [
        r"new\s+Random\s*\(\s*\)",
    ]),
    ("unseeded-random", MAJOR, frozenset(TS_EXTENSIONS), [
        r"Math\.random\(\)",
    ]),
    ("unpinned-identity", MAJOR, frozenset(CS_EXTENSIONS), [
        r"Guid\.NewGuid\s*\(\s*\)",
    ]),
    ("unpinned-identity", MAJOR, frozenset(TS_EXTENSIONS), [
        r"crypto\.randomUUID\(\)",
    ]),
    ("environment", MAJOR, frozenset(CS_EXTENSIONS), [
        r"Environment\.(GetEnvironmentVariable|CurrentDirectory|MachineName|UserName|ProcessPath)",
        r"AppDomain\.CurrentDomain", r"ConfigurationManager\.", r"IConfiguration.*json.*file",
    ]),
    ("environment", MAJOR, frozenset(TS_EXTENSIONS), [
        r"process\.env\.", r"process\.cwd\(\)", r"import\.meta\.dir",
    ]),
    ("filesystem", MAJOR, frozenset(CS_EXTENSIONS), [
        r"System\.IO\.(File|Directory|Path)\.", r"(?<!Fake)File\.(Read|Write|Exists|Delete)",
        r"Directory\.(Create|Delete|Get)", r"Path\.GetTempPath", r"Path\.GetTempFileName",
    ]),
    ("filesystem", MAJOR, frozenset(TS_EXTENSIONS), [
        r"node:fs", r'from\s+["\']fs["\']',
    ]),
    ("network", MAJOR, frozenset(CS_EXTENSIONS), [
        r"new\s+HttpClient\s*\(\s*\)", r"https?://(?!localhost|127\.0\.0\.1)",
    ]),
    ("network", MAJOR, frozenset(TS_EXTENSIONS), [
        r"fetch\s*\(", r"https?://(?!localhost|127\.0\.0\.1)",
    ]),
    ("process-or-port", MAJOR, frozenset(CS_EXTENSIONS), [
        r"Process\.(Start|GetProcesses)", r"new\s+(TcpListener|Socket|HttpListener)",
        r"\.Listen\s*\(",
    ]),
    ("process-or-port", MAJOR, frozenset(TS_EXTENSIONS), [
        r"new\s+Worker", r"child_process", r"net\.createServer", r"\.listen\s*\(",
    ]),
    ("storage", MAJOR, frozenset(TS_EXTENSIONS), [
        r"\blocalStorage\b", r"\bsessionStorage\b", r"\bindexedDB\b",
    ]),
    ("global-mutation", MAJOR, frozenset(TS_EXTENSIONS), [
        r"globalThis\.\w+\s*=", r"document\.title\s*=", r"window\.\w+\s*=",
    ]),
    ("mutable-static", MAJOR, frozenset(CS_EXTENSIONS), [
        r"static\s+(?!readonly)\w+\s+\w+\s*(=|;)",
    ]),
    # Never mitigable — T1-ISO-01, always blocker regardless of file context.
    ("wall-clock-assertion", BLOCKER, frozenset(CS_EXTENSIONS), [
        r"Assert.*Elapsed", r"Should.*Elapsed", r"BeLessThan.*Milliseconds",
    ]),
    ("wall-clock-assertion", BLOCKER, frozenset(TS_EXTENSIONS), [
        r"expect\(.*(duration|elapsed|took|ms)\)",
    ]),
]

_COMPILED = [
    (category, severity, exts, [re.compile(p) for p in patterns])
    for category, severity, exts, patterns in _CATEGORIES
]

_LINE_COMMENT_RE = re.compile(r"//.*$")
_BLOCK_COMMENT_START_RE = re.compile(r"/\*")
_BLOCK_COMMENT_END_RE = re.compile(r"\*/")


def _strip_comments(text: str) -> List[str]:
    """Return `text`'s lines with `//...` and `/* ... */` spans blanked out.

    A heuristic, not a tokenizer — it does not track string literals, so `"//"` inside a string
    is (rarely) mis-treated as a comment start. Acceptable for a scanner whose findings are data
    for a human to read, never a gate (see the module docstring).
    """
    out: List[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw
        if in_block:
            end = _BLOCK_COMMENT_END_RE.search(line)
            if end is None:
                out.append("")
                continue
            line = line[end.end():]
            in_block = False
        while True:
            start = _BLOCK_COMMENT_START_RE.search(line)
            if start is None:
                break
            end = _BLOCK_COMMENT_END_RE.search(line, start.end())
            if end is None:
                line = line[: start.start()]
                in_block = True
                break
            line = line[: start.start()] + line[end.end():]
        line = _LINE_COMMENT_RE.sub("", line)
        out.append(line)
    return out


def _extension_for(filename: str) -> str:
    return Path(filename).suffix


def scan_text(text: str, filename: str) -> List[Finding]:
    """Findings in `text`, attributed to `filename` for its extension and for reporting."""
    ext = _extension_for(filename)
    if ext not in ALL_EXTENSIONS:
        return []
    raw_lines = text.splitlines()
    stripped_lines = _strip_comments(text)

    mitigation_groups_present = {
        group for group, marker_re in MITIGATION_GROUPS.items() if marker_re.search(text)
    }

    findings: List[Finding] = []
    for category, severity, exts, patterns in _COMPILED:
        if ext not in exts:
            continue
        mitigated = category in mitigation_groups_present and category not in NEVER_MITIGABLE
        for lineno, stripped in enumerate(stripped_lines, start=1):
            if any(p.search(stripped) for p in patterns):
                findings.append(Finding(
                    file=filename, line=lineno, category=category,
                    severity=MITIGATED if mitigated else severity,
                    snippet=raw_lines[lineno - 1].strip()[:200],
                    mitigated=mitigated,
                ))
    findings.sort(key=lambda f: (f.line, f.category))
    return findings


def _iter_target_files(paths: Iterable[str]) -> Iterable[Path]:
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix in ALL_EXTENSIONS:
                yield p
            continue
        if not p.is_dir():
            continue
        for child in sorted(p.rglob("*")):
            if not child.is_file() or child.suffix not in ALL_EXTENSIONS:
                continue
            if SKIP_DIR_NAMES & set(child.relative_to(p).parts[:-1]):
                continue
            yield child


def scan_paths(paths: Iterable[str]) -> List[Finding]:
    findings: List[Finding] = []
    for path in _iter_target_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_text(text, str(path)))
    return findings


def _format_text(findings: List[Finding]) -> str:
    lines = [
        f"{f.file}:{f.line}:{f.category}:{f.severity}:{f.snippet}" for f in findings
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI entry point. Always returns 0 — findings are data, never a gate."""
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="files or directories to scan")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the text form")
    args = ap.parse_args(argv)

    findings = scan_paths(args.paths)
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        text = _format_text(findings)
        if text:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
