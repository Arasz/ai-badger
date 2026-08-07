#!/usr/bin/env python3
"""Report open pull requests that no `pull_request`-triggered workflow will ever run on.

A pull request conflicting with its base has no `refs/pull/N/merge` for GitHub to check out,
so no `pull_request` workflow run is dispatched for it at all. Every required status check
whose only trigger is `pull_request` then reports nothing — and the mergebox renders "has not
reported" exactly like "still running". PR #341 is the worked example (see the tests).

Input is the JSON body of the `gh api graphql` query in
`.github/workflows/stuck-pr-watch.yml`; output is a JSON report on stdout. Filtering only —
the workflow does the posting, so no untrusted pull request text reaches a shell.

Usage: conflicting_pr_report.py [--from <file>] | conflicting_pr_report.py --print-comment
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, NamedTuple

# Single source of truth for the dedup: the workflow posts `comment_body()`, and a later run
# recognises its own notice by finding this string. Two spellings would mean either a notice
# re-posted every six hours, or one never posted while the run reports success.
MARKER = "<!-- ai-badger:stuck-pr-watch -->"

CONFLICTING = "CONFLICTING"
MERGEABLE = "MERGEABLE"

_NOTICE = """\
### This pull request is stuck, not slow

It conflicts with the base branch, so GitHub computes no merge ref for it and dispatches
**no `pull_request`-triggered workflow runs at all**. `Secret scan` and `CodeQL` are both
`pull_request`-triggered, so the required `gitleaks` check will never report on this head —
not late, not red, simply never. The pull request cannot merge however long you wait.

`build (3.10)` still reports, which is what makes this look like an ordinary slow check:
`Lint and test` triggers on `push`, and a push is unaffected by the conflict.

**Fix:** merge the base branch into this one (this repo merges, never rebases) and push. The
`pull_request` workflows start on that push, and this notice stops applying.

{marker}
"""


class Report(NamedTuple):
    """What one sweep of the open pull requests found."""

    checked: int
    stuck: List[int]
    needs_comment: List[int]
    unknown: List[int]


def comment_body() -> str:
    """The notice posted on a stuck pull request, carrying the marker the dedup reads."""
    return _NOTICE.format(marker=MARKER)


def _nodes(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Walk to the pull request nodes, refusing a payload that is merely shaped wrong.

    A missing key here means the query changed or the API errored. Returning an empty list
    would report "nothing stuck", which is the silent pass this detector exists to prevent.
    """
    try:
        nodes = payload["data"]["repository"]["pullRequests"]["nodes"]
    except (KeyError, TypeError) as exc:
        raise ValueError("payload has no data.repository.pullRequests.nodes") from exc
    if not isinstance(nodes, list):
        raise ValueError("data.repository.pullRequests.nodes is not a list")
    return nodes


def _already_noticed(node: Dict[str, Any]) -> bool:
    comments = (node.get("comments") or {}).get("nodes") or []
    return any(MARKER in (comment.get("body") or "") for comment in comments)


def stuck_pull_requests(payload: Dict[str, Any]) -> Report:
    """Split the open pull requests into stuck, still-to-notify, and not-yet-computed."""
    stuck: List[int] = []
    needs_comment: List[int] = []
    unknown: List[int] = []

    nodes = _nodes(payload)
    for node in nodes:
        number = node["number"]
        state = node.get("mergeable") or "UNKNOWN"
        if state == CONFLICTING:
            stuck.append(number)
            if not _already_noticed(node):
                needs_comment.append(number)
        elif state != MERGEABLE:
            # GitHub computes mergeability lazily and answers UNKNOWN until it has. Saying so
            # is honest; folding it into "clean" would hide exactly the state we are hunting.
            unknown.append(number)

    return Report(checked=len(nodes), stuck=stuck, needs_comment=needs_comment, unknown=unknown)


def main(argv: List[str]) -> int:
    """Entry point: print the notice, or the JSON report for the payload given."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", metavar="FILE",
                        help="read the GraphQL payload from FILE instead of stdin")
    parser.add_argument("--print-comment", action="store_true",
                        help="print the notice body and exit")
    args = parser.parse_args(argv)

    if args.print_comment:
        sys.stdout.write(comment_body())
        return 0

    text = (open(args.source, encoding="utf-8").read() if args.source  # pylint: disable=R1732
            else sys.stdin.read())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"conflicting_pr_report: input is not JSON: {exc}", file=sys.stderr)
        return 2

    if payload.get("errors"):
        print(f"conflicting_pr_report: GraphQL errors: {payload['errors']}", file=sys.stderr)
        return 2

    try:
        result = stuck_pull_requests(payload)
    except ValueError as exc:
        print(f"conflicting_pr_report: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result._asdict()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
