#!/usr/bin/env python3
"""Turn recorded retrieval telemetry into *candidate* eval fixtures (issue #140, step 2).

The eval fixture sets are author-written, which biases them: the queries were invented by the
person who also wrote the descriptions being matched. This reads the `ai_badger_hooks/
mcp_retrieval` records the hooks already write (docs/retrieval.md §6) and proposes the queries
people really typed as fixture material.

What it will not do: decide what the right answer was. A candidate carries the *observed*
outcome and never an `expect` field — a human adds that, and that review is also the privacy
gate, because a real query is user content and this repository is public.

Redaction, in order of strength:
  * `AI_BADGER_DEBUG_REDACT` at write time — the text was never on disk; nothing to harvest.
  * default output — the query is replaced by its SHA-256, so two runs can be joined and
    counted without the text ever leaving the machine.
  * `--include-queries` — writes the text, for the human doing the review to read.
A candidate's `project` is always a 12-hex-character digest of the project path, never the path.

Stdlib only — gates/deps_guard.py fails the build on any undeclared third-party import.

Usage: fixture_harvest.py [--log <audit.jsonl>] [--out <candidates.jsonl>]
                          [--include-queries] [--min-seen N] [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Mirrors features/common/hooks/debug_log.py rather than importing it: that module is copied
# into four deployment shapes and imports nothing from the framework, so this reads its wire
# format the way any other reader would.
DEBUG_DIR_ENV = "AI_BADGER_DEBUG_DIR"
REDACT_ENV = "AI_BADGER_DEBUG_REDACT"
MAX_FIELD_CHARS = 200
MAX_QUERY_CHARS = 2000
# A query whose length is exactly a cap the writer applied is a prefix, not a question. 200 was
# the cap for every field before #219 raised the query's share, and records written under it are
# still in circulation — so both lengths stay unusable, and only both.
CLIP_LENGTHS = (MAX_FIELD_CHARS, MAX_QUERY_CHARS)

KEY_COMPONENT = "c"
KEY_EVENT = "e"
KEY_QUERY = "q"
KEY_RETURNED = "r"
KEY_PROJECT = "p"

RETRIEVAL_COMPONENT = "ai_badger_hooks/mcp_retrieval"

# Same component, different subject: these record whether a tool the agent called was one the
# index knew, not what retrieval did with a query. They carry no query and never can.
TOOL_CHECK_EVENTS = frozenset({"known", "unknown", "server_unindexed"})

SOURCE_TELEMETRY = "telemetry"
PROJECT_DIGEST_CHARS = 12

# Harness-injected turns (`<system-reminder>`, `<task-notification>`, …) are not things a person
# typed, and a fixture set full of them measures the harness. Errs toward dropping: a real query
# that happens to contain markup is lost, which costs one candidate.
_MACHINE_RE = re.compile(r"<[/A-Za-z][^>\s]*>")


def default_log_path() -> Path:
    """`$AI_BADGER_DEBUG_DIR/audit.jsonl`, else `~/.ai-badger/debug/audit.jsonl`."""
    override = os.environ.get(DEBUG_DIR_ENV)
    base = Path(override) if override else Path.home() / ".ai-badger" / "debug"
    return base / "audit.jsonl"


def load_records(path) -> List[Dict[str, Any]]:
    """Every parseable JSON object in the log, one per line.

    A truncated final line is normal for an append-only log a process may have died inside of,
    so an unreadable line is skipped rather than fatal.
    """
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def is_machine_shaped(query: str) -> bool:
    """True when the text looks like a harness-generated turn rather than something typed."""
    return bool(_MACHINE_RE.search(query))


def project_digest(project: Optional[str]) -> Optional[str]:
    """A short stable digest of a project path — never the path, which names a client."""
    if not project:
        return None
    return hashlib.sha256(project.encode("utf-8")).hexdigest()[:PROJECT_DIGEST_CHARS]


def query_digest(query: str) -> str:
    """The SHA-256 that stands in for a query when the text stays on the machine."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def split_returned(returned) -> List[str]:
    """The `r` field's comma-separated tool names as a list; empty for a silence."""
    if not returned:
        return []
    return [name.strip() for name in str(returned).split(",") if name.strip()]


@dataclass
class Harvest:
    """What one log yielded, and what each unusable record was unusable for."""

    total: int = 0
    retrieval: int = 0
    tool_checks: int = 0
    redacted: int = 0
    clipped: int = 0
    machine: int = 0
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def harvestable(self) -> int:
        return len(self.candidates)

    @property
    def occurrences(self) -> int:
        """Records behind those candidates — duplicates collapse, but they still happened."""
        return sum(c["seen"] for c in self.candidates)


def harvest(records: Sequence[Dict[str, Any]], harvested: str) -> Harvest:
    """Classify every record and collect the harvestable queries as candidates.

    Identical queries collapse into one candidate with a `seen` count; the first record's
    outcome and project are the ones kept, because a repeated query against a changed index is
    a different observation and averaging the two would invent a third that never happened.
    """
    result = Harvest()
    seen: Dict[str, Dict[str, Any]] = {}
    for record in records:
        result.total += 1
        if record.get(KEY_COMPONENT) != RETRIEVAL_COMPONENT:
            continue
        result.retrieval += 1
        event = record.get(KEY_EVENT, "")
        if event in TOOL_CHECK_EVENTS:
            result.tool_checks += 1
            continue
        query = record.get(KEY_QUERY)
        if not query:
            result.redacted += 1
            continue
        if len(query) in CLIP_LENGTHS or len(query) > MAX_QUERY_CHARS:
            result.clipped += 1
            continue
        if is_machine_shaped(query):
            result.machine += 1
            continue
        existing = seen.get(query)
        if existing is not None:
            existing["seen"] += 1
            continue
        candidate = {
            "query": query,
            "observed": {"event": event, "returned": split_returned(record.get(KEY_RETURNED))},
            "seen": 1,
            "source": SOURCE_TELEMETRY,
            "harvested": harvested,
            "project": project_digest(record.get(KEY_PROJECT)),
        }
        seen[query] = candidate
        result.candidates.append(candidate)
    return result


def render_candidates(
    candidates: Sequence[Dict[str, Any]], include_queries: bool = False
) -> List[Dict[str, Any]]:
    """Candidates as they should be written out; the query text only when asked for.

    The digest is present either way, so a redacted run and an unredacted one can be joined
    on the same key.
    """
    rendered = []
    for candidate in candidates:
        row: Dict[str, Any] = {"query_sha256": query_digest(candidate["query"])}
        if include_queries:
            row["query"] = candidate["query"]
        for key, value in candidate.items():
            if key != "query":
                row[key] = value
        rendered.append(row)
    return rendered


def format_report(result: Harvest, log_path: str) -> str:
    """Human-readable summary: every bucket counted, and why an empty harvest is empty."""
    lines = [
        f"log={log_path}",
        f"records={result.total}  retrieval={result.retrieval}  tool_checks={result.tool_checks}",
        f"not harvestable: redacted={result.redacted}  clipped={result.clipped}"
        f"  machine={result.machine}",
        f"harvestable: {result.harvestable} distinct queries"
        f" from {result.occurrences} records",
    ]
    if result.redacted:
        lines.append("")
        lines.append(
            f"{result.redacted} record(s) were written with {REDACT_ENV} set: the query text was"
            " never stored, so nothing can be recovered from them. Unset it (the"
            " call-behaviorist skill turns the log on and off) before the session you want to"
            " harvest from."
        )
    if result.clipped:
        lines.append(
            f"{result.clipped} record(s) were stored at a field cap "
            f"({', '.join(str(n) for n in CLIP_LENGTHS)} chars): the stored"
            " text is a prefix of what was typed, so it is not the query and is dropped."
        )
    lines.append("")
    lines.append(
        "Candidates carry no `expect` field. A human decides the right answer, and that review"
        " is also the privacy gate before anything is checked in."
    )
    return "\n".join(lines)


def write_candidates(path, rows: Sequence[Dict[str, Any]]) -> None:
    """One JSON object per line, the format the eval fixture sets already use."""
    Path(path).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def main(argv=None) -> int:
    """CLI entry point: read one audit log, report it, optionally write the candidates."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--include-queries", action="store_true")
    ap.add_argument("--min-seen", type=int, default=1)
    ap.add_argument("--date", default=None)
    args = ap.parse_args(argv)

    log_path = Path(args.log) if args.log else default_log_path()
    if not log_path.is_file():
        print(f"audit log not found: {log_path}")
        return 1

    result = harvest(load_records(log_path), args.date or date.today().isoformat())
    print(format_report(result, str(log_path)))

    if args.out:
        kept = [c for c in result.candidates if c["seen"] >= args.min_seen]
        write_candidates(args.out, render_candidates(kept, include_queries=args.include_queries))
        print(f"\nwrote {len(kept)} candidates to {args.out}")
        if args.include_queries:
            print("that file contains user query text — read it before it goes anywhere")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
