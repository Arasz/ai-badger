"""GitHub publisher tests against an in-memory fake of the `gh api` surface."""

import copy
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "features/common/skills/review-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("review_publish", SCRIPTS / "review_publish.py")
publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish)

REPO = "acme/shop"
PR = 7
ME = "review-bot"
HEAD1 = "a1" * 20
HEAD2 = "b2" * 20
NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
FP_A = "aaaa1111bbbb2222"
FP_B = "cccc3333dddd4444"
FP_C = "eeee5555ffff6666"
REMOTES = ("https://github.com/acme/shop.git",)


class FakeGitHub:
    """Stateful fake of the endpoints the publisher uses; records every call."""

    def __init__(self, page_size=2, head=HEAD1):
        self.page_size = page_size
        self.head = head
        self.calls = []
        self.review_comments = []
        self.issue_comments = []
        self.resolved = set()
        self.next_id = 1000
        self.failures = []  # list of (predicate, status); each fires once

    def fail_once(self, predicate, status):
        self.failures.append((predicate, status))

    def _id(self):
        self.next_id += 1
        return self.next_id

    def _pages(self, items):
        chunks = [items[i:i + self.page_size] for i in range(0, len(items), self.page_size)]
        return "".join(json.dumps(chunk) for chunk in chunks or [[]]) + "\n"

    def add_review_comment(self, login, body, path="src/a.py", line=10, reply_to=None):
        comment = {"id": self._id(), "user": {"login": login}, "body": body, "path": path,
                   "line": line, "original_line": line, "in_reply_to_id": reply_to,
                   "author_association": "MEMBER",
                   "created_at": f"2026-11-{10 + len(self.review_comments) % 9:02d}T08:00:00Z"}
        self.review_comments.append(comment)
        return comment

    def add_issue_comment(self, login, body):
        comment = {"id": self._id(), "user": {"login": login}, "body": body}
        self.issue_comments.append(comment)
        return comment

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]

    def __call__(self, argv, stdin):
        assert argv[0] == "api"
        payload = json.loads(stdin) if stdin else None
        if argv[1] == "graphql":
            is_mutation = "resolveReviewThread" in payload["query"]
            method = "POST" if is_mutation else "GET"
            self.calls.append((method, "graphql", payload))
            self._maybe_fail(method, "graphql", payload)
            return self._graphql(payload, is_mutation)
        if argv[1] == "--method":
            method, endpoint = argv[2], argv[3]
        else:
            method, endpoint = "GET", argv[-1]
        self.calls.append((method, endpoint, payload))
        assert "--repo" not in argv
        self._maybe_fail(method, endpoint, payload)
        return self._rest(method, endpoint.split("?")[0], payload)

    def _maybe_fail(self, method, endpoint, payload):
        for i, (predicate, status) in enumerate(self.failures):
            if predicate(method, endpoint, payload):
                del self.failures[i]
                raise publish.GhError(status, f"HTTP {status}")

    def _rest(self, method, endpoint, payload):
        base = f"repos/{REPO}"
        if endpoint == "user":
            return json.dumps({"login": ME})
        if endpoint == f"{base}/pulls/{PR}":
            return json.dumps({"head": {"sha": self.head}, "base": {"ref": "main"}})
        if endpoint == f"{base}/pulls/{PR}/comments" and method == "GET":
            return self._pages(self.review_comments)
        if endpoint == f"{base}/issues/{PR}/comments" and method == "GET":
            return self._pages(self.issue_comments)
        if endpoint == f"{base}/pulls/{PR}/reviews" and method == "POST":
            for item in payload["comments"]:
                self.add_review_comment(ME, item["body"], item["path"], item["line"])
            return json.dumps({"id": self._id()})
        if endpoint == f"{base}/issues/{PR}/comments" and method == "POST":
            return json.dumps(self.add_issue_comment(ME, payload["body"]))
        if (m := re.fullmatch(rf"{base}/pulls/{PR}/comments/(\d+)/replies", endpoint)):
            parent = self._find(self.review_comments, int(m.group(1)))
            return json.dumps(self.add_review_comment(ME, payload["body"], parent["path"],
                                                      parent["line"], parent["id"]))
        if (m := re.fullmatch(rf"{base}/pulls/comments/(\d+)", endpoint)) and method == "PATCH":
            self._find(self.review_comments, int(m.group(1)))["body"] = payload["body"]
            return "{}"
        if (m := re.fullmatch(rf"{base}/issues/comments/(\d+)", endpoint)) and method == "PATCH":
            self._find(self.issue_comments, int(m.group(1)))["body"] = payload["body"]
            return "{}"
        raise AssertionError(f"unexpected call {method} {endpoint}")

    @staticmethod
    def _find(items, comment_id):
        return next(c for c in items if c["id"] == comment_id)

    def _graphql(self, payload, is_mutation):
        if is_mutation:
            self.resolved.add(payload["variables"]["threadId"])
            return json.dumps({"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}})
        roots = [c for c in self.review_comments if c["in_reply_to_id"] is None]
        start = int(payload["variables"].get("after") or 0)
        page = roots[start:start + self.page_size]
        nodes = []
        asks_created = "createdAt" in payload["query"]
        for root in page:
            thread = [root] + [c for c in self.review_comments if c["in_reply_to_id"] == root["id"]]
            nodes.append({
                "id": f"T_{root['id']}",
                "isResolved": f"T_{root['id']}" in self.resolved,
                "comments": {"nodes": [{
                    "databaseId": c["id"], "body": c["body"], "url": f"https://x/{c['id']}",
                    "authorAssociation": c["author_association"],
                    "author": {"login": c["user"]["login"]},
                    **({"createdAt": c["created_at"]} if asks_created else {}),
                } for c in thread]},
            })
        end = start + len(page)
        info = {"hasNextPage": end < len(roots), "endCursor": str(end)}
        return json.dumps({"data": {"repository": {"pullRequest": {
            "reviewThreads": {"pageInfo": info, "nodes": nodes}}}}})


def finding(fp, path, start, end, **over):
    item = {
        "fingerprint": fp, "lanes": ["qa"], "kind": "null_deref", "severity": "major",
        "location": {"path": path, "start": start, "end": end, "symbol": "charge"},
        "in_diff": True, "title": f"Finding {fp[:4]}", "reason": "It breaks.",
        "agent": {"repro": "", "context": "", "fix": ""}, "tags": [], "disposition": None,
        "evidence": [],
    }
    item.update(over)
    return item


def make_state(findings=None, head=HEAD1, n=1, **over):
    if findings is None:
        findings = [finding(FP_A, "src/a.py", 10, 12), finding(FP_B, "src/b.py", 30, 30),
                    finding(FP_C, "src/c.py", 5, 5, in_diff=False)]
    state = {
        "repo": REPO, "pr": PR, "now": NOW,
        "round": {"n": n, "head_sha": head, "findings": findings, "verdict": "Fix before merge",
                  "lanes": {"qa": {"status": "done", "error": None},
                            "business": {"status": "done", "error": None}}},
        "flow": {"ac_source": "pasted"},
        "previous_findings": [], "changed_ranges": {}, "verified_fixed": [],
    }
    state.update(over)
    return state


def run(fake, state, dry_run=False, remotes=REMOTES):
    return publish.publish(fake, state, list(remotes), dry_run=dry_run)


def write_endpoints(fake):
    return [(method, endpoint) for method, endpoint, _ in fake.writes()]


# --- ac1 ---------------------------------------------------------------------------------


def test_first_run_one_review_post_one_summary_post():
    fake = FakeGitHub()
    run(fake, make_state())
    assert write_endpoints(fake) == [("POST", f"repos/{REPO}/pulls/{PR}/reviews"),
                                     ("POST", f"repos/{REPO}/issues/{PR}/comments")]
    review = fake.writes()[0][2]
    assert review["commit_id"] == HEAD1
    assert [(c["path"], c["line"], c["side"]) for c in review["comments"]] == [
        ("src/a.py", 10, "RIGHT"), ("src/b.py", 30, "RIGHT")]
    summary = fake.writes()[1][2]["body"]
    assert summary.startswith("<!-- ai-badger-review:summary v1 -->")
    assert "src/c.py" in summary
    assert not any("src/c.py" in c["body"] for c in review["comments"])


def test_identical_rerun_zero_writes():
    fake = FakeGitHub()
    run(fake, make_state())
    before = len(fake.writes())
    run(fake, make_state(now=NOW + timedelta(hours=3)))
    assert len(fake.writes()) == before
    assert len(fake.issue_comments) == 1 and len(fake.review_comments) == 2


def test_changed_body_patches():
    fake = FakeGitHub()
    run(fake, make_state())
    own_a = next(c for c in fake.review_comments if FP_A in c["body"])
    changed = make_state()
    changed["round"]["findings"][0]["title"] = "A sharper title"
    del fake.calls[:]
    run(fake, changed)
    assert write_endpoints(fake) == [("PATCH", f"repos/{REPO}/pulls/comments/{own_a['id']}")]
    assert "A sharper title" in own_a["body"]
    assert len(fake.review_comments) == 2


@pytest.mark.parametrize("severity", ["blocker", "major", "minor", "nit"])
def test_event_always_comment(severity):
    fake = FakeGitHub()
    state = make_state([finding(FP_A, "src/a.py", 10, 12, severity=severity)])
    run(fake, state)
    reviews = [p for m, e, p in fake.writes() if e.endswith("/reviews")]
    assert [r["event"] for r in reviews] == ["COMMENT"]


# --- ac2 ---------------------------------------------------------------------------------


def test_spoofed_marker_from_foreign_author_ignored():
    fake = FakeGitHub()
    rendered = publish.render_inline(finding(FP_A, "src/a.py", 10, 12))
    spoof_inline = fake.add_review_comment("mallory", rendered)
    spoof_summary = fake.add_issue_comment("mallory", "<!-- ai-badger-review:summary v1 -->\nx")
    run(fake, make_state())
    endpoints = write_endpoints(fake)
    assert ("POST", f"repos/{REPO}/issues/{PR}/comments") in endpoints
    assert all(str(spoof_inline["id"]) not in e and str(spoof_summary["id"]) not in e
               for _, e in endpoints)
    review = fake.writes()[0][2]
    assert sorted(c["path"] for c in review["comments"]) == ["src/a.py", "src/b.py"]


class TestPagination:
    """Pagination: markers past the first page are still found."""

    def test_marker_on_page_two_found_no_duplicate_post(self):
        fake = FakeGitHub(page_size=2)
        for i in range(3):
            fake.add_issue_comment("alice", f"filler {i}")
            fake.add_review_comment("alice", f"filler {i}", "src/z.py", i + 1)
        run(fake, make_state())
        assert fake.issue_comments[-1]["user"]["login"] == ME  # summary sits on page 2
        del fake.calls[:]
        changed = make_state()
        changed["round"]["lanes"]["business"] = {"status": "failed", "error": "timeout"}
        run(fake, changed)
        summary_id = fake.issue_comments[-1]["id"]
        assert write_endpoints(fake) == [("PATCH", f"repos/{REPO}/issues/comments/{summary_id}")]
        assert len(fake.issue_comments) == 4 and len(fake.review_comments) == 5

    def test_paginated_output_concatenated_arrays_parsed(self):
        assert publish.parse_pages('[{"a":1}][{"a":2}]\n[]\n[{"a":3}]') == [
            {"a": 1}, {"a": 2}, {"a": 3}]
        assert publish.parse_pages("") == []


def test_deleted_marker_reposted():
    fake = FakeGitHub()
    run(fake, make_state())
    fake.issue_comments.clear()
    del fake.calls[:]
    run(fake, make_state())
    assert write_endpoints(fake) == [("POST", f"repos/{REPO}/issues/{PR}/comments")]


def test_parse_marker_reads_each_kind():
    body = publish.render_inline(finding(FP_A, "src/a.py", 10, 12))
    marker = publish.parse_marker(body)
    assert marker["kind"] == "finding" and marker["fp"] == FP_A and len(marker["digest"]) == 12
    assert publish.parse_marker("<!-- ai-badger-review:summary v1 -->\n##")["kind"] == "summary"
    assert publish.parse_marker("quoted:\n<!-- ai-badger-review:summary v1 -->") is None


# --- ac3 ---------------------------------------------------------------------------------


def round_two(**over):
    first = make_state()["round"]["findings"]
    return make_state([], head=HEAD2, n=2, previous_findings=first, **over)


def test_unchanged_anchored_lines_not_resolved():
    fake = FakeGitHub()
    run(fake, make_state())
    own = {fp: next(c for c in fake.review_comments if fp in c["body"]) for fp in (FP_A, FP_B)}
    fake.head = HEAD2
    del fake.calls[:]
    state = round_two(changed_ranges={"src/a.py": [(11, 11)], "src/b.py": [(1, 5)]})
    results = run(fake, state)
    endpoints = write_endpoints(fake)
    assert ("POST", f"repos/{REPO}/pulls/{PR}/comments/{own[FP_A]['id']}/replies") in endpoints
    assert not any(str(own[FP_B]["id"]) in e for _, e in endpoints)
    assert fake.resolved == {f"T_{own[FP_A]['id']}"}
    assert {"op": "mark_not_reported", "fingerprint": FP_B} in [
        {k: r[k] for k in ("op", "fingerprint")} for r in results if "fingerprint" in r]
    summary = fake.issue_comments[-1]["body"]
    assert "Not re-reported (1)" in summary and FP_B in summary
    assert summary.index("Not re-reported (1)") < summary.index("<!-- ai-badger-review:state ")
    assert summary.count("Not re-reported") == 1
    del fake.calls[:]
    run(fake, state)
    assert write_endpoints(fake) == []


def test_failed_resolve_resumes_without_second_reply():
    fake = FakeGitHub()
    run(fake, make_state())
    fake.head = HEAD2
    fake.fail_once(lambda m, e, p: e == "graphql" and m == "POST", 502)
    state = round_two(changed_ranges={"src/a.py": [(10, 10)]})
    with pytest.raises(publish.PublishFailed) as err:
        run(fake, state)
    assert [r["op"] for r in err.value.results] == ["reply"]
    del fake.calls[:]
    run(fake, state)
    assert [e for _, e in write_endpoints(fake)] == ["graphql", f"repos/{REPO}/issues/comments/"
                                                     f"{fake.issue_comments[-1]['id']}"]
    assert sum(1 for c in fake.review_comments if c["in_reply_to_id"]) == 1


def test_verified_fixed_resolved_without_line_change():
    fake = FakeGitHub()
    run(fake, make_state())
    own_b = next(c for c in fake.review_comments if FP_B in c["body"])
    fake.head = HEAD2
    run(fake, round_two(verified_fixed=[FP_B]))
    assert f"T_{own_b['id']}" in fake.resolved


class TestRefuse:
    """Refusals: typed, exit code 2, and no write reaches GitHub."""

    def test_refuse_when_head_moved(self):
        fake = FakeGitHub(head=HEAD2)
        with pytest.raises(publish.PublishRefused) as err:
            run(fake, make_state())
        assert err.value.code == "head_moved" and err.value.exit_code == 2
        assert fake.writes() == []

    @pytest.mark.parametrize("remote", ["git@github.com:other/shop.git",
                                        "https://github.com/acme/shopping.git", None])
    def test_refuse_on_remote_mismatch(self, remote):
        fake = FakeGitHub()
        with pytest.raises(publish.PublishRefused) as err:
            run(fake, make_state(), remotes=[remote] if remote else [])
        assert err.value.code == "remote_mismatch" and err.value.exit_code == 2
        assert fake.writes() == []

    @pytest.mark.parametrize("remote", ["git@github.com:acme/shop.git",
                                        "ssh://git@github.com/acme/shop",
                                        "https://github.com/Acme/Shop/"])
    def test_matching_remote_accepted(self, remote):
        fake = FakeGitHub()
        run(fake, make_state(), remotes=["git@github.com:fork/shop.git", remote])
        assert len(fake.writes()) == 2

    def test_403_exits_2_with_no_write(self):
        fake = FakeGitHub()
        fake.fail_once(lambda m, e, p: m == "POST", 403)
        with pytest.raises(publish.PublishRefused) as err:
            run(fake, make_state())
        assert err.value.code == "forbidden" and err.value.exit_code == 2
        assert len(fake.writes()) == 1
        assert fake.review_comments == [] and fake.issue_comments == []


def test_partial_failure_resumes_without_duplicates():
    fake = FakeGitHub()
    fake.fail_once(lambda m, e, p: m == "POST" and e.endswith(f"issues/{PR}/comments"), 502)
    with pytest.raises(publish.PublishFailed) as err:
        run(fake, make_state())
    assert [r["op"] for r in err.value.results] == ["create_review"]
    assert len(fake.review_comments) == 2 and fake.issue_comments == []
    del fake.calls[:]
    run(fake, make_state())
    assert write_endpoints(fake) == [("POST", f"repos/{REPO}/issues/{PR}/comments")]
    assert len(fake.review_comments) == 2 and len(fake.issue_comments) == 1


def test_dry_run_writes_nothing():
    fake = FakeGitHub()
    results = run(fake, make_state(), dry_run=True)
    assert fake.writes() == []
    assert [r["op"] for r in results] == ["create_review", "create_summary"]
    assert all(r["dry_run"] for r in results)


@pytest.mark.parametrize("repo", ["acme/shop/../../evil", "acme/..", "acme"])
def test_plan_publish_is_pure_and_refuses_bad_repo(repo):
    state = make_state(repo=repo)
    existing = {"login": ME, "inline": {}, "replied": set(), "summary": None, "threads": {}}
    snapshot = copy.deepcopy(state)
    with pytest.raises(publish.PublishRefused) as err:
        publish.plan_publish(state, existing, HEAD1)
    assert err.value.code == "bad_input"
    assert state == snapshot


# --- threads -----------------------------------------------------------------------------


def test_fetch_threads_returns_replies_by_fingerprint():
    fake = FakeGitHub(page_size=1)
    run(fake, make_state())
    own_a = next(c for c in fake.review_comments if FP_A in c["body"])
    own_b = next(c for c in fake.review_comments if FP_B in c["body"])
    reply = fake.add_review_comment("alice", "Not reachable: guarded upstream.", reply_to=own_a["id"])
    reply["author_association"] = "OWNER"
    fake.add_review_comment("mallory", "hijack", reply_to=own_b["id"])["author_association"] = "NONE"
    fake.add_review_comment(ME, "<!-- ai-badger-review:resolved v1 fp=x -->", reply_to=own_b["id"])
    foreign_root = fake.add_review_comment("mallory", publish.render_inline(
        finding(FP_C, "src/c.py", 5, 5)))
    fake.add_review_comment("alice", "reply on spoof", reply_to=foreign_root["id"])
    replies = publish.fetch_threads(fake, REPO, PR, ME)
    assert [(r["fingerprint"], r["author"], r["association"], r["comment_id"]) for r in replies] == [
        (FP_A, "alice", "OWNER", reply["id"]), (FP_B, "mallory", "NONE", replies[1]["comment_id"])]
    assert replies[0]["thread_id"] == f"T_{own_a['id']}"
    assert replies[0]["body"] == "Not reachable: guarded upstream."


def test_fetch_threads_reports_each_reply_created_at_from_github():
    fake = FakeGitHub(page_size=1)
    run(fake, make_state())
    own_a = next(c for c in fake.review_comments if FP_A in c["body"])
    own_b = next(c for c in fake.review_comments if FP_B in c["body"])
    first = fake.add_review_comment("alice", "Fixed.", reply_to=own_a["id"])
    second = fake.add_review_comment("bob", "Out of scope.", reply_to=own_b["id"])
    assert first["created_at"] != second["created_at"]
    replies = publish.fetch_threads(fake, REPO, PR, ME)
    assert [(r["comment_id"], r["created_at"]) for r in replies] == [
        (first["id"], first["created_at"]), (second["id"], second["created_at"])]


def test_summary_verdict_comes_from_the_round_state():
    fake = FakeGitHub()
    state = make_state()
    state["round"]["verdict"] = "Block"
    run(fake, state)
    assert "## Review verdict: Block\n" in fake.issue_comments[-1]["body"]


def test_publish_passes_not_reported_to_the_renderer_without_splicing(monkeypatch):
    seen = []
    real = publish.render_summary

    def spy(rnd, flow, now):
        seen.append(list(rnd.get("not_reported") or []))
        return real(rnd, flow, now)

    monkeypatch.setattr(publish, "render_summary", spy)
    fake = FakeGitHub()
    run(fake, make_state())
    fake.head = HEAD2
    run(fake, round_two(changed_ranges={"src/a.py": [(11, 11)]}))
    assert seen == [[], [FP_B]]
    assert not hasattr(publish, "_with_not_reported")
