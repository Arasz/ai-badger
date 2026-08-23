#!/usr/bin/env python3
"""Compute recall@1/@3, false-fire rate and coverage margin for the MCP BM25 matcher.

The checked-in eval runner issue #140 asked for: ADR-0004's own harness "lived in another
repo, could not be run, and could not fail" (docs/adr/0012). This one runs in this repo,
against a named fixture file and a named index, and prints a report a human can read plus a
`--json-out` structure a machine can diff between two runs.

Stdlib only — gates/deps_guard.py fails the build on any undeclared third-party import.

Usage: retrieval_eval.py [--root <dir>] [--fixtures <path>] [--index <path>]
                          [--top-n N] [--threshold T] [--json-out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl  # pylint: disable=wrong-import-position

_RETRIEVAL_DIR = str(
    Path(__file__).resolve().parent.parent / "features" / "common" / "retrieval"
)
if _RETRIEVAL_DIR not in sys.path:
    sys.path.insert(0, _RETRIEVAL_DIR)
import mcp_matcher  # pylint: disable=wrong-import-position
from tokenizer import tokenize  # pylint: disable=wrong-import-position

DEFAULT_FIXTURES = Path("features/common/retrieval/eval/mcp_queries.jsonl")
DEFAULT_INDEX = Path("features/common/retrieval/eval/eval_index.json")

# Tokenized-length buckets, shortest first. Issue #165: the coverage gate's denominator ran
# over every query term, so it worked on keyword-shaped queries and suppressed correct matches
# on sentence-shaped ones — and a single recall number over a whole fixture set cannot show
# that. The boundaries separate the three fixture sets' regimes: keyword (both older sets
# average 3.8 and 4.8), short sentence, and real user message (the long set averages 15.3).
LENGTH_BUCKETS = ((0, 4), (5, 9), (10, 19), (20, None))


def bucket_label(tokens: int) -> str:
    """The `LENGTH_BUCKETS` label a query of `tokens` terms falls in."""
    for low, high in LENGTH_BUCKETS:
        if high is None:
            if tokens >= low:
                return f"{low}+"
        elif low <= tokens <= high:
            return f"{low}-{high}"
    return f"{LENGTH_BUCKETS[-1][0]}+"


def load_fixtures(path: Path) -> List[Dict[str, Any]]:
    """One JSON object per line; blank lines are skipped."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@dataclass(frozen=True)
class FixtureRow:
    """One fixture's expected tools against what the matcher actually returned."""

    query: str
    expect: List[str]
    cls: Optional[str]
    returned: List[str]
    tokens: int = 0

    @property
    def is_positive(self) -> bool:
        return bool(self.expect)

    @property
    def fired(self) -> bool:
        return bool(self.returned)

    @property
    def hit_at_1(self) -> bool:
        return bool(self.returned) and self.returned[0] in self.expect

    @property
    def hit_at_3(self) -> bool:
        return any(t in self.expect for t in self.returned)


def _rate(hits: int, total: int) -> Optional[float]:
    return hits / total if total else None


def _group_stats(rows: Sequence["FixtureRow"]) -> Dict[str, Any]:
    """The four headline numbers for one subset of fixtures."""
    positives = [r for r in rows if r.is_positive]
    negatives = [r for r in rows if not r.is_positive]
    return {
        "n": len(rows),
        "recall_at_1": _rate(sum(1 for r in positives if r.hit_at_1), len(positives)),
        "recall_at_3": _rate(sum(1 for r in positives if r.hit_at_3), len(positives)),
        "false_fire_rate": _rate(sum(1 for r in negatives if r.fired), len(negatives)),
    }


@dataclass(frozen=True)
class EvalReport:
    """Aggregate metrics plus per-fixture and per-class detail."""

    rows: List[FixtureRow]
    coverage_margin: Optional[float]

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def positives(self) -> List[FixtureRow]:
        return [r for r in self.rows if r.is_positive]

    @property
    def negatives(self) -> List[FixtureRow]:
        return [r for r in self.rows if not r.is_positive]

    @property
    def n_positive(self) -> int:
        return len(self.positives)

    @property
    def n_negative(self) -> int:
        return len(self.negatives)

    @property
    def recall_at_1(self) -> Optional[float]:
        return _rate(sum(1 for r in self.positives if r.hit_at_1), self.n_positive)

    @property
    def recall_at_3(self) -> Optional[float]:
        return _rate(sum(1 for r in self.positives if r.hit_at_3), self.n_positive)

    @property
    def false_fire_rate(self) -> Optional[float]:
        return _rate(sum(1 for r in self.negatives if r.fired), self.n_negative)

    @property
    def by_class(self) -> Dict[str, Dict[str, Any]]:
        """Per-`class` breakdown, for fixture sets that tag each query (issue #140's hard set)."""
        classes: Dict[str, List[FixtureRow]] = {}
        for row in self.rows:
            if row.cls is None:
                continue
            classes.setdefault(row.cls, []).append(row)
        return {cls: _group_stats(rows) for cls, rows in classes.items()}

    @property
    def by_query_length(self) -> Dict[str, Dict[str, Any]]:
        """Per-length-bucket breakdown, shortest bucket first (issue #165).

        The metric that could not see the defect this exists for: recall held at 1.000 on
        4-token fixtures while half of all 15-token ones returned nothing.
        """
        buckets: Dict[str, List[FixtureRow]] = {}
        for row in self.rows:
            buckets.setdefault(bucket_label(row.tokens), []).append(row)
        ordered = sorted(buckets.items(), key=lambda kv: min(r.tokens for r in kv[1]))
        out = {}
        for label, rows in ordered:
            stats = _group_stats(rows)
            stats["mean_tokens"] = sum(r.tokens for r in rows) / len(rows)
            out[label] = stats
        return out


def _coverage_margin(
    fixtures: Sequence[Dict[str, Any]],
    index: Dict[str, Any],
    top_n: int,
    threshold: float,
) -> Optional[float]:
    """Tightest gated true-positive coverage minus the worst gated false-fire coverage.

    Reproduces the measurement docs/adr/0012 reports by hand: the gap between the lowest
    coverage among positives the matcher actually got right and the highest coverage among
    negatives that fired anyway. A negative margin is a legitimate result — it means the two
    classes cross, i.e. no scalar threshold cleanly separates them on this fixture set.
    """
    corpus = mcp_matcher.build_corpus(index)
    if corpus is None:
        return None
    true_positive_coverages = []
    false_fire_coverages = []
    for fixture in fixtures:
        terms = tokenize(fixture["query"])
        if not terms:
            continue
        ranked = corpus.rank(terms, coverage_cap=mcp_matcher.COVERAGE_TERM_CAP)
        gated = [r for r in ranked if r.matched_terms >= 1 and r.coverage >= threshold]
        top = gated[:top_n]
        expect = fixture.get("expect", [])
        if expect:
            for r in top:
                if r.doc_id in expect:
                    true_positive_coverages.append(r.coverage)
        elif top:
            false_fire_coverages.append(top[0].coverage)
    if not true_positive_coverages or not false_fire_coverages:
        return None
    return min(true_positive_coverages) - max(false_fire_coverages)


def evaluate(
    fixtures: Sequence[Dict[str, Any]],
    index: Dict[str, Any],
    top_n: int = mcp_matcher.TOP_N,
    threshold: float = mcp_matcher.DEFAULT_COVERAGE_THRESHOLD,
) -> EvalReport:
    """Run every fixture's query through the real matcher and score the results."""
    rows = []
    for fixture in fixtures:
        results = mcp_matcher.find_relevant_tools(
            fixture["query"], index, top_n=top_n, threshold=threshold
        )
        rows.append(FixtureRow(
            query=fixture["query"],
            expect=fixture.get("expect", []),
            cls=fixture.get("class"),
            returned=[r.tool for r in results],
            tokens=len(tokenize(fixture["query"])),
        ))
    margin = _coverage_margin(fixtures, index, top_n, threshold)
    return EvalReport(rows=rows, coverage_margin=margin)


def _doc_tokens(index: Dict[str, Any], tool: str) -> Optional[set]:
    for server in index.get("sources", []):
        prefix = f"{server.get('name', '')}:"
        if not tool.startswith(prefix):
            continue
        tool_def = server.get("tools", {}).get(tool[len(prefix):])
        if tool_def is None:
            continue
        toks = set(tokenize(tool.replace(":", " ")))
        toks |= set(tokenize(" ".join(tool_def.get("tags", []))))
        toks |= set(tokenize(tool_def.get("intent", "")))
        return toks
    return None


def query_document_overlap(query_tokens: Sequence[str], doc_tokens: set) -> float:
    """Fraction of `query_tokens` that also appear in `doc_tokens`; 0.0 for an empty query."""
    if not query_tokens:
        return 0.0
    matched = sum(1 for t in query_tokens if t in doc_tokens)
    return matched / len(query_tokens)


def overlap_stats(fixtures: Sequence[Dict[str, Any]], index: Dict[str, Any]) -> Dict[str, Any]:
    """Mean query<->document token overlap over positive fixtures, and how many sit >= 0.50.

    Mirrors the measurement docs/retrieval.md reports for the original fixture set (mean
    0.781, 40 of 43 at >= 0.50) so the same statistic can be produced for any fixture set.
    """
    per_fixture = []
    for fixture in fixtures:
        expect = fixture.get("expect", [])
        if not expect:
            continue
        query_tokens = tokenize(fixture["query"])
        best = 0.0
        for tool in expect:
            doc_tokens = _doc_tokens(index, tool)
            if doc_tokens is None:
                continue
            best = max(best, query_document_overlap(query_tokens, doc_tokens))
        per_fixture.append({"query": fixture["query"], "overlap": best})
    n = len(per_fixture)
    mean = sum(p["overlap"] for p in per_fixture) / n if n else 0.0
    at_least_half = sum(1 for p in per_fixture if p["overlap"] >= 0.5)
    return {"n": n, "mean": mean, "at_least_half": at_least_half, "per_fixture": per_fixture}


def format_report(report: EvalReport, title: str = "") -> str:
    """Human-readable summary: headline metrics, per-class breakdown, per-fixture rows."""
    lines = []
    if title:
        lines.append(title)
    lines.append(
        f"n={report.n} positives={report.n_positive} negatives={report.n_negative}"
    )
    r1, r3 = _fmt(report.recall_at_1), _fmt(report.recall_at_3)
    ff, margin = _fmt(report.false_fire_rate), _fmt(report.coverage_margin)
    lines.append(f"recall@1={r1}  recall@3={r3}  false_fire={ff}  coverage_margin={margin}")
    if report.by_class:
        lines.append("")
        lines.append("by class:")
        for cls, stats in sorted(report.by_class.items()):
            r1, r3 = _fmt(stats["recall_at_1"]), _fmt(stats["recall_at_3"])
            ff = _fmt(stats["false_fire_rate"])
            lines.append(
                f"  {cls:20s} n={stats['n']:<4d} recall@1={r1} recall@3={r3} false_fire={ff}"
            )
    lines.append("")
    lines.append("by query length (tokens):")
    for label, stats in report.by_query_length.items():
        r1, r3 = _fmt(stats["recall_at_1"]), _fmt(stats["recall_at_3"])
        ff = _fmt(stats["false_fire_rate"])
        lines.append(
            f"  {label:20s} n={stats['n']:<4d} recall@1={r1} recall@3={r3} false_fire={ff}"
            f" mean={stats['mean_tokens']:.1f}"
        )
    lines.append("")
    lines.append("per-fixture:")
    for row in report.rows:
        outcome = _row_outcome(row)
        lines.append(f"  [{outcome}] {row.query!r} expect={row.expect} got={row.returned}")
    return "\n".join(lines)


def _row_outcome(row: FixtureRow) -> str:
    if row.is_positive:
        if row.hit_at_1:
            return "hit@1"
        if row.hit_at_3:
            return "hit@3"
        return "miss"
    return "fire" if row.fired else "silent"


def _fmt(value: Optional[float]) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def report_to_json(report: EvalReport) -> Dict[str, Any]:
    """A plain, `json.dumps`-safe structure suitable for diffing two runs."""
    return {
        "n": report.n,
        "n_positive": report.n_positive,
        "n_negative": report.n_negative,
        "recall_at_1": report.recall_at_1,
        "recall_at_3": report.recall_at_3,
        "false_fire_rate": report.false_fire_rate,
        "coverage_margin": report.coverage_margin,
        "by_class": report.by_class,
        "by_query_length": report.by_query_length,
        "rows": [
            {
                "query": r.query,
                "expect": r.expect,
                "class": r.cls,
                "returned": r.returned,
                "tokens": r.tokens,
                "hit_at_1": r.hit_at_1,
                "hit_at_3": r.hit_at_3,
                "fired": r.fired,
            }
            for r in report.rows
        ],
    }


def main(argv=None) -> int:
    """CLI entry point: run one fixture file against one index and report the result."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root")
    ap.add_argument("--fixtures", default=None)
    ap.add_argument("--index", default=None)
    ap.add_argument("--top-n", type=int, default=mcp_matcher.TOP_N)
    ap.add_argument("--threshold", type=float, default=mcp_matcher.DEFAULT_COVERAGE_THRESHOLD)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()
    fixtures_path = Path(args.fixtures) if args.fixtures else root / DEFAULT_FIXTURES
    index_path = Path(args.index) if args.index else root / DEFAULT_INDEX

    if not fixtures_path.exists():
        print(f"fixture file not found: {fixtures_path}")
        return 1
    if not index_path.exists():
        print(f"index file not found: {index_path}")
        return 1

    fixtures = load_fixtures(fixtures_path)
    index = bl.load_json(index_path)
    report = evaluate(fixtures, index, top_n=args.top_n, threshold=args.threshold)

    print(format_report(report, title=f"fixtures={fixtures_path}  index={index_path}"))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report_to_json(report), indent=2), encoding="utf-8"
        )
        print(f"\nwrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
