"""Publish a review round to GitHub idempotently, and read author replies back.

Stdlib only, plain dicts. Every GitHub call goes through an injected ``Runner`` that takes
``gh`` arguments (without the leading ``gh``) and stdin, returns stdout, and raises ``GhError``.

State dict: repo ("owner/name"), pr, now (aware datetime), round and flow (as for
``review_render.render_summary``), previous_findings (findings of the last published round),
changed_ranges ({path: [(start, end)]} changed between that round's head and this one),
verified_fixed (fingerprints a worker verified as fixed).
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from review_render import effective_severity, render_inline, render_summary  # pylint: disable=wrong-import-position

Runner = Callable[[List[str], Optional[str]], str]

MARKER = re.compile(
    r"\A<!-- ai-badger-review:(?P<kind>finding|summary|resolved) v1"
    r"(?: fp=(?P<fp>[0-9a-f]{8,64}))?(?: body=(?P<digest>[0-9a-f]{12}))? -->"
)
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REMOTE = re.compile(r"(?:^git@github\.com:|^(?:https|ssh|git)://(?:[^@/]+@)?github\.com/)"
                     r"(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$")
_STATUS = re.compile(r"HTTP (\d{3})")
_UPDATED = re.compile(r"^- Updated: .*$", re.MULTILINE)

THREADS_QUERY = (
    "query($owner:String!,$name:String!,$pr:Int!,$after:String){repository(owner:$owner,"
    "name:$name){pullRequest(number:$pr){reviewThreads(first:100,after:$after){pageInfo"
    "{hasNextPage endCursor} nodes{id isResolved comments(first:100){nodes{databaseId body "
    "url createdAt authorAssociation author{login}}}}}}}}"
)
RESOLVE_MUTATION = (
    "mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId})"
    "{thread{isResolved}}}"
)


class GhError(Exception):
    """A failed ``gh`` call; ``status`` is the HTTP status, or 0 when none was reported."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class PublishRefused(Exception):
    """Publishing was refused; ``results`` holds the writes applied before it. Exit code 2."""

    exit_code = 2

    def __init__(self, code: str, message: str = "", results: list | None = None):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.results = results or []


class PublishFailed(Exception):
    """A write failed mid-run; ``results`` holds the actions applied before it. Re-run to resume."""

    exit_code = 1

    def __init__(self, results: list, error: GhError):
        super().__init__(str(error))
        self.results = results
        self.error = error


def parse_marker(body: str) -> dict | None:
    """Marker at the very start of a comment body as {kind, fp, digest}, else None."""
    match = MARKER.match(body or "")
    return match.groupdict() if match else None


def parse_pages(text: str) -> list:
    """Items from ``gh api --paginate`` output, which may be several JSON arrays back to back."""
    decoder = json.JSONDecoder()
    items, pos = [], 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return items
        page, pos = decoder.raw_decode(text, pos)
        items.extend(page)


def gh_runner(argv: list[str], stdin: str | None) -> str:
    """Real runner: ``gh <argv>``; a non-zero exit raises GhError with the HTTP status."""
    proc = subprocess.run(["gh", *argv], input=stdin, capture_output=True, text=True,
                          check=False)
    if proc.returncode != 0:
        match = _STATUS.search(proc.stderr)
        raise GhError(int(match.group(1)) if match else 0, proc.stderr.strip())
    return proc.stdout


def _check_target(repo, pr):
    if not isinstance(repo, str) or not _REPO.fullmatch(repo) or ".." in repo:
        raise PublishRefused("bad_input", f"repo is not owner/name: {repo!r}")
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 1:
        raise PublishRefused("bad_input", f"pr is not a positive number: {pr!r}")


def check_remote(repo: str, remotes: list[str]) -> None:
    """Refuse unless one cwd git remote URL points at ``repo`` on github.com."""
    for url in remotes:
        match = _REMOTE.search((url or "").strip())
        if match and match.group("repo").lower() == repo.lower():
            return
    raise PublishRefused("remote_mismatch", f"no git remote points at {repo}")


def _get(runner, endpoint):
    return json.loads(runner(["api", endpoint], None))


def _get_all(runner, endpoint):
    return parse_pages(runner(["api", "--paginate", f"{endpoint}?per_page=100"], None))


def _graphql(runner, query, variables):
    out = json.loads(runner(["api", "graphql", "--input", "-"],
                            json.dumps({"query": query, "variables": variables})))
    if out.get("errors") or "data" not in out:
        raise GhError(0, f"graphql error: {out.get('errors')}")
    return out["data"]


def _threads(runner, repo, pr):
    owner, name = repo.split("/")
    after, nodes = None, []
    while True:
        data = _graphql(runner, THREADS_QUERY,
                        {"owner": owner, "name": name, "pr": pr, "after": after})
        page = data["repository"]["pullRequest"]["reviewThreads"]
        nodes.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        after = page["pageInfo"]["endCursor"]


def _own_marker(comment_body, author, login, kind):
    marker = parse_marker(comment_body)
    if author != login or not marker or marker["kind"] != kind:
        return None
    return marker


def _thread_root(thread, login):
    """(fingerprint, root comment id) of a thread rooted at our own finding comment, else None."""
    comments = thread["comments"]["nodes"]
    if not comments:
        return None
    root = comments[0]
    marker = _own_marker(root.get("body"), (root.get("author") or {}).get("login"), login,
                         "finding")
    return (marker["fp"], root.get("databaseId")) if marker else None


def read_head(runner: Runner, repo: str, pr: int) -> str:
    """Current head sha of the pull request."""
    _check_target(repo, pr)
    return _get(runner, f"repos/{repo}/pulls/{pr}")["head"]["sha"]


def read_existing(runner: Runner, repo: str, pr: int, login: str) -> dict:
    """Our own comments on the PR, found by marker AND author == ``login``.

    ``inline`` holds the newest finding comment per fingerprint, ``older`` the ones it replaced;
    ``replied`` and ``threads`` are keyed by the root comment id.
    """
    _check_target(repo, pr)
    inline, older, replied = {}, [], set()
    for comment in _get_all(runner, f"repos/{repo}/pulls/{pr}/comments"):
        author = comment["user"]["login"]
        if comment.get("in_reply_to_id"):
            marker = _own_marker(comment["body"], author, login, "resolved")
            if marker and marker["fp"]:
                replied.add(comment["in_reply_to_id"])
            continue
        marker = _own_marker(comment["body"], author, login, "finding")
        if not marker:
            continue
        entry = {"id": comment["id"], "fp": marker["fp"], "digest": marker["digest"],
                 "path": comment.get("path"),
                 "line": comment.get("line") or comment.get("original_line")}
        current = inline.get(marker["fp"])
        if current is not None and current["id"] > entry["id"]:
            current, entry = entry, current
        if current is not None:
            older.append(current)
        inline[marker["fp"]] = entry
    summary = None
    for comment in _get_all(runner, f"repos/{repo}/issues/{pr}/comments"):
        if _own_marker(comment["body"], comment["user"]["login"], login, "summary"):
            summary = {"id": comment["id"], "body": comment["body"]}
            break
    threads = {}
    for thread in _threads(runner, repo, pr):
        root = _thread_root(thread, login)
        if root and root[1] not in threads:
            threads[root[1]] = {"id": thread["id"], "resolved": bool(thread["isResolved"])}
    return {"login": login, "inline": inline, "older": older, "replied": replied,
            "summary": summary, "threads": threads}


def fetch_threads(runner: Runner, repo: str, pr: int, login: str) -> list[dict]:
    """Replies by others in threads rooted at our own finding comments, keyed by fingerprint."""
    _check_target(repo, pr)
    replies = []
    for thread in _threads(runner, repo, pr):
        root = _thread_root(thread, login)
        if not root:
            continue
        fp = root[0]
        for comment in thread["comments"]["nodes"][1:]:
            author = (comment.get("author") or {}).get("login")
            if author == login:
                continue
            replies.append({"fingerprint": fp, "thread_id": thread["id"],
                            "comment_id": comment["databaseId"], "author": author,
                            "association": comment["authorAssociation"],
                            "body": comment["body"], "url": comment.get("url"),
                            "created_at": comment["createdAt"]})
    return replies


def _intersects(ranges, start, end):
    return any(lo <= end and start <= hi for lo, hi in ranges)


def _anchor(fp, previous, comment):
    found = previous.get(fp)
    if found:
        loc = found["location"]
        return loc["path"], int(loc["start"]), int(loc["end"])
    line = comment.get("line")
    return comment.get("path"), line, line


def _same_summary(old, new):
    return _UPDATED.sub("", old.replace("\r\n", "\n")) == _UPDATED.sub("", new)


def _write(op, method, endpoint, payload, **extra):
    return {"op": op, "method": method, "endpoint": endpoint, "payload": payload, **extra}


def _resolve_actions(base, pr, comment, existing, reason):
    """Reply once with the resolved marker on ``comment``'s thread, then resolve the thread."""
    thread = existing["threads"].get(comment["id"])
    if thread and thread["resolved"]:
        return []
    fp, actions = comment["fp"], []
    if comment["id"] not in existing["replied"]:
        actions.append(_write(
            "reply", "POST", f"{base}/pulls/{pr}/comments/{comment['id']}/replies",
            {"body": f"<!-- ai-badger-review:resolved v1 fp={fp} -->\n{reason}."},
            fingerprint=fp))
    if thread:
        actions.append(_write("resolve", "POST", "graphql",
                              {"query": RESOLVE_MUTATION,
                               "variables": {"threadId": thread["id"]}}, fingerprint=fp))
    return actions


def _anchor_of(finding):
    loc = finding["location"]
    return loc["path"], int(loc["start"])


def plan_publish(state: dict, existing: dict, head_sha: str) -> list[dict]:
    """Actions that bring GitHub in line with ``state``; pure, makes every decision."""
    repo, pr = state.get("repo"), state.get("pr")
    _check_target(repo, pr)
    rnd = state["round"]
    if head_sha != rnd["head_sha"]:
        raise PublishRefused("head_moved", f"PR head is {head_sha}, round reviewed "
                                           f"{rnd['head_sha']}")
    base = f"repos/{repo}"
    findings = {f["fingerprint"]: f for f in rnd["findings"]}
    inline_bodies = {fp: render_inline(f) for fp, f in findings.items()
                     if f.get("in_diff") and effective_severity(f) is not None}
    actions, new_comments = [], []
    retired = list(existing.get("older") or [])
    for fp, body in inline_bodies.items():
        mine = existing["inline"].get(fp)
        path, line = _anchor_of(findings[fp])
        if mine is None or (mine["path"], mine["line"]) != (path, line):
            new_comments.append({"path": path, "line": line, "side": "RIGHT", "body": body})
            if mine is not None:
                retired.append({**mine, "fp": fp})
        elif mine["digest"] != parse_marker(body)["digest"]:
            actions.append(_write("update_inline", "PATCH", f"{base}/pulls/comments/{mine['id']}",
                                  {"body": body}, fingerprint=fp))
    if new_comments:
        actions.insert(0, _write("create_review", "POST", f"{base}/pulls/{pr}/reviews", {
            "commit_id": rnd["head_sha"], "event": "COMMENT",
            "body": f"ai-badger review, round {int(rnd['n'])}: {len(new_comments)} new "
                    "inline finding(s). The summary comment has the verdict.",
            "comments": new_comments}))
    for old in sorted(retired, key=lambda comment: comment["id"]):
        if old["fp"] in inline_bodies:
            path, line = _anchor_of(findings[old["fp"]])
            reason = f"Moved to `{path}:{line}`"
        else:
            reason = "Superseded by a newer comment"
        actions.extend(_resolve_actions(base, pr, old, existing, reason))
    previous = {f["fingerprint"]: f for f in state.get("previous_findings") or []}
    changed = state.get("changed_ranges") or {}
    fixed = set(state.get("verified_fixed") or [])
    not_reported = []
    for fp, mine in sorted(existing["inline"].items()):
        thread = existing["threads"].get(mine["id"])
        if fp in inline_bodies or (thread and thread["resolved"]):
            continue
        if fp in findings and effective_severity(findings[fp]) is not None:
            continue
        path, start, end = _anchor(fp, previous, mine)
        moved = start is not None and _intersects(changed.get(path, ()), start, end)
        if not (moved or fp in fixed):
            not_reported.append(fp)
            actions.append({"op": "mark_not_reported", "fingerprint": fp})
            continue
        reason = "Resolved: verified fixed" if fp in fixed else \
            f"Resolved: the anchored lines changed in `{rnd['head_sha']}`"
        actions.extend(_resolve_actions(base, pr, {**mine, "fp": fp}, existing, reason))
    summary = render_summary({**rnd, "not_reported": not_reported}, state["flow"], state["now"])
    old = existing["summary"]
    if old is None:
        actions.append(_write("create_summary", "POST", f"{base}/issues/{pr}/comments",
                              {"body": summary}))
    elif not _same_summary(old["body"], summary):
        actions.append(_write("update_summary", "PATCH", f"{base}/issues/comments/{old['id']}",
                              {"body": summary}))
    return actions


def _argv(action):
    if action["endpoint"] == "graphql":
        return ["api", "graphql", "--input", "-"]
    return ["api", "--method", action["method"], action["endpoint"], "--input", "-"]


SUMMARY_OPS = ("create_summary", "update_summary")


def apply(runner: Runner, actions: list[dict], dry_run: bool = False,
          check_head: Callable[[], None] | None = None) -> list[dict]:
    """Run the planned writes in order; stops at the first failure. ``dry_run`` writes nothing.

    ``check_head`` runs before the first write and again before the summary write; a
    ``PublishRefused`` it raises carries the results applied so far.
    """
    results, checked = [], False
    for action in actions:
        result = {"op": action["op"], "dry_run": dry_run}
        if "fingerprint" in action:
            result["fingerprint"] = action["fingerprint"]
        if action["op"] == "mark_not_reported" or dry_run:
            results.append(result)
            continue
        if check_head is not None and (not checked or action["op"] in SUMMARY_OPS):
            try:
                check_head()
            except PublishRefused as refusal:
                refusal.results = results
                raise
            checked = True
        try:
            out = runner(_argv(action), json.dumps(action["payload"]))
        except GhError as error:
            if error.status == 403:
                raise PublishRefused("forbidden", str(error), results) from error
            raise PublishFailed(results, error) from error
        result["response"] = json.loads(out) if out.strip() else None
        results.append(result)
    return results


def publish(runner: Runner, state: dict, remotes: list[str], dry_run: bool = False) -> list[dict]:
    """Check the remote and head, read our existing comments, then plan and apply.

    The head is read again before the first write and before the summary write, so a push
    during the run stops it with ``head_moved`` instead of publishing a stale verdict.
    """
    _check_target(state.get("repo"), state.get("pr"))
    check_remote(state["repo"], remotes)
    login = _get(runner, "user")["login"]
    head = read_head(runner, state["repo"], state["pr"])
    existing = read_existing(runner, state["repo"], state["pr"], login)

    def check_head():
        current = read_head(runner, state["repo"], state["pr"])
        if current != state["round"]["head_sha"]:
            raise PublishRefused("head_moved", f"PR head moved to {current} during publish")

    return apply(runner, plan_publish(state, existing, head), dry_run, check_head)
